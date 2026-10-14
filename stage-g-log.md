# 阶段 G：后台探索与集成交接

## 最终交接第 2 步：文档与接口（2026-10-14）

- 已核对并更新 decisions-design.md 第 20 节实施细节、plan.md 当前快照、deployment.md、ui-developer-handoff.md 和 README。README 原简介、视频链接及下载说明保持原样，历史评估不改写为新架构评估。
- 接口交接补充启停/恢复/选择流程、错误处理、timings 与命中计数的真实含义，明确建议不是已算结果、202 不是完成、无后台澄清回复或任意候选执行接口；补充真实探索候选和前台 `60.00` 产物节选、原回执位置及验证限制。后续 UI 消费现有 HTTP，开发者模式不读 SQLite 或接收 worker token。
- 清理 plan 当前入口中累叠的旧状态，历史阶段过程继续保留在本日志及 F 日志。当前基线为 main/4c05c32 加未提交 G 改动；全量与真实冒烟早于最终误抢占修复，修复后 37 项定向回归，日常实例未升级。源码复制/部署需包含未提交新文件，旧测试镜像不能代表最终修复。
- 本轮只改文档，未重跑业务测试/模型请求，未部署、commit/push。下一步为最终交付摘要及范围确认，不实施两项界面重构。
- 文档验证：六份文档的本地 Markdown 链接目标存在；接口文档 6 个 JSON 示例可解析，G 响应节选与原始回执逐字段一致；README 原简介/视频区块及历史评估以后内容与 HEAD 对比未变。git diff --check 通过，仅既有换行提示。

## 最终审查第 1 步：代码双轴审查（2026-10-14）

- 使用 code-review / karpathy-guidelines，两个独立子 Agent 分别审查 Standards / Spec，主 Agent 核对并复现。固定基线 `4c05c32edfe30b747642a87e5848c778dda288e2`，无后续提交；审查范围为 `git diff 4c05c32` 加未跟踪的 G 实现/API/测试/探针，避免漏掉新文件。标准来源 AGENTS.md，规格来源 decisions-design.md 第 12/13/20 节、plan.md G 与本轮确认范围。
- **Standards：1 项 P2，已修复关闭。** 前台 resume 在校验会话归属、配置及恢复条件之前执行全局后台抢占；跨会话请求虽被 404 拒绝，仍停止正在执行的探索。已完成 run 的 resume 和 submit 幂等重放也会停止探索，可能浪费不能补发的后台候选预算，违反副作用/访问边界。现在 submit 仅新建并接纳后抢占；resume 所有校验及接纳成功后才抢占，busy 查询排除 background run，合法前台恢复仍有优先权。
- 新增四场景回归（跨会话拒绝、完成恢复、完成提交重放、合法恢复）；修复前 `-k only_admitted --basetemp data/stage-g/review-preempt-red` 为 3 failed / 1 passed，准确复现。修复后 `.venv/Scripts/python.exe -m pytest -q backend/tests/test_csv_exploration.py backend/tests/test_conversation_runs.py backend/tests/test_run_scheduling.py backend/tests/test_run_api.py --basetemp data/stage-g/review-preempt-green --junitxml=data/stage-g/review-preempt-green.xml` → **37 passed / 13.79s**，15 条既有 durability 提示。Standards 子 Agent 已只读复核修复，原问题关闭。
- **Spec：0 项确认的重大偏差。** 核对后台/前台预算、现有执行器与缓存复用、前台优先、停止/失效清理、跨会话边界、结果不自动进入聊天与 UI 排除范围；未发现新的阻塞项。不是对任意模型输出语义正确性的保证。
- `git diff --check` 通过（既有 CRLF 提示）。本次不重复全量、Linux 构建或真实模型探针：此前 571 项双平台全量和真实冒烟是此小修复之前的证据；修复后以本节定向回归及审查复核为证，旧测试镜像不包含本次修复。
- 最终代码审查目前无未解决的阻塞发现；下一步仍需文档/接口交接及最终交付摘要，尚不宣布整个 G 完成。本次无部署、commit/push。

## 分步集成回归：第 4 步真实应用冒烟（2026-10-14）

