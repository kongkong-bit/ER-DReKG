# 运行与复现说明

本文说明代码环境和本地数据配置。所有路径均相对于仓库根目录。

## 软件环境

- Windows 10/11（当前维护环境）
- Python 3.12；后端依赖和锁文件：`backend/pyproject.toml`、`backend/uv.lock`
- Node.js/npm；前端依赖和锁文件：`frontend/package.json`、`frontend/package-lock.json`
- Docker Desktop；PostgreSQL 17、Neo4j 5 Community（见 `docker-compose.yml`）
- S1/R 富集分析需 R 与 Bioconductor 依赖，具体版本记录在 `experiments/s1_pathway_enrichment/environment_manifest.json`

## 配置与启动

1. 复制 `.env.example` 为根目录 `.env`，为 PostgreSQL 和 Neo4j 设置本机密码。`.env` 已被忽略，不能提交。
2. 在仓库根目录运行 `docker compose up -d postgres neo4j`。
3. 在 `backend/` 安装依赖并迁移数据库：

   ```powershell
   uv sync
   uv run alembic upgrade head
   uv run uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
   ```

4. 在 `frontend/` 运行 `npm ci` 和 `npm run dev -- --host 127.0.0.1 --port 5173`。
5. 图谱模式由 `.env` 中 `GRAPH_SOURCE` 等变量决定。CSV 离线模式所需图谱数据目录由 `GRAPH_DATA_DIR` 指定；Neo4j 模式需要先构建/导入图谱，相关脚本位于 `kg/scripts/`。

## 数据准备

代码仓库不保证包含所有原始数据。开始复现实验前，依据各阶段报告的数据清单准备对应输入：

- S1：GSE42568 表达/limma 输入。报告及既有结果位于 `s1_初步_gse42568_limma/` 和 `experiments/s1_pathway_enrichment/`。
- S2：GSE70138 Level 5 GCTX 和签名、基因、扰动、质量元数据。GCTX 体积数 GB，需从 GEO 获取；文件名、字段和筛选条件见 `s2_lincs/reports/00_data_audit.md` 与 `s2_lincs/reports/formal_s2_screen_report.md`。
- 外部验证：按 Exp010/Exp011 报告中的数据来源和清单获取输入。不得将本机缓存或下载文件误认为代码仓库提供的数据。

请遵循 `docs/audit/source_license_audit.md` 和原数据集的引用、许可要求。忽略规则排除了大型输入、上传数据和本地缓存；小型审计报告、脚本及精选结果可纳入版本控制。

## 运行分析与验证

- S2 评分与单元测试脚本、参数和数据依赖说明位于 `s2_lincs/`。
- S1 通路分析脚本、R 环境清单、输入与报告位于 `experiments/s1_pathway_enrichment/`。
- 平台 API 测试位于 `backend/tests/`；用 `cd backend; uv run pytest` 运行。
- 前端构建可在 `frontend/` 使用 `npm ci`、`npm run build`。

阶段结果与局限以对应报告为准。当前正式候选仍是计算初筛结果，尚无新增实验验证。
