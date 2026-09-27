# M4.5.1 统一配置契约

日期：2026-09-27；基准HEAD：2f3ad2de62d0be220d231cd7d800a02e4c1b0353，包含当前未提交M4.4工作。
状态：用户已明确确认本具体契约（包括新HTTP接口与测试边界），作为M4.5.3实施依据；现已实现并完成受控验证，真实提供方复验待授权。M4.5.2限流建议与Embedding扩展取舍见m452-voyage-embedding-assessment.md，未自动改变本契约。

## 1. 范围与当前实现差异

统一放在Settings。推理仅Gemini/Groq，允许模型名称与各自Key；无任意Base URL。检索Top K为最终PDF选取数1–20，默认8；重排默认沿启动配置（仓库默认false），词法/向量各20、RRF k60、28000字符证据预算固定。
Embedding必做为Voyage模型/凭据状态/本地限流展示及Voyage Key覆盖。模型固定沿启动模型，本轮不能更换模型或维度；OpenAI-compatible Embedding和索引重建仍为M4.5.2条件评估，不在本文偷偷纳入。

实施前代码（历史差异）：main.py启动时创建Settings、模型、gateway、retriever与AnswerService；question_tasks.py使用同一answers对象，没有任务配置快照。embeddings.py有共享持久化预算（3RPM/10000TPM、最少20秒）与缓存，reranking.py独立单在途/完成后20秒冷却。Settings前端仍是说明页。须新增配置管理及任务绑定，不能仅添加表单或直接改共享对象。

## 2. 配置语义与Key生命周期

- 启动默认：进程启动时读取环境/.env，之后不回写文件。Gemini/Groq分别保留启动模型名与Key，Voyage使用启动模型/Key。
- 当前配置：单用户本地实例全局生效，不按conversation_id或浏览器标签隔离。浏览器草稿不等于已应用配置。
- 修订标识revision：每次应用/清除/恢复生成新的不透明标识，跨重启不复用。旧页面提交时返回409，必须重新读取，不能覆盖另一标签的新配置。
- Key三态：environment（使用启动Key）、override（内存覆盖Key）、disabled（显式清空、不回落环境Key）。没有可用环境Key时公开状态为missing。
- 读取仅返回credential_status及credential_source，不返回Key、尾号、hash或可恢复凭据。输入框不预填旧Key。
- 刷新：重新GET当前状态，空白Key框表示未修改；后端覆盖保持。草稿Key不持久化到local/sessionStorage、URL、SQLite、日志、响应或镜像；发送后清空输入框。
- 重启：全部运行期配置覆盖/测试状态清除，恢复启动默认；已有任务元数据/文档/答案按原生命周期保留。不是永久保存Settings。
- 清除：禁止后续新任务使用所清凭据；既有已接收任务仍持有自己的内存快照直至实际执行退出。清除不等于撤回已发请求、供应商吊销Key或立即擦除所有内存副本；UI明确提示。
- 恢复默认：显式恢复启动模型/Key与参数，可能重新启用环境Key，必须与“清除凭据”使用不同按钮。

## 3. HTTP接口（统一JSON错误封装；不新增用户认证体系）

所有响应Cache-Control:no-store。写接口仅JSON；不启用任意跨域访问，浏览器Origin存在时需与当前访问来源匹配。保持单用户本地/回环部署，不宣称安全多租户。无Key请求体/供应商原始异常日志。

### GET /api/settings

返回revision、generation、retrieval、embedding、lifecycle：
- generation：provider（gemini/groq）；profiles.gemini/profiles.groq各含model、credential_status（configured/missing/disabled）、credential_source（environment/override/none）。
- retrieval：top_k、rerank_enabled、固定lexical_candidates=20、semantic_candidates=20、rrf_k=60、context_char_budget=28000、rerank_model、rerank_budget_seconds=5。
- embedding：provider、model（只读）、credential_status/source、模型/维度配置可编辑=false；local_limits为运行值与来源，account_limits_verified=false（未核对时），不把本地限制当供应商实际额度。
- lifecycle：scope=instance、persistence=memory、restart=environment_defaults。
GET不测Key、不发模型请求。健康接口仍只表明服务活着，不代表模型可用。