- 在独立 `data/stage-g/app-20261014T081207Z/runtime` 创建新数据，Compose 项目 `siteco-g-smoke-20261014t081207z`，loopback 临时端口。构建并启动当前工作区前后端、宿主 pull worker、固定 pandas 执行镜像，未覆盖旧实例或旧数据。前后端健康检查通过；真实浏览器通过 Nginx /api 访问真实后端，没有 HTTP mock。
- 镜像：backend `sha256:6ae7a32d760425a5d903db07acd053215673f83f9fff3d7460a07812a6dbf3b3`；frontend `sha256:c91ede61e34943732ca846b522e7b103fd8ca6fac774ccbcac698eda24f691a5`。源码仍为 `4c05c32` 加当前未提交 G 工作区，并非仅提交版本。
- 浏览器上传 Rondel PDF，真实 embedding/检索/生成回答 3000 K、ON/OFF 两个编号 `0MD5307L1830`、`0MD5307L0930`，与既有原页核对一致；展开引用并成功显示第 2 页图像/来源区域。原件 SHA-256 仍为 `78a20a04658b46ad947eccce4d96e08f757f348e721b0d8159e5f9f1b7bff561`。保留 layout_uncertain 警告，不将区域标注当作语义正确性的证明。
- 浏览器上传明确标注为合成数据的 3 行 CSV（Price 为 10、20、30，未声明单位），实际隔离计算总和 `60.00`，与独立算术核对一致；结果表在界面显示，unit 为 null，无货币推断。
- 共 **5 次生成模型调用**（PDF 2、CSV 3，均在每轮 6 次限额内），另有真实 Voyage embedding 请求。本轮 CSV **2 次隔离执行**：首次生成脚本调用未导入的 load_tables，NameError；系统在现有预算内修复，第二次成功，两次均清理。没有修改产品代码掩盖此历史，不称第一次执行即成功。
- 最初浏览器探针断言将界面 `60.00` 写死为 `60`，误报失败；接口数值与截图均正确。修正临时探针断言，重启同一独立数据实例，复用已完成两轮而不重新付费问答，完成表格显示、停止及刷新验证。停止操作发生在新请求尚未产生模型调用时；停止状态持久化，刷新无新增 run，答案与表格恢复。执行中容器强制停止/清理沿用此前 priority 探针证据，本轮不重复。
- 回执目录 `data/stage-g/app-20261014T081207Z/`：`browser-receipt.json`、`deployment-receipt.json` 均 passed，`audit.json` 保存调用/执行核对，`attempt1-*` 保留首次断言失败；`pdf-preview.png`、`csv-result.png` 为实际界面。临时脚本 `data/stage-g/app-smoke.py` / `app-smoke.cjs` 保留在忽略的验证目录。过程命令为 `.venv/Scripts/python.exe data/stage-g/app-smoke.py`，断言修正后的续跑加参数 `data/stage-g/app-20261014T081207Z`。
- 后台探索显式关闭，0 模型/执行调用；复用此前探索真实验证。无浏览器 pageerror。已停止宿主 worker、清理本次 worker 容器并 compose down；结束时 docker ps 为空。**这是新版本独立实例真实验证，用户日常应用没有升级或持续运行**。
- 第 4 步通过（同一数据跨探针断言修正续跑，产品代码未变）；尚待第 5 步最终双轴集成审查及交接核对，不宣布整个 G 已完成。未 commit/push。

## 分步集成回归：第 3 步前端（2026-10-13）

- `frontend/` 执行 `npm run build`：TypeScript 检查与 Vite 生产构建通过。
- 沿用 F 当前架构浏览器用例，临时本机 Vite 18188，设置 `M24_BASE_URL=http://127.0.0.1:18188` 后执行 `npx playwright test tests/graph-chat.spec.mjs tests/settings.spec.mjs`：**10 passed，10.8 秒**，无失败；日志 `data/stage-g/browser-step3.log`。
- 覆盖保存会话恢复且不重复提交、澄清、依赖失败部分结果、停止/恢复、刷新后显式恢复、历史来源失效提示、CSV 分页/数值折线、桌面与移动设置。浏览器使用模拟后端，不代表真实上传/provider/原件预览端到端验收；这些留给第 4 步。未运行旧 `/api/questions` 架构测试或扩展新 UI 测试。
- 浏览器警告为 NO_COLOR/FORCE_COLOR 冲突。Vite 另记录设置用例未模拟的 `/api/sessions` 请求连接 8000 失败（本轮未启动后端）；设置断言通过，但不能据此证明真实会话服务可用。无产品代码修改，无需复测；临时 Vite 已停止。未部署、调用真实模型或 commit/push。下一步为新版本应用端到端冒烟。

## 分步集成回归：第 2 步 Linux / Docker（2026-10-13）

