from __future__ import annotations

import csv
import json
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from kg_top10.sources import ChEMBLAdapter, DGIdbAdapter, OpenTargetsAdapter, PubChemAdapter, PubMedAdapter, ReactomeAdapter


def read_rows(path: Path):
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_rows(path: Path, rows: list[dict[str, str]]):
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = list(rows[0]) if rows else ["run_id", "pert_id", "drug_name", "source", "status", "record_count", "snapshot_path", "error"]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    run_id = "TOP10_SOURCE_RUN:" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + ":" + uuid.uuid4().hex[:8]
    run_dir = root / "data" / "raw" / "top10_kg" / "runs" / run_id.rsplit(":", 1)[-1]
    cache_dir = root / "data" / "raw" / "top10_kg" / "source_cache"
    rows = read_rows(root / "experiments/final_results/results/final_top10.csv")
    mappings = {row["pert_id"]: row for row in read_rows(root / "experiments/final_results/mechanism/final_neo4j_drug_mapping.csv")}
    targets = read_rows(root / "experiments/final_results/mechanism/final_neo4j_direct_targets.csv")
    targets_by_pert: dict[str, list[str]] = {}
    for row in targets:
        targets_by_pert.setdefault(row["pert_id"], []).append(row.get("target_symbol", ""))

    adapters = {
        "pubchem": PubChemAdapter(cache_dir), "chembl": ChEMBLAdapter(cache_dir), "dgidb": DGIdbAdapter(cache_dir),
        "reactome": ReactomeAdapter(cache_dir), "opentargets": OpenTargetsAdapter(cache_dir), "pubmed": PubMedAdapter(cache_dir),
    }
    results: list[dict[str, str]] = []

    def record(pert_id: str, drug_name: str, source: str, result):
        _, status = result
        results.append({"run_id": run_id, "pert_id": pert_id, "drug_name": drug_name, "source": source, "status": status.status, "record_count": str(status.record_count), "snapshot_path": status.snapshot_path or "", "error": status.error or ""})

    for row in rows:
        pert_id, drug_name = row["pert_id"], row["drug_name"]
        record(pert_id, drug_name, "pubchem", adapters["pubchem"].resolve(drug_name))
        mapping = mappings.get(pert_id, {})
        chembl_id = mapping.get("graph_drug_ids", "").split(",")[0].strip()
        record(pert_id, drug_name, "chembl", adapters["chembl"].resolve(chembl_id) if chembl_id else adapters["chembl"].search(drug_name))
        record(pert_id, drug_name, "dgidb", adapters["dgidb"].resolve(drug_name))
        record(pert_id, drug_name, "pubmed", adapters["pubmed"].search(f'"{drug_name}" AND (MCF7 OR "breast cancer")'))
        symbols = sorted(set(targets_by_pert.get(pert_id, [])))
        if symbols:
            record(pert_id, drug_name, "reactome", adapters["reactome"].pathways_for_gene(symbols[0]))
        else:
            results.append({"run_id": run_id, "pert_id": pert_id, "drug_name": drug_name, "source": "reactome", "status": "skipped", "record_count": "0", "snapshot_path": "", "error": "当前图谱没有可核实的 target_symbol"})
        results.append({"run_id": run_id, "pert_id": pert_id, "drug_name": drug_name, "source": "opentargets", "status": "skipped", "record_count": "0", "snapshot_path": "", "error": "项目疾病 ID 为 MONDO:0007254；未自动把它猜测为 Open Targets EFO ID"})

    write_rows(run_dir / "source_status.csv", results)
    (run_dir / "run_manifest.json").write_text(json.dumps({"run_id": run_id, "created_at": datetime.now(timezone.utc).isoformat(), "top10_count": len(rows), "policy": "failed or skipped sources never become graph facts", "source_status": "source_status.csv"}, ensure_ascii=False, indent=2), encoding="utf-8")
    write_rows(root / "reports/top10_kg/external_source_status.csv", results)
    print(json.dumps({"run_id": run_id, "rows": len(results), "ok": sum(item["status"] == "ok" for item in results), "failed": sum(item["status"] == "failed" for item in results), "skipped": sum(item["status"] == "skipped" for item in results)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
