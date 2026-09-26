# M2.6 Voyage SDK / tokenizer 定向核对

核对日期：2026-09-26。只读官方文档、PyPI 发行包源码及 Voyage 官方 Hugging Face 仓库；未安装依赖、读取密钥或调用 Embedding API。

## 最少依赖与可复现 tokenizer

- PyPI 当前版本为 `voyageai==0.5.0`，Python 要求 `>=3.9,<3.15`。基础依赖包含 requests、aiohttp、tenacity、numpy、aiolimiter、pillow、pydantic、tokenizers、langchain-text-splitters；本地模型 extras 才引入 torch / sentence-transformers / transformers。不要安装 `[local]`。[PyPI](https://pypi.org/project/voyageai/0.5.0/)
- SDK `count_tokens(texts, model=...)` 调用 `tokenize`，后者调用 `tokenizers.Tokenizer.from_pretrained('voyageai/' + model)`、`no_truncation()`、`encode_batch(texts)`，最终累加编码长度。它不调用 Embedding，也不需要 transformers。官方教程的 AutoTokenizer 是另一种加载路径，当前任务不必引入。[SDK _base.py](https://github.com/voyage-ai/voyageai-python/blob/main/voyageai/_base.py)、[官方 tokenization](https://docs.voyageai.com/docs/tokenization)
- 只下载官方 `voyageai/voyage-4` 的 `tokenizer.json` 即可 `Tokenizer.from_file(path)`；不要 snapshot 下载整个仓库或加载任何模型。当前固定 revision `44f3b2ae4ddf33403ed4dd66bec3fa48ff7dbbf9`，文件 7,031,645 bytes，SHA-256 `c0382117ea329cdf097041132f6d735924b697924d6f6fc3945713e96ce87539`。JSON 的 truncation / padding 均为 null，post_processor 为 ByteLevel，无额外 BOS/EOS。以上为本次直接读取文件计算所得。[固定文件](https://huggingface.co/voyageai/voyage-4/resolve/44f3b2ae4ddf33403ed4dd66bec3fa48ff7dbbf9/tokenizer.json)
- 建议项目下载步骤显式指定 D 盘运行目录下的 tokenizer 文件，校验 SHA 后原子替换；运行时只 `from_file`、`no_truncation`、`no_padding`。这样运行时无 Hub 请求、没有默认 C 盘缓存。替代方式是 `hf_hub_download(..., revision=..., cache_dir=<D盘路径>, token=False)`；若依赖环境变量，必须在 import 前配置 `HF_HOME` / `HF_HUB_CACHE`。Docker 映射同一 D 盘运行数据目录，不迁移 Docker 镜像缓存。[下载接口](https://huggingface.co/docs/huggingface_hub/package_reference/file_download)、[缓存变量](https://huggingface.co/docs/huggingface_hub/package_reference/environment_variables)

## input_type 与 token 预算

`count_tokens` 没有 `input_type` 参数，故不会自动加任务前缀。官方 API 在 `input_type=query` / `document` 时分别在服务端加以下前缀（末尾空格属于前缀）：

```python
"Represent the query for retrieving supporting documents: "
"Represent the document for retrieval: "
```

预算建议对每条 `prefix + text` 的完整字符串编码并累加，而不是把前缀长度与正文长度简单相加；BPE 边界可能影响结果。发送 API 时仍只发送正文并传 input_type，避免双重前缀。本地计数用于保守预留，成功后保存 API `usage.total_tokens` 以观察计数差异；官方没有在这些页面承诺每种服务内部 token 开销与本地计数完全一致，不把本地数宣称为计费真值。[API input_type / usage 定义](https://docs.voyageai.com/reference/embeddings-api)

显式传 `model='voyage-4'`、`input_type`、`output_dimension=1024`、`truncation=False`。单条模型上限 32,000 tokens，批次上限 320K tokens / 1,000 条；项目的 10K TPM 更严格，不能只按供应商批次上限分批。超出项目单分钟容量的单条需提前拒绝或在既有证据边界内规划后续切分，不能无限等额度。[模型能力](https://docs.voyageai.com/docs/embeddings)、[请求约束](https://docs.voyageai.com/reference/embeddings-api)

## 重试、超时与错误

对照 PyPI 0.5.0 wheel 源码：

- `Client(max_retries=0)` 的 Tenacity 控制器仍执行首次调用，但不做应用层再次调用；其正整数实际传给 `stop_after_attempt`，不要按“首次之外重试 N 次”推算。
- 仍存在独立连接层重试：底层 requests 的 HTTPS HTTPAdapter 固定 `max_retries=2`。所以 SDK 的零重试参数不等于完全禁用内部连接尝试。
- `timeout` 经 `_params.request_timeout` 传给 requests；省略/假值回落为 600 秒。同步 float 是 requests 连接/读取超时语义，不是整个任务总时限，也不取消项目队列等待。异步使用 aiohttp total timeout，语义不同。
- 400 → InvalidRequestError；401 → AuthenticationError；422 → MalformedRequestError；429 → RateLimitError；500 → ServerError；502/503/504 → ServiceUnavailableError；requests Timeout → Voyage Timeout；其他请求异常 → APIConnectionError。错误对象通常带 http_status、headers；格式错误的错误响应可能丢失 headers。
- `Retry-After` 可从异常 `headers` 读取，但不保证服务器总提供。正常 VoyageHttpResponse 虽有 retry_after 属性，Embedding 结果包装不应被假定公开全部响应头。项目应大小写不敏感解析、限制异常等待值，缺失时使用自己的退避策略；不要输出原始异常/响应正文。

[Client 源码](https://github.com/voyage-ai/voyageai-python/blob/main/voyageai/client.py)、[请求层源码](https://github.com/voyage-ai/voyageai-python/blob/main/voyageai/api_resources/api_requestor.py)、[错误定义](https://github.com/voyage-ai/voyageai-python/blob/main/voyageai/error.py)。GitHub main 会变化；上述结论以本次下载的 0.5.0 wheel 为准，其 PyPI SHA-256 为 `5d7e8dc3b74cac4646d4a835a65cf8c9764070c90353e322d84a91a16207e78b`。

## 实施建议与限制

继续使用已确认 SDK，无需改 REST。进一步源码核对找到公开覆盖口：`voyageai.requestssession` 支持 `requests.Session` 或无参 Session 工厂，`_make_session` 优先使用它。建议应用初始化时、首次调用前设置工厂，工厂创建 Session 并 `mount('https://', HTTPAdapter(max_retries=0))`，同时 `Client(max_retries=0, timeout=30)`。使用工厂可以让 SDK 的线程本地会话和 180 秒会话轮换各自创建新对象，避免共享同一已关闭 Session。该配置是进程全局，统一只设置一次，不在每次请求中临时切换。[公开声明](https://github.com/voyage-ai/voyageai-python/blob/main/voyageai/__init__.py)、[工厂使用](https://github.com/voyage-ai/voyageai-python/blob/main/voyageai/api_resources/api_requestor.py)

默认连接层重试的细分：requests 将整数转为 urllib3 Retry；connect 错误属于请求送出前的失败，通常不会消耗服务端 RPM。默认 allowed_methods 不含 POST，因此 Embedding POST 的 read/status 不按此默认策略重试。不能把所有 TLS/代理/未知网络错误都等同于确定“服务端未收到”，更不能承诺其账户计费行为；最稳妥仍用上述公开 Session 工厂完全关闭自动重试，外层每次显式尝试预留预算，超时不退还该尝试额度。[Requests HTTPAdapter](https://requests.readthedocs.io/en/latest/api/#requests.adapters.HTTPAdapter)、[urllib3 Retry](https://urllib3.readthedocs.io/en/stable/reference/urllib3.util.html#urllib3.util.Retry)

当前研究没有真实请求，因此尚未实证服务端 usage 差值、实际 429 返回头、账户实际限制；应由后续少量串行真实验收记录，不能从 SDK 源码推定账户行为。
