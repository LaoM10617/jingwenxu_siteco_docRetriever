# 阶段 B 实施与验证记录

日期：2026-10-12。授权：用户在 A 完成后明确“接下来请你执行阶段B”。当前：B 代码、跨平台回归、真实 Docker HTTP 验证和审查均完成；不推进 C。架构细节只在 decisions-design.md 第 15 节维护。

## 基线与改动

- `main / 269d5fe`，无 commit/push。接手时 A 的未提交改动完整存在；没有覆盖或删除它们。
- 实读 AGENTS.md、设计、计划、A Log，核对 Docker 前后端健康及挂载；Python 3.12.10 / pip check 正常。
- 新增 `backend/app/sessions.py`、`artifacts.py`、`session_api.py`；修改 `documents.py`、`uploads.py`、`main.py`。
- 新增 `test_sessions.py`（11）、`test_artifact_lifecycle.py`（7）、`test_session_api.py`（2）、`test_session_uploads.py`（5）：合计 25 个 B 专项用例。旧 `test_documents.py` 更新上传响应新增版本字段的精确断言。
- 新增 `scripts/prepare_stage_b_validation.py`、`scripts/probe_stage_b.py`，更新设计和计划；B 无新增依赖，工作树中 requirements 改动属于 A。

## 完成能力

| 能力 | 代码已实现 | 验证 |
| --- | --- | --- |
| Session/消息 | 独立持久化、无 TTL、显式删除、来源依赖、历史/当前上下文分开 | 新进程读取、模拟两天后仍存在、HTTP 重启 |
| 范围 | 本轮/持续/用途、讨论对象分离、版本冲突、追加规则事件 | A/B/C 来源优先级、跨会话拒绝、并发单成功 |
| 版本 | 显式逻辑身份、独立上传版本、ready 自动加入所属会话 | 新旧并存、不默认替换、未知 session 上传回滚 |
| 快照 | 接收时保存版本、用途/筛选与修订号，重复请求幂等 | 之后上传/规则修改不改历史，重复来源规范化 |
| 产物/缓存 | session 内登记、版本/口径复用校验、失效与历史读取 | 改来源/过滤条件不复用、不能跨会话取缓存 |
| 删除 | 会话移除/垃圾桶/恢复/永久删除，持久删除意图 | unlink 与 SQL 清理失败后重启可继续，无已删除来源重新可用 |

公开 session API 可独立使用；没有要求旧 UI 已适配，也没有实现 C 主图/自然语言解析。产物发布为内部可信接口，不开放任意客户端伪造专业结果。

## 数据与迁移验证

旧运行目录：`D:\Projects\SITECO-document-chat\data\docker-e2e`，挂载 `/app/runtime`。默认 `data/runtime` 另存在，本轮不改它。

运行 `scripts/prepare_stage_b_validation.py`：SQLite backup API 以只读源连接复制一致数据库；复制 4 份原件（合计 13,364,860 bytes），逐份对照 content_hash 验证。备份在：

`data/stage-b/20261012T141906480385Z/backup`

只读原件/源库，未迁移或清空正在使用的运行目录。`runtime` 是首次验证副本；`runtime-retry` 是从 backup 新复制的最终验证副本。上传、垃圾桶和永久删除仅操作这些副本中的测试资料。

迁移为增量建表及版本登记；不重解析/重新 embedding 已有资料，不把旧文件自动加入新 session。旧问答表留在旧协议内，新 session/消息表独立；C 再切换问答入口。

## 测试命令和结果

```powershell
.\.venv\Scripts\python.exe -m pytest backend/tests/test_sessions.py backend/tests/test_artifact_lifecycle.py backend/tests/test_session_api.py backend/tests/test_session_uploads.py -q
.\.venv\Scripts\python.exe -m pytest -q --basetemp data/stage-b/pytest-windows-final
docker build --target test -t siteco-phase-b-tests -f backend/Dockerfile .
.\.venv\Scripts\python.exe scripts/prepare_stage_b_validation.py
.\.venv\Scripts\python.exe scripts/probe_stage_b.py data/stage-b/20261012T141906480385Z/runtime-retry
```

最后一条需要新准备的副本；验证会修改副本，不能重复用已完成的副本冒充首次迁移。

- Windows 最终：**410 passed、11 skipped、10 subtests passed，127.90s**。
- Linux 最终 Docker test target：**410 passed、11 skipped、10 subtests passed，79.58s**。镜像 `siteco-phase-b-tests:latest`，image ID `34db886cec9e`。
- 11 项 skip 为 A 的显式 Docker 执行器测试，B 未改执行器，未机械重跑；A 的真实 11 项通过证据见 A Log。B 的 Docker HTTP 验证单独记录，不把 skip 称为通过。
- 专项最终代码包含 25 个 B 用例；旧回归保持通过，测试中的 provider 外部调用依然是模拟，不声称真实模型问答验证。
- 真实 Docker HTTP：全部通过。验证旧库副本打开/不自动关联、全表 CSV 上传/显式版本关系/隔离、容器重启保持 session/消息/快照/产物、移除/垃圾桶/恢复/永久删除及派生失效。全表样本采用现有 11,386 行 CSV，无密钥、无真实模型/Voyage调用。回执 `data/stage-b/20261012T141906480385Z/http-receipt.json`；验收与诊断容器均清理。

## 审查、失败复现和修复

- 使用 karpathy-guidelines / codebase-design / tdd；领域细节按 domain-modeling 记录进现有设计；故障按 diagnosing-bugs，审查按 code-review Standards/Spec 双轴。
- SessionStore 各纵向切片先缺接口失败再实现；上传初测因缺 session 状态失败，接入后通过；删除先缺接口，新增持久意图后通过。
- 旧上传测试严格要求原三字段；版本协议增加两字段后，仅该断言失败，按新协议更新。
- 双轴审查发现重复来源导致合法快照发布 UNIQUE 失败；本轮/default/purpose 三条测试先 **3 failed**，入口保序去重后全部通过。
- scope.filters 保存为不透明约束，新增回归验证不同筛选口径不能命中旧结果缓存。
- 真实 HTTP 首次验证重启后连不上：服务日志显示 startup complete、容器内 health 正常；直接复现 Docker 将动态主机端口从 49675 改为 60790。修正验收脚本在 restart 后重新读取映射，不修改业务代码。最终复验使用全新副本。
- Standards / Spec 最终代码复核均通过，无剩余 B 阻塞发现；审查要求的真实 HTTP 复验现已通过，可以交接。

## 限制与下一步入口

- B 新 Session 无 TTL；旧 `/api/questions`、旧内存调度和旧 UI 会话逻辑仍存在，按 C 计划替换。当前主服务未重建部署 B，B 真实验证使用独立容器。
- 仍有旧导入/解析资源限制：20 MiB / 10 活跃文件 / PDF 50 页 / CSV 20,000 行。B 审查后保留于现有处理模块，D/E 再调整，不把这些上限定为新产品要求。
- 产物目前为小型 SQLite JSON，没有大型文件/图像的存储与清理协议；D 扩展时需要统一依赖登记。缓存不跨 session。
- SQLite 单机事务保证当前短操作一致性，C 长图调用不能把业务写事务跨模型调用持有；继续用 A 的 session 串行化与幂等恢复方案。
- 下一步 C 经用户安排后，从 SessionStore.snapshot/messages 和 ArtifactStore.publish/reuse 接入真实主图/PDF 路径，再验证模型、引用、停止/恢复。不得把 B 的确定性生命周期验收称作新 Agent 问答已完成。
