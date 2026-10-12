# 阶段 C 实施与交接记录

日期：2026-10-12。状态：代码已实现、自动化验证与双轴审查通过、真实 Gemini / Voyage PDF 链路已验证。用户授权直接实施 C，完成后停止，不自动推进 D。

后续接手更正（2026-10-12）：用户已将 A–C 提交为 `e389512` 并推送。本轮 D 接手核对 main、HEAD 与本地 origin/main 均为该提交，初始工作区干净。下文“未提交／269d5fe”是阶段 C 当时快照，不能作为当前 Git 状态。旧运行容器仍未部署新架构。

## 1. 实现

- `conversation_runs.py`：LangGraph 主图，严格 Intent、版本化范围、用途／持续规则、指代线索、PDF 专业调度、澄清 interrupt、停止和显式恢复。app.sqlite3 为业务权威，conversation-checkpoints.sqlite3 为图恢复库。
- `pdf_specialist.py`：任务私有 LangGraph，复用混合检索、来源验证、页码／坐标预览和确定性数值工具；TaskPackage → TaskResult、证据与公开回答，诊断另存。
- `run_api.py`：新会话运行接口，4 线程执行；同 run 调度去重并覆盖 resume 与旧 worker 退出交错。主图同 session 跨进程串行锁独立于业务库事务。
- `run_cleanup.py`：会话删除及来源永久删除的 checkpoint 清理意图；活跃执行结束或启动后重试，不触发模型。永久删除清理任务输出、证据、技术事件，历史回答显示来源不可用。
- SessionStore 的规则变更有幂等 operation_id；规则／消息／焦点和 ArtifactStore 发布可组合入调用方事务。规则更新、结果发布均在事务内校验停止，发布同时登记产物、消息、证据、focus、完成状态与用户事件。
- 前端 useChat/ChatThread/App 使用新会话接口；会话不再 24 小时过期，刷新读取服务器历史，支持无选材提问、澄清、停止、显式恢复和来源不可用提示。上传关联会话，本轮选材按 session 保存。
- RuntimeBindings 的脱敏快照增加限流行为。既有运行持有接受时绑定；重启显式恢复比较行为而非随机 revision；凭据不写业务库或 checkpoint。

## 2. 测试证据

| 检查 | 命令 | 结果 |
| --- | --- | --- |
| Windows 全量 | `.venv/Scripts/python.exe -m pytest -q` | 436 passed、11 skipped、10 subtests passed，164.68 秒 |
| 最后规则事务修复与新增用例 | `.venv/Scripts/python.exe -m pytest -q backend/tests/test_conversation_runs.py backend/tests/test_run_api.py` | 15 passed，9.41 秒；包含主图 11 + HTTP 4。此修复在 Windows 全量收集后加入，已定向回归 |
| Linux 最终全量 | `docker build --target test -t siteco-phase-c-tests -f backend/Dockerfile .` | 437 passed、11 skipped、10 subtests passed，89.54 秒；包含最终规则修复与新增用例 |
| 前端构建 | `npm run build`（frontend） | TypeScript 检查与 Vite 构建通过 |
| 浏览器交互／设置 | `node node_modules/@playwright/test/cli.js test tests/graph-chat.spec.mjs tests/settings.spec.mjs`（frontend） | 8 passed，9.0 秒，包含桌面与移动设置 |
| diff 检查 | `git diff --check` | 通过（仅现有 CRLF 提示） |

11 项跳过为执行器 Docker 集成测试，C 未改执行器；A 已在真实 Docker 独立通过，本阶段不重复宣称新测。首次最终浏览器重跑因沙箱内 Vite 与宿主浏览器网络隔离而 8 项连接超时；将同一临时 Vite 放到宿主 127.0.0.1 后 8 项全部通过，无产品代码绕过。

关键行为用例：

- 运行接收即保存用户消息、重复 request_id 幂等、跨 session 隔离。
- 自然语言解释的受控结构化输出验证本轮 A、持续 B、价格用途 C；新增 D 不改已定 B；移除 B 后拒绝扩大来源，明确本轮 A 可覆盖。
- 同会话追问使用 focus 解析对象，并重新调用专业图取证，不把旧 assistant 回答作为事实上下文。
- interrupt 重启后读取不调用模型；澄清答复幂等；停止后的待答澄清可继续填写。
- provider 阻塞期间停止，迟到结果不发布；规则提案期间资料改变则不写规则；运行中设置改变不影响已绑定配置，重启配置不同拒绝恢复。
- 真实子进程在业务发布后、checkpoint 完成前 `os._exit(73)`，重开仍仅一份结果，不重调模型。
- 人为卡住旧 worker 退出窗口，再 resume，任务不滞留 queued。
- SQLite checkpoint 清理失败保留持久意图；重试只清理不执行。源 PDF 永久删除后任务输出／证据／checkpoint 均清除，历史回答仍存在且来源不可用。
- PDF 子图测试使用真实解析／FAISS／FTS、受控模型，验证子集、停止、来源移除、引用拒绝、澄清和 W→kW 确定性换算。

