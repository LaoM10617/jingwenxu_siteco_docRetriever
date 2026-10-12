# 阶段 D 实施记录

日期：2026-10-12。状态：阶段 D 既定范围代码已实现、最终测试通过、真实环境已验证、双轴审查通过。未部署到旧运行容器、未 commit/push。用户已确认宿主 worker 主动领取、隔离 pandas 与 CSV 子图按需 review。下方过程记录保留当时证据，最终交接见文末。

## 接手事实

- main / `e389512`，与本地 origin/main 一致，接手工作区干净。用户告知已推送；本轮未 fetch、commit 或 push。
- 已读 AGENTS.md、decisions-design.md、plan.md、stage-c-log.md。只有 AGENTS.md 被 Git 忽略；其余三份文档已跟踪。
- Windows Python 3.12.10、Node v24.19.0。Docker 两个旧容器 healthy，未重建或部署；不代表新主图已部署。

## 代码已实现

- 通用解析、原始值和稳定行身份；完整 SITECO 模式按列名派生订单号/Decimal 价格，其他同名价格列必须明确口径。
- 确定性基础概览及保守类型建议，HTTP 导入摘要透传；完整表头与行摘要校验、旧快照恢复。
- 会话范围内完整 CSV 执行输入快照，包含文件版本、摘要和行标识，拒绝跨会话或已移除来源。
- `scripts/probe_stage_d_csv.py` 使用独立副本验证真实全表与固定隔离计算，不调用模型。

## 测试与真实证据

- CSV 解析/生命周期最终定向测试：78 passed；命令 `.venv/Scripts/python.exe -m pytest -q backend/tests/test_csv_parsing.py backend/tests/test_csv_lifecycle.py --basetemp data/stage-d/csv-price-fixed`。
- 会话上传、主图、协议、HTTP、产物回归：35 passed；命令 `.venv/Scripts/python.exe -m pytest -q backend/tests/test_session_uploads.py backend/tests/test_agent_protocol.py backend/tests/test_conversation_runs.py backend/tests/test_run_api.py backend/tests/test_artifact_lifecycle.py --basetemp data/stage-d/tests-integration-host`。
- 最终 Windows 全量：`.venv/Scripts/python.exe -m pytest -q --basetemp data/stage-d/tests-final-host` → **453 passed、11 skipped、10 subtests passed**，164.33 秒。11 项为未启用的 Docker 隔离套件，本切片未修改执行器，不能算作本轮已重跑；另有下述真实固定脚本验证。首次全量 447 passed、4 failed，4 项失败为旧测试将合法单列 CSV 当作无效输入，已改为重复列名并更新错误文案断言，保留原验证目的。`git diff --check` 通过，仅现有 CRLF 提示。本轮未做 Linux 全量或前端构建（前端未改）。
- 真实命令 `.venv/Scripts/python.exe scripts/probe_stage_d_csv.py`；金额修复后最终回执 `data/stage-d/20261012T162548475554Z/receipt.json`。11,386 行、11,386 个行身份，Decimal 全表合计 `9623342.01`，与独立整数分计算脚本一致；货币未由原表声明，不推断 EUR。固定 Docker 脚本控制器总耗时约 1.281 秒，清理成功，原件 SHA-256 未变。早期成功回执也保留。
- 数据仅新增 `data/stage-d/` 内测试目录与验证副本。首次探针因内部上传返回结构读取错误退出，修正后成功；失败副本保留用于诊断，不改旧数据。
- 沙箱默认 pytest 临时目录不可写，项目内 TestClient 在沙箱卡住；同测试经批准在宿主独立 basetemp 运行成功。相关沙箱进程已中止。没有把环境失败算作产品测试通过。

## 当前切片审查

以 `e389512` 至工作区变更及新增文件为范围，按 AGENTS/计划进行 code-review 双轴审查。Standards 与 Spec 各发现同一金额口径 P2：任意同名 Listenpreis 被当作德式价格。已修复为只有完整旧 SITECO schema 使用原价格规则，并以 `1.234` 歧义值、空值和完整列重排测试回归。两轴只读复核均无剩余已发现阻塞项。该结论只覆盖当前 CSV 基础切片，不是整个 D 的阶段审查通过。

## 基础切片结束时的未决事项（历史）

- 等待用户对后端控制程序通信和 pandas 依赖的选择，详见设计第 17 节与研究记录。
- 随后实现受控分析计划/脚本生成、确定性口径校验、有限修正、主图 CSV 接入、表格/图表产物及复用、旧入口退役。
- 任意生成脚本接入前需完成持久任务身份、孤儿回收与失败/取消/恢复验证；当前固定脚本成功不能替代上述证据。
- 20,000 行、20 MiB 和 10 活跃文件仍是现有防护限制，尚未调整；通用编码选择、复杂类型澄清、关联放大与空键语义仍待执行链路落地。
- E 未开始。当前不宣称阶段 D 审查完成或新架构已部署。

