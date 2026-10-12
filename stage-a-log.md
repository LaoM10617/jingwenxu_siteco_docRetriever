# 阶段 A 实施与验证记录

日期：2026-10-12。范围：用户本轮最终明确只执行 A。当前：阶段 A 实施、验证及审查完成；B–G 未开始。决定的权威记录为 decisions-design.md 第 14 节，本文记录实际执行证据。

## 基线与数据处置

- 分支 `main`，HEAD `269d5fe`；初始工作树仅 decisions-design.md / plan.md 未跟踪。本轮没有 commit/push。
- 实际读取被忽略的 AGENTS.md。没有访问旧项目，也没有修改忽略规则。
- Docker `document-chat-backend-1` / `document-chat-frontend-1` 健康；实际后端 bind mount 为 `D:\Projects\SITECO-document-chat\data\docker-e2e` → `/app/runtime`。默认 `data/runtime` 也存在，不能据配置默认值误处置运行数据。
- 顶层验收原件：CSV 1,725,711 bytes、采购条款 PDF 114,934 bytes、Trunking PDF 4,956,719 bytes；原件、旧运行库及索引全部保留。本次无迁移/清空，因此未做不必要的原件复制。未来迁移需先备份实际使用的 uploads 和业务 SQLite 一致快照。
- 验证只新增 `data/stage-a/` 与临时 job 目录；原始输入复制进只读挂载，容器完成后删除 job。统计输出/回执保留在 `data/stage-a/statistics-0.json`、`statistics-1.json`、`executor-receipt.json`，该目录已由既有规则忽略。
- Windows 默认 Python 3.14.7，使用已有 Python 3.12.10 建立项目 `.venv`。Linux 使用现有 Python 3.12.14 / bookworm digest 镜像。没有改变系统 Python。

## 已实现内容

| 接口/文件 | 代码已实现 | 验证范围 |
| --- | --- | --- |
| agent_protocol.py | v1 任务、结果、范围、证据/产物、两类事件；严格不可变 schema 与结果约束校验 | 7 个自动化协议测试；非模型语义判断 |
| agent_state.py | StateGraph、SQLite 分库、interrupt/resume、请求/发布幂等、恢复列表、session 跨进程锁 | 7 个真实 SQLite/子进程测试，包含两个强制退出窗口 |
| python_executor.py | 独立宿主 controller、非特权一次性容器、输出限额、超时/停止/清理 | 11 个真实 Docker 测试；固定可信脚本 |
| probe_agent_state.py | submit / inspect / list / resume CLI | 独立进程暂停→读取→恢复 |
| siteco_statistics.py / probe_python_executor.py | 全表固定统计、独立 Decimal oracle、产物描述、计时回执 | 两次真实容器统计，与全部记录预期一致 |

A 不替换旧 HTTP 或 UI；没有实现正式会话/资料生命周期、模型任务规划、通用 CSV Agent、pandas 或任意自然语言代码生成。状态图为固定澄清/发布探针，不宣称主 Agent 已交付。

## 测试和复现

从项目根目录执行（Windows Python 为 `.venv\Scripts\python.exe`）：

```powershell
.\.venv\Scripts\python.exe -m pip check
.\.venv\Scripts\python.exe -m pytest backend/tests/test_agent_protocol.py backend/tests/test_agent_state.py -q
$env:SITECO_DOCKER_TESTS='1'
.\.venv\Scripts\python.exe -m pytest backend/tests/test_python_executor.py -q
Remove-Item Env:SITECO_DOCKER_TESTS
.\.venv\Scripts\python.exe scripts/probe_python_executor.py
docker build --target test -t siteco-phase-a-tests -f backend/Dockerfile .
.\.venv\Scripts\python.exe -m pytest -q --basetemp data/stage-a/pytest-windows-final
```

Docker 测试默认 skip，必须显式启用；Linux build 内不开放 daemon，所以执行器测试跳过并由宿主真实 Docker 测试补足。不能把 skip 当成通过。Docker/原生依赖验证需要本机允许 Docker named pipe / 原生库访问。

手动恢复（命令分别运行即不同进程）：

```powershell
.\.venv\Scripts\python.exe scripts/probe_agent_state.py --root data/stage-a/state-probe submit s1 q1 'Unit?'
.\.venv\Scripts\python.exe scripts/probe_agent_state.py --root data/stage-a/state-probe list
# 将上一命令返回的 run_id 放在下一命令中
.\.venv\Scripts\python.exe scripts/probe_agent_state.py --root data/stage-a/state-probe resume RUN_ID EUR
```

### 实际结果

