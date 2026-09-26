# 当前交接摘要

更新日期：2026-09-26。

## 当前阶段与目标

- M0 进行中；目录、Git/GitHub 起点和最小开发环境已建立，尚未迁移代码或完成 M0 验收。
- 本轮按用户要求独立安装 Python 3.12.10，用 py -3.12 重建 backend/.venv，验证后更新开发说明和 P-006。
- 应用框架、解析、模型、检索与应用测试边界仍待确定；依赖分批补充。

## 接手入口与已确认选择

- [AGENTS.md](../AGENTS.md)、[Milestones](../milestones_and_execution_plan.md)、[决策](../decisions.md)、[开发环境](../docs/development.md)。
- 本地需求：[requirements_draft.md](../requirements_draft.md)，按用户要求忽略，不随仓库交付。
- P-001：先检查材料再确定关键方案；P-002：milestone 与交接。
- P-003：忽略需求草案、private/data/tmp、真实环境变量及生成产物；保留人工开发记录，M5 整理面试官可见内容及历史。
- P-004：私有仓库与首次提交前确认；P-005：Python 3.12 后端、pip/venv；P-006：独立 Python 安装替代 Codex 基础解释器，框架及应用依赖另定。

## 工作区与 Git 状态

- 工作目录：D:\Projects\Retrieval_SITECO；main 尚无提交，无暂存内容，审查基准待首次提交后建立。
- origin：https://github.com/LaoM10617/jingwenxu_siteco_docRetriever.git；已验证私有空仓库，本轮没有远程写入、邀请、commit 或 push。
- 12 个可入库文件仍未跟踪：.dockerignore、.env.example、.gitignore、AGENTS.md、README.md、decisions.md、docs/development.md、docs/reuse.md、eval/materials.md、logs/current.md、logs/m0.md、milestones_and_execution_plan.md。
- 本轮重建忽略的 backend/.venv；修改 development.md、decisions.md 和人工日志。安装包和安装日志位于被忽略的 tmp/installers。
- .dockerignore、.env.example 仍为空；README 目前为目录树。应用源码目录仍为空，Git 不保留空目录。

## 实际验证

- Docker Desktop 4.92.0；CLI/Engine 29.8.0；Compose v5.5.1。
- WSL 2.7.14.0，docker-desktop 为 Running / VERSION 2；Docker 为 Linux/amd64，内核 6.18.33.2-microsoft-standard-WSL2。
- docker run --rm hello-world 输出 Hello from Docker，测试容器已自动移除，镜像保留在缓存。
- Docker 已按用户安装在 LOCALAPPDATA/Programs/DockerDesktop。保存的用户 PATH 已含 CLI 目录，当前 Codex 进程环境未刷新；本轮使用明确路径与会话级 PATH 验证成功，没有修改永久 PATH 或 WSL 配置。
- Node 24.19.0、npm 11.17.0 与 Node 运行检查通过；未安装前端应用依赖。
- py -3.12 已指向独立安装的 Python 3.12.10：LOCALAPPDATA/Programs/Python/Python312。官方安装器签名 Valid（Python Software Foundation），退出码 0。全局 python 仍为 3.14.7，旧项目未修改。
- 虚拟环境 pip 25.0.1，目前只含 pip；隔离检查、ssl/sqlite3/venv 导入及 pip check 通过。
- git check-ignore 确认 backend/.venv 被忽略；开发文档中的会话 PATH 与隔离检查命令执行成功。

## 限制与注意事项

- 本机 venv 已不依赖 Codex 缓存，而依赖独立 Python312 安装。3.12.10 是最后提供传统 Windows 安装器的版本，不是最新安全补丁；从原 3.12.14 降至 3.12.10 的取舍已记录，后续验证依赖并单独选择容器补丁版本。
- Docker 工具检查不等于项目镜像构建；应用依赖兼容、模型连通性、前端构建、Docker 项目构建和端到端流程未验证。
- .dockerignore 应在首次项目镜像构建前补齐。
- 普通 shell 仍遇 helper_unknown_error: setup refresh had errors；工具提升权限路径成功，不作为项目运行要求。
- 本轮未启动应用服务、未修改旧项目、未改 PATH 或文件关联、未改 Docker/WSL。

## 下一步

- 确认首个迁移模块及首次公共测试边界后再迁移和安装相应依赖；此前定向检查的 RRF 是独立候选。
- 用户已授权首次本地提交，message 为 initialize project structure and development setup；明确不 push。随后仅盘点迁移候选，等待用户人工 review，不执行迁移。
- M0 未完成，不将最小环境就绪描述为应用或容器化交付完成。
