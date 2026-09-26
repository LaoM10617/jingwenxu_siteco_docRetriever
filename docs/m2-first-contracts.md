# M2 第一批实施契约建议

2026-09-26。状态：用户已统一确认第一批实施范围（P-016），T-002至T-005已批准；尚未实现。正文保留方案讨论措辞，后置项仍后置，具体版本随实施核验。

## 已确定模型与本轮核对

用户指定voyage-4，账号约束按用户提供3 RPM/10,000 TPM；官方文档公开的是其他额度层级，不据此覆盖用户账号限制。Groq截图和官方模型页均为openai/gpt-oss-120b，on_demand不属于model ID；当前Key实际可用性未调用验证。

建议Voyage使用1024维/float32，document/query两种input_type，关闭静默截断；所有模型配置随向量保存。向量缓存键包含文本哈希、model、dimension、dtype、input_type及影响结果的配置；解析/切块版本属于文档处理版本。CSV精确索引不用Embedding。

3 RPM和10K TPM须由文档/问题请求共享的调度器控制，串行、有界、按滚动窗口同时计请求和token；重试也计预算，SDK隐式重试关闭或纳入同一调度。片段合批但不超过token预算，候选单批不超过约4K输入token（含实际计数的任务前缀并留余量），不是按固定片段数。问题优先下一个请求槽；正在发出的请求不抢占；连续查询可能推迟摄入，UI报告等待配额而非解析失败。外部其他客户端消耗同组织额度仍可能429，不能承诺绝对不触限。token计数使用模型对应tokenizer，必要小型tokenizer资源缓存放D盘；不下载模型权重。实际429有限退避，超过预算提示用户，不自动付费或换Embedding模型。

## 存储与运行建议

- 标准库sqlite3，不引入ORM、Postgres或独立向量数据库；少量明确SQL与schema版本即可。按P-020改为FAISS CPU：每份文档一个IndexFlatIP及位置到evidence_id映射；仅搜索所选ready文档，归一化float32内积排名，局部top-k合并全局top-k，同分边界须保持一致规则。不先全局top_k再过滤。
- SQLite：documents保存身份/hash/status/stage/error/解析与索引配置；evidence保存页/记录定位、原文/CSV原值及文档归属；向量按维度/dtype和配置存BLOB。价格记录订单号作为字符串建立精确索引，保留重复来源。
- 原始文件放data/runtime/uploads，SQLite放data/runtime/app.sqlite3；绑定挂载整个runtime到容器/app/runtime，文件名由服务端ID产生。项目材料与运行资料分目录。
- 外部解析/Embedding期间不持数据库长事务；分批保存待发布证据/向量，检索仅JOIN ready文档。完成内存索引构建后，协调最终短事务与进程内索引/映射的可见性并置ready，实现整体发布；失败半成品不可查。重启将queued/processing标为中断失败，可手动重试；ready从磁盘读取并重建内存Flat索引，不调用Embedding；重建完成后才服务查询。首版不持久化FAISS文件，具体发布/同分约束见P-020。
- 首版一个后端进程，一个有界摄入工作线程/队列；每个线程独立SQLite连接、短写事务与busy timeout。先用默认日志模式验证，不在Windows绑定挂载上未经验证宣称WAL可靠。进程内等待不得阻塞HTTP事件循环。
- 普通存储相比向量数据库部署简单、原子发布易解释；代价为SQL/版本管理及受限规模的线性检索。未作性能承诺。
- Docker组织按P-018改为最小双容器：前端Node构建静态文件并交由静态服务器容器提供，代理/api到独立Python/FastAPI容器；Compose统一启动，仅后端绑定D盘runtime并注入模型Key。不增加数据库/Redis/任务容器。镜像缓存仍在C盘Docker数据盘，不自动迁移。

## 依赖分批

第一批API：fastapi、uvicorn、python-multipart、pydantic-settings；测试pytest、httpx；sqlite3/csv/Decimal来自Python标准库。
解析批：pdfplumber；已有NumPy/rank-bm25保留，不增加pandas或OCR。
检索批：faiss-cpu，Windows/Python3.12与Linux/amd64实际安装验证后锁定，NumPy仍保留。
模型批：voyageai及匹配token计数支持；生成时再加google-genai与groq。使用供应商SDK减少协议重复，重试统一控制；当前不安装。
前端批：React+TypeScript+Vite、npm锁文件；先不用全局状态库/SSR框架；后续交互行为需要时才加对应测试依赖。
Python沿用pip/venv、直接依赖文件+锁文件，开发测试依赖分开；验证Windows与Linux安装/构建。具体版本安装时核验并锁定，不在讨论阶段凭空选版本。