## 后续实施：完整 D 链路

- 用户确认执行方案后，已实现业务库 ExecutionJobs、Bearer 后端领取/心跳/完成接口、独立可信宿主 HostWorker、持久实例/交付日志及所有者孤儿回收。后端与隔离容器均无 Docker socket。
- 新 CSV LangGraph 专业图接入主图：原文约束/澄清、文件名及字段概览、完整表输入、结构化计划、生成脚本、校验与有界修正、按需 review。业务歧义返回澄清。原始数据与结果数据可在隔离镜像中用 pandas 操作；金额和关联辅助函数具有明确口径。
- 结果表、代码/计划/单位/来源依赖与图表分别持久化；简单改图无新执行任务，后续筛选可读取完整旧结果表。前端增加 100 行分页和 bar/line/scatter 基础图，数值 line/scatter 按真实横坐标绘制。完整数据不因显示预览而截断。
- 移除旧 `/api/questions`、旧 worker 与 TTL memory，迁移有效业务回归至可复用模块或新主图接口。旧历史窗口/队列专项测试随被删除实现退役；不是同数量的新能力测试，复杂长会话留 F。
- 应用/宿主未安装 pandas，仅 runner 固定四包及 hash。最终镜像 `sha256:522aa06bcb398a357adbf29c9bc9d07cbf8e9b306914744818ec3eec1da99a9b`。配置与可复制启动命令见 [runner/README.md](runner/README.md)，配置名为 `EXECUTION_IMAGE`、`EXECUTION_WORKER_TOKEN`。

### 审查与实测驱动修复

- 初次完整 Windows 回归 455 passed / 1 failed / 11 skipped；失败为 reuse_chart 参数校验顺序，已修。
- 双轴审查发现并修复：失败 task 缓存阻断显式恢复、reuse_chart 的 repair 被忽略、CSV overview 丢失文件名、数值 line 横轴等距失真。补齐完整旧结果输入及父产物身份，防止再筛选误回到原表。
- 真实 Gemini 首次金额正确但列形状/空值/单位要求丢失，原因是主图 objective 摘要遗漏原要求；改为原文 constraints 始终传入，不依赖模型摘要完整。
- 显式恢复红测揭示 CSV 子图继承父 checkpoint 重放失败结果；关闭子图 checkpoint 后，当前锁定 LangGraph 的同步 durability 分支又访问未初始化 future。按本地源码确认，临时子图显式使用 `compile(checkpointer=False).invoke(..., durability='exit')`；有已知无 checkpoint 的 durability 提示，不影响执行，主图仍同步持久化。
- 第二个真实模型回归发现图表 title 缺失：`wire_schema` 误把 properties 下的业务字段名当作元数据剔除。已修 schema 字段遍历并加入关键字同名字段回归，未通过默认值掩盖问题。
- 恢复回归覆盖三次失败显式重试后成功、重启不自动执行、保留成功执行结果；坏 plan/review 回执仅在显式恢复时失效，坏 review 不丢有效 plan。调用累计审计不清零。
- 最终 Spec 复核追加发现显式旧产物失效时可能退回原表，已改为规划前明确拒绝；4 条失效/范围/非表格用例通过。随后真实三轮探针前两轮通过、第三轮因模型把 purpose 从 csv_analysis 改成 null 被正确拒绝；修复主图用途连续性，不放宽专业图复用边界。新增回归验证省略用途沿用、显式不同用途拒绝且不执行。
- Windows 全量中 checkpoint 清理用例一次失败，经发布后 barrier 稳定复现：业务 completed 早于最终 checkpoint/锁释放，既定异步清理尚未结束。仅修测试等待真实应用 finally 清理，无手工触发 purge、无放宽删除断言，定向 2 passed。

### 后续验证过程

