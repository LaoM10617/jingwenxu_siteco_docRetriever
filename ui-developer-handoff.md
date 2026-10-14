# UI 与独立开发者模式接口交接

日期：2026-10-14。本文记录已存在的后端契约和后续界面入口，不实施视觉重构或开发者标签页。设计权威为 `decisions-design.md`，阶段完成、测试及部署状态以 `plan.md`、`stage-g-log.md` 为准。

当前 `main / HEAD / 本地 origin/main = 4c05c32`，G 实现和本交接仍未提交；该提交只含此前获准的 README 更新。G 已有双平台全量、真实探索和应用冒烟证据；最后抢占修复后定向 37 项通过，详见日志版本边界。独立验证实例已停止，日常实例未升级。F 真实验证仍为跨修复续跑，历史 partial 不改写；本轮无 commit/push。

## 1. 身份、状态和客户端职责

- `session_id`：持久会话；浏览器只保存当前会话指针和界面状态，消息、规则、运行和产物由后端持久化。
- `DocumentVersion`：`{"document_id":"逻辑文件身份","version_id":"不可变版本身份"}`。上传返回的旧兼容 `document_id` 是存储版本身份；`logical_document_id` 才是逻辑文件。资料列表和 `/api/documents/{document_id}` 仍使用存储版本身份。不能假定新版逻辑身份始终等于版本身份。
- session `data_version` / `rule_version`：乐观并发版本。提交、关联、规则更新前读取；冲突后刷新并让用户确认当前范围，不用旧版本盲重发。
- `request_id`：一次提交的稳定幂等身份；连接中断时先查会话 runs，再用同一身份及相同内容重放，不能生成新身份导致重复付费。
- `turn_id` / `run_id` / `task_id`：交互、可恢复执行、专业任务的不同身份；不要按消息文本拼接或推断。
- `artifact_id`、`snapshot_id` 和来源依赖共同描述结果；历史可见不等于当前可复用。`source_available=false` 应保留历史回答并显示来源不可用。

后端没有多人账号权限系统。session 限定的 run、snapshot、artifact 接口会检查身份归属；全局文档库、版本查询及 evidence/preview 路由不接收 session 参数。不能把当前会话隔离宣传成完整用户认证/文档访问控制。

## 2. 会话、来源、范围和版本

以下路由均已实现，JSON 请求拒绝未知字段。省略路径前缀时以 `/api/sessions/{sid}` 为准。

| 操作 | HTTP 接口 | 主要请求/返回 |
| --- | --- | --- |
| 创建/列表/读取/删除会话 | `POST/GET /api/sessions`；`GET/DELETE /api/sessions/{sid}` | 创建无需 body；读取含来源、规则、focus、两类版本号。删除连带任务/checkpoint 清理，不自动重跑模型。 |
| 加入/移除会话来源 | `POST /sources`；`POST /sources/remove` | `{source: DocumentVersion, expected_data_version}`；移除不等于全局删除。 |
| 持续规则 | `PUT /rules` | `{expected_rule_version, default_sources: null或数组, purpose_sources: {用途: 来源数组}}`；这是整体规则写入，不是单字段 merge。 |
| 讨论对象 | `PUT /focus` | `{focus: ResolvedReference或null}`；是指代线索，不授予来源权限。正式结构见 `agent_protocol.py`。 |
| 形成/读取确定范围 | `POST /snapshots`；`GET /snapshots/{snapshot_id}` | `{request_id, expected_data_version, expected_rule_version, purpose?, explicit_sources?, filters?}`。 |
| 消息 | `GET/POST /messages` | 写入只接受 `{message_id, content}` 的用户消息；正常提问走 runs，避免另写重复消息。 |
| 会话事件 | `GET /events` | 持续规则等会话变化；与 run 事件分开。 |

显式本轮 `explicit_sources` 可覆盖持续范围，但只能选会话当前可用来源；省略不等于空数组。新文件/新版本不自动替换旧版，不重写运行中快照。

