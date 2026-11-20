from __future__ import annotations

import csv
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def rows(path: Path):
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def norm(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.casefold())


def snapshot(row: dict[str, str]):
    path = Path(row["snapshot_path"])
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8")).get("payload")


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    status_rows = rows(root / "reports/top10_kg/external_source_status.csv")
    top10 = rows(root / "experiments/final_results/results/final_top10.csv")
    existing = {row["pert_id"]: row for row in rows(root / "experiments/final_results/mechanism/final_neo4j_drug_mapping.csv")}
    by_drug: dict[str, dict[str, dict[str, str]]] = {}
    for row in status_rows:
        by_drug.setdefault(row["pert_id"], {})[row["source"]] = row

    identity: list[dict[str, str]] = []
    records: list[dict[str, str]] = []
    report_dir = root / "reports/top10_kg/drug_reports"
    report_dir.mkdir(parents=True, exist_ok=True)
    for item in top10:
        pert_id, name = item["pert_id"], item["drug_name"]
        source_rows = by_drug.get(pert_id, {})
        usable = lambda source: source_rows.get(source, {}).get("status") in {"ok", "cached"}
        pubchem = snapshot(source_rows["pubchem"]) if usable("pubchem") else None
        properties = (pubchem or {}).get("PropertyTable", {}).get("Properties", []) if isinstance(pubchem, dict) else []
        property_row = properties[0] if len(properties) == 1 else {}
        chembl = snapshot(source_rows["chembl"]) if usable("chembl") else None
        chembl_rows = []
        if isinstance(chembl, dict) and chembl.get("molecule_chembl_id"):
            chembl_rows = [chembl]
        elif isinstance(chembl, dict):
            chembl_rows = [row for row in chembl.get("molecules", []) if norm(row.get("pref_name") or "") == norm(name) and row.get("molecule_type") == "Small molecule"]
        chembl_rows = [row for row in chembl_rows if row.get("molecule_structures", {}).get("standard_inchi_key")]
        pubchem_key = property_row.get("InChIKey", "")
        matching_chembl = [row for row in chembl_rows if not pubchem_key or row.get("molecule_structures", {}).get("standard_inchi_key") == pubchem_key]
        previous = existing.get(pert_id, {})
        previous_exact = previous.get("neo4j_mapping", "").lower().startswith("exact")
        if previous_exact:
            mapping_status = "exact"
        elif len(matching_chembl) == 1 and pubchem_key:
            mapping_status = "exact_external_confirmed"
        elif len(properties) == 1:
            mapping_status = "external_candidate_manual_review"
        else:
            mapping_status = "unmatched"
        chembl_id = (matching_chembl[0].get("molecule_chembl_id") if len(matching_chembl) == 1 else "") or previous.get("graph_drug_ids", "")
        identity.append({"pert_id": pert_id, "pert_iname": name, "canonical_name": property_row.get("Title", name), "aliases": ";".join(sorted({row.get("molecule_synonym", "") for row in (matching_chembl[0].get("molecule_synonyms", []) if matching_chembl else []) if row.get("molecule_synonym")})), "chembl_id": chembl_id, "pubchem_cid": str(property_row.get("CID", "")), "inchikey": pubchem_key or previous.get("inchi_key", ""), "drugbank_id": "", "mapping_status": mapping_status, "mapping_evidence": "; ".join(source_rows[source].get("snapshot_path", "") for source in ("pubchem", "chembl") if source_rows.get(source, {}).get("status") == "ok"), "review_status": "verified_existing_graph" if previous_exact else ("external_structure_match" if mapping_status == "exact_external_confirmed" else "manual_review_required")})
        for source, row in source_rows.items():
            if row.get("status") in {"ok", "cached"}:
                records.append({"pert_id": pert_id, "drug_name": name, "source": source, "source_run_id": row.get("run_id", ""), "source_record_id": row.get("snapshot_path", "").split("\\")[-1], "snapshot_path": row.get("snapshot_path", ""), "evidence_type": "identity" if source in {"pubchem", "chembl"} else "literature_search", "validation_status": "raw_snapshot_validated"})
        gaps = [f"{source}:{row['status']}" for source, row in sorted(source_rows.items()) if row.get("status") not in {"ok", "cached"}]
        special = "；注意：iniparib 的 PARP 抑制机制存在争议，不能从名称或筛选分数确认。" if name.casefold() == "iniparib" else "；注意：doxorubicin 已有乳腺癌临床使用背景，本项目结果不是首次治疗发现。" if name.casefold() == "doxorubicin" else ""
        (report_dir / f"{int(item['rank']):02d}_{name.replace(' ', '_')}.md").write_text("\n".join([f"# {item['rank']}. {name}", "", f"- LINCS pert_id：`{pert_id}`", f"- WTCS：`{item['WTCS_median']}`（表达逆转关联，不是疗效证明）", f"- 身份状态：`{mapping_status}`", f"- ChEMBL：`{chembl_id or '未确认'}`；PubChem CID：`{property_row.get('CID', '未确认')}`；InChIKey：`{pubchem_key or previous.get('inchi_key', '未确认')}`", f"- 本次外部来源状态：" + "；".join(f"{source}={row['status']}" for source, row in sorted(source_rows.items())), f"- 未解决来源：{', '.join(gaps) if gaps else '无'}", "", "## 解释边界", "当前档案只记录已返回且保存原始快照的来源结果。数据库查询、PubMed 检索、S1/S2 表达交集和图谱路径不能单独升级为因果机制或临床疗效。" + special, ""]), encoding="utf-8")

    output = root / "data/processed/top10_kg"
    output.mkdir(parents=True, exist_ok=True)
    for path, data in [(output / "top10_external_identity.csv", identity), (output / "top10_external_records.csv", records)]:
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(data[0]))
            writer.writeheader(); writer.writerows(data)
    exact_after = sum(row["mapping_status"] in {"exact", "exact_external_confirmed"} for row in identity)
    (root / "reports/top10_kg/after_external_metrics.json").write_text(json.dumps({"top10_count": len(identity), "exact_or_external_confirmed_identity_count": exact_after, "exact_or_external_confirmed_identity_rate": exact_after / len(identity), "external_records": len(records), "source_status_rows": len(status_rows), "formal_graph_imported": False, "interpretation": "外部快照已规范化，但在 Neo4j 导入前仍需人工/规则复核；这些记录不自动改变正式图谱。"}, ensure_ascii=False, indent=2), encoding="utf-8")
    (root / "reports/top10_kg/before_after_comparison.md").write_text(f"# 建设前后对比\n\n- 建设前精确身份：5/10。\n- 外部快照后身份：{exact_after}/10（其中 external_candidate_manual_review 不计入确认）。\n- 外部来源归档记录：{len(records)} 条；成功/失败/跳过详见 `external_source_status.csv`。\n- 直接靶点、通路和完整路径仍保持建设前正式图谱口径：5/10、5/10、5/10。\n- Neo4j 正式增量导入：尚未执行；外部快照需要先通过语义和来源完整性复核。\n", encoding="utf-8")
    print(json.dumps({"identity_rows": len(identity), "exact_or_external_confirmed": exact_after, "external_records": len(records)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