## 3. 真实环境验证

命令：`.venv/Scripts/python.exe scripts/probe_stage_c.py`。

第一次执行被自动审批拦截（要求明确具体数据与第三方服务）。用户随后明确授权一次 `SITECO_Trunking_Systems_EN.pdf` + Gemini / Voyage 验证，按同一脚本执行通过；未扩大模型调用范围。

- 数据副本：`data/stage-c/20261012T145256771671Z/runtime`。原 `data/docker-e2e` 的 SQLite 用 backup API 只读复制，原件和索引／tokenizer 副本用于独立 uvicorn HTTP 服务。运行前后 4 份原件 SHA-256 一致。
- 回执：`data/stage-c/20261012T145256771671Z/receipt.json`；provider 日志：同目录 `server.log`，没有密钥值。
- Gemini `gemini-3.5-flash-lite`：intent 4.110 秒、answer 3.625 秒；Voyage `voyage-4` 查询嵌入：93 tokens、0.890 秒。未做批量评估，未真实调用 Groq；rerank 关闭，没有本阶段真实 rerank 验证。
- 真正走 HTTP → 主图 → PDF 图 → Voyage／Gemini → 原子结果发布。重复请求返回同 run；用户／开发者事件分别读取。
- 回答 3 条引用：DUS 31 最大 IP50（第 3 页）、Licross IP20–IP64（第 10 页）、Modario 31 IP20（第 21 页）。用 pypdfium2 从副本渲染三页并目视核对产品、文字及页码。该题验证局部事实检索，不代表整份 PDF 覆盖性总结。
- 临时 uvicorn 已终止。最后的停止／删除／调度竞态修复由自动化回归验证，没有重复付费调用。

## 4. 审查与处理

按 code-review 双轴审查执行，Standards 和 Spec 复核均无剩余已发现的阻塞项。修复：停止后澄清输入丢失、历史来源不可用提示缺失、恢复与 worker 退出竞态、规则更新迟到副作用、删除后的图派生缓存／checkpoint 清理。相应行为测试通过；最终全量结果仍须以下交接快照为准。

## 5. 边界和后续入口

- C 是主图 + PDF 事实检索纵向链路。新图对 CSV 请求给出明确尚未支持的澄清；通用 CSV／跨专业协作属于 D/F，覆盖性阅读属于 E，长会话摘要属于 F，后台探索属于 G。
- 旧 `/api/questions` 保留短期兼容精确 CSV、混合请求与分页；其旧状态表不属于新 session。新页面完全走新图。D 完成 CSV 迁移后应删除兼容入口及旧 worker/memory，不长期并存两套问答架构。
- 新页面只做协议适配；暂无会话列表／删除 UI、视觉改版或开发者标签页，后端已有相关基础接口。旧 UI 专属 Playwright 套件依赖旧 questions/sessionStorage/TTL 协议，保留为历史迁移参考；本阶段针对新图交互执行独立测试，不能把结果称为所有旧前端测试通过。
- 同步外部调用停止后可能等当前请求返回才能释放线程；不会继续发布或调新调用。每 run 总模型调用预算 6 次，单次显式执行期限 240 秒，PDF 子任务有独立更小预算；不是对所有任务的性能承诺。
- 新旧运行数据隔离；当前正在运行的 `document-chat-backend-1` / `document-chat-frontend-1` 未重新部署，仍是旧代码，健康状态保持。新实现已通过独立 HTTP／测试镜像验证，打开旧 8080 页面不代表新图已部署。
- 没有 commit/push。AGENTS.md 仍忽略且已读；所有 A/B 未提交改动保留。

## 6. 最终交接快照

- 分支 main，HEAD `269d5fe`；全部 A–C 实现与文档未提交，未 push。
- C 新增：conversation_runs/pdf_specialist/run_api/run_cleanup、对应 5 类测试文件及 publication transaction 测试、frontend/tests/graph-chat.spec.mjs、scripts/probe_stage_c.py、本文；更新 main/runtime_bindings/uploads/sessions/artifacts/session_api、前端 3 文件、session 测试、decisions-design/plan。A/B 既有未提交变更全部保留。
- 环境：Windows `.venv` Python 3.12.10；Linux Python 3.12.14；Node v24.19.0。`siteco-phase-c-tests:latest` image config digest `e5beae405b0a23dc868a40d4154d8e2db82704c1663675343f6d88468a6c0812`。
- 实际数据／配置：`DATA_DIR/app.sqlite3`、`conversation-checkpoints.sqlite3`、`conversation-locks/`、原 `uploads/` 和 tokenizer；生成与嵌入配置沿用现有设置，不保存密钥值。真实验证副本及回执见第 3 节。
- `document-chat-backend-1` 与 `document-chat-frontend-1` 保持 healthy；临时 Vite、uvicorn 已停止。没有遗留验证容器。
- 阶段 C 在既定事实检索范围完成；无已知阻塞缺陷。下一步 D 入口：受控 Python 通用 CSV 解析／执行、旧 CSV 能力迁移与旧问题入口退役；依赖和 broker 部署按既有规则先讨论。
