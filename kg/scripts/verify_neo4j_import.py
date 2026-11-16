from __future__ import annotations

import csv
import hashlib
import json
import os
import subprocess
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from neo4j import GraphDatabase

ROOT = Path(__file__).resolve().parents[2]
BASE = ROOT / "experiments" / "platform_phase_b"
EXT = ROOT / "experiments" / "platform_phase_b_pathways"
REPORT = EXT / "neo4j_import_validation.json"
IMPORTER = ROOT / "kg" / "scripts" / "import_phase_b_to_neo4j.py"
RELATION_MAP = {
    "DRG-GEN": "TARGETS",
    "PWY-GEN": "CONTAINS_GENE",
    "PROJECT-HAS_CANDIDATE": "HAS_CANDIDATE",
    "PROJECT-REFERENCES_DRUG": "REFERENCES_DRUG",
    "PROJECT-HAS_DEG": "HAS_DEG",
    "S1-ENRICHED-PATHWAY": "HAS_ENRICHED_PATHWAY",
    "S1-ENRICHED-GENE": "HAS_ENRICHED_GENE",
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_env() -> dict[str, str]:
    values = {}
    path = ROOT / ".env"
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            key, separator, value = line.partition("=")
            if separator and key and not key.startswith("#"):
                values[key] = value
    return values


def csv_expected_counts() -> tuple[dict[str, int], dict[str, int], int]:
    node_types: dict[str, str] = {}
    edge_ids: dict[str, str] = {}
    edge_properties: dict[str, str] = {}
    for path in [BASE / "subgraph_nodes.csv", EXT / "pathway_nodes.csv", EXT / "gene_nodes.csv"]:
        with path.open(encoding="utf-8-sig", newline="") as handle:
            for row in csv.DictReader(handle):
                previous = node_types.setdefault(row["id"], row["type"])
                if previous != row["type"]:
                    raise ValueError(f"Node ID {row['id']} has conflicting types {previous}/{row['type']}")
    for path in [BASE / "subgraph_edges.csv", EXT / "pathway_edges.csv"]:
        with path.open(encoding="utf-8-sig", newline="") as handle:
            for row in csv.DictReader(handle):
                relation = RELATION_MAP.get(row["label"])
                if not relation:
                    raise ValueError(f"Unmapped relation label {row['label']}")
                key = f"{row['from']}|{relation}|{row['to']}|{row['source_release']}"
                properties = row["properties_json"] or "{}"
                prior = edge_properties.setdefault(key, properties)
                if prior != properties:
                    raise ValueError(f"Duplicate relationship key has conflicting source assertions: {key}")
                edge_ids[key] = relation
    return dict(Counter(node_types.values())), dict(Counter(edge_ids.values())), len(node_types)


def database_counts(driver, database: str) -> dict:
    with driver.session(database=database) as session:
        node_rows = session.run("MATCH (n) UNWIND labels(n) AS label RETURN label, count(*) AS count ORDER BY label").data()
        edge_rows = session.run("MATCH ()-[r]->() RETURN type(r) AS type, count(*) AS count ORDER BY type").data()
        broken_evidence = session.run("MATCH ()-[r]->() WHERE r.source_release IS NULL OR r.source_assertion_json IS NULL OR r.evidence_ids IS NULL OR size(r.evidence_ids) = 0 RETURN count(r) AS count").single()["count"]
        route = session.run(
            "MATCH (ctx:DiseaseContext {project_slug: 'erpos-gse42568'})-[:HAS_ENRICHED_PATHWAY]->(p) "
            "-[:HAS_ENRICHED_GENE]->(g)<-[:TARGETS]-(d)<-[:REFERENCES_DRUG]-(c) "
            "RETURN count(*) AS route_count, count(DISTINCT c.id) AS candidate_count, "
            "count(DISTINCT d.id) AS drug_count, count(DISTINCT g.id) AS target_gene_count"
        ).single().data()
    return {
        "nodes_by_type": {row["label"]: row["count"] for row in node_rows},
        "edges_by_type": {row["type"]: row["count"] for row in edge_rows},
        "source_assertion_missing_edge_count": broken_evidence,
        "candidate_target_pathway_routes": route,
    }


def run_importer(env: dict[str, str]) -> dict:
    result = subprocess.run([sys.executable, str(IMPORTER)], cwd=ROOT, env=env, capture_output=True, text=True, timeout=300)
    if result.returncode:
        raise RuntimeError(f"Importer failed (exit {result.returncode}): {result.stderr[-2000:]}")
    return json.loads(result.stdout)


def main() -> None:
    env = os.environ.copy()
    env.update(load_env())
    uri = env["NEO4J_URI"]
    database = env.get("NEO4J_DATABASE", "neo4j")
    expected_nodes, expected_edges, unique_node_count = csv_expected_counts()
    input_paths = [BASE / "subgraph_nodes.csv", BASE / "subgraph_edges.csv", EXT / "pathway_nodes.csv", EXT / "gene_nodes.csv", EXT / "pathway_edges.csv"]
    driver = GraphDatabase.driver(uri, auth=(env["NEO4J_USER"], env["NEO4J_PASSWORD"]))
    try:
        driver.verify_connectivity()
        before = database_counts(driver, database)
        import_one = run_importer(env)
        after_first_import = database_counts(driver, database)
        import_two = run_importer(env)
        after = database_counts(driver, database)
    finally:
        driver.close()

    expected = {"nodes_by_type": expected_nodes, "edges_by_type": expected_edges}
    actual = {"nodes_by_type": after["nodes_by_type"], "edges_by_type": after["edges_by_type"]}
    passed = (
        after_first_import == after
        and expected["nodes_by_type"] == actual["nodes_by_type"]
        and expected["edges_by_type"] == actual["edges_by_type"]
        and after["source_assertion_missing_edge_count"] == 0
        and after["candidate_target_pathway_routes"] == {"route_count": 1422, "candidate_count": 22, "drug_count": 22, "target_gene_count": 41}
    )
    report = {
        "status": "PASS" if passed else "FAIL",
        "verified_at_utc": datetime.now(timezone.utc).isoformat(),
        "graph_build_id": "GRAPH_BUILD:ERPOS_S1_PATHWAY_20261113",
        "analysis_run_id": "ANALYSIS_RUN:S1_PATHWAY_ENRICHMENT_20261112",
        "database": "Neo4j local Compose service",
        "import_runs": [import_one.get("status"), import_two.get("status")],
        "idempotency": {"status": "PASS" if after_first_import == after else "FAIL", "before": after_first_import, "after": after, "pre_refresh_state": before},
        "expected_unique_node_count": unique_node_count,
        "expected_counts": expected,
        "actual_counts": after,
        "input_sha256": {path.relative_to(ROOT).as_posix(): sha256(path) for path in input_paths},
        "checks": {
            "csv_expected_counts_match_database": expected["nodes_by_type"] == actual["nodes_by_type"] and expected["edges_by_type"] == actual["edges_by_type"],
            "all_imported_relationships_have_source_release_assertion_and_evidence_id": after["source_assertion_missing_edge_count"] == 0,
            "candidate_target_s1_pathway_route_count_matches_csv_audit": after["candidate_target_pathway_routes"] == {"route_count": 1422, "candidate_count": 22, "drug_count": 22, "target_gene_count": 41},
        },
    }
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"status": report["status"], "import_runs": report["import_runs"], "node_count": unique_node_count, "edge_count": sum(expected_edges.values()), "routes": after["candidate_target_pathway_routes"], "report": REPORT.relative_to(ROOT).as_posix()}, ensure_ascii=False, indent=2))
    if not passed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
