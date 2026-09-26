# 当前交接摘要：M2.2验收通过（生命周期范围）

2026-09-26。M0/M1完成；M2.1基础运行、M2.2上传/生命周期/HTTP验收通过。真实解析、Embedding、FAISS、问答和前端未实现，M2整体未完成。

## 当前依据

P-010至P-022，docs/m2-first-contracts.md；T-002至005已批准。FastAPI/React+TS、最小双容器；SQLite持久化、按文档FAISS CPU IndexFlatIP（选定未安装）；data/runtime绑定D盘，Docker镜像/缓存仍在C盘。20MiB、PDF50页、CSV20,000记录、10活跃文件、德英；108页报告退出M2基线。voyage-4 1024维/float32，3RPM/10KTPM共享调度；Gemini/Groq免费优先，付费由用户切换。保留题M4/M5再用。

## 实现与验证

- config/main健康与配置、Docker/Compose无Key启动和磁盘保留已验证。一个后端进程，UID10001、单worker。运行中SQLite仅后端访问，使用HTTP轮询；不跨Windows/Linux同时打开数据库。
- documents.py持久化原文件/身份/hash、原子容量预留、20MiB实际字节和接收清理；单有界队列/工作线程，四状态、stage、完整发布门槛、retry沿原ID且重查容量、关闭/启动中断失败。关闭协作等待2秒，迟到结果不能发布；非可靠任务队列。
- processing.py为适配器契约。正式默认上传202后failed/processing_not_configured，不伪造ready；测试适配器证明成功发布和恢复。JSON证据/manifest不替代未来原始向量BLOB存储。
- HTTP六接口已接：health、POST上传、GET列表、GET详情、POST retry、GET分页evidence。未知404、未ready409、大小413、类型415、参数422、存储503；公开字段白名单与error code/message/retryable。progress=null、warnings=[]，计数与解析警告待真实处理器接入。
- 最新Windows/Linux各52测试+10subtests，pip check通过，1条既有Starlette/httpx弃用警告。包含实际子进程终止、旧ready隔离、重试/容量；HTTP补分页/未知ID/脱敏/中断。Linux测试时序假设已修正为处理器事件同步。
- Docker全HTTP验收：独立同名上传、轮询失败、证据门槛、down/up后列表/详情保留、health200。隔离项目siteco-m22-http已down；忽略tmp/m22-http-acceptance保留验收数据。早前宿主并发读SQLite异常详见logs/m2.md，本轮全HTTP正常。
- 无真实Key读取/模型调用/commit/push。解析器、FAISS和模型SDK未安装。详细操作及证据见README、docs/development.md、logs/m2.md。

## Git与环境

main；M2审查基准仍为4307e22ceb08b70d6dca459137355b0551f2e6c1。用户已授权将当前框架/模型决策、M2.1与M2.2实现作为检查点提交并推送，提交消息为“Confirm frameworks, models, and embeddings; configure APIs and initial Docker setups; and establish closed-loop upload and lifecycle management processes.”。本摘要随该检查点提交；具体提交ID及推送结果以Git历史/远程为准。完整M2阶段审查仍待后续端到端完成。密钥、原材料、运行数据和临时验收产物保持忽略。


Docker29.8.0 Linux/amd64；必要时会话PATH加LocalAppData/Programs/DockerDesktop/resources/bin。Docker VHDX在C盘，不自行迁移或清理无关数据。无本次遗留运行容器。

## 下一步

进入PDF/CSV解析到证据，先拆步骤和具体依赖/解析语义（T-003、pdf技能），再实施。真实文档到ready需解析、Embedding、FAISS接入后验收；不要把M2.2测试适配器成功当作真实检索成功。前端/问答、整体Docker浏览器端到端及M2双轴审查仍待完成。
