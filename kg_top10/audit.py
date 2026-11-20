from __future__ import annotations

import csv
import hashlib
import json
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


TOP10_RELATIVE = Path("experiments/final_results/results/final_top10.csv")
MAPPING_RELATIVE = Path("experiments/final_results/mechanism/final_neo4j_drug_mapping.csv")
TARGET_RELATIVE = Path("experiments/final_results/mechanism/final_neo4j_direct_targets.csv")
PATH_RELATIVE = Path("experiments/final_results/mechanism/top10_mechanism_paths.csv")
EVIDENCE_RELATIVE = Path("experiments/final_results/mechanism/top10_evidence_citations.csv")


@dataclass(frozen=True)
class CandidateAudit:
    rank: int
    pert_id: str
    drug_name: str
    mapping_status: str
    graph_drug_id: str | None
    inchikey: str | None
    direct_target_count: int
    pathway_count: int
    evidence_count: int
    complete_path: bool
    evidence_complete: bool
    gaps: tuple[str, ...]


def _read_csv(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        return []
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _unique(values: list[str | None]) -> list[str]:
    return sorted({value.strip() for value in values if value and value.strip()})


def _sha256(path: Path) -> str | None:
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_inputs(repo_root: Path) -> dict[str, list[dict[str, str]]]:
    paths = {
        "top10": repo_root / TOP10_RELATIVE,
        "mapping": repo_root / MAPPING_RELATIVE,
        "targets": repo_root / TARGET_RELATIVE,
        "paths": repo_root / PATH_RELATIVE,
        "evidence": repo_root / EVIDENCE_RELATIVE,
    }
    return {name: _read_csv(path) for name, path in paths.items()}


def _mapping_status(row: dict[str, str] | None) -> str:
    if row is None:
        return "unmatched_no_mapping_record"
    raw = row.get("neo4j_mapping", "").strip().lower()
    if raw.startswith("exact"):
        return "exact"
    if "ambiguous" in raw:
        return "ambiguous"
    return "unmatched"


def _candidate_audits(inputs: dict[str, list[dict[str, str]]]) -> list[CandidateAudit]:
    mapping_by_pert = {row.get("pert_id", ""): row for row in inputs["mapping"]}
    targets_by_pert: dict[str, list[dict[str, str]]] = defaultdict(list)
    paths_by_pert: dict[str, list[dict[str, str]]] = defaultdict(list)
    evidence_by_pert: dict[str, set[str]] = defaultdict(set)
    for row in inputs["targets"]:
        targets_by_pert[row.get("pert_id", "")].append(row)
        evidence_by_pert[row.get("pert_id", "")].update(_unique([row.get("target_evidence_ids")]))
    for row in inputs["paths"]:
        paths_by_pert[row.get("pert_id", "")].append(row)
        evidence_by_pert[row.get("pert_id", "")].update(
            _unique([row.get("target_evidence_ids"), row.get("pathway_evidence_ids"), row.get("disease_context_evidence_ids")])
        )
    for row in inputs["evidence"]:
        evidence_by_pert[row.get("pert_id", "")].update(_unique([row.get("evidence_id"), row.get("evidence_ids")]))

    audits: list[CandidateAudit] = []
    for row in inputs["top10"]:
        pert_id = row.get("pert_id", "")
        mapping = mapping_by_pert.get(pert_id)
        targets = targets_by_pert[pert_id]
        paths = paths_by_pert[pert_id]
        target_ids = _unique([item.get("target_gene_id") for item in targets])
        pathway_ids = _unique([item.get("pathway_id") for item in paths])
        gaps: list[str] = []
        status = _mapping_status(mapping)
        if status != "exact":
            gaps.append("identity_not_exactly_mapped")
        if not target_ids:
            gaps.append("no_direct_target_evidence_in_current_graph")
        if not pathway_ids:
            gaps.append("no_target_pathway_connection_in_current_graph")
        if not any(item.get("disease_context_evidence_ids", "").strip() for item in paths):
            gaps.append("no_disease_context_evidence_on_path")
        if not evidence_by_pert[pert_id]:
            gaps.append("no_traceable_evidence_id")
        audits.append(CandidateAudit(
            rank=int(row.get("rank") or 0), pert_id=pert_id, drug_name=row.get("drug_name", ""),
            mapping_status=status, graph_drug_id=(mapping or {}).get("graph_drug_ids") or None,
            inchikey=(mapping or {}).get("inchi_key") or None, direct_target_count=len(target_ids),
            pathway_count=len(pathway_ids), evidence_count=len(evidence_by_pert[pert_id]),
            complete_path=bool(target_ids and pathway_ids and any(item.get("disease_context_evidence_ids", "").strip() for item in paths)),
            evidence_complete=bool(evidence_by_pert[pert_id] and not gaps), gaps=tuple(gaps),
        ))
    return audits


def _write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_reports(repo_root: Path, audits: list[CandidateAudit], inputs: dict[str, list[dict[str, str]]], output_dir: Path) -> None:
    report_dir = repo_root / "reports" / "top10_kg"
    report_dir.mkdir(parents=True, exist_ok=True)
    exact = sum(item.mapping_status == "exact" for item in audits)
    direct = sum(item.direct_target_count > 0 for item in audits)
    pathway = sum(item.pathway_count > 0 for item in audits)
    complete = sum(item.complete_path for item in audits)
    evidence_complete = sum(item.evidence_complete for item in audits)
    now = datetime.now(timezone.utc).isoformat()
    metrics = {
        "status": "audited", "generated_at": now, "top10_count": len(audits),
        "identity_exact_count": exact, "identity_exact_rate": exact / len(audits) if audits else 0,
        "direct_target_count": direct, "direct_target_rate": direct / len(audits) if audits else 0,
        "pathway_count": pathway, "pathway_rate": pathway / len(audits) if audits else 0,
        "complete_mechanism_path_count": complete, "complete_mechanism_path_rate": complete / len(audits) if audits else 0,
        "evidence_complete_archive_count": evidence_complete, "source_row_counts": {key: len(value) for key, value in inputs.items()},
        "source_sha256": {str(path.relative_to(repo_root)): _sha256(path) for path in [repo_root / TOP10_RELATIVE, repo_root / MAPPING_RELATIVE, repo_root / TARGET_RELATIVE, repo_root / PATH_RELATIVE, repo_root / EVIDENCE_RELATIVE]},
        "interpretation": "这些是当前版本的证据覆盖指标，不是药物疗效概率。",
    }
    _write_json(report_dir / "baseline_metrics.json", metrics)
    missing_rows = [{**asdict(item), "gaps": ";".join(item.gaps)} for item in audits if item.gaps]
    _write_csv(report_dir / "top10_missing_evidence.csv", missing_rows, list(missing_rows[0].keys()) if missing_rows else list(asdict(audits[0]).keys()) + ["gaps"])
    baseline_lines = ["# Top 10 知识图谱建设前审计", "", f"生成时间：{now}", "", "## 基线指标", "", f"- 身份精确映射：{exact}/{len(audits)}", f"- 当前图谱有直接靶点记录：{direct}/{len(audits)}", f"- 当前图谱有靶点—通路连接：{pathway}/{len(audits)}", f"- 有疾病上下文证据的完整路径：{complete}/{len(audits)}", "", "## 逐药物缺口", ""]
    for item in audits:
        baseline_lines.append(f"- {item.rank}. **{item.drug_name}** (`{item.pert_id}`)：身份 `{item.mapping_status}`；直接靶点 {item.direct_target_count}；通路 {item.pathway_count}；证据 ID {item.evidence_count}；缺口：{', '.join(item.gaps) if item.gaps else '无'}")
    baseline_lines += ["", "## 判定边界", "", "当前图谱中的数据库断言、S1 交集和 LINCS 表达响应不能直接升级为因果关系或临床疗效结论。"]
    (report_dir / "baseline_audit.md").write_text("\n".join(baseline_lines) + "\n", encoding="utf-8")

    identity_rows = []
    mapping_by_pert = {row.get("pert_id", ""): row for row in inputs["mapping"]}
    for item in audits:
        source = mapping_by_pert.get(item.pert_id, {})
        identity_rows.append({"pert_id": item.pert_id, "pert_iname": item.drug_name, "canonical_name": item.drug_name, "aliases": "", "chembl_id": item.graph_drug_id or "", "pubchem_cid": "", "inchikey": item.inchikey or "", "drugbank_id": "", "mapping_status": item.mapping_status, "mapping_evidence": "OptimusKG 3.2 exact InChIKey audit" if item.mapping_status == "exact" else "当前图谱无 exact InChIKey 记录；需外部解析或人工复核", "review_status": "automatically_verified_against_existing_graph" if item.mapping_status == "exact" else "manual_review_required"})
    _write_csv(output_dir / "top10_drug_identity.csv", identity_rows, list(identity_rows[0].keys()))
    (report_dir / "identity_mapping_report.md").write_text("# Top 10 身份映射报告\n\n本报告仅登记当前仓库已有的稳定标识符和图谱匹配结果；未联网成功或没有可核实记录的字段留空。\n\n" + "\n".join(f"- {row['canonical_name']}：{row['mapping_status']}；{row['mapping_evidence']}" for row in identity_rows) + "\n", encoding="utf-8")
    (report_dir / "source_ingestion_report.md").write_text("# 外部来源补全报告\n\n当前运行生成的是离线基线和现有 OptimusKG 证据归档。ChEMBL、DGIdb、Reactome、Open Targets、PubChem、PubMed 适配器已提供缓存/重试/原始快照接口；在显式运行联网抓取前，不把未抓取内容计为新增证据。\n\n已纳入的本地来源：OptimusKG 3.2、GSE42568 S1、LINCS/GSE70138 S2、现有 Final05 结果。\n", encoding="utf-8")
    (report_dir / "evidence_quality_audit.md").write_text("# 证据质量审计\n\n- 核心关系必须携带 evidence ID；缺少证据 ID 的关系在专项报告中保留为缺口。\n- `transcriptomic_response`、`database_association` 与 `curated_mechanism` 不互相升级。\n- ER 阳性特异性证据与一般乳腺癌证据分开；本次离线审计不把一般疾病关联升级为 ER+ 特异证据。\n- iniparib 的 PARP 机制争议、doxorubicin 的既有临床使用背景保留在后续药物档案中。\n", encoding="utf-8")
    (report_dir / "pathway_analysis_report.md").write_text("# 机制路径审计\n\n当前路径来自已登记的药物—基因—S1 富集通路—疾病上下文交集。路径存在只表示可追溯证据共现，不自动表示药物抑制疾病通路。\n", encoding="utf-8")
    (report_dir / "top10_mechanism_summary.md").write_text("# Top 10 机制证据摘要\n\n" + "\n".join(f"- {item.rank}. {item.drug_name}：{item.direct_target_count} 个当前图谱靶点，{item.pathway_count} 条通路，证据 {item.evidence_count} 条，机制等级：{'A/B 候选' if item.complete_path else 'U/C，仍有缺口'}。" for item in audits) + "\n", encoding="utf-8")
    (report_dir / "before_after_comparison.md").write_text("# 建设前后对比\n\n当前仓库已完成建设前快照；外部补全尚未在本次离线运行中执行，因此新增证据计数为 0。后续每次适配器抓取应读取 `baseline_metrics.json` 并追加带 run_id 的增量统计，不能覆盖基线。\n", encoding="utf-8")
    (report_dir / "unresolved_evidence_gaps.md").write_text("# 未解决证据缺口\n\n" + "\n".join(f"- {item.drug_name}：{', '.join(item.gaps) if item.gaps else '当前离线输入未发现缺口'}" for item in audits) + "\n", encoding="utf-8")
    (report_dir / "final_acceptance_report.md").write_text("# Top 10 专项建设验收\n\n当前阶段完成：P0 基线审计、现有身份映射归档、证据缺口分药物输出、路径覆盖统计、离线验收报告。\n\n未宣称完成：外部 API 联网抓取、Neo4j 增量写入、外部文献全文核查。原因是本次运行只使用仓库已有的可验证输入，避免在没有成功来源快照时构造正式事实。\n\n验收门槛：核心关系必须来源可追溯；未满足的候选保持缺口状态。\n", encoding="utf-8")


def _write_claim_evidence_archive(output_dir: Path, inputs: dict[str, list[dict[str, str]]]) -> None:
    """Normalize existing graph assertions without upgrading their semantics."""
    claims: list[dict[str, str]] = []
    evidences: dict[str, dict[str, str]] = {}
    paths: list[dict[str, str]] = []
    for row in inputs["targets"]:
        assertion = {}
        try:
            assertion = json.loads(row.get("target_assertion_json", "{}"))
        except json.JSONDecodeError:
            pass
        relations = assertion.get("relation_assertions") or []
        relation_types = ";".join(sorted({str(item.get("relation", "")).strip() for item in relations if item.get("relation")})) or "UNSPECIFIED_ASSOCIATION"
        source_record_id = str(assertion.get("source_record_id") or "")
        claim_key = "|".join([row.get("pert_id", ""), row.get("target_gene_id", ""), relation_types, source_record_id])
        claim_id = hashlib.sha256(claim_key.encode()).hexdigest()
        evidence_ids = _unique([row.get("target_evidence_ids")])
        claims.append({"claim_id": claim_id, "subject_id": row.get("graph_drug_id", ""), "predicate": relation_types, "object_id": row.get("target_gene_id", ""), "status": "supported" if evidence_ids else "unresolved", "source_record_id": source_record_id, "evidence_ids": ";".join(evidence_ids), "semantic_note": "保留原始关系类别；不能由表达响应升级为直接靶向。"})
        for evidence_id in evidence_ids:
            evidences.setdefault(evidence_id, {"evidence_id": evidence_id, "source_name": ";".join(sorted({str(item.get("source", "")).strip() for item in relations if item.get("source")})) or "existing_graph", "source_record_id": source_record_id, "source_version": "OptimusKG 3.2", "source_url": ";".join(assertion.get("source_urls") or []), "evidence_type": "curated_mechanism" if any(str(item.get("relation", "")).upper() in {"TARGET", "INHIBITOR", "INHIBITS"} for item in relations) else "database_association", "support_direction": "supported"})
    for row in inputs["paths"]:
        path_key = "|".join([row.get("pert_id", ""), row.get("target_gene_id", ""), row.get("pathway_id", "")])
        paths.append({"path_id": hashlib.sha256(path_key.encode()).hexdigest(), "pert_id": row.get("pert_id", ""), "target_gene_id": row.get("target_gene_id", ""), "pathway_id": row.get("pathway_id", ""), "pathway_label": row.get("pathway_label", ""), "disease_context_evidence_ids": row.get("disease_context_evidence_ids", ""), "status": "traceable" if row.get("target_evidence_ids") and row.get("pathway_evidence_ids") else "partial"})
    if claims:
        _write_csv(output_dir / "top10_claims.csv", claims, list(claims[0].keys()))
    if evidences:
        evidence_rows = list(evidences.values())
        _write_csv(output_dir / "top10_evidence.csv", evidence_rows, list(evidence_rows[0].keys()))
    if paths:
        _write_csv(output_dir / "top10_mechanism_paths.csv", paths, list(paths[0].keys()))


def run_audit(repo_root: Path, output_dir: Path | None = None) -> dict[str, Any]:
    repo_root = repo_root.resolve()
    output_dir = (output_dir or repo_root / "data/processed/top10_kg").resolve()
    inputs = _load_inputs(repo_root)
    audits = _candidate_audits(inputs)
    output_dir.mkdir(parents=True, exist_ok=True)
    audit_rows = [{**asdict(item), "gaps": ";".join(item.gaps)} for item in audits]
    _write_csv(output_dir / "baseline_candidate_audit.csv", audit_rows, list(audit_rows[0].keys()))
    _write_claim_evidence_archive(output_dir, inputs)
    _write_reports(repo_root, audits, inputs, output_dir)
    return {"candidates": audit_rows, "output_dir": str(output_dir), "metrics": json.loads((repo_root / "reports/top10_kg/baseline_metrics.json").read_text(encoding="utf-8"))}