| 文档操作 | HTTP 接口 | 约束 |
| --- | --- | --- |
| 上传 | `POST /api/documents?session_id={sid}&logical_document_id={logical_id}` | multipart 唯一 `file` 字段；新逻辑文件省略 logical_document_id。202 只表示接收，处理成功后才可分析。 |
| 处理进度/列表 | `GET /api/documents/{storage_id}`；`GET /api/documents` | `status/stage/error/warnings/parsing`；`progress` 目前为 null，不伪造百分比。CSV parsing 含确定性 profile。 |
| 版本身份 | `GET /api/document-versions/{version_id}` | 返回逻辑 document_id、version_id、status。暂无专门的版本时间线列表接口。 |
| 垃圾桶/恢复 | `POST /api/documents/{storage_id}/trash`；`POST .../restore`；`GET /api/trash` | 垃圾桶来源不可参与新分析；恢复后重新检查适用性。 |
| 永久删除 | `DELETE /api/documents/{storage_id}`；`DELETE /api/trash` | 先放入垃圾桶，再永久删除；直接删 ready 文档返回 409。清理相关派生内容，历史回答保留不可用标记。界面须区分移除、垃圾桶和永久删除。 |
| 处理重试 | `POST /api/documents/{storage_id}/retry` | 202；仅对文档处理，不是 run 恢复。 |

## 3. 前台执行、澄清、停止和恢复

`POST /api/sessions/{sid}/runs` 返回 202，请求：

```json
{
  "request_id": "ui-stable-request-001",
  "question": "按刚才的结果表筛选 Price 小于 200，保留单位。",
  "expected_data_version": 3,
  "expected_rule_version": 1,
  "explicit_sources": null
}
```

以上是请求形状示例，版本号必须替换为当前读取值。`GET /runs` 列表及 `GET /runs/{run_id}` 返回 `status/question/clarification/answer/partial_answer/source_available/artifact_ids/artifacts/error/config_snapshot` 等。

| 状态/字段 | 界面行为 |
| --- | --- |
| `queued` / `running` | 显示进度和停止入口；轮询 run 与用户事件。 |
| `waiting`，或 stopped 且 `clarification` 非空 | 展示问题；`POST /runs/{run_id}/resume` 提交 `{"reply":"用户实际答复"}`。不能用空 resume 代替回答。 |
| `stopped` / `recoverable` / 可恢复的 `failed` | 显示明确继续入口；无待答澄清时 resume body 为 `{}`。重启不自动恢复或付费。 |
| `completed` | 读取 answer；仍必须检查 `answer.outcome`，completed 不等于内容完整。 |
| `partial_answer` 非空但未完成 | 明确显示“已保存的部分结果”，保留 failed/waiting/stopped 的状态和继续入口，不能伪装最终答复。 |
| `answer.outcome=partial` | 显示 gaps/warnings；已完成部分结果不会自动追加预算。 |

停止接口为 `POST /runs/{run_id}/stop`。provider 已发出的请求可能无法立即取消；停止阻止新调度和迟到发布，锁释放前 resume 可返回 `run_busy`。不要用浏览器 AbortController 代替后端 stop。

前台每交互轮最多 6 次真实模型调用。一次新的明确澄清答复是新交互轮；相同答复重放不重复授予预算。显式失败重试可有新有界尝试，普通停止/恢复不刷新额度；累计费用不受“整个 run 六次”保证。配置行为发生变化时恢复会拒绝，不能静默替换模型。`config_snapshot` 已脱敏，但属于诊断信息，不必在普通聊天正文展示。

## 4. 答案、来源预览、表格及图表

答案使用 `segments`（text、citation_ids、calculation_ids）、`citations`、`calculations`、`gaps`、`warnings` 和 `outcome`。渲染富文本时保留结构化引用绑定，不从 Markdown 文本反推证据。技术诊断和代码不应混入面向用户的结果正文。

- `GET /api/documents/{storage_id}/evidence?offset=0&limit=20`：最多 100 条；返回 evidence_id、text、locator 及适用的原始 CSV 字段。
- `GET /api/documents/{storage_id}/evidence/{evidence_id}/preview`：`Cache-Control: no-store`；PDF 返回 page_number、width、height、image data URL、regions、notice。regions 的 box 为相对 `[x,y,width,height]`，role 区分 evidence/context。notice 存在时可能仅原页无可靠高亮，不能自行画猜测坐标。阅读引用可能只有整页精度。
- 同一 preview 路由对 CSV 返回 `kind=csv`、record_number、headers、raw_values；以原始逻辑记录展示，不能将含换行字段按物理行拆开。
- `GET /api/sessions/{sid}/artifacts/{aid}`：kind、payload、scope、calculation、unit、invalidated、source_available；其中 artifact `version_id="1"` 是产物格式/记录版本，不是来源版本。
- `GET .../artifacts/{aid}/rows?offset=0&limit=100`：columns、rows、total、offset、limit、has_more、scope、unit、source_available；最多每页 100 行。完整 payload 接口并非分页，界面大表优先 rows。
- `POST .../artifacts/{aid}/reuse` 请求 `{"snapshot_id":"当前快照"}`：只做当前范围下的复用校验；不是把产物写进聊天，也不是执行新分析。来源/用途/过滤/依赖不匹配返回冲突。

