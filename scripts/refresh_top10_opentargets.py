from __future__ import annotations

import csv
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from kg_top10.sources import OpenTargetsAdapter


def read_rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_rows(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    status_path = root / "reports/top10_kg/external_source_status.csv"
    top10 = read_rows(root / "experiments/final_results/results/final_top10.csv")
    target_rows = read_rows(root / "experiments/final_results/mechanism/final_neo4j_direct_targets.csv")
    ids_by_pert: dict[str, list[str]] = {}
    for row in target_rows:
        if row.get("target_gene_id", "").strip():
            ids_by_pert.setdefault(row["pert_id"], []).append(row["target_gene_id"].strip())
    run_id = "TOP10_OPENTARGETS_REFRESH:" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + ":" + uuid.uuid4().hex[:8]
    adapter = OpenTargetsAdapter(root / "data/raw/top10_kg/source_cache")
    refreshed = []
    for item in top10:
        ids = sorted(set(ids_by_pert.get(item["pert_id"], [])))
        if ids:
            _, result = adapter.target_disease(ids[0], "MONDO_0007254")
            refreshed.append({"run_id": run_id, "pert_id": item["pert_id"], "drug_name": item["drug_name"], "source": "opentargets", "status": result.status, "record_count": str(result.record_count), "snapshot_path": result.snapshot_path or "", "error": result.error or ""})
        else:
            refreshed.append({"run_id": run_id, "pert_id": item["pert_id"], "drug_name": item["drug_name"], "source": "opentargets", "status": "skipped", "record_count": "0", "snapshot_path": "", "error": "当前图谱没有可核实的 Ensembl target ID"})
    by_pert = {row["pert_id"]: row for row in refreshed}
    rows = read_rows(status_path)
    output = [by_pert[row["pert_id"]] if row["source"] == "opentargets" else row for row in rows]
    write_rows(status_path, output)
    print({"run_id": run_id, "opentargets_ok": sum(row["status"] in {"ok", "cached"} for row in refreshed), "opentargets_skipped": sum(row["status"] == "skipped" for row in refreshed), "opentargets_failed": sum(row["status"] == "failed" for row in refreshed)})


if __name__ == "__main__":
    main()
