# 当前交接：M2.7内部回答/引用完成开发小验收，下一步M2.8

2026-09-27检查点更新：用户授权将本轮M2.7改动commit/push，消息为
Implemented model answer；本提交身份与推送结果以Git记录为准。既有255+10双平台测试
作为本次代码完成证据，本轮不重复真实模型调用。以下历史摘要中的“未提交”描述提交前状态。
用户同时调整后续范围：M2.8包含聊天/来源、静态构建/运行配置/README/dockerignore，
以及独立空runtime经浏览器新上传PDF/CSV的两路Docker冒烟，不借开发索引或答案集。
密钥只后端运行时注入；两路冒烟不替代M3矩阵。当前先分析方案，不实施M2.8代码。
该调整覆盖下文旧的“M2.9才做两路闭环”安排；M2最终固定范围双轴审查仍必需。

2026-09-26。M2.1–M2.6已按各自范围验收；用户先后授权M2.7全部六步，现内部工具、
生成和引用发布已实现。M2.8问题任务HTTP/聊天UI与M2.9真实Docker浏览器闭环仍待做，
M2整体未完成。保留一次真实CSV空规划质量失败，不宣称全部问题可靠。

## 已确认范围

- P-026：PDF FTS5/BM25+Voyage-4/1024+每文档FAISS+RRF；两路全局20、等权k60、
  默认8，未调参；语义失败不静默降级。ready完整发布、缓存恢复不重新Embedding。
- P-027/P-028：模型提严格结构化条件，确定性工具执行；Decimal、白名单、证据绑定，
  禁任意SQL/Python。精确未命中不模糊替代。部分回答保留可验证事实与缺口。
- conversation隔离，每轮独立/冻结范围；不送其他会话历史。同会话多轮指代后续。
- M2.8：202+1–2秒轮询、完整JSON、真实等待状态、聊天和CSV分页。SSE/逐token后置。
  不自动加持久聊天、自带Key面板、原文高亮。M2.9做Docker闭环及最终双轴审查。
- 初始问题总截止240秒、Embedding入场最多180秒且受总截止限制、生成每次最多60秒。
  同步调用协作取消而非立即强杀；M2.8须防迟到worker覆盖终态。nginx120秒为读取间隔。

## 实际代码与限制

docs/m27-question-contract.md是内部契约。QuestionTools.prepare先验证全ready范围，再执行
有界路由（PDF/CSV各最多一次）；CSV显式字符串订单、全量计数/首50条、重复来源保留。
PDF保持原问题检索。EvidenceTools仅从本次证据取数，无调用方直接数值。
PDF计算初始仅单独显式PRODUCT LABEL: NUMBER UNIT（可带条件），无额外context；
表格/跨段不自动断言数值归属，证据仍可用于带来源的部分回答/参数列举。

AnswerService接真实StructuredModel：PDF无需规划调用，CSV/mixed模型规划；草稿分片引用、
最多一轮10个计算、再最终生成。每问题最多3次模型调用，无自动修复/重试/fallback。
28k字符完整证据项预算，超出整条省略并计数；保留工具总数及全部返回warnings。
DocumentService.read_evidence_id按(doc,evidence)回查当前ready来源，只有本轮实际给模型的
S1…可引用；非法整段丢弃、部分发布/全部失败。文件名/页码/原文后端提供。
引用存在只是来源身份保证，不是语义正确性的完整证明。

官方SDK google-genai2.25.0/groq1.7.0、零重试、严格JSON及finish/error处理，详情见
docs/m27-generation-notes.md。新锁websockets16.1.1兼容genai，其余既有运行pins保留。
app.state.answers已构造，无新HTTP、前端变化或启动模型调用。

## 验证

Windows255 tests+10subtests（41.87s）、Linux Docker同255+10（35.10s）通过，新增30项
生成/引用测试；镜像siteco-backend:m27-answer-test。SDK受控HTTP+真实临时存储测边界。
最终git diff --check、验收脚本py_compile与pip check通过；18091 health及两个容器healthy。
真实开发结果详见eval/results/m27_answers.md：
- D09首轮空计划错误需澄清；相同实现第二次正确183,20/01.06.2026，记录1，4.110s。
  无根因/修复结论；不能把仅合法JSON当正确答案。验收脚本空回答现返回失败。
- D01正确Incoterms2020，第1页ArticleII.3；7/8证据入上下文，partial，82.672s。
- D06第2页两型号参数对应，answered，20.937s；保留layout_uncertain，无表格数值运算。
两份PDF相关页已视觉核对。Gemini5次成功API调用（含空规划），Voyage6次已记录成功
调用8366tokens；初始记录器漏失败尝试，不能称总调用数。D01慢主要在生成前，离线额度
表确认provider重试冷却；原错误码未记录，不能直接称429。脚本现补失败/等待日志。
Gemini真实验证、Groq仅受控HTTP；没有保留题或付费切换。M2.6历史12浏览器检查不能
当作本轮问答浏览器验收。尚无任务HTTP超时终态或新上传→聊天闭环验证。

## Git与运行

main/本地origin/main检查点a00f896c489c2bdbb6d8b197b2e006166ea727aa；未fetch/commit/push。
未提交包含M2.7前后三步：questions/question_numbers/answers/generation、来源回查、main
构造、retrieval回调、依赖锁、4测试文件、开发验收脚本、契约/研究/验收/决策/日志。
本轮基准a00f896；M2最终审查基准4307e22，届时固定目标及staged/unstaged/untracked范围，
按AGENTS/code-review执行Standards与Spec并行子代理审查。当前未做该阶段完成审查。

现有预览仍M2.6：http://127.0.0.1:18091/，backend18090，Compose siteco-m26-acceptance，
D:/Projects/Retrieval_SITECO/tmp/m26-docker/runtime。原ready Rondel
8989ca6429c14f908842ee8a92a8d995。旧18089/18087未改。无新常驻服务。
本轮独立验收目录tmp/m27-gemini-csv、tmp/m27-gemini-csv-v2、tmp/m27-gemini-pdf，
进程均已退出/service.stop完成。仅对已停止独立目录只读额度表，未访问运行服务SQLite。
Docker镜像/缓存C盘、数据D盘不迁移；根目录密钥忽略，不输出/提交/入镜像。
20MiB/PDF50页/CSV20000条/10活跃文档；无OCR/视觉推理/本地模型，108页报告不在基线。
Voyage共享3RPM/10KTPM、至少20秒间隔、query优先；变付费前通知用户。

默认shell沙箱初始化失败，命令通过require_escalated运行。真实外发初被自动审查拒绝；
用户随后明确批准Gemini＋Voyage仅D01/D06/D09开发材料验收，后续成功执行。不是待授权。
Python backend/.venv/Scripts/python.exe；Docker CLI位于LOCALAPPDATA/Programs/DockerDesktop/resources/bin。

## 下一步

按已确认M2.8方向接任务HTTP/轮询和聊天UI，展示引用、业务结果、分页/省略/布局警告及
真实额度等待；总截止从接受问题开始，worker迟到不能改终态。不要把内部答案测试当UI完成。
随后M2.9真实Docker浏览器新上传→问答，再固定范围Standards/Spec审查与修复。