### PATCH /api/settings

请求含必需expected_revision，以下部分均可省略；至少有一项变化：
- generation.provider；generation.profiles.gemini/groq下model、credential。
- retrieval.top_k、rerank_enabled。
- embedding.credential；拒绝provider/model/base_url/dimensions/限流参数写入（后续额度检查另定）。
credential为{action:keep}、{action:replace,value:...}、{action:clear}、{action:default}之一。省略相当keep；replace必须非空，Key最多4096字符，模型名去首尾空白且1–200字符。reject未知字段、bool型Top K、越界值和不支持提供方。

先局部校验、在单次锁内比较revision并原子应用；失败不部分生效。成功200返回GET同形态的脱敏当前配置与新revision。应用不隐含模型调用或测试，不要求先通过测试；没有测试时显示“未验证”，有Key不等于可用。允许保存缺Key配置，但新任务在需要该凭据时明确失败，不偷偷切换模型/账户。

### POST /api/settings/test

请求含expected_revision、target（generation/embedding）、可选draft（与PATCH同一字段语义），explicit_probe=true。不支持target=rerank；本阶段不额外增加重排测试调用。
先解析候选配置，捕获不可变快照，再发一次探测；不应用/持久化候选配置，不改文档/索引。测试期间应用其他配置不影响已发测试；响应带tested_revision和tested_public_config，UI只对仍匹配的草稿显示有效结果，编辑后取消成功标记。
- generation：固定无用户文档/历史的小提示，要求返回固定简单JSON结构和值，复用现有提供方结构化输出适配与本地schema校验。一次调用、无工具链/重试，不保证该模型所有复杂问答schema都可用。
- embedding：固定短文本一次query embedding，验证有限数值、维度与当前索引模型契约一致；不入库、不重建索引；必须经过共享本地额度控制，不能绕过限流。
- 整个测试最多20秒（含等待）；本地等待不足以在预算内完成时返回local_rate_limited，不发请求。每实例一个在途探测，重复点击返回409 test_in_progress；前端禁止重复提交，不自动重POST。请求可已计费，即使用户关闭页面。
- 成功及供应商失败均200返回结构化探测结果：status=passed/failed、target、tested_revision、tested_public_config、elapsed_seconds、code、安全message；不返回模型原文/Key。code区分authentication_failed、model_unavailable、structured_output_unsupported、invalid_output、dimension_mismatch、provider_rate_limited、local_rate_limited、timeout、provider_unavailable、provider_error。无法确定的供应商错误用provider_error，不凭模糊文本硬判。
- 输入422、revision冲突409、测试忙409；缺Key返回failed/missing_key，不调用供应商。
UI按钮明确“将向所选供应商发送固定测试文本，可能计费”；调用授权来自用户主动测试，不因打开Settings/刷新自动发生。代理开发期真实测试仍需明确外发授权，不沿用已耗尽M4.4额度。

### POST /api/settings/clear

请求expected_revision、scope（gemini/groq/voyage/all）、mode（credentials/defaults）。
- credentials：选定凭据置disabled，模型/检索参数保留；all禁用三项凭据。明确“清除后新任务不能使用该Key，既有任务继续”。
- defaults：scope为供应商时恢复其启动模型/凭据，当前generation.provider不变；all恢复全部启动配置，包括推理选择、Top K默认8及启动重排开关。
成功返回脱敏GET形态与新revision；无外发，无删除文档/聊天/缓存。PATCH中的clear/default只作用对应凭据，模型恢复使用本接口，避免隐含模型切换。

## 4. 任务配置冻结和索引边界

