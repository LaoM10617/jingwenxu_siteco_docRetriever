# 本地 Docker 部署与迁移

本文件描述新架构的部署操作。2026-10-14 已用独立 Compose 实例验证新版本
前后端、宿主 worker 和真实 PDF/CSV 浏览器链路，验证后已停止；日常实例未升级。
最终抢占修复仅有后续定向回归，早先验证镜像不含该修复，启动当前版本须重新构建。
源码为 `main / 4c05c32` 加未提交 G 改动；只克隆该提交不会获得 G。部署前须完整
转移已核对的源码或使用后续获准提交版本。执行以下步骤前先确认目标实例和数据目录。

## 新实例

需要 Docker Linux 容器引擎（Windows 使用 Docker Desktop）和宿主 Python 3.12。
当前 runner 锁文件的验证平台是 Linux/amd64；其他平台未验证。后端保持单进程
Uvicorn，不增加副本；业务 SQLite 与 checkpoint 协调依赖此运行约束。

1. 将仓库复制到目标机器，复制 `.env.example` 为项目根目录的 `.env`。
   在本机安全编辑密钥，不粘贴到日志、聊天、命令行参数或前端构建变量。
   `.env` 被 Git 和 Docker build context 排除；运行环境变量优先于 `.env`。
2. 设置 `COMPOSE_PROJECT_NAME`、`HOST_PORT`、`FRONTEND_PORT` 和 `HOST_DATA_DIR`。
   第二实例必须使用不同名字、端口、数据目录、worker 目录与 token。
   相对 bind 路径以 Compose 文件所在目录解析；Windows 绝对路径可使用
   `D:/siteco-data/runtime`。容器内部固定 `DATA_DIR=/app/runtime`。
3. 预先创建目标 runtime 目录。Compose 不自动创建不存在的 bind 源，避免路径拼错
   后悄悄启动一个空实例。Linux 上确保 UID/GID `10001:10001` 可读写该目录；
   Windows 确认 Docker Desktop 文件共享及目录 ACL。SQLite 文件应放本机磁盘，
   不放网络共享或同时被同步软件写入的目录。
4. 在仓库根目录构建并获取固定镜像身份：

   ```powershell
   docker build -t siteco-csv-runner:local -f runner/Dockerfile .
   docker image inspect --format '{{.Id}}' siteco-csv-runner:local
   docker compose build
   ```

   将完整 `sha256:...` 写入 `.env` 的 `EXECUTION_IMAGE`。生成随机
   `EXECUTION_WORKER_TOKEN`，仅交给后端与该实例的可信宿主 worker。
   模型密钥按选用 provider 配置：`GEMINI_API_KEY` 或 `GROQ_API_KEY`；
   PDF embedding/rerank 使用 `VOYAGE_API_KEY`。缺少密钥允许本地启动，相关能力
   会报配置错误，不能据此声称真实链路可用。
5. 校验配置、准备固定摘要 tokenizer，再启动：

   ```powershell
   docker compose config --quiet
   docker compose run --rm --no-deps backend python -m app.prepare_tokenizer /app/runtime/tokenizers
   docker compose up -d
   ```

   不将普通 `docker compose config` 或 `docker inspect` 的环境变量输出写入记录，
   它们可能展开密钥。tokenizer 准备需要一次联网；迁移已校验的 tokenizer 可离线复用。
6. 宿主安装锁定依赖，启动主动领取 worker（这里沿用独立 `.venv`）：

   ```powershell
   py -3.12 -m venv .venv
   .venv/Scripts/python.exe -m pip install -r backend/requirements.lock.txt
   .venv/Scripts/python.exe scripts/run_python_worker.py --backend http://127.0.0.1:8000 --work-dir data/python-worker --image sha256:YOUR_IMAGE_ID
   ```

   将示例端口替换为 `HOST_PORT`。启动前由可信进程环境注入同一
   `EXECUTION_WORKER_TOKEN`；worker **不会**读取 `.env`。不要用 shell 执行或
   `Invoke-Expression` 加载 dotenv。Linux 使用 `.venv/bin/python` 和等价环境注入。
   如使用服务管理器，保存工作目录、解释器、image 与 backend 参数，将 token 放入
   仅服务用户可读的配置。Compose 不管理宿主 worker 的开机启动。