- 当前工作区构建：`docker build --target test -t siteco-phase-g-tests -f backend/Dockerfile .`，退出码 0。测试层实际执行（非缓存），Linux 非 root 用户下 **571 passed、15 skipped、10 subtests passed、92 warnings，162.27 秒**；警告均为已有 LangGraph durability 提示。
- 完整构建日志：`data/stage-g/linux-build-20261013.log`。测试镜像 manifest `sha256:920fe596ca584aca141a8cd283fe334a5a18f525d0bef2f6fcf1d29ecf629ccc`。
- 15 项默认跳过的真实隔离专项另行运行：宿主设置 `SITECO_DOCKER_TESTS=1`、`SITECO_RUNNER_IMAGE=sha256:522aa06bcb398a357adbf29c9bc9d07cbf8e9b306914744818ec3eec1da99a9b`，执行 `.venv/Scripts/python.exe -m pytest -q -rs backend/tests/test_python_executor.py backend/tests/test_csv_runtime_docker.py --basetemp data/stage-g/docker-step2-20261013 --junitxml=data/stage-g/docker-step2-20261013.xml` → **15 passed，28.66 秒**。该专项是 Windows 宿主驱动真实 Linux 隔离容器，符合现有 host worker 边界，不是测试镜像内嵌套 Docker。
- 无失败，无需代码修复或重复测试。未运行前端或额外付费模型验证，未部署应用、commit/push；后续进入第 3 步前端构建/浏览器回归。第 1、2 步通过不等同 G 最终审查完成。

## 分步集成回归：第 1 步 Windows 全量（2026-10-13）

- 按用户限定只执行 Windows 后端全量一次，无产品代码修改，未扩大到 Linux、前端、真实模型或部署。
- 命令：`.venv/Scripts/python.exe -m pytest -q -rs --basetemp data/stage-g/full-windows-20261013 --junitxml=data/stage-g/full-windows-20261013.xml`，宿主执行，退出码 0。
- 结果：**571 passed、15 skipped、10 subtests passed、92 warnings，304.51 秒**。JUnit 证据：`data/stage-g/full-windows-20261013.xml`。
- 15 项跳过全部是显式启用 Docker/固定 pandas 镜像才运行的专项（csv_runtime_docker 4 项、python_executor 11 项），本轮未启用，不计作本轮通过。92 条警告均为既有 LangGraph 无 checkpointer 时 durability 无效的提示。
- 本次覆盖上一节计时修复及立即恢复竞态测试后的工作区；未发现测试失败，无需追加复测。main / 本地 origin/main 仍为 `4c05c32`，G 改动未提交；无 commit/push。
- Windows 全量待办已完成。剩余 Linux Docker 回归、前端构建/浏览器、应用端到端冒烟和最终集成审查按后续步骤进行；不代表 G 全部验收或已部署。

## 最新限定验证（2026-10-13）

用户仅要求完成探索定向测试、计时核对和两个探针，优先严重问题；没有执行全量回归、最终双轴审查或部署，**仍不宣布阶段 G 全部完成**。下文早期“未运行”等为历史快照，本节更新其中测试与探针状态。

