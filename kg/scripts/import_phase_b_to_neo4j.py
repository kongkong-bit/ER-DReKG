from __future__ import annotations

import csv
import argparse
import hashlib
import json
import os
import sys
from collections import defaultdict
from pathlib import Path

# Project S1 enrichment assertions can be much larger than the csv module's
# 128 KiB default field limit; keep complete, auditable source assertions.
csv.field_size_limit(min(sys.maxsize, 2_147_483_647))

ROOT = Path(__file__).resolve().parents[2]
SUBGRAPH = ROOT / "experiments" / "platform_phase_b"
PATHWAY_EXTENSION = ROOT / "experiments" / "platform_phase_b_pathways"
ALLOWED_LABELS = {"Drug", "Gene", "Pathway", "GeneSet", "Candidate", "DiseaseContext", "Disease", "S2Condition"}
RELATION_MAP = {
    "DRG-GEN": "TARGETS",
    "PWY-GEN": "CONTAINS_GENE",
    "PROJECT-HAS_CANDIDATE": "HAS_CANDIDATE",
    "PROJECT-REFERENCES_DRUG": "REFERENCES_DRUG",
    "PROJECT-HAS_DEG": "HAS_DEG",
    "S1-ENRICHED-PATHWAY": "HAS_ENRICHED_PATHWAY",
    "S1-ENRICHED-GENE": "HAS_ENRICHED_GENE",
    "PROJECT-ABOUT_DISEASE": "ABOUT_DISEASE",
    "PROJECT-HAS_S2_CONDITION": "HAS_S2_CONDITION",
}


def to_neo4j_properties(values: dict) -> dict:
    """Convert JSON node properties to Neo4j's scalar/list property model."""
    result = {}
    for key, value in values.items():
        if value is None:
            continue
        if isinstance(value, (str, bool, int, float)):
            result[key] = value
        elif isinstance(value, list):
            if not value:
                continue
            if all(isinstance(item, (str, bool, int, float)) and item is not None for item in value):
                types = {type(item) for item in value}
                numeric_types = {int, float}
                if len(types) == 1 or types.issubset(numeric_types):
                    result[key] = value
                else:
                    result[key] = json.dumps(value, ensure_ascii=False, sort_keys=True)
            else:
                result[key] = json.dumps(value, ensure_ascii=False, sort_keys=True)
        else:
            result[key] = json.dumps(value, ensure_ascii=False, sort_keys=True)
    return result


def prepare_biocypher_import_rows(node_rows: list[dict], edge_rows: list[dict], graph_build_id: str):
    """Translate bundle rows with BioCypher and prepare versioned MERGE rows."""
    try:
        from .biocypher_adapter import translate_graph_rows
    except ImportError:  # direct CLI execution
        from biocypher_adapter import translate_graph_rows
    translated_nodes, translated_edges, biocypher_report = translate_graph_rows(node_rows, edge_rows)

    node_label_by_id: dict[str, str] = {}
    node_display_by_id = {row["id"]: row["label"] for row in node_rows}
    nodes_by_label = defaultdict(list)
    for node in translated_nodes:
        if node.node_label not in ALLOWED_LABELS:
            raise ValueError(f"Unapproved BioCypher node label: {node.node_label}")
        previous = node_label_by_id.setdefault(node.node_id, node.node_label)
        if previous != node.node_label:
            raise ValueError(f"Node ID {node.node_id} appears under both {previous} and {node.node_label}")
        props = to_neo4j_properties(node.properties)
        props.update({"id": node.node_id, "label": node_display_by_id.get(node.node_id) or node.node_id, "type": node.node_label})
        if node.node_label in {"Candidate", "DiseaseContext", "S2Condition"}:
            props.setdefault("project_id", "PROJECT:ERPOS_GSE42568")
        nodes_by_label[node.node_label].append(props)

    edges_by_relation = defaultdict(list)
    allowed_relations = set(RELATION_MAP.values())
    for source_row, edge in zip(edge_rows, translated_edges):
        relation = edge.relationship_label
        if relation not in allowed_relations:
            raise ValueError(f"Unapproved BioCypher relationship: {relation}")
        source_label = node_label_by_id.get(edge.source_id)
        target_label = node_label_by_id.get(edge.target_id)
        if not source_label or not target_label:
            raise ValueError(f"Relationship endpoint missing from BioCypher nodes: {edge.source_id} -> {edge.target_id}")
        source_assertion = json.loads(source_row["properties_json"] or "{}")
        input_relation = source_row["label"]
        source_release = source_row["source_release"]
        edge_key = (relation, source_label, target_label)
        evidence_id = hashlib.sha256(f"{source_row['from']}|{input_relation}|{source_row['to']}|{source_release}".encode()).hexdigest()
        edges_by_relation[edge_key].append({
            "from": edge.source_id,
            "to": edge.target_id,
            "id": f"{edge.source_id}|{relation}|{edge.target_id}|{source_release}",
            "evidence_ids": [evidence_id],
            "source_release": source_release,
            "source_assertion_json": json.dumps(source_assertion, ensure_ascii=False, sort_keys=True),
            "relation_label": input_relation,
            "undirected": source_row["undirected"].lower() == "true",
            "graph_build_id": graph_build_id,
        })
    return nodes_by_label, edges_by_relation, biocypher_report


