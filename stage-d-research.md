# 阶段 D 执行器接入研究

核对日期：2026-10-12。本文是候选方案与技术依据，不是用户已确认的决定或实现证据。后端接入方式与新增依赖仍等待用户决定；已确认的隔离方向以 decisions-design.md 第 14.4 节为准。本次未安装依赖、部署服务、挂载 Docker socket 或运行新的 Docker 验证。

## 已有实现与复用

已读取 AGENTS.md、decisions-design.md、plan.md、stage-c-log.md、stage-a-research.md，以及以下代码：

- backend/app/python_executor.py：可复用一次性容器、只读输入副本、无网络、非 root、资源约束、有限 JSON 输出、取消与超时清理。Docker create 响应丢失时按预分配名称清理的逻辑也应保留。
- backend/tests/test_python_executor.py：11 项真实 Docker 测试需要在 D 修改执行器后重跑；阶段 C 的跳过不是本轮通过证据。
- scripts/probe_python_executor.py：可复用 SITECO 全表统计与独立 Decimal 预期、阶段耗时和清理证据。
- backend/app/agent_protocol.py：复用 TaskPackage、TaskResult、来源范围与产物描述协议。
- compose.yaml、backend/Dockerfile、backend/requirements.txt 和 lock：后端目前有模型密钥、没有 Docker socket；执行镜像目前仅有标准库。现有应用 NumPy 依赖不代表独立执行镜像已安装 NumPy。

当前执行器缺少后端 broker、稳定 job 身份、持久运行登记、容器归属标签与进程强杀后的孤儿回收。不能仅把现有 execute 方法包装成任意宿主路径可调用的接口。

## 接入候选（历史讨论，已由后续确认取代）

后续用户已明确选择宿主 worker 主动领取、隔离 pandas 和按需 review；当前实现与固定依赖见 decisions-design.md 第 17 节。下列推荐仅保留当时比较过程，不是当前待决事项。

| 方案 | 收益 | 代价与约束 |
| --- | --- | --- |
| 宿主认证 HTTP broker（推荐） | 后端与控制程序通过小接口通信；复用现有执行器；不共享业务库写入职责 | 新增宿主进程、认证配置与网络可达性验证；请求不得选择宿主任意路径、镜像或 Docker 参数 |
| 宿主 worker 从后端领取任务 | 不新增宿主监听端口，后端沿用已有本地发布端口 | 增加领取、租约、结果回传与取消轮询协议 |
| 专用共享目录 spool | 无新增网络监听 | 增加跨 Windows/Linux 原子文件提交、权限、轮询、结果与垃圾清理协议，维护面更大 |

推荐 HTTP 请求只携带稳定 job 身份、内容摘要、脚本以及有限输入内容/版本摘要，由可信 broker 选择固定镜像和隔离参数。使用后端认证配置，不向模型公开 broker 接口或凭据。后端保留业务状态及产物发布权威；broker 仅维护执行生命周期。失败返回明确状态，不伪装空统计。