## 第一批HTTP Interface

以下接口足以完成接收/状态/证据，回答接口留第二批。

- GET /api/health：200 status/version；不调用任何模型，不返回密钥。缺少模型Key不导致进程无法启动，相关操作单独报告配置问题。
- POST /api/documents：multipart单个file；接收落盘并记录queued后202，返回document_id/original_filename/status。选择多个文件由前端逐个提交。大小/类型不合格可直接413/415，解析发现页数/记录数等超限则异步failed，不把202当处理成功。网络重试可能重复上传，此批不引入完整幂等键协议。
- GET /api/documents：文档列表，身份、类型、状态、阶段、进度计数、warnings、结构化error；不返回本地路径和Key。
- GET /api/documents/{id}：详情/轮询，404表示未知ID。progress包含已完成/总片段数（总数已知才给），处理中可标waiting_rate_limit及retry_after_seconds；不伪造精确完成时间。
- GET /api/documents/{id}/evidence?offset=0&limit=20：仅ready返回分页证据（建议limit最大100）；包含evidence_id/text/locator/raw_values等适用字段；未ready返回409，未知404。未开放半成品预览。
- POST /api/documents/{id}/retry：仅可重试的failed项，202；处理中重复请求409，不重复排队；复用已完成兼容向量，但首版不承诺断点精确恢复。

建议统一error字段code/message/retryable，可选retry_after_seconds。账号凭据请求字段在前端配置批具体确定；此次不暴露读取服务器Key的接口。

10文档限制建议queued/processing/ready占位，failed不占位；重试重新检查并原子预留。达到10份ready后如何释放位置尚待确定：建议M3增加单文档删除，而非本轮偷偷加入删除范围。失败记录/原文件清理需在交付前有明确操作。

## 内部Interface与测试边界（候选编号）

T-002 DocumentService：submit/list/get/retry/read_evidence。覆盖同名不同身份、容量原子预留、状态顺序、半成品不可查、失败和重启恢复；读取ready资料不调用模型。临时真实SQLite+临时文件验收，不以全mock证明持久化。

T-003 parse_document(stored_file, media_type, limits) -> ParsedDocument：输出来源证据及warnings，结构错误抛明确失败。覆盖PDF物理页码/参数归属/空文本、CSV记录号/带引号换行/前导零/原始字段；超限用小型可控fixture，不跑最大并发压力。价格Decimal规则按P-008/P-009核对。真实开发PDF用pdf技能核对，保留材料不调参。

T-004 EmbeddingGateway.embed(texts, input_type) -> vectors：内部管理token分批、共享限流、缓存及供应商调用；覆盖3RPM/10KTPM、查询优先、重试上限、模型/维度缓存隔离、向量数量/维度/非有限值校验。用假时钟和假供应商，不真实等待一分钟，不在普通测试中消耗API。返回非法批次不发布文档。

T-005 HTTP上述六个接口：202/404/409/413/415、字段与错误可行动、敏感信息不泄漏、真实文件上传到证据。HTTP层少量契约检查，深层行为由T-002至004覆盖，避免每层重复同一套测试。

T-001 tracing沿用。第二批再明确POST /api/questions、retrieve(question, document_ids)、lookup_orders(order_ids, document_ids)与引用校验；届时补fusion/lexical正式测试。不能为了首批省时改变最终支持的PDF+CSV主线。

## 分段验收

A：API+SQLite+Docker健康接口，模型客户端fake、不用凭据。
B：PDF/CSV到证据、失败与重启行为；检查开发材料。
C：Voyage适配器与假时钟限流自动测试通过后，真实Voyage只做一小批文档Embedding及一个问题Embedding，串行共享预算；这只证明接入，不代替效果评估。生成模型接入另做少量真实调用，不自动整套13题或保留题。
D：最薄前端上传/状态/证据，再进入检索与回答。

## 官方依据

- https://docs.voyageai.com/docs/embeddings ：voyage-4/维度/input_type/批量参数。
- https://docs.voyageai.com/docs/rate-limits ：组织/项目额度、批量与退避；本账号数值按用户提供。
- https://docs.voyageai.com/docs/tokenization ：模型对应token计数。
- https://console.groq.com/docs/model/openai/gpt-oss-120b ：模型ID。
- https://docs.python.org/3.12/library/sqlite3.html ：标准库SQLite事务与连接。
- https://vite.dev/guide/ ：前端构建工具。
