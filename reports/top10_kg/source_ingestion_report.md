# 外部来源补全报告

本次运行生成 60 条来源状态记录；PubChem、ChEMBL、PubMed 以及部分 Reactome 返回并保存原始快照，可用外部记录共 35 条。失败或跳过来源不会进入正式图谱事实。

DGIdb 当前接口返回 HTML 应用页而非 JSON；Open Targets 因项目疾病 `MONDO:0007254` 没有安全的 EFO 映射而跳过；Reactome 对已有正式 target_symbol 的 5 个候选成功或命中缓存，其余 5 个保持跳过。

状态明细见 `external_source_status.csv`；所有成功快照均保留原始 URL、payload 和 run_id。

已纳入的本地来源：OptimusKG 3.2、GSE42568 S1、LINCS/GSE70138 S2、现有 Final05 结果。
