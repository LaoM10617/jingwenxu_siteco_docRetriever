# 更新日志

## 未提交：CSV 计算正确性与确定性数值工具（2026-10-15）

对应 `problems-to-be-solved.md` 第 3、4 步（P8、P9、P10、P12 的主要部分）。目标：Ökobaudat 演示中均值、求和、排序、图表稳定且精确。

- **沙箱工具**（`csv_runtime.py`，需重建 runner 镜像）：
  - `decimals()` 默认 `decimal_separator='auto'`，按整列推断，列内同时出现 `.` 和 `,` 时报错；支持科学计数法（`7,41E-20`）；接受单个字符串、整数和 Decimal，浮点仍拒绝。
  - 新增 `exact_mean()`（34 位有效数字）。
  - 新增 `top_n()`：排除空值，保留边界并列，拒绝字符串，避免按文本排序；返回诊断。
- **执行前处理**（`csv_specialist.py`）：
  - 前置导入 `Decimal`、pandas 和全部辅助函数。
  - 删除模型臆造的 `from <错误模块> import <辅助函数名>` 行。
- **概览**：每列附整列数值格式 `numeric`（小数分隔符、是否含科学计数法、非数值个数）。
- **提示词**：
  - 统一用 `decimals` / `exact_sum` / `exact_mean` / `top_n`，禁止 float 和自写解析；计数保持整数；旧结果先转换再比较。
  - 用户给出的筛选值精确匹配，不得扩展。
  - unit 必须填写，无法确定时写明“单位未在数据中给出”。
  - review 阶段逐项核对上述规则。
- **回答格式**：表格下方确定性附加 `Filters / Grouped by / Aggregations / Assumptions / Unit / Source rows`，内容取自已记录的计划，不增加模型调用。
- **测试**：全量 574 passed，3 failed（同前，本机有密钥所致）；Docker 运行时测试 5 passed（runner `sha256:4b314f0c…`）。
- **真实验证**（本地后端 + host worker + Gemini，Ökobaudat，与 `truth.json` 比对）：第二轮 8 题 7 题正确（A1-A3 精确筛选、均值/最小/最大、一级分类均值 + 图表、科学计数法求和、最低 5 个、前 10 名含并列、分组求和 + 图表）。唯一失败的“在上一张表上筛选”修复后，连续两次 d3 → d4 均正确。
- **部署**：`.env` 的 `EXECUTION_IMAGE` 已更新为 `sha256:4b314f0c…`（原文件备份在会话临时目录）。worker 启动命令也要使用这个镜像 ID；Docker 后端需重新构建。

## 未提交：执行任务迁移、载荷生命周期、脚本前置导入（2026-10-15）

对应 `problems-to-be-solved.md` 的 P1、P2/P3/P4/P13（不含去重）、P10。用户确认：迁移保留结果缓存；暂不做输入去重。

- **迁移**（`execution_jobs.py`）：启动时检测旧的 `payload` 列，同一事务内重建表。有 `result` 的行保留，`task_json` 取自 `json_extract(payload,'$.task')`；未完成的行丢弃。
- **载荷生命周期**：`execute()` 的 `finally` 在所有退出路径删除载荷文件；`claim()` 在租约提交后读不到文件时返回无任务；启动时清空 `execution_payloads/`（含 `*.json.tmp`）。删除会话、永久删除文档、任务被拒、命中缓存都不再留下文件。
- **前置导入**（`csv_specialist.py`）：执行前在生成的脚本前加 `import pandas as pd` 与 `from siteco_analysis import …`，避免第一次执行出现 `NameError`。
- **测试**：相关 6 个测试文件 74 passed（新增迁移测试；载荷删除断言；更新脚本断言）。迁移在 `data/docker-e2e/app.sqlite3` 的**副本**上验证：2 个未完成行被丢弃，`integrity_check` ok，原库未改。
- **真实验证**（本地后端 + host worker + Gemini，Ökobaudat CSV，2 个问题）：A1-A3 按单位计数正确，只执行 1 次，每轮结束后载荷目录为空。GWP 统计问题失败：模型写了不存在的 `from decimals import decimals`，又未指定逗号小数分隔符，属于 P9/P11，本轮未处理。
- **未做**：Docker 后端验证、全量 pytest、前端测试。