- 新图/产物/设置 Playwright：9 passed；`npm run build` 通过。临时 Vite 为 127.0.0.1:18187，未替换旧服务。旧协议的历史浏览器套件不代表新协议验收，本轮选择新图及设置套件并新增真实浏览器分页/横轴用例。
- 最终 runner 真实 Docker：15 passed / 19.94 秒。命令：设置 `SITECO_DOCKER_TESTS=1`、`SITECO_RUNNER_IMAGE` 为上方镜像后，`.venv/Scripts/python.exe -m pytest backend/tests/test_python_executor.py backend/tests/test_csv_runtime_docker.py -q --basetemp data/stage-d/docker-final-env`。11 项隔离加 4 项 pandas/helper；覆盖非 root、网络/密钥/宿主文件/写入隔离、资源/输出/超时/停止、关联基数和空键、前导零、NA、Decimal 大数尾数、150 行结果完整加载。
- `scripts/probe_stage_d_worker_recovery.py` 使用真实 ExecutionJobs、HTTP、worker 进程及 Docker，受控 HTTP 注入失败，无模型。首次三场景回执 `data/stage-d/worker-recovery-20261012T173654750687Z/receipt.json` 均通过且无残留容器；最终还将增加运行状态确认后重跑。
- 真实 Gemini 中间回执 `data/stage-d/20261012T174009504869Z/receipt.json`：完整表结果 metric/value 正确，11,386 / 9623342.01；第二轮暴露上述 title schema 问题，因此该回执整体标 failed。早期失败回执保留，不当作完整验收。

数据仅位于独立 `data/stage-d/`、worker staging 与测试镜像；原件不变，旧运行容器仍是旧代码。未 commit/push，E 未开始。

## 最终验证与交接

- Windows 冻结代码全量：`.venv/Scripts/python.exe -m pytest -q --basetemp data/stage-d/final-windows-3` → **471 passed、15 skipped、10 subtests passed**，140.65 秒。15 项 Docker 测试已另行真实通过，不计作此命令运行；28 条 LangGraph 1.2.14 无 checkpoint durability 提示已解释，非失败。
- Linux 最终独立镜像：`docker build --target test -t siteco-phase-d-tests -f backend/Dockerfile .` → **471 passed、15 skipped、10 subtests passed**，79.72 秒；镜像 ID `sha256:fe5d151271df3b31fe1ac4b2da294f2fb9c9520e0acb06cb8cf6cad3c6bb8cfe`。同样 28 条已知 durability 提示。较早 469 项通过记录被本次最终证据取代。
- 最终三轮真实 Gemini 回执：`data/stage-d/20261012T174750760175Z/receipt.json`，整体 **passed**。模型 `gemini-3.5-flash-lite`，调用次数分别 3 / 2 / 3，共 8 次；无 Voyage 调用。第一轮完整 11,386 行与 Decimal 合计 `9623342.01` 正确；第二轮保留原表数据且无新增执行任务；第三轮完整旧表筛选到 metric=total 的一行，实际首次脚本漏 import、经 review 修正后成功（2 个执行任务，失败+成功），不是只靠模拟证明修正循环。最终脚本实际使用 `load_artifacts()`，未重新聚合原 CSV。原件摘要未变。
- 最终真实 worker 故障回执：`data/stage-d/worker-recovery-20261012T174157758689Z/receipt.json`。强杀和停止前都确认 `State.Running=true`；强杀后确认运行孤儿存在再重启回收。三场景均只领取一次、无残留容器；完成响应丢失仅重传相同结果。复现命令：`.venv/Scripts/python.exe scripts/probe_stage_d_worker_recovery.py --image <上述固定镜像>`。
- 最终独立 Standards / Spec 审查及主 Agent 集成复核无未解决阻塞项。审查基准为 `e389512` 至工作区修改与新增文件；已发现问题及修复证据如上，非仅对单一子模块宣布完成。
- 真实环境边界：Gemini 验证上述三轮；关联、空键、精确数值、隔离与资源限制为真实 Docker 确定性测试；其它模型输入/恢复竞争为自动化测试。未进行批量模型正确率或压力测试；Groq 此阶段未实测。模型 review 不保证任意生成代码正确，复杂依赖协作与长会话留 F。
- 当前规模边界：输入文件 20 MiB、最多 10 活跃文件、CSV 20,000 行；UTF-8/UTF-16 BOM 与逗号/分号/Tab。结果表最多 20,000 行/100 列/16 MiB；更大规模、其他编码手工选择、文件导出仍未实现。图表为基础 SVG 预览，完整数据在分页表；并非后续视觉改版。
- 分支 `main` / HEAD `e389512` 未变。本阶段所有变更未提交，含新增 runner、worker、专业图、产物 UI、验证脚本和文档，以及旧 worker/memory 删除与测试迁移；未 commit/push。
- 未替换旧 Docker 部署；核对 `document-chat-frontend-1` 与 `document-chat-backend-1` 仍原运行实例且 healthy。独立模型探针 server/worker 和 Vite 18187 已停止，原件及旧 `data/docker-e2e` 未迁移。后续启动方法见 runner/README.md，不应把当前 healthy 旧容器当成 D 已部署。
- 下一步入口：阶段 E 的 PDF 完整阅读与专题分析；本轮没有实施 E。继续前读取 AGENTS、设计、计划与本日志，无需重新决定已确认的 worker/pandas 方案。
