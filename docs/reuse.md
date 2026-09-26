# 代码复用记录

## M0 已验收迁移（2026-09-26）

用户已人工审查并迁移以下内容；适配细节和历史验证见 [M0 日志](../logs/m0.md)，已确认边界见 P-007。

- Knowledge-Assistant/app/rag/fusion.py → backend/app/retrieval/fusion.py：字符串 chunk ID、参数/重复校验、稳定同分排序；标准库。
- Knowledge-Assistant/app/rag/lexical.py → backend/app/retrieval/lexical.py：移除 jieba，采用德英文本/型号分词、BM25L、原子快照替换和词项交集过滤；rank-bm25 0.2.2 / NumPy 2.5.3。
- Knowledge-Assistant/app/services/tracing.py → backend/app/services/tracing.py：深拷贝、耗时校验、窗口统计和 nearest-rank P95；标准库。
- tests/test_tracing.py：随 tracing 适配的一个正式测试文件，共 10 个用例。

项目 Python 3.12.10 中完成四文件 AST 检查、10 个 tracing 测试、fusion/lexical 一次性行为检查和 pip check。依赖及复现命令见 [development.md](development.md)。本轮没有修改迁移源码或新增正式测试。

fusion/lexical 正式测试随后续实现补齐；稳定 chunk ID、最终 top_k 前的文档范围过滤、应用集成与 Linux 容器验证尚未完成。其他候选没有迁移，旧环境与整套依赖没有复制。迁移不代表最终启用全部模块。

---

以下保留迁移前的静态盘点、来源哈希与候选建议，仅描述当时状态；已确认迁移以以上记录为准。

# 可复用代码盘点：人工 review 草案

日期：2026-09-26。状态：仅静态盘点，等待用户人工审查；没有迁移、安装依赖或执行业务测试。

SITECO 基准提交：`c3bc35c84b71fd5a39f1d2d49f5eb800c427688a`。
来源工作区：`D:/Projects/Knowledge-Assistant`，本轮 Git 检查显示其不是仓库，不能提供来源 commit。
文末 SHA256 固定本次实际读取版本；迁移前重新核对，来源有变更则重新审查。
本文的路径、接口验证项和迁移批次全部是候选，不构成新增能力或测试边界的批准。

## 结论与建议顺序

1. 首先人工 review `fusion.py`。它是首个独立迁移候选，但仅在决定保留多路检索融合时迁移；迁移不等于最终启用混合检索。
2. `tracing.py` 无第三方依赖，可独立验证，但不是 M0 必做；需要阶段耗时记录时再取用。
3. BM25、重试、会话历史、解析、回答校验、SSE 分别在相关方案确认后适配。
4. 不整套迁移 KnowledgeBase、配置、启动流程、旧 UI、缓存或旧 requirements 文件。

“已静态审阅”不等于“已验证正确”。本轮没有行为验证结果，也没有批准迁移任何模块。

## A. 优先人工审查的独立候选

### A1. RRF 排名融合

- 源码：[fusion.py](../../Knowledge-Assistant/app/rag/fusion.py)，函数第 6–12 行；整个文件仅 12 行。
- 候选目标：`backend/app/retrieval/fusion.py`；对应检查位于 `backend/tests/test_fusion.py`。
- 直接依赖：Python 标准库 typing；没有旧配置、模型、数据库或 LangChain 依赖。
- Interface：多路 ID 排名列表、平滑参数 k、top_k，返回融合后的 ID 列表。
- 静态发现：跨列表相同 ID 会累计分数；单路内部重复 ID 也会重复计分；同分顺序受 ID 首次出现顺序影响。k=-1 会在第一名分母为零；负 top_k 使用 Python 负切片；不可哈希 ID 会失败。
- 人工 review 重点：约定单路 ID 是否必须唯一、参数有效范围，以及同分时的确定性。不要把这些约定留成隐含行为，也不要未经确认添加一套通用校验框架。
- 候选验证：手算融合排名、跨路重叠、空输入、top_k=0/超长、同分；对重复 ID/非法参数按确认后的 Interface 验证。
- 已有测试：在当前旧 tests 中未找到直接的 fusion 专项测试。需要新建确认后的公共行为测试。
- 迁移条件：人工接受实现与输入约定，统一确认首次测试边界，再进行最小迁移和行为验证。

