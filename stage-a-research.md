# 阶段 A 技术核对

核对日期：2026-10-12。范围：LangGraph + SQLite 恢复协议与 Docker Python 执行边界。本文是研究依据和建议，不替代 decisions-design.md 的已确认决定或 plan.md 的运行证据。

## 依赖候选与已有环境

已读取本地 AGENTS.md、decisions-design.md、plan.md、backend/requirements.txt、backend/requirements.lock.txt、backend/Dockerfile、compose.yaml。现有基线为 Python 3.12，直接依赖固定 Pydantic 2.13.5、FastAPI 0.141.1、google-genai 2.25.0、groq 1.7.0；尚无 LangGraph。Compose 的业务后端接收模型密钥，不能直接作为脚本环境。

候选是 `langgraph==1.2.14` 和 `langgraph-checkpoint-sqlite==3.1.1`。发布元数据均要求 Python >=3.10；前者要求 Pydantic >=2.7.4、langchain-core >=1.4.7,<2，两者的 checkpoint 依赖交集为 >=4.1.0,<5.0.0。SQLite 包还引入 aiosqlite >=0.20 和 sqlite-vec >=0.1.6。现有 Python/Pydantic 满足直接声明约束，但完整依赖解析、Windows/Linux wheel 安装及实际行为必须测试；本研究未执行安装。[LangGraph 1.2.14 元数据](https://pypi.org/pypi/langgraph/1.2.14/json)，[SQLite saver 3.1.1 元数据](https://pypi.org/pypi/langgraph-checkpoint-sqlite/3.1.1/json)。

建议保留现有 provider SDK 入口，不引入额外 LangChain provider wrapper；成功解析、pip check、恢复测试后固定完整依赖闭包。研究进程直接通过 PowerShell 访问 PyPI JSON 遇到 DNS 失败；官方网页读取成功，此问题不代表包不兼容。

SQLite saver 官方面向本地、测试或轻量部署，符合当前单用户本地验证范围。严格反序列化使用 `LANGGRAPH_STRICT_MSGPACK=true` 或显式 `allowed_msgpack_modules`；图业务状态以 JSON 基本类型保存，恢复测试应同时覆盖框架 interrupt 值。[SQLite saver 官方说明](https://pypi.org/project/langgraph-checkpoint-sqlite/3.1.1/)。

## 恢复、身份与发布

官方协议：恢复使用同一 `thread_id` 和 `Command(resume=...)`；interrupt 所在节点从开头重新运行，父节点中调用的子图 interrupt 也会导致父调用节点重跑。不要用宽泛异常捕获吞掉 interrupt；中断值使用可序列化结构。[Interrupts](https://docs.langchain.com/oss/python/langgraph/interrupts)。

Checkpointer 存储 thread 的图状态；应用数据存储是另一个职责。持久文件 saver 才能跨进程重启，InMemorySaver 不满足要求。[Persistence](https://docs.langchain.com/oss/python/langgraph/persistence)。

项目实施建议（由上述行为推导，不是框架自动保证）：

- Session ID 表示会话；Turn ID 表示用户轮次；Run ID 表示一次可恢复执行，重试和恢复保留 Run ID。专业任务有 Task ID 和 Parent Run ID。图 thread 使用明确的一对一 Run ID 映射；长期会话工作状态由业务存储持有并在新 Run 接收时加载。
- 同一 Run 的 invoke/resume 必须串行；同一 Session 的业务工作状态更新使用版本校验。独立 Run 的图执行可以并行，不能把 SQLite 支持多个连接误解为允许同一逻辑 thread 并发推进。
- 业务产物按稳定 operation key 注册，并对重复 key 核对 payload 一致；文件先写暂存位置、校验后发布。业务提交成功但 checkpoint 尚未写入时，重放读取已提交产物，避免重复发布。不要宣称 checkpoint 和业务事务有天然跨库原子性。
- 停机后只列出可恢复 Run，不在 startup 自动调用 invoke，以免重复收费。计算或模型调用在崩溃窗口仍可能重复执行；产物幂等与付费调用 exactly-once 是不同承诺。

SQLite 一次只允许一个 writer；WAL 可使 reader 与 writer 并存，但不提供多 writer 同时提交。建议短事务、busy timeout、WAL，使用真实多连接并发写入和重复恢复测试核对；不在模型调用或 Docker 等待期间持有业务事务。[SQLite isolation](https://www.sqlite.org/isolation.html)。

## Python 容器边界

Docker 文档支持只读 rootfs、非 root 用户、capability 收缩、no-new-privileges、PID/CPU/内存约束。`--memory-swap` 与 `--memory` 相同可避免默认额外 swap allowance。[Docker run](https://docs.docker.com/engine/containers/run/)，[CLI flags](https://docs.docker.com/reference/cli/docker/container/run/)。`--network none` 仅保留 loopback，不能访问应用网络。[None driver](https://docs.docker.com/engine/network/drivers/none/)。

建议 A 验证采用宿主可信控制进程创建每次独立的 Linux runner 容器：不继承应用 env，不挂载项目根目录、配置、Docker socket 或控制进程目录；仅挂载选定输入快照和可信统计脚本为只读。执行容器的能力边界与宿主 Docker controller 分开。Docker daemon 权限本身强，应仅由可信控制面持有；若后续要向业务容器提供 socket 或部署常驻 broker，属于需要单独确认的部署取舍。[Docker Engine security](https://docs.docker.com/engine/security/)。

建议初值（待测）：非 root UID 10001；`--read-only --network none --cap-drop ALL --security-opt no-new-privileges --pids-limit 64 --cpus 1 --memory 256m --memory-swap 256m`；有大小上限的 tmpfs 作为工作/输出空间；墙钟超时由控制面停止并移除容器。tmpfs 的 size 可约束挂载容量，但数据可能写入 swap，应结合内存/swap 配置验证。[tmpfs mounts](https://docs.docker.com/engine/storage/tmpfs/)。

A 的固定脚本可使用 Python 标准库 csv/decimal/json 完成全表统计，无须提前确定 pandas 或 PandasAI。控制面仍需限制 stdout/stderr、返回文件大小/数量，并拒绝产物路径穿越或符号链接；tmpfs 总量限制不能替代逐产物协议验证。非零退出、超时、取消、OOM 应区分返回，不能当作空结果。

## 实施验收清单（尚非通过证据）

1. 两个独立 Python 进程分别 interrupt 和 resume；读取原 checkpoint、范围快照与产物身份。
2. 重复请求/重复恢复、发布后模拟异常再恢复，最终产物与用户发布事件仅一次；不同 Run 并发写入不串状态。
3. 实际 inspect 核对容器 User、ReadonlyRootfs、NetworkMode、CapDrop、SecurityOpt、Memory、MemorySwap、PidsLimit 和 Mounts，不打印 Env。
4. 容器内实际探测应用密钥变量缺失、应用路径不可读、输入与 rootfs 不可写、外网失败；超时与主动停止后容器不存在。
5. SITECO 11,386 行全量统计与宿主独立预期一致；分别记录冷启动、数据加载、计算、输出和总耗时。环境未跑通就保留为未验证。