在问题被成功接受并持久化任务时，原子捕获推理provider/model/key、Voyage key、Top K、重排启用及固定算法参数。快照包含凭据的部分只留内存，非秘密摘要随任务持久化并通过任务GET展示。执行planning/resolve/generate以及query embedding/rerank均使用该快照，排队期间也不能读新配置。

现有同conversation/request_id重试先返回原任务，再考虑当前配置，不重新冻结/取Key或再次调用；不同请求内容仍409。公开config_snapshot至少含revision、provider/model、embedding provider/model、top_k、rerank_enabled及固定策略参数，不含Key或凭据指纹。旧任务无该摘要时返回null，不能按今天配置补造历史。

上传在文档提交被接受时捕获摄入用Voyage配置，后续分批embedding使用同一快照；不能每批取新Key。切Key仍沿用同模型索引，不删除原向量/缓存。缓存身份由原模型/输入规则决定，不能因仅换Key宣称索引失效；无凭据时不凭缓存绕过“禁用此服务”的明确行为。

任务完成、失败、过期或取消后释放快照；如果后台请求仍在执行，实际执行退出后释放最后引用。启动中断旧任务沿现有question_interrupted/processing_interrupted处理，不恢复秘密快照、不自动重POST。

配置变更不得重置或绕过共享embedding配额/冷却及重排单在途门槛。旧新任务共享实例准入控制，换Key不会假设获得另一份额度；多账户精确额度隔离不在本次范围。测试探测同样遵守此规则。模型/维度切换与索引重建仍被拒绝，直到另行契约批准。

## 5. 逐轮检索诊断

PDF任务结果新增非秘密retrieval_diagnostics（旧任务可缺省）：策略rrf/rrf_reranked/rrf_fallback、词法候选数、向量候选数、去重并集数、requested_top_k、selected_count、context_included_count、context_omitted_count、重排status/reason/seconds。
计数只针对PDF；混合任务不能把CSV记录混入PDF的遗漏数。并集数在final Top K截取前计算；进入上下文数在evidence_context预算处理后计算；失败发生在相应阶段之前用null，不能填0冒充无命中。分数不是置信度。最终上下文与历史快照可复核，不能用当前Settings重算旧答案标签。

## 6. 测试边界与验收（已确认）

沿Settings HTTP接口、实际任务HTTP/临时SQLite、现有DocumentService/PdfRetriever/QuestionTools和浏览器入口测试；供应商与时间受控，不测试私有字段代替行为。

1. GET/应用/清除/默认：脱敏、no-store、非法输入、原子更新、旧revision冲突、多标签刷新、缺Key；配置读取和应用零外发。
2. 探测：每次恰好一次，固定payload无文档，连接与结构化失败可区分，缺Key零调用，超时/429/本地预算/重复点击、失败不改配置，成功不冒充全能力验收。
3. 快照：任务A接受→修改或清除→任务B接受，受控供应商确认A全链路用旧配置、B用新配置；queued同样冻结。同次提交重试返回A；上传跨embedding批次不切Key。
4. 重启：内存覆盖清除、启动默认恢复，已有公开任务快照保留，旧任务缺字段兼容；无Key落盘/日志/响应。超时后台退出清理，不靠清空共享字典让在途任务失效。
5. 检索：Top K 1/8/20、40候选上限、去重计数、预算遗漏、混合PDF/CSV分开计数、重排开关/故障回退、配置变化不能重置限流。
6. 浏览器：Settings加载/草稿/测试/应用/清除/恢复、刷新状态、Key框清空、忙与错误提示、新旧轮配置显示；真实双提供方验收与受控测试分开报告。

实施状态：接口、前端和任务配置冻结已完成，受控验证见eval/results/m45_settings.md。前端仅测试已应用配置，草稿须先应用；HTTP仍支持候选draft。P-038确认不扩展Embedding服务或重建索引。真实提供方验收待授权，正式evaluation/M5保留。