### A2. 有界请求记录器（可选）

- 源码：[tracing.py](../../Knowledge-Assistant/app/services/tracing.py)，TraceRecorder 第 12–46 行；全局实例第 50 行。
- 候选目标：`backend/app/services/tracing.py`；测试候选 `backend/tests/test_tracing.py`。
- 直接依赖：threading、time、collections.deque，均为标准库。
- 可复用内容：有容量上限的最近记录、加锁与耗时汇总；不默认复制旧 cache/intent 字段及全局实例。
- 静态发现：record 修改调用方字典并直接保存引用，recent 也返回原字典引用；外部后续修改会改变已记录数据。P95 采用固定下标公式，需要明确小样本口径；缺少 total_ms 的记录按 0 计入。
- 已有测试：[test_tracing.py](../../Knowledge-Assistant/tests/test_tracing.py) 覆盖容量、空记录及部分统计；未覆盖字典别名与完整分位数口径。本轮未运行。
- 候选验证：容量淘汰、倒序、空集合、耗时汇总以及记录快照是否不可被调用方改写。
- 迁移条件：确实需要该模块，并先确认字段和公共行为。单纯为了多迁移一个文件没有必要。

## B. 有复用价值，但必须先适配

### B1. 分词与 BM25

- 源码：[lexical.py](../../Knowledge-Assistant/app/rag/lexical.py)，tokenize 第 17–24 行，BM25Index 第 27–48 行。
- 候选目标：`backend/app/retrieval/lexical.py`；测试候选 `backend/tests/test_lexical.py`。
- 直接依赖：jieba、rank_bm25；旧锁文件记录 jieba 0.42.1、rank-bm25 0.2.2，后者的传递依赖包含 NumPy。这些是旧环境版本线索，不是 SITECO 已验证版本。
- 价值：casefold、保留带点号/连字符的词及拆分形式，可作为技术型号检索起点。
- 耦合：返回整数下标，依赖调用方保持与语料完全一致的顺序；add_documents 实际替换整个索引，不是增量追加。导入模块会调整 jieba 全局日志级别。
- 待核对：空语料/全空分词未显式处理；只保留 score>0，小语料下不能把零分视为无词面匹配。旧 test_knowledge_import.py:50–63 特意使用三个片段避开两个片段时的零 IDF 情况，不能将该测试视为小语料覆盖完整。
- 候选验证：一/二/多片段、无匹配、空输入、德语变音字符、型号/数字/单位、重建后下标一致性；确认中文范围后决定是否需要 jieba。
- 前置选择：BM25 是否启用、支持语言、片段 ID 与查询范围；当前不安装包、不迁移。

### B2. 模型调用重试

- 源码：[resilience.py](../../Knowledge-Assistant/app/services/resilience.py)，异常分类第 18–28 行，同步/异步调用第 31–57 行。
- 候选目标：`backend/app/services/resilience.py`，仅保留被选模型客户端需要的部分。
- 直接依赖：httpx、openai、tenacity；导入 app.config 会加载 dotenv 和旧全局配置。旧锁文件分别记录 0.28.1、3.19.2、9.1.4，不直接沿用。
- 待适配：移除旧 settings 耦合，由已确认调用方式提供重试参数；核对 SDK 自带重试，避免叠加；确认超时预算、取消传播与可重试错误分类。
- 静态发现：异步包装器 await fn(...)，不能仅凭注释宣称支持异步生成器 astream；safe_call 吞异常，只适合已明确的非关键操作。
- 现有调用：retriever 使用同步包装器；chat 的模型生成没有调用 ainvoke_with_retry，只有 JSON/schema 输出错误的单次重试。
- 候选验证：429/5xx/连接超时可重试，认证/参数错误不重试，最大次数、取消、最终异常；使用假客户端与可控等待，不调用真实模型。
- 前置选择：模型 SDK 与错误策略。已有 test_stability.py 主要检查异常分类，不是完整重试行为验证。