表格行保持原始标识字符串；不要将前导零编号转数值。图表为独立产物，引用结果表；当前 UI 支持 bar/line/scatter，超过 100 行只是图形预览而非完整总体截断。图形数值轴必须按实际数值定位。永久删除后非回答 payload 可为空，分页返回 410；普通会话移除仍可保留历史表但 source_available=false，不能继续作为新计算依据。

## 5. 开发者观察通道

用户事件：`GET /api/sessions/{sid}/runs/{rid}/events`。开发者事件：`GET /api/developer/sessions/{sid}/runs/{rid}/events`。均返回数组，项目为 `event_id/channel/kind/payload`；目前无游标、分页或 SSE，客户端用 event_id 去重，不能把数组长度当调用次数。

已实现开发事件含 `model_call`（call、node）、`execution`（完整 task、result 和 diagnostics）、`clarification_round`、`retry`、`summary_deferred` 和 `error`。现有产物 `calculation` 另保留脚本/计划，这些均可通过既有可读接口支持开发者展示，不需先增加框架。普通 UI 不展示这些技术字段。调用计数在 provider 调用前记账，是尝试审计，不是供应商账单；新轮基线和累计次数应分别展示。PDF 机械覆盖和模型语义充分性独立，不能只显示“100% 已读”后隐藏 partial。

模型回执、执行租约/交付、交互摘要在后端存储，尚无独立通用 HTTP 调试详情路由。后续独立开发者模式先复用现有 events 和产物读取；需要额外字段时再确认最小读取接口，不让前端直读 SQLite，也不复用宿主 worker 的认证 claim/heartbeat/complete 接口做 UI 监控。worker token 永不发送给浏览器。

普通用户设置继续使用 `GET/PATCH /api/settings`、`POST /api/settings/clear`、`POST /api/settings/test`；模型、reranking、Top K 不移入独立开发者模式。凭据输入保持现有秘密值处理，不将完整配置或密钥复制进诊断导出。

## 6. 可核对的真实历史示例

来源为 `data/stage-f/20261012T190430617383Z/receipt.json` 及其 `runtime/app.sqlite3` 只读查询。session 为 `65f6c928f5fb4fd09f8e71992f0b6d77`。以下只节选非敏感字段；价格是人工验证夹具，**不是实际 SITECO 报价**。

```json
{
  "run_id": "f3b577a1c5c34eb5b90b9738f1f2d8e3",
  "status": "completed",
  "answer": {"outcome": "partial"},
  "artifacts": [
    {"artifact_id": "f3b577a1c5c34eb5b90b9738f1f2d8e3:csv:0:csv-result", "kind": "table"},
    {"artifact_id": "f3b577a1c5c34eb5b90b9738f1f2d8e3:answer", "kind": "answer"}
  ]
}
```

上表产物真实 payload 的 columns/rows 为：

```json
{"columns":["Order No.","Price"],"rows":[["0MD5307L1830","150.00"],["0MD5307L0930","250.00"]]}
```

该 run 的模型事件依次为 intent、pdf_facts_answer、csv_plan、csv_review、csv_review。早期 PDF 专业结果误报 CSV 缺席，因而历史 answer 仍 partial；数值及来源已核对，修复后没有重跑该模型步骤，不能在新 UI 中把该历史 partial 改成 answered。

真实筛选 run `61eb31b2e5e648c38d7c8d9bb3b3231b` 仅留 `["0MD5307L1830","150.00"]`；图表 run `996a07bfb4c24b10941b76988e718341` 复用结果、没有新增执行任务。更新报价 run `695edd14cdfd48d281c7012f66016a4a` 得到 175.00/225.00，来源依赖改为 PDF+D，不含 C，保留历史 partial。澄清排序 run `8f63b2d953964b2a8bbaa33fa0a83834` 在回执中同时保留 stopped 和恢复后 completed 快照，可用作界面状态样例，不能误当两条新 run。

```json
{"event_id":"cb7758eb33dc477e8cb0dc8c8479e852:model:0","channel":"developer","kind":"model_call","payload":{"call":1,"node":"intent"}}
```

这是数据库中的真实事件形状，event_id 中编号从 0 起而 payload.call 从 1 起；UI 展示应使用 payload.call。

## 7. 阶段 G 探索接口

代码入口为 `backend/app/exploration_api.py`、`csv_exploration.py`。以下路径前缀为 `/api/sessions/{sid}/explorations`；本节接口代码已核对，最终测试与真实探针证据见阶段 G 日志，不以此清单代替验收。