- `pip check`：通过；新增精确依赖 LangGraph 1.2.14、SQLite saver 3.1.1、checkpoint 4.2.0、prebuilt 1.1.0、SDK 0.4.6、aiosqlite 0.22.1、sqlite-vec 0.1.9、ormsgpack 1.12.2。既有 provider/Pydantic 锁定版本保留。
- 协议：7 passed；状态：7 passed；真实 Docker：11 passed in 14.62s。
- 最终 Linux Docker test target：385 passed、11 skipped、10 subtests passed，69.29s；镜像 `siteco-phase-a-tests:latest` 构建成功（镜像 ID `ab536c8fabef`）。
- 最终 Windows Python 3.12.10：385 passed、11 skipped、10 subtests passed，121.60s。11 项 skip 均为显式开关的真实 Docker 测试，已经独立运行通过。
- Windows 首次受限运行在 FAISS 原生模块加载时报 `0xc0000008`，21 个收集错误；相同环境解除工具沙箱限制后 `import faiss` 成功，旧回归可运行，无需修改 FAISS 版本。
- 本轮不调用真实模型/Voyage；现有 provider 适配模拟测试与完整依赖安装验证兼容性，不冒充真实端到端问答。

### 固定 CSV 统计及耗时

文件 SHA-256：`b58bcea0e2d5c1e9f0017a25d3f1153bf75c25c0e78dd02a9a711ceb699483b9`。

全表 11,386 条记录，11,386 个有效价格，0 个缺失；价格字段合计 `9623342.01`。容器用逐项整数分计算，独立期望用已有 `parse_csv` + Decimal 求和；保留重复行、不去重。源文件没有声明币种，产物不擅自宣称 EUR。这是协议/计算验证，不代表金额合计具有报价业务意义。

| 耗时（秒） | 首次新容器 | 第二次新容器 |
| --- | ---: | ---: |
| create | 0.281 | 0.219 |
| 启动+计算+输出接收 | 0.797 | 0.610 |
| worker 数据加载 | 0.2425 | 0.1358 |
| worker 统计 | 0.0165 | 0.0071 |
| worker JSON 编码 | 0.0015 | 0.00007 |
| 控制端总耗时（含清理） | 1.250 | 1.016 |

这是本机已有镜像的首次/重复新容器测量，不包含镜像下载、模型生成、pandas 导入；输出传输包含在启动+执行项，未声称单独测量传输时延。审查后增加清理核查会有少量开销，不据这些数字承诺产品延迟。

## 审查与红绿证据

使用 karpathy-guidelines、codebase-design、tdd、research、domain-modeling；故障定位使用 diagnosing-bugs，交接使用 code-review 的 Standards/Spec 双轴子 Agent 审查。以 `269d5fe` 与当前未提交/未跟踪文件为范围，以本地 AGENTS.md 和 plan.md A 为标准/规格；按项目规则不引入旧技能 issue tracker 或旧 milestone。

- 协议 3 轮红绿切片验证任务字段、范围/身份、澄清/事件。
- 状态恢复列表新增前 AttributeError，实现后通过；真实 `os._exit(73)` 模拟发布业务提交后退出，恢复只留一条发布。
- Linux 首轮 1 failed / 383 passed / 9 skipped：checkpoint 默认异步落盘，业务已答复仍可能显示 waiting。增加答复提交后 `os._exit(74)` 的精确失败回归；显式 sync durability，inspect 根据已保存答复区分 waiting/recoverable，后续恢复不重复索要答案。
- 双轴审查均指出 Docker 创建响应不确定时遗留容器、指数数值溢出被当成有效 JSON；先复现 2 failed，再修复按唯一容器名清理及有限浮点解析；执行器全量 11 passed。
- 最终审查结果：Standards / Spec 两条独立复核均通过，无剩余 A 阻塞发现。两个执行器缺陷和 checkpoint 时序问题均有失败复现、修复及通过证据。

## 限制与下一步

- SQLite/文件锁只验证单机本地存储。图恢复与业务发布没有跨库事务，正确性依赖持久身份、内容一致性校验与重放测试。
- 独立 controller 不是生产后端 broker。宿主控制程序被强杀/断电后的孤儿回收尚未实现；Docker daemon 不可用时明确报清理错误并给 job 名。任意模型脚本接入前须完成这些运行生命周期要求。
- v1 范围字符串不证明业务口径或模型答案正确；当前资料可用性/访问校验在 B 建立。
- 下一步 B：按 decisions-design.md 14.1 实现正式会话、文件版本及关联持久化；承接现有原件/索引，明确迁移路径。开始前需用户授权下一阶段。本轮停在 A。