### B3. 会话历史

- 源码：[memory.py](../../Knowledge-Assistant/app/services/memory.py)，MemoryStore 第 11–41 行。
- 候选目标：`backend/app/chat/memory.py`，仅在选择会话历史后建立。
- 直接依赖：langchain-core；另耦合旧 settings/dotenv。旧锁文件 langchain-core 1.6.4，仅作来源记录。
- 待适配：明确是否保留 LangChain 消息类型；构造参数采用 or 会把显式 0 当默认值；读取可能返回内部列表/消息引用；会话总数无上限。
- 候选验证：不同 session 隔离、轮数裁剪、清空、读取不改变存储，以及约定参数行为。
- 局限：历史只被传给回答生成，不用于检索问题改写；不能因此宣称多轮指代检索已实现，也不包含文档访问隔离。

### B4. 文件解析

- 源码：[loader.py](../../Knowledge-Assistant/app/rag/loader.py)，parse_file 第 8–16 行，PDF/DOCX 第 19–29 行。
- 候选目标：`backend/app/documents/parsing.py`，不保留纯字符串 Interface 作为既定方案。
- 依赖：TXT/Markdown 使用标准库；PDF 延迟导入 pypdf（旧锁 6.19.0）；DOCX 延迟导入 python-docx（旧锁 1.2.0）。
- 静态发现：PDF 把非空页拼成一个字符串，页码与页界限丢失；DOCX 仅读 paragraphs，未处理表格；文本解码 errors=ignore 会静默丢字节。没有 OCR 或结构化布局能力。
- 可复用：格式分派和基础提取调用经验；不原样迁移解析输出。
- 前置选择：M1 材料检查、支持格式、来源粒度和失败行为。候选验证需要真实页面与提取结果核对；本轮没有解析样本文档。

### B5. 回答校验与传输流程

- 源码：[chat.py](../../Knowledge-Assistant/app/services/chat.py)，ModelAnswer:39，prepare_sources:45，generate_answer:55，validate_answer:72，chat_events:86；[schemas.py](../../Knowledge-Assistant/app/schemas.py):20。
- 候选目标：独立校验逻辑放 `backend/app/chat/validation.py`；编排放 `backend/app/chat/service.py`；HTTP/SSE 封装在 `backend/app/api/` 中按实际框架落位。
- 直接依赖：pydantic、langchain-core；编排经 retriever 带入 langchain-openai、切分器、BM25、配置和其他模块。
- 可复用：先验证结构和引用 ID，再发布正文；无证据/服务故障不显示为成功；JSON 和 SSE 共用业务流程。
- 必须替换：固定英语、Netlight 风格业务约束与整题拒答策略；Source 强制 URL/访问日期等网页字段，不能直接用于上传 PDF；全局 kb/memory/traces。
- 局限：引用 ID 有效不等于事实被证据支持；正则拒绝所有方括号可能误伤合法内容。生成器的 token 事件一次发送整段正文，不是逐 token 流式。
- 候选验证：未知/重复引用、空答案、结构错误、部分可回答策略、模型异常、取消和终止事件；先确认新来源与响应 Interface。
- 旧 test_chat.py 有契约和错误案例，但同时固定英语、网页来源和上传 403，不可整文件照搬。

## C. 暂不整体迁移

### C1. KnowledgeBase 与检索编排