Docker Desktop 官方提供 host.docker.internal 访问宿主服务；这不保证所有平台上的 loopback 监听均可达。Windows 监听地址、防火墙、容器到宿主访问和未授权访问拒绝必须在选定部署中实测。不要为方便直接暴露到所有网络接口。[Docker Desktop 网络说明](https://docs.docker.com/desktop/features/networking/networking-how-tos/)

## 接入生成脚本前必须完成的恢复条件

以下为项目实现建议，不是 Docker 自动提供的保证：

- 稳定 job 身份加内容摘要：同身份同内容返回已有结果，同身份不同内容拒绝；区分业务幂等发布与可能重复发生的实际计算。
- 在 Docker create 前持久登记 job、预分配容器名、输入摘要和 staging 归属；使用项目实例及 job 标签，避免宽泛名称前缀清理其他任务。
- broker 单实例控制；启动时核对本实例残留容器与 staging，只清理自己的孤儿。重启标记 interrupted，不自动重新计算或触发模型调用。
- Docker 不可用、清理失败必须保留可诊断记录，不宣称完成；任务超时不等于包含创建和清理的总请求硬时限。
- 后端发布结果前再次检查停止、来源删除及 run 状态，拒绝迟到结果；停止应可终止正在运行的容器。
- 真实验证 broker 被强杀、create 响应丢失、完成响应丢失、取消竞争、重启回收和重复 job。

Docker 守护进程属于高权限控制面；继续仅由可信宿主程序持有权限，后端与脚本均不挂载 socket。[Docker Engine 安全说明](https://docs.docker.com/engine/security/)

## pandas 候选与正确性（调查时记录）

pandas 3.0.6 已由官方文档标题及版本专属 PyPI JSON 确认存在，因此可作为候选；尚未安装、解析依赖、锁定 wheel 或完成兼容验证，不是已批准依赖。PyPI 元数据列出 Python 3.12 支持分类。下一步需对选定 Python 3.12/Linux 执行镜像实际解析、固定完整依赖并运行 pip check。[pandas 3.0.6 发布元数据](https://pypi.org/pypi/pandas/3.0.6/json)

推荐仅执行镜像增加 pandas，不引入 PandasAI。官方列出的必需依赖为 NumPy、python-dateutil，Windows/Pyodide 另需 tzdata；无需为 CSV 分析引入所有可选 extras。图表可先返回结构化数据与规格，不因 pandas 自动画图能力就引入 matplotlib。[pandas 安装说明](https://pandas.pydata.org/docs/getting_started/install.html)

通用 CSV 原始层应保存字符串、稳定行身份与显式缺失规则，再按已确认语义构建计算值。pandas read_csv 默认把空串、NA 类文本和 NULL 等识别为缺失值；不能直接依赖默认推断保留编号和原始值。金额应使用 Decimal 或明确缩放整数，不能把二进制浮点聚合作为精确金额依据。[read_csv 参数](https://pandas.pydata.org/docs/reference/api/pandas.read_csv.html)

pandas merge 会匹配两侧 null 键，与常见 SQL 行为不同。需明确空键口径，并对 one_to_one、one_to_many、many_to_one 使用 validate；many_to_many 本身不执行唯一性检查，仍要检查连接放大与结果规模。[merge 行为与校验](https://pandas.pydata.org/docs/reference/api/pandas.merge.html)

## 资源与验证建议

先在现有 1 CPU、256 MiB 内存、等值 memory-swap、64 PID、30 秒执行时间和 1 MiB 合计输出限制下实测 pandas 导入、SITECO 全表、分组与 join；没有证据前不承诺这些限制足够，也不直接调高默认值。内存与 swap 相等用于限制额外 swap allowance，实际行为依赖运行环境。[Docker 资源约束](https://docs.docker.com/engine/containers/resource_constraints/)

新增 NumPy 后应评估 BLAS 线程数，通过可信固定环境配置限制线程，避免耗尽 PID 配额；这些变量不能从应用环境整体继承。记录镜像身份、安装闭包、启动/加载/计算/序列化耗时及峰值资源。验证 OOM、无限输出、网络、密钥、宿主文件、只读输入、非 root 和停止；加入 broker 往返、重启回收及未授权访问。D 完成标准仍需真实环境证据，mock 只覆盖错误与竞争路径。

## 后续落地结果

用户已批准 pandas。实际在 CPython 3.12/Linux amd64 解析并锁定四包 wheel hash（见 runner/requirements.lock），Docker build 的 `pip check` 通过，真实隔离/helper 与 11,386 行分析证据见 stage-d-log.md。固定 BLAS 线程为 1，原 256 MiB/1 CPU/64 PID 边界下已验证基准；输出为支持完整结果提高至 16 MiB。未测所有可能数据规模的峰值内存，不将当前成功外推为通用性能保证。

实际实现为后端 HTTP 接口供宿主 worker 主动领取，宿主无入站监听端口。已通过真实 worker 强杀回收、运行中停止和完成响应丢失后的幂等重传；Docker create 响应异常由隔离执行器测试覆盖。不存在宿主 HTTP broker 部署。