| 操作 | 接口 | 内容 |
| --- | --- | --- |
| 列表与开关状态 | `GET` | `{enabled, items}`；开关 session 级，默认开启。 |
| 设置开关 | `PUT /settings` | `{"enabled":false}`；关闭停止该 session 后台工作，不影响前台六次预算。 |
| 单项详情 | `GET /{identity}` | 身份、来源版本、status、overview、candidates、计数、budget、error。 |
| 停止 | `POST /{identity}/stop` | 阻止后续工作和迟到发布，保留消耗计数。 |
| 显式继续 | `POST /{identity}/resume` | 无需 body，202；先开启开关；沿用剩余预算，不追加额度。 |
| 选中已算结果 | `POST /{identity}/select` | `{"artifact_id":"该候选已发布的产物身份"}`；返回 artifact_id/focus，选为后续讨论对象，不自动发聊天消息。 |
| 开发者详情 | `GET /api/developer/sessions/{sid}/explorations/{identity}` | 普通详情外含 diagnostics/timings；耗时分 load/generation/cache/compute，不当作供应商账单。 |

单项身份按 session 与版本稳定生成；即使共享同一个原文件，另一 session 不能读取该项或其产物。普通前台 runs 列表不混入后台任务。模型生成的候选只提供 title/objective，`state=suggested` 表示**待执行建议**，不能显示数字成果；`state=computed` 才通过 artifact_ids 链接**已计算结果**，还必须显示 result_status/gaps，partial 不是完整结论。overview 是完整 CSV 确定性概览；字段类型候选及少量样例不等于已确认业务口径，也不是计算总体。

状态包括 `queued/running/completed/partial/clarification/failed/stopped/disabled/invalidated`。`clarification` 表示预计算口径需要用户明确；探索不提供 reply 接口，用户应通过前台新请求明确口径。关闭后重新开启只允许尚未启动的 disabled 项进入队列，stopped/failed 需要明确 resume。真正接纳的前台请求抢占后台时，后台停止并记录 foreground_priority；无效恢复/已完成重放不抢占，客户端不能自动反复重试。来源或规则失效后清理概览/候选/技术输出并拒绝继续，历史消耗不重置。启动时旧 queued/running 转 stopped，首次发现的历史来源只建概览不自动付费；运行期发现的新来源可自动排队。详细实施语义见设计第 20 节。

用户已确认每 session 每 CSV 版本最多 3 次后台模型调用（候选 1、预计算计划/复核共最多 2）、最多 3 条候选、预计算 1 条、最多 2 次隔离执行。普通详情的 `model_calls/execution_calls` 是已消耗次数；`budget` 是上限。确定性概览不消耗模型预算，重启/重放不刷新，无自动追加额度。后台结果默认不进入聊天或意图上下文，用户显式 select 后才成为可继续讨论的对象；继续筛选仍须通过既有范围/用途/来源校验。

### 7.1 客户端调用顺序与错误处理

1. 创建/读取 session，读取探索列表；若不希望导入后产生模型调用，先 `PUT /settings` 关闭，再上传。关闭仍保留确定性概览。
2. 轮询列表/详情（例如 1–2 秒间隔，无 SSE），展示概览及各候选 state。建议只提供“作为新问题”操作，向前台 runs 提交其 objective；不存在“执行任意后台候选”的接口。
3. 已计算候选用 artifact_ids 读取产物和分页结果；用户选择继续讨论时才调用 select，检查返回 focus。select 不提交聊天或新计算。
4. stop 后读取最终状态；resume 返回 202 仅表示请求已接收，可能仍保持终态，不能视为新结果完成。先开启开关，并显示剩余预算；失效、口径待澄清或预算耗尽转前台新请求，不循环 resume。

| 常见返回 | 操作 |
| --- | --- |
| 404 exploration_not_found / artifact_not_found | 身份不存在或不属于当前会话；刷新，不切换到其它会话猜测查询。 |
| 409 exploration_disabled | 用户明确开启后再恢复。 |
| 409 run_config_changed | 恢复原行为配置，或发新前台请求；不静默换模型。 |
| 409 来源/规则冲突 | 刷新来源与探索状态；失效项不可恢复，保留其历史消耗。 |
| 422 请求校验失败 | 修正请求形状；不要自动重试相同无效 body。 |

后台失败可能体现为 HTTP 200 的 `status=failed` 和 error，而非当前读取请求报错。开发者 `diagnostics.failure` 为 `{phase,type,code}`；phase 可为 prepare/candidates/precompute/publish。不要把模型脚本、完整 diagnostics 或配置快照直接呈现为用户答案。