浏览器打开 `http://127.0.0.1:8080`（或所选前端端口）；健康检查为后端
`/api/health`。这只验证服务存活。另做一份小 CSV 上传/确定性概览/分析、停止和
重启恢复验证；PDF 需独立验证真实 embedding、检索和引用。记录源码提交、镜像 ID、
实例名、数据路径及检查结果，不记录密钥。前台每轮模型调用硬限仍为 6。

## 存储与边界

| 路径 | 内容与迁移要求 |
| --- | --- |
| `HOST_DATA_DIR/uploads/` | 原始资料；与业务库一起保留、备份并校验摘要 |
| `HOST_DATA_DIR/app.sqlite3` | 文档/版本、session、消息、规则、索引、产物、调用回执、执行任务及后台探索业务状态的权威库 |
| `HOST_DATA_DIR/conversation-checkpoints.sqlite3` | LangGraph 检查点；不能替代业务库，也不能单独恢复为另一份业务状态 |
| `HOST_DATA_DIR/tokenizers/` | 固定版本公开 tokenizer，可重新准备；不是模型权重 |
| runtime 内其他文件、SQLite sidecar 与锁目录 | 随整目录冷备份保留；不要从运行中的实例挑选复制单个数据库 |
| worker `--work-dir` | `worker.sqlite3` 保存实例身份及交付回执，另有锁和临时输入/产物；每实例独占、包含用户数据，限制读取权限 |

阶段 A 探针中的 `business.sqlite` / `checkpoints.sqlite` 不是当前正式应用的库名。
worker 不直接读写后端 SQLite；后端不挂 Docker socket。只有可信 worker 启动
无网络、只读根目录、非 root、有限资源的一次性 pandas 容器。
固定镜像更新后，后端和 worker 必须一起更新。已有 run 保存旧执行镜像快照，
恢复它需要旧镜像/相容配置；不能把换镜像当作透明恢复。

本应用仍是个人本地实例，无多人账号隔离；session 访问规则是应用内部边界。
默认端口仅绑定 loopback，迁移不应顺手改为公开监听。跨机器 worker 需要 HTTPS。
后台结果保存在独立接口中，不自动发布到聊天；具体接口见阶段 G 交接。

## 一致备份与恢复

采用停写后的整目录冷备份，避免业务库与 checkpoint 各自在线备份产生不同时间点。

1. 关闭后台探索、停止或等待前台运行结束，禁止新上传/新请求。
2. 正常停止宿主 worker，确认该 worker 所属的执行容器已结束；正常停止目标
   Compose 实例（`docker compose stop`）。确认不存在继续写入同一目录的本地
   Python 服务。不要在此步骤删除容器卷或原始资料。
3. 将完整 runtime 和 worker work-dir 复制到新的备份目录，保留所有 SQLite
   sidecar；同时保存源码提交、锁文件、runner 镜像身份。密钥另外加密备份，不与
   可分享的数据包混放。备份本身包含原始资料和对话，需要相同访问保护。
4. 校验原始资料复制前后 SHA-256 一致；在备份副本上对两份正式 SQLite 执行
   `PRAGMA integrity_check`，保留结果。不要在活跃库上复制单个 `.sqlite3` 文件
   并遗漏 `-wal` / `-shm`。
5. 在目标机器恢复到新的目录，先恢复权限；更新 bind 路径和 worker 路径。
   同机不要同时启动原实例和使用同一 worker 身份的克隆。需要继续旧任务时，
   使用 `docker image save` / `docker image load` 迁移原 runner 镜像并核验 ID；
   重新构建不保证保留相同 ID。
6. 启动后检查健康、session/资料/历史产物、worker 通信。中断任务不会自动重算，
   通过显式恢复入口处理；worker 重启仅回收自己的容器并重传已有交付回执。
   后台探索持久预算不得因复制/重启补发。恢复验证完成前保留原备份。

代码升级先在上述副本与独立实例名/端口上验证。新版本建表不等于支持向旧版本
反向迁移；回滚需要配套代码、镜像和升级前数据快照，不能仅切回旧容器镜像。