## SQLite 并发与 CSV 执行任务存储（2026-10-15，提交 `4774fd4`）

基线 `main` / `0660cc3`，以下改动均在工作区，**尚未 commit**。目标是消除 CSV
计算期间的 SQLite 锁竞争：大体积脚本与 CSV 输入曾整块写入 `execution_jobs`
表，写事务持锁时间随输入规模增长，同时轮询、worker 领取和心跳都在抢唯一的写锁，
各模块的 busy timeout 又不一致（显式 30 s 与 Python 默认 5 s 混用），导致同一
竞争在不同位置表现为快速失败或长时间卡顿。

### 状态标注

| 项目 | 状态 |
| --- | --- |
| 下列后端改动 | 代码已实现 |
| 后端全量 pytest | 572 passed / 3 failed / 15 skipped（见“测试”），失败项与本次改动无关 |
| 前端 Playwright 新用例 | 已编写，本次整理**未运行** |
| Docker 后端 + host worker + 真实 CSV 计算 | **未在真实环境验证** |
| 旧数据库 `execution_jobs` 迁移 | **缺失**，见“已知问题 1” |

### 1. 统一 SQLite 连接入口（新增 `backend/app/db.py`）

- 新增 `connect(database, *, timeout=BUSY_TIMEOUT_SECONDS, **kwargs)`，
  `BUSY_TIMEOUT_SECONDS = 30`。
- 以下模块的 `sqlite3.connect(...)` 全部改为 `app.db.connect`：
  `artifacts.py`、`conversation_runs.py`（业务库、会话锁、LangGraph checkpoint
  连接）、`csv_store.py`、`documents.py`、`embeddings.py`、`execution_jobs.py`、
  `host_worker.py`、`pdf_store.py`、`retrieval/pdf.py`、`run_cleanup.py`、
  `sessions.py`。其中 `csv_store`、`documents`、`embeddings`、`pdf_store`、
  `retrieval/pdf`、`run_cleanup` 原先未传 timeout，实际使用 5 s 默认值，本次统一为 30 s。
- 有意保留的直接连接：`conversation_runs._running` 与 `host_worker.exclusive`
  使用 `timeout=0` 做非阻塞试锁；`main.py` 启动检查使用 `timeout=1` 快速失败。
- 未迁移：`agent_state.py` 三处仍直接 `sqlite3.connect(..., timeout=30)`，数值一致，
  但未经统一入口。

### 2. 业务库启用 WAL（`main.py`）

- 启动检查时对 `DATA_DIR/app.sqlite3` 执行 `PRAGMA journal_mode=WAL` 与
  `PRAGMA synchronous=NORMAL`。WAL 模式写入数据库文件并持久生效，读者不再被写者阻塞。
- `conversation-checkpoints.sqlite3` 与 worker 自己的数据库**未切换**，仍为默认日志模式。
- 新增 `siteco.storage` logger（ERROR 级、不向上传播）：`sqlite3.Error` / `OSError`
  返回 503 `storage_unavailable` 之前记录请求方法、路径与异常 `repr`，便于把用户看到
  的 503 与具体锁或 IO 错误对应起来。

### 3. 执行任务载荷移出 SQLite（`execution_jobs.py`、`run_cleanup.py`）

- **表结构变更**：`execution_jobs.payload`（含 task、script、inputs、image）改名为
  `task_json`，只保存 `task` 部分（几 KB），供可用性检查和来源失效匹配使用。
- 脚本与 CSV 输入（上限 64 MiB）写入 `DATA_DIR/execution_payloads/<job_id>.json`，
  先写 `.tmp` 再 `replace`，保证原子性；写文件发生在**任何 SQLite 事务之外**，
  写事务只触及小的固定列。
- `claim()`：在写事务内只完成选取与租约写入；事务提交、锁释放后再读取载荷文件返回给 worker。
- `execute()` 轮询：改为不加 `BEGIN IMMEDIATE` 的普通读事务（`_db(write=False)`）；
  仅在检测到租约过期或已中断时升级为写事务，并在写事务内重新检查（期间租约可能已续期
  或结果已写入），避免误判中断。
- 清理：`purge_session` / `purge_source` 删除行后同步删除对应载荷文件；
  `run_cleanup.invalidate_source` 的 JSON 路径改为 `json_each(task_json, '$.scope.documents')`，
  只删行不删文件。`ExecutionJobs` 构造时扫描 `execution_payloads/*.json`，
  删除无对应行的孤儿文件（覆盖原始 SQL 删除和 `ON DELETE CASCADE` 等不经过文件系统的路径）。

