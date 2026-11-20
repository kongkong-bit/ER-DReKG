from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def read_rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def import_rows(root: Path) -> dict[str, int]:
    processed = root / "data/processed/top10_kg"
    identity = read_rows(processed / "top10_external_identity.csv")
    evidence = read_rows(processed / "top10_external_records.csv")
    claims = read_rows(processed / "top10_claims.csv")
    paths = read_rows(processed / "top10_mechanism_paths.csv")
    if not all(row.get("snapshot_path") for row in evidence):
        raise RuntimeError("外部证据存在空快照路径，拒绝导入")
    return {"drug_nodes": len(identity), "evidence_nodes": len(evidence), "claim_nodes": len(claims), "path_nodes": len(paths)}


def apply(root: Path, counts: dict[str, int], backup_path: Path) -> dict[str, object]:
    if os.getenv("TOP10_KG_ALLOW_NEO4J_WRITE") != "1":
        raise RuntimeError("需要显式设置 TOP10_KG_ALLOW_NEO4J_WRITE=1")
    if not backup_path.is_file():
        raise RuntimeError(f"备份凭据不存在：{backup_path}")
    from neo4j import GraphDatabase

    uri = os.environ["NEO4J_URI"]
    user = os.environ["NEO4J_USER"]
    password = os.environ["NEO4J_PASSWORD"]
    database = os.getenv("NEO4J_DATABASE", "neo4j")
    run_id = "top10_kg_v1"
    identity = read_rows(root / "data/processed/top10_kg/top10_external_identity.csv")
    evidence = read_rows(root / "data/processed/top10_kg/top10_external_records.csv")
    claims = read_rows(root / "data/processed/top10_kg/top10_claims.csv")
    paths = read_rows(root / "data/processed/top10_kg/top10_mechanism_paths.csv")
    driver = GraphDatabase.driver(uri, auth=(user, password))
    try:
        driver.verify_connectivity()
        with driver.session(database=database) as session:
            session.run("CREATE CONSTRAINT top10_drug_key IF NOT EXISTS FOR (n:Top10Drug) REQUIRE n.pert_id IS UNIQUE").consume()
            session.run("CREATE CONSTRAINT top10_evidence_key IF NOT EXISTS FOR (n:Top10Evidence) REQUIRE n.evidence_key IS UNIQUE").consume()

            def write(tx):
                for row in identity:
                    tx.run("MERGE (d:Top10Drug {pert_id: $pert_id}) SET d += $props", pert_id=row["pert_id"], props={"name": row["pert_iname"], "mapping_status": row["mapping_status"], "chembl_id": row.get("chembl_id", ""), "pubchem_cid": row.get("pubchem_cid", ""), "inchikey": row.get("inchikey", ""), "run_id": run_id}).consume()
                for row in evidence:
                    key = f"{row['pert_id']}::{row['source']}::{row['source_record_id']}"
                    tx.run("MERGE (e:Top10Evidence {evidence_key: $key}) SET e += $props WITH e MATCH (d:Top10Drug {pert_id: $pert_id}) MERGE (d)-[:HAS_EXTERNAL_EVIDENCE {run_id: $run_id}]->(e)", key=key, pert_id=row["pert_id"], run_id=run_id, props={"source": row["source"], "source_record_id": row["source_record_id"], "snapshot_path": row["snapshot_path"], "evidence_type": row["evidence_type"], "validation_status": row["validation_status"], "run_id": run_id}).consume()
                for row in claims:
                    tx.run("MERGE (c:Top10Claim {claim_id: $claim_id}) SET c += $props", claim_id=row["claim_id"], props={"subject_id": row["subject_id"], "predicate": row["predicate"], "object_id": row["object_id"], "status": row["status"], "source_record_id": row["source_record_id"], "run_id": run_id}).consume()
                for row in paths:
                    tx.run("MERGE (p:Top10MechanismPath {path_id: $path_id}) SET p += $props WITH p MATCH (d:Top10Drug {pert_id: $pert_id}) MERGE (d)-[:HAS_MECHANISM_PATH {run_id: $run_id}]->(p)", path_id=row["path_id"], pert_id=row["pert_id"], run_id=run_id, props={"target_gene_id": row["target_gene_id"], "pathway_id": row["pathway_id"], "pathway_label": row["pathway_label"], "status": row["status"], "run_id": run_id}).consume()

            session.execute_write(write)
        result = {"status": "PASS", "write_performed": True, "backup_path": str(backup_path), **counts}
    finally:
        driver.close()
    (root / "reports/top10_kg/neo4j_import_result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="安全执行 Top 10 Neo4j 增量导入；默认只做校验")
    parser.add_argument("--apply", action="store_true", help="实际写入；必须同时满足环境变量和备份文件要求")
    parser.add_argument("--backup-path", type=Path, help="已完成的 Neo4j 备份凭据文件")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    counts = import_rows(root)
    if not args.apply:
        print(json.dumps({"status": "DRY_RUN", "write_performed": False, **counts}, ensure_ascii=False))
        return
    if args.backup_path is None:
        raise SystemExit("--apply 必须提供 --backup-path")
    print(json.dumps(apply(root, counts, args.backup_path), ensure_ascii=False))


if __name__ == "__main__":
    main()