- 源码：[retriever.py](../../Knowledge-Assistant/app/rag/retriever.py)，模型构建:25–44，切分:47–60，KnowledgeBase:85–252，全局实例:255。
- 候选复用片段：切分配置经验、候选融合与计时、确定性片段 ID；确认方案后分别放入 documents/chunking.py、retrieval/service.py 及模型调用模块，路径本身不是已确认架构。
- 依赖：langchain-core、langchain-openai、langchain-text-splitters，以及 lexical/loader/manifest/reranker/resilience/settings；可选 langchain-milvus 和运行中的 Milvus。
- 导入即创建全局 kb 和客户端；启用 Milvus/reset 时构造流程会尝试 drop_collection。不能通过“导入看看”验证独立性。
- 文档处理先写向量库，再修改内存文档与 BM25；没有覆盖整个过程的原子提交/回滚。新上传失败的一致性不能直接依赖该实现。
- 查询没有用户选择的文档范围参数；重复来源要求重启；字符切分不是 token 切分。Milvus 分支吞检索异常为 []，可能把服务故障误当无证据。
- 结论：不是 M0 独立迁移单元，后续只借鉴已确认流程。

### C2. 其他模块与旧应用外壳

- `ratelimit.py:10–43`：算法本体仅标准库，但文件导入旧 settings 并创建全局 limiter；过期清理仅处理当前访问 key，其他非空过期队列可能残留。限流不是已确认能力；若需要，候选目标 services/ratelimit.py，先确认按谁限流及容量行为。
- `reranker.py:16–54`：依赖 langchain-core、settings、可选 sentence-transformers/CrossEncoder 及模型下载；会设置 HF_ENDPOINT，异常回退原顺序。启用标志不证明实际重排成功。只有材料评估证明有必要时再研究，暂不安排迁移目标。
- `semantic_cache.py:12–88`：经 tokenize 间接需要 jieba/rank-bm25；缓存 key 没有文档范围/版本，不能直接用于动态上传。当前主聊天路径也没有启用缓存；暂不迁移。
- `manifest.py:10–48`：标准库实现，但目标是固定 Markdown 与网页来源清单，不是上传生命周期。路径校验和哈希做法可参考，不整体迁移。
- `main.py` / `config.py`：FastAPI 启动即导入固定语料，ingest 明确返回 403；配置加载旧 .env 和 AIROBOT_* 默认值。新入口与配置应随新需求建立，不复制整份。
- `static/dashboard.html`：仅定向检查交互 JS，未做完整 UI 审查。可借鉴 textContent、安全 URL、AbortController、epoch 防旧响应污染和缺失终止事件处理；无上传 UI，网页来源白名单绑定 manifest。若选 React，应在 frontend/src 按新状态模型重写，不能复制整页。
- `app/agents/`：当前只有 __init__.py；没有可迁移的实际 Agent 实现，不根据旧文档或 pycache 推断存在源代码。
- `scripts/`：仅静态搜索入口与副作用，未逐文件完成迁移审查。包含固定 8010 端口、旧业务题目、manifest 和报告路径；select_provider 会写 .env。迁移来源之外的运行数据、报告、凭据、.venv 和启动脚本不随代码整包复制。

## 测试资产与依赖清单处理

- 保留旧测试的场景思想，不把旧测试通过当成 SITECO 验收。
- tracing 测试最独立；BM25 现有用例通过完整 KnowledgeBase 运行，迁移时需要新 Interface 的独立测试。
- test_knowledge_import.py 使用旧资料目录、固定 3 个来源、上传锁 403；只借鉴隔离/失败一致性场景。
- test_dashboard.cjs 使用手写 DOM/VM 桩及固定品牌按钮，不能替代新前端浏览器端到端验证。
- RRF、记录器等可用标准库 unittest 验证，不必为首个独立模块先安装整个测试生态；是否采用该边界与方式仍需统一确认。
- 不复制旧 requirements.txt / requirements.lock.txt：前者大量使用 >=，后者包含整套旧应用及传递依赖。直接 import 的 httpx/openai/pydantic/langchain-core 等并非都在旧顶层清单显式声明。
- 旧 requirements 注释提到的 requirements-extra.txt / requirements-eval.txt 在本次文件枚举中不存在；Milvus 和重排不能据此宣称可复现。
- 新依赖仅按最终迁移内容声明，在本项目 Python 3.12 与后续 Linux 容器中验证安装及行为后锁定。

## 人工 review 后再执行的最小批次

