# Top 10 知识图谱建设前审计

生成时间：2026-11-20T10:27:25.598179+00:00

## 基线指标

- 身份精确映射：5/10
- 当前图谱有直接靶点记录：5/10
- 当前图谱有靶点—通路连接：5/10
- 有疾病上下文证据的完整路径：5/10

## 逐药物缺口

- 1. **ponatinib** (`BRD-K44227013`)：身份 `exact`；直接靶点 21；通路 99；证据 ID 251；缺口：无
- 2. **mocetinostat** (`BRD-K16485616`)：身份 `exact`；直接靶点 5；通路 37；证据 ID 79；缺口：无
- 3. **MK-2461** (`BRD-K56405753`)：身份 `unmatched`；直接靶点 0；通路 0；证据 ID 0；缺口：identity_not_exactly_mapped, no_direct_target_evidence_in_current_graph, no_target_pathway_connection_in_current_graph, no_disease_context_evidence_on_path, no_traceable_evidence_id
- 4. **doxorubicin** (`BRD-K92093830`)：身份 `exact`；直接靶点 31；通路 88；证据 ID 224；缺口：无
- 5. **rebastinib** (`BRD-K76694128`)：身份 `unmatched`；直接靶点 0；通路 0；证据 ID 0；缺口：identity_not_exactly_mapped, no_direct_target_evidence_in_current_graph, no_target_pathway_connection_in_current_graph, no_disease_context_evidence_on_path, no_traceable_evidence_id
- 6. **PHA-767491** (`BRD-K50000283`)：身份 `unmatched`；直接靶点 0；通路 0；证据 ID 0；缺口：identity_not_exactly_mapped, no_direct_target_evidence_in_current_graph, no_target_pathway_connection_in_current_graph, no_disease_context_evidence_on_path, no_traceable_evidence_id
- 7. **iniparib** (`BRD-K11153516`)：身份 `exact`；直接靶点 1；通路 40；证据 ID 81；缺口：无
- 8. **balaglitazone** (`BRD-A00147595`)：身份 `exact`；直接靶点 3；通路 82；证据 ID 167；缺口：无
- 9. **PFI-1** (`BRD-K13094524`)：身份 `unmatched`；直接靶点 0；通路 0；证据 ID 0；缺口：identity_not_exactly_mapped, no_direct_target_evidence_in_current_graph, no_target_pathway_connection_in_current_graph, no_disease_context_evidence_on_path, no_traceable_evidence_id
- 10. **JNJ-26481585** (`BRD-K83837640`)：身份 `unmatched`；直接靶点 0；通路 0；证据 ID 0；缺口：identity_not_exactly_mapped, no_direct_target_evidence_in_current_graph, no_target_pathway_connection_in_current_graph, no_disease_context_evidence_on_path, no_traceable_evidence_id

## 判定边界

当前图谱中的数据库断言、S1 交集和 LINCS 表达响应不能直接升级为因果关系或临床疗效结论。