- 当前 main / 本地 origin/main 为 `4c05c32`，此前仅 README 按用户要求提交并推送。G 修改仍未提交；本次没有 commit/push。
- 宿主执行 `.venv/Scripts/python.exe -m pytest -q backend/tests/test_csv_exploration.py backend/tests/test_execution_jobs.py --basetemp data/stage-g/targeted-host`：28 passed / 16.18s，包含 HTTP 和两次隔离执行终身上限。
- 计时核对发现：原实现只累计最后一次执行，遗漏失败尝试，缓存重放还会重复累计。已改为 ExecutionJobs 接受执行回执时累计一次，重复回执/缓存重放不增加计算耗时；开发者 timings 增加 `model_cache_hits`、`execution_cache_hits`（次数而非秒）。两次失败执行各 0.01s 的回归先红（实际 0.01、应为 0.02）后绿，恢复后仍 0.02，两个缓存命中计数均为 2。
- 修复后相同两文件测试（`--basetemp data/stage-g/timing-host`）：28 passed / 13.62s，7 条已有 LangGraph durability 提示。另新增在模型调用未返回时停止并立即恢复的竞态测试，验证旧响应不发布、预算不重置、不重复付费；`-k immediate_resume --basetemp data/stage-g/resume-race`：1 passed / 1.97s。没有为此重跑全量测试。
- `scripts/probe_stage_g.py --image sha256:522aa06bcb398a357adbf29c9bc9d07cbf8e9b306914744818ec3eec1da99a9b`：passed，回执 `data/stage-g/20261013T203836246207Z/receipt.json`。真实 Gemini `gemini-3.5-flash-lite`、HTTP、宿主 worker、Docker pandas，共 3 次模型调用、1 次隔离执行。验证关闭探索仍有确定性概览、候选与预计算区分、结果不自动进入聊天、选择/复用、跨会话拒绝、重启无重复付费、来源移除后失效。
- 独立用标准库 csv + Decimal 核对原始样本 11,386 行、18 列，每列非空数与百分比全部匹配，原件哈希未改变。记录 `data/stage-g/20261013T203836246207Z/numeric-review.json`；总行数见概览/溯源，模型产物表为逐列完整率。
- `scripts/probe_stage_g_priority.py --image <同一 digest>`：passed，回执 `data/stage-g/priority-20261013T203849055210Z/receipt.json`。受控模型、真实 HTTP/worker/Docker；各动作前确认执行容器正在运行。前台响应 0.312s，抢占清理 0.922s，停止清理 1.265s，删除清理 1.141s；不是实际 provider 优先级性能验收。
- 保留首次 priority 失败回执 `data/stage-g/priority-20261013T203720830545Z/receipt.json`：直接删除 ready 文档被 409 拒绝，是探针未遵循先 trash 再 delete 的接口规则；已修正探针并重跑通过，不是产品删除缺陷。
- 两个真实探针完成于此次计时修复之前；修复后的计时与缓存语义通过定向测试验证，未额外消耗模型预算重跑真实探针。验证使用独立 data/stage-g 目录和临时服务；结束时 `docker ps` 无运行容器，不能沿用早期旧容器 healthy 的描述。本次未启动/升级用户应用。
- `git diff --check` 通过，仅原有 CRLF 提示。剩余：最终跨平台全量回归、最终双轴集成审查、完整接口示例与整体交接核对；F 历史 partial 和跨修复续跑限制保持。

日期：2026-10-13。状态：进行中，尚未完成实现、验证或审查。本轮不实施 UI 视觉重构与独立开发者模式界面，不 commit/push，不替换旧运行容器。

## 接手事实

- 已读取本地 Git 忽略的 AGENTS.md、decisions-design.md、plan.md、stage-d/e/f-log.md。
- main / HEAD / 本地 origin/main 均为 `25bf99d9b6a2cd253fbfe6be82b1784b9c83964e`，接手工作区干净；用户确认已推送，未 fetch。F 的未提交文字为提交前快照，已修正当前入口，历史验证过程保留。
- Python 3.12.10、Node v24.19.0；Docker 只读宿主查询确认 `document-chat-backend-1` 仍 image `4b31263d4424`，与 `document-chat-frontend-1` 均 healthy。该状态不证明新架构已部署。
- F 的真实验收是跨修复续跑；其历史 dependent/update partial、最终版本未重跑这些模型步骤、摘要语义局限继续保留。
- 用户已确认后台每 session/CSV 版本 3 次模型调用、3 候选、1 预计算、2 次隔离执行，不因重启/重放重置；权威决定见设计第 20 节。

## 验证安排与数据边界

- 先复用既有会话、专业子图、执行器、产物/缓存及完整任务测试接口做红绿验证，再做 Windows/Linux 回归与真实宿主 worker/pandas 小样本验证。
- 真实验证仅在独立 `data/stage-g/` 目录，临时服务使用 loopback 随机端口；原始资料、旧运行目录与旧容器保持独立。凭据只在环境/内存使用，回执不保存密钥。
- 计划记录预算消耗、确定性概览正确性、后台候选/已计算结果、前台优先、停止/恢复、来源失效、跨 session 访问及幂等；接口与部署交接另附实际例子。
- 初始定向基线命令因 `data/stage-g` 父目录尚不存在出现 27 个 fixture setup 错误，没有执行产品行为；已创建目录后重跑，不将此记为代码回归。

## 用户接回执行时的快照（2026-10-13）

用户要求停止推进，列出剩余工作由其自行完成。以下为中途交接，**不是阶段 G 完成验收**。全部 G 修改仍未提交，HEAD / 本地 origin/main 仍为 25bf99d；旧容器未部署。

### 已落盘与已验证