建议先决定 A1 的输入约定和必要性。如果批准，首次测试边界仅覆盖 RRF 公共函数的排名、去重约定与参数行为；在 decisions.md 记录后才实现测试与迁移。A2/B1 及其他候选逐项选择，不随 A1 自动获批。

迁移前核对来源哈希；迁移时保留来源路径、哈希、修改说明和验证结果。旧工作区未检测到 LICENSE 文件；本清单记录个人旧代码来源，不代替第三方组件许可证核对。

## 本次来源快照 SHA256

以下为实际源码/测试/依赖文件的内容摘要，不包含凭据或业务数据。
- `app/rag/fusion.py` — `98aceaee91b48ad85e839c4bdf852481ad6cff22d54b10facd3af0b7c7aae747`
- `app/rag/lexical.py` — `ab63a3f116d03a1e6240032144ef07a1683ecafef53a883d2ba4dcd1955bef3c`
- `app/rag/loader.py` — `a8e5058e2037811cd8d147768661df55fab3582fcb9649f98769e4c101803de7`
- `app/rag/retriever.py` — `6fc9e225c010576e778a53b8aa2aaac00085e7a86a78a3b56774ff6c321f2390`
- `app/rag/reranker.py` — `eea9bac94d2735a883b0bd103f7ac1b8f7d5e97c87165f1c837a6fd77f37b27e`
- `app/rag/manifest.py` — `072fc93ebbcf5fddb8c6c04432005021dea0c4e4a78871ba06a772ef4fe7dd88`
- `app/services/tracing.py` — `52d455492fdfb21c060d5ae28755a61e5ce7314eb222f08e76b5266f0bb4c819`
- `app/services/ratelimit.py` — `255927e1ca76fe01201977c6b91a9fa9abfba8d4552ce227200f693f2352812d`
- `app/services/resilience.py` — `d2d04590eaf19b69720e3b4307bf9d05ee6bbfcaf4b490ce06223f67bc7442d9`
- `app/services/memory.py` — `3a2f776b3e78e19039b9b987f7740f72f3563ad25c4c0aa7bedaac63c03182a8`
- `app/services/semantic_cache.py` — `bb335481371ea26b6aee490fd8b240c91ec66d1ce3b5580d95b8fb5dd7b5dc03`
- `app/services/chat.py` — `956b3461bb3916c5edc2400db10869ec536979dfdccac55b2ce44d04821fa1d2`
- `app/schemas.py` — `357b3ba013874e5b707cf6eeafdf7aa70750f57e42aafbec8c27984c6dd2a027`
- `app/main.py` — `d3479fbb259cfb1eddba252a686e5535c4885a86094073bf6ab98a3c5c218164`
- `app/config.py` — `92eeebdd41226072252f94c0d20f46d3a7418f654bcc5543414e9179517f6cee`
- `app/static/dashboard.html` — `6ca7e4af9888ab516b8e7090ef18a2a709d19487de9b1620999c13d04f67538a`
- `tests/test_tracing.py` — `24b7005a7cafa780f974ffd8e6f81244a5c32e16b08a062a4a6adfbc7425a5b6`
- `tests/test_stability.py` — `29dc8bd948427cdae7c2492b75b62c4c62fef4908d645687aab7780cda1a72c3`
- `tests/test_chat.py` — `84d929a6e36d3c6e35b087cec5ac8c914cb33a9005086e2ea3bd949c660e0447`
- `tests/test_knowledge_import.py` — `42d7f86a5ab3e12e3eacb285b660743f8d26191e5b3fdd7aa6a6f5b00ddf4ae4`
- `tests/test_dashboard.cjs` — `db32de30d9f9ceef0c9db983da8c88947772d5aeb118b7e8a88d3dfc1bc9e743`
- `requirements.txt` — `3d064a9310a4295dc171cad193b4465d3420080d22b775f1c9c03beb596fbb9e`
- `requirements.lock.txt` — `5cd9eb0cb239557662835c0c4b8eeab3a246b88e7824e13bdd5d5d641ba3997d`
