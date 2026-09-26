# M2 模型选择研究

查阅日期：2026-09-26。仅核对官方文档/发布者模型卡；没有访问凭据、调用模型或测量本项目质量。以下建议是候选，不是已确认决策。

## 最小建议

先确认用户之前实际用的 embedding model ID。Gemini Embedding 是托管 API；Google 可下载的 EmbeddingGemma 是另一产品，不能把两者统称为开源 Gemini。

建议保留用户已验证的 Gemini 生成模型作为首个基线。若愿意支付少量费用，优先通过付费配额、限制并发和避免无意义重复调用解决开发限流；不先实现自动跨供应商路由。Embedding 在沿用现有托管模型与 EmbeddingGemma 本地运行之间选一个，不同时落地多个。

## Embedding：三个候选方向

1. **现有 Gemini Embedding API**。官方目前列出稳定版 `gemini-embedding-001`（纯文本，2,048 token）与 `gemini-embedding-2`（多模态，8,192 token）。前者支持 `RETRIEVAL_QUERY` / `RETRIEVAL_DOCUMENT`，后者改用提示前缀；向量空间互不兼容，切换需要重建。2 的 PDF 输入最多六页/请求，不能把长册直接作为一条向量。建议：文本 RAG 不为多模态名头换模型；若原有模型可用且检索开发题表现好，沿用最省集成成本。API 优点是依赖轻；风险是索引和查询都受网络/配额影响。[官方说明](https://ai.google.dev/gemini-api/docs/embeddings)
2. **Google EmbeddingGemma 300M**。开放权重、100+ 语言训练、2K 输入、768 维，可缩至 512/256/128 并归一化；是面向设备端的文本 embedding。建议：若希望反复切块/重建索引不消耗远程额度，它是本项目优先试验的本地候选。代价是模型下载、推理依赖和镜像体积，还须遵守 Gemma 使用条款；开放权重不等于无条件许可。不能从多语榜单推断其必定擅长 SITECO 德语技术表格。[模型卡](https://ai.google.dev/gemma/docs/embeddinggemma/model_card)
3. **intfloat/multilingual-e5-small**。384 维、最多 512 token；非英语文本也必须使用 query/passage 对应前缀（实际前缀拼写为 `query: ` / `passage: `）。建议：优先 CPU 轻量部署时的备选；短窗口更容易截掉表头/型号关联，因此切块必须按 tokenizer 限制，不能只看字符数。[发布者模型卡](https://huggingface.co/intfloat/multilingual-e5-small/blob/main/README.md)

其他：BGE-M3 支持 100+ 语言、8,192 token、1024 维，兼具 dense/sparse/multi-vector；本阶段用不到的能力更多，先不引入，仅在基线检索失败且证据解析完整时考虑对照。长上下文不意味着应把整本宣传册作为一个片段。[发布者模型卡](https://huggingface.co/BAAI/bge-m3)

上述取舍均为工程推断，未测本项目精度。比较应固定解析、片段与开发题，记录证据 Recall@k、跨德英查询、型号混淆、索引时间、查询延迟和内存；不要把生成正确率单独当 embedding 指标。CSV 订单号/价格应走精确查询，不靠 embedding。模型名称、维度、前缀、归一化和片段版本都属于索引身份。

## 生成模型与预算

官方目录目前推荐新项目使用稳定 `gemini-3.5-flash-lite` 或 `gemini-3.8-flash`；2.5 系列仍服务，但访问限制为历史活跃使用者。因此不能把用户以前能用的 ID 自动当作评审方新账号也能用的默认值。[模型目录](https://ai.google.dev/gemini-api/docs/models)

当前标准付费价（美元/百万 token）：3.5 Flash-Lite 输入 0.30、输出 2.50；3.8 Flash 输入 0.75、输出 3.75，后者优惠至 2026-12-31，2027-01-01 起为 1.50/7.50。输出计费含 thinking token。Embedding 2 文本为 0.20/百万 token。价格示例仅估算：每次 5,000 输入＋1,000 总计费输出，1,000 次约 4 美元（3.5 Flash-Lite）或 7.50 美元（3.8 当前价）；不含税、重试、其他功能。实际用量未测，不能视为本项目报价。[官方价格](https://ai.google.dev/gemini-api/docs/pricing)

建议（推断）：不要为新而换掉已验证模型。先用同一小组开发题验证可用的稳定 ID；Flash-Lite 是成本候选，Flash 是质量对照。这里没有证据证明任何一个必定胜过用户过去的模型。

## 免费限流与备用

Gemini 限额按 project 而非 API key，受 RPM/TPM/RPD 等约束；日配额按太平洋午夜重置。当前真实额度在 AI Studio 查看，官方也不保证表中额度等于实际容量；付费仍有限流。换同项目 key 不解决。[官方限流](https://ai.google.dev/gemini-api/docs/rate-limits)

建议（推断）：确定性单元测试不调用模型；真实模型测试单独显式运行。缓存已处理文档 embedding，缓存键含模型/维度/前缀/文本与处理版本；仅对短暂 429/5xx 按服务端等待建议有限退避。日额度耗尽要明确提示，不能持续重试。开发可选择已验证 Groq 备用，但记录提供方/模型，不悄悄改变正式评测对象。

Groq 限额按 organization，精确额度查看账号。其 Structured Outputs 严格模式当前支持 GPT-OSS 20B/120B 及 Qwen3.8 27B；schema 合规并不保证引用或事实正确。即使接备用也保留服务端引用校验和超时处理。Groq 自身也有限额，因此免费供应商接力提高可用性但不提供稳定容量保证。[限流](https://console.groq.com/docs/rate-limits)；[结构化输出](https://console.groq.com/docs/structured-outputs)

## 本地成本收益

父任务只读核实本机 RAM 15.7 GiB、RTX 3060 Laptop 6 GiB VRAM。工程判断：本地 embedding 比本地生成更值得优先投入。数百 M 参数 embedding 适合这个量级；生成模型即使量化，还需要上下文 KV cache、运行时和系统余量。按纯权重算术，4B/8B 的 4-bit 权重约 2/4 GB，不等于实际总显存。CPU/GPU 混合推理可运行超出显存的模型，但速度必须实测。[llama.cpp 官方支持说明](https://github.com/ggml-org/llama.cpp)

本地生成的收益是离线、无远程请求配额、数据在本地；代价是下载和部署、推理延迟、质量验证与评审硬件门槛。两天交付中，为节省几美元 API 花费加入这一整层通常不划算；除非离线是明确需求或付费不可接受。以上是成本判断，不是已测性能结论。

## 数据条款边注

不能简单说“Gemini 免费数据一律用于训练”：EEA、瑞士和英国用户的免费服务也适用 Paid Services 的数据使用条款（Google 不用这些提示/回答改进产品）。同一条款另规定，向上述地区用户提供 API Clients 只能用 Paid Services。不要将这两条混为一谈，也不要把不用于产品改进解释为不存储任何数据。[官方条款](https://ai.google.dev/gemini-api/terms)