- 探索初版：`csv_exploration.py`、`exploration_api.py` 及应用接线；业务库探索状态/预算、共享 CSV 专业图与执行器、后台 run 隐藏、context_visible 控制、前台抢占、选择 focus、失效清理。需要完成以下验证与修复，不能仅以文件存在视作全部可用。
- 部署配置与 `deployment.md` 已完成初稿；`docker compose config --quiet` 通过。`ui-developer-handoff.md` 已包含现有接口、探索接口及 F 真实例子，尚缺 G 真实例子和最终状态核对。
- 接手定向基线：`.venv/Scripts/python.exe -m pytest -q backend/tests/test_csv_runs.py backend/tests/test_execution_jobs.py backend/tests/test_artifact_lifecycle.py --basetemp data/stage-g/baseline-2` → 27 passed，5 条既有 durability 提示。
- 真实隔离：设置 `SITECO_DOCKER_TESTS=1`、`SITECO_RUNNER_IMAGE=sha256:522aa06bcb398a357adbf29c9bc9d07cbf8e9b306914744818ec3eec1da99a9b` 后，`pytest -q backend/tests/test_python_executor.py backend/tests/test_csv_runtime_docker.py --basetemp data/stage-g/docker-isolation` → 15 passed / 20.15 秒。
- 子 Agent 报告探索核心 10 项、context 10 项、ExecutionJobs 12 项通过；这些是中间版本结果，主 Agent 尚未做终版全量复核。HTTP 用例在沙箱 Windows asyncio socketpair 初始化处卡住，尚需宿主执行；新增“两次执行终身限制”用例结果未确认。
- Gemini/Voyage 凭据存在，固定 pandas 镜像存在。项目配置未设置 EXECUTION_IMAGE / EXECUTION_WORKER_TOKEN；探针会用临时环境提供，不修改项目密钥配置。

### 剩余工作（推荐顺序）

1. 修复已知审查项：探索 execute 的非 DocumentError 异常仅映射为 exploration_failed，未保存错误类型/失败阶段；scheduler 同样只有固定 warning。应在开发者通道保存安全的异常类型与阶段（不保存可能含密钥的原始异常文本），补行为回归。
2. 完成 `backend/tests/test_csv_exploration.py` 的 HTTP 与两次执行上限测试；复核停止/恢复竞态、配置变化恢复、历史启动不付费、清理、前台优先及跨会话边界。计时字段刚调整，应确认加载/生成/缓存/计算分别统计，修复次数累计和缓存命中不误算计算耗时。
3. 执行 `scripts/probe_stage_g.py --image <固定镜像>`：真实 Gemini → HTTP → 后台探索 → 宿主 worker → pandas。脚本已写但**未运行**，仅早期 py_compile 通过；需修正可能的探针/实现问题，并独立核对实际计划和数值。每次新目录可能消耗最多三次后台模型调用，记录失败过程及总调用次数。
4. 执行 `scripts/probe_stage_g_priority.py --image <固定镜像>`：受控模型、真实 HTTP/worker/Docker，确认执行容器已运行后测试前台抢占、停止、删除及清理。脚本已写但**未运行、未验证**，不能称为真实 provider 验收。
5. 完成最终 Windows 全量、Linux Docker test target、前端构建及必要浏览器回归。最新 G 工作区尚未全量回归。旧 worker 恢复探针为新增 kind 字段调整了最小 fixture，尚未重跑。
6. 完成独立 Standards / Spec 两轴审查及修复复核。目前仅初审，Standards 发现第 1 项；Spec 尚未完成，不能宣称通过。
7. 按实际代码补 `decisions-design.md` 第 20 节实施语义，更新 `plan.md`、本日志、接口交接中的 G 实例、测试证据、已知限制及部署状态。F 的历史 partial 和跨修复续跑限制继续保留。

不需要本轮实施 UI 视觉重构、独立开发者界面或替换旧容器。后续如部署应单独明确实例/数据路径；commit/push 仍等待用户主动要求。

## 用户限定修复：探索失败诊断（2026-10-13）

用户随后仅授权修复上述审查项，其余 G 收尾及部署不继续执行。

- `csv_exploration.py` 记录 prepare/candidates/precompute/publish 失败阶段、异常类型与错误码至开发者 diagnostics.failure；普通接口不增加诊断字段。scheduler 日志记录 discover/admission/execute 阶段及异常类型，不记录异常原文、凭据或输入。
- 新增 4 个复现用例，修复前全部失败；修复后 `.venv/Scripts/python.exe -m pytest -q backend/tests/test_csv_exploration.py -k 'not http' --basetemp data/stage-g/diagnostics-green` → **15 passed、1 deselected**，11.69 秒，7 条既有 durability 提示。包含新增两次执行终身限制用例；HTTP 用例本次明确排除，未声称通过。
- `git diff --check` 通过，只有已有 CRLF 提示。未执行真实模型探针、全量回归或部署，未 commit/push。前述待办第 1 项已修复，第 2 项的“两次执行上限”已有此次通过证据；其余未完成事项保留。