def main(
    graph_build_id: str = "GRAPH_BUILD:LEGACY_PHASE_B",
    subgraph_dir: Path = SUBGRAPH,
    pathway_extension_dir: Path | None = PATHWAY_EXTENSION,
) -> None:
    def read_rows(path: Path) -> list[dict[str, str]]:
        if not path.is_file():
            return []
        with path.open(encoding="utf-8-sig", newline="") as stream:
            return list(csv.DictReader(stream))

    # BioCypher translates the actual entities consumed by the importer.
    # Persistence remains custom Cypher so relationship identity includes the
    # source release and each relationship can be scoped to a GraphBuild.
    node_rows = read_rows(subgraph_dir / "subgraph_nodes.csv")
    edge_rows = read_rows(subgraph_dir / "subgraph_edges.csv")
    if pathway_extension_dir and pathway_extension_dir.exists():
        for filename in ["pathway_nodes.csv", "gene_nodes.csv"]:
            node_rows.extend(read_rows(pathway_extension_dir / filename))
        if (pathway_extension_dir / "pathway_edges.csv").is_file():
            edge_rows.extend(read_rows(pathway_extension_dir / "pathway_edges.csv"))
    nodes_by_label, edges_by_relation, biocypher_report = prepare_biocypher_import_rows(node_rows, edge_rows, graph_build_id)

    # Connect only after the complete BioCypher translation and validation pass.
    from neo4j import GraphDatabase
    uri = os.environ["NEO4J_URI"]
    user = os.environ["NEO4J_USER"]
    password = os.environ["NEO4J_PASSWORD"]
    database = os.getenv("NEO4J_DATABASE", "neo4j")
    driver = GraphDatabase.driver(uri, auth=(user, password))
    try:
        driver.verify_connectivity()
        with driver.session(database=database) as session:
            for label in sorted(ALLOWED_LABELS):
                session.run(f"CREATE CONSTRAINT {label.lower()}_id_unique IF NOT EXISTS FOR (n:{label}) REQUIRE n.id IS UNIQUE").consume()
            for label, rows in nodes_by_label.items():
                query = f"UNWIND $rows AS row MERGE (n:{label} {{id: row.id}}) SET n += row"
                session.run(query, rows=rows).consume()
            for (relation, from_label, to_label), rows in edges_by_relation.items():
                query = f"UNWIND $rows AS row MATCH (a:{from_label} {{id: row.from}}) MATCH (b:{to_label} {{id: row.to}}) MERGE (a)-[r:{relation} {{id: row.id}}]->(b) SET r += row SET r.graph_build_ids = reduce(acc = [], value IN coalesce(r.graph_build_ids, []) + [row.graph_build_id] | CASE WHEN value IN acc THEN acc ELSE acc + value END) REMOVE r.graph_build_id"
                session.run(query, rows=rows).consume()
            check = session.run("MATCH (n) WHERE n.id STARTS WITH 'CANDIDATE:' RETURN count(n) AS candidates").single()["candidates"]
            edge_count_labels = {f"{relation} ({from_label}->{to_label})": len(rows) for (relation, from_label, to_label), rows in edges_by_relation.items()}
            print(json.dumps({"status": "PASS", "biocypher": biocypher_report, "node_counts_by_type": {k: len(v) for k, v in nodes_by_label.items()}, "edge_counts_by_type": edge_count_labels, "candidate_nodes_in_db": check}, ensure_ascii=False, indent=2))
    finally:
        driver.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="将审计后的 Phase B 子图按版本幂等导入 Neo4j")
    parser.add_argument("--graph-build-id", default="GRAPH_BUILD:LEGACY_PHASE_B")
    parser.add_argument("--subgraph-dir", type=Path, default=SUBGRAPH)
    parser.add_argument("--pathway-extension-dir", type=Path, default=PATHWAY_EXTENSION)
    args = parser.parse_args()
    main(args.graph_build_id, args.subgraph_dir, args.pathway_extension_dir)
