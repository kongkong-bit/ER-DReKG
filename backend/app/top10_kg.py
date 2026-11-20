from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
REPORT_DIR = ROOT / "reports" / "top10_kg"


def load_top10_audit() -> dict[str, Any]:
    metrics_path = REPORT_DIR / "baseline_metrics.json"
    audit_path = ROOT / "data" / "processed" / "top10_kg" / "baseline_candidate_audit.csv"
    if not metrics_path.is_file() or not audit_path.is_file():
        return {"available": False, "reason": "Top 10 专项审计尚未生成；请运行 scripts/run_top10_kg_audit.py"}
    metrics = json.loads(metrics_path.read_text(encoding="utf-8"))
    external_metrics_path = REPORT_DIR / "after_external_metrics.json"
    external_metrics = json.loads(external_metrics_path.read_text(encoding="utf-8")) if external_metrics_path.is_file() else None
    with audit_path.open(encoding="utf-8-sig", newline="") as handle:
        candidates = list(csv.DictReader(handle))
    return {"available": True, "metrics": metrics, "external_metrics": external_metrics, "candidates": candidates}