`timings` 中 `load_seconds` 为初次概览加载，`generation_seconds` 为实际模型调用累计，`cache_seconds` 为模型回执查询时间，`compute_seconds` 为被接纳的执行回执累计，`specialist_total_seconds` 为专业流程累计。它们有重叠，不可相加；取消或被拒绝的回传不保证计入 compute。`model_cache_hits` / `execution_cache_hits` 是计数，未发生时字段可以缺省，显示为 0。现有观测不提供准确账单费用或完整链路时序。

### 7.2 G 真实探索响应节选

来源：`data/stage-g/20261013T203836246207Z/receipt.json`；以下字段取自该次真实响应，省略其它字段及第三条候选。示例身份仅属于已停止的验证实例，不可对新实例照抄使用。

```json
{
  "exploration_id": "explore:b66cf5df6ae4f72e22370fc2fe5078db3933b51b1db73b008fc54d57bce2165e",
  "session_id": "a2c54b93ce80441ea8514fe0515cd64c",
  "status": "completed",
  "model_calls": 3,
  "execution_calls": 1,
  "candidates": [
    {
      "candidate_id": "1",
      "title": "Row Count and Completeness Check",
      "state": "computed",
      "result_status": "completed",
      "gaps": [],
      "artifact_ids": ["explore:b66cf5df6ae4f72e22370fc2fe5078db3933b51b1db73b008fc54d57bce2165e:precompute:csv-result"]
    },
    {
      "candidate_id": "2",
      "title": "Rabattgruppe Distribution Analysis",
      "state": "suggested",
      "artifact_ids": []
    }
  ]
}
```

对该实例的请求形状：

```http
POST /api/sessions/a2c54b93ce80441ea8514fe0515cd64c/explorations/explore:b66cf5df6ae4f72e22370fc2fe5078db3933b51b1db73b008fc54d57bce2165e/select
Content-Type: application/json

{"artifact_id":"explore:b66cf5df6ae4f72e22370fc2fe5078db3933b51b1db73b008fc54d57bce2165e:precompute:csv-result"}
```

路径参数在客户端用 encodeURIComponent 编码。此请求只选择已算结果；第二条 suggested 没有 artifact_id，不能发送 select。该次概览为 11,386 行/18 列，逐列完整率由独立 csv + Decimal 核对一致。真实计时快照早于计时修复，命中计数以修复后测试为证；不将新字段伪装成当时回执已有值。

### 7.3 真实前台计算与恢复样例

来源：`data/stage-g/app-20261014T081207Z/browser-receipt.json` / `audit.json`。用户通过真实浏览器提交合成 CSV 的三行 Price（10、20、30）求和。运行 `cc6b3f8724f64bea80f5e0fe9e2e2fef` 完成，表格分页响应节选：

```json
{
  "artifact_id": "cc6b3f8724f64bea80f5e0fe9e2e2fef:csv:0:csv-result",
  "columns": ["total_price"],
  "rows": [["60.00"]],
  "total": 1,
  "offset": 0,
  "limit": 100,
  "has_more": false,
  "source_available": true,
  "unit": null
}
```

这是字符串保留精度的合法结果，界面不得要求数字必须渲染为 `60` 或擅加货币单位。该 CSV run 用 3 次生成调用，第一次执行因缺少 load_tables 导入失败，第二次预算内修复成功；开发者视图应保留失败尝试。PDF run 用 2 次生成调用并显示真实原页；随后停止的新 run 未发生模型调用，刷新保留 stopped。此验证跨探针断言修正续跑，未重新付费生成已完成两轮。

## 8. 后续入口与限制

UI 优化从 `frontend/src/useChat.ts`、`api.ts` 及现有来源/产物组件接入，保留当前 run 协议和服务端持久历史。先用真实历史 partial、stopped+clarification、source_available=false、分页和版本并存样例验收，不只设计成功答案。

独立开发者模式以现有 developer events 和脱敏配置快照为起点；未实现时间戳/延迟/费用聚合面板、执行任务详情 API、通用日志导出和评估系统。普通列表多为全量读取，长期历史分页是后续接口优化点。本轮不提前决定新框架、状态归属或持久化方案。

保留 D–F 边界：20 MiB 输入、10 活跃文件、CSV 20,000 行；UTF-8/UTF-16 BOM 和逗号/分号/Tab；PDF 50 页、无 OCR；结果 20,000 行/100 列/16 MiB；模型 review 不能证明任意脚本或业务解释正确。F 不含任意历史语义缓存、跨轮全文增量阅读；来源预览可能只有整页精度，语义充分性可为 partial。