### 4. 会话锁与 worker 超时

- `ConversationRuns`（`conversation_runs.py`）：`inspect()` 移到会话锁之外执行，
  它只读状态组装响应，不必在持锁期间进行。其余运行逻辑未改，仅缩进调整
  （由 early return 改为条件块）。
- `host_worker.WorkerClient` HTTP 超时由 10 s 调为 35 s，长于后端 30 s busy timeout：
  锁竞争下较慢的 claim/heartbeat 会收到明确的错误响应，而不是客户端先放弃、
  服务端事务却已提交（例如租约已写入但 worker 不知情）。

### 5. 同一工作区内的其他未提交改动（非后端，简述）

- 前端品牌名改为 “Intelligent Document Analysis”。
- 回答来源按 文档 + 页码/记录 去重；单一来源直接显示预览按钮，多来源折叠为
  “Open original source” 列表，标签为 `文件名 · Page N` / `Record N`；
  不再默认展开提取文本。历史答案来源不可用时不显示来源入口。
- 警告去重并折叠到 “See warnings”，带页码前缀。
- `frontend/tests/graph-chat.spec.mjs` 新增对应用例（未运行）。
- 未跟踪：`.vscode/`、`test_data/ZM-I/`（新样本 PDF/CSV/XLSX）、`worker.txt`
  （本地 worker 启动命令，通过 `Read-Host` 读取 token，不含密钥值）。

### 测试

```powershell
.venv/Scripts/python.exe -m pytest -q -p no:cacheprovider
```

结果：**572 passed, 3 failed, 15 skipped**（202 s，Windows）。3 个失败：

- `test_document_http.py::test_pdf_coverage_and_unpublished_evidence_survive_restart`
- `test_generation.py::test_transport_timeout_and_missing_key_are_explicit`
- `test_settings.py::test_probe_uses_fixed_payload_once_and_does_not_apply`

均断言“缺少密钥”的行为，而本机环境变量中已设置 `VOYAGE_API_KEY` / `GEMINI_API_KEY` /
`GROQ_API_KEY`，判断为环境依赖，与本次 SQLite 改动无关；未在无密钥环境中重跑确认。
现有测试覆盖新表结构的读写路径，但**没有**专门针对载荷文件生命周期、孤儿扫描、
轮询读/写升级或 WAL 的新增测试。

### 已知问题与待办

1. **缺少 `execution_jobs` 迁移（阻塞部署）。** 建表语句为 `CREATE TABLE IF NOT EXISTS`，
   旧库保留 `payload` 列，首次 `INSERT ... task_json` 会失败并表现为 503
   `storage_unavailable`，CSV 计算不可用。只读核对：当前 `HOST_DATA_DIR=./data/docker-e2e`
   的 `app.sqlite3` 仍为旧结构（含 `payload` 列，journal_mode=delete）；
   `data/local-e2e`、`data/runtime` 尚无该表，不受影响。其他表在构造函数中用
   `ALTER TABLE` 迁移，建议同样处理（执行任务为可重建的临时状态，也可在备份后直接重建该表）。
2. **永久删除后载荷暂留磁盘。** `invalidate_source` 只删行，含 CSV 原始内容的载荷文件
   要到下次进程启动的孤儿扫描才删除，与“永久删除”的语义存在时间差。
3. **少量孤儿文件。** `execute()` 在写入载荷后若因 `source_unavailable` 或探索预算拒绝而
   未插入行，或命中已完成结果缓存，文件仍保留到下次启动扫描；扫描只匹配 `*.json`，
   崩溃遗留的 `*.json.tmp` 不会被清除。
4. **WAL 部署注意。** 数据库旁会出现 `app.sqlite3-wal` / `-shm`；备份须在停服后进行或同时
   复制这些文件。Docker Desktop（Windows）bind mount 上的 WAL 共享内存行为未验证。
   `deployment.md` 尚未更新。
5. `agent_state.py` 未使用统一连接入口（见第 1 节）。
6. 需要 Docker 后端 + host worker + 真实 CSV 计算的端到端验证，以及前端 Playwright 回归。
