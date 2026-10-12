# 阶段 E：PDF 阅读与专题分析

状态：阶段 E 既定范围已实现，相关测试、真实验证与最终双轴审查完成。分支 main，HEAD e389512；D/E 全部修改仍未提交，未 commit/push。旧运行容器未部署新代码。以下早期记录保留排错过程，最终结论以末尾验收为准。

## 已实现

- 完整原生页面阅读表示、旧缓存按需补齐、稳定阅读引用与原件摘要校验；保留原有效检索身份。
- facts/coverage/topic 三路径；逐文件检索/阅读、批次回执、机械覆盖与语义充分性分别记录。
- 每轮 6 次模型调用；显式停止/恢复复用成功回执，无后台自动付费恢复。

## 验证进度

- 数据层：`pytest backend/tests/test_pdf_reading.py backend/tests/test_parsing.py backend/tests/test_pdf_publication.py backend/tests/test_source_preview.py -q --basetemp data/stage-e/reading-final-2`：49 passed。
- 主图与专业图：`pytest -q backend/tests/test_pdf_runs.py backend/tests/test_pdf_analysis.py backend/tests/test_pdf_specialist.py --basetemp data/stage-e/integrated-1`：22 passed，包含停止后重建服务、坏引用显式恢复、成功批次不重复调用及单次发布。
- 第一真实探针在索引前因缺少 tokenizer 失败，无生成调用；补充固定 tokenizer 后两份 PDF 索引成功。失败目录 `data/stage-e/20261012T181112045986Z`。
- 首次真实两轮：`data/stage-e/20261012T181206187161Z/receipt.json`，摘要 4 次、专题 5 次 Gemini 调用，Voyage 索引。发现单文件批次误报另一文件缺失，正在修正并准备重新验证；不能以链路完成替代语义验收。
- Spec 审查发现空汇总错误标完成，已改为 partial+gap 并补测试。目标页范围之外页面的覆盖口径正在调整。
- 第二真实两轮 `data/stage-e/20261012T181602634638Z/receipt.json`：4+5 次调用，复用只读复制的索引，无新 embedding；假资料缺失已消除，摘要 `mm²` 正确，但专题仍仅分别列事实，未明确比较关系。
- 第三真实专题 `data/stage-e/20261012T181816599481Z/receipt.json`：5 次调用，技术事实/原页引用正确，仍缺少明确横向比较。读取真实 synthesis 回执确认不是发布时丢失；停止重复完整调用，改用成功阅读回执作单次汇总重放诊断。此前累计 23 次 Gemini 调用，所有单轮均不超过 6 次。
- 中间全量：Windows `--basetemp data/stage-e/final-windows-1` 与 Linux `docker build --target test -t siteco-phase-e-tests -f backend/Dockerfile .` 均 501 passed、15 skipped、10 subtests passed。后续提示/多来源校验定向 Windows/Linux 各 28 passed；此为中间证据，比较输出结构修复尚待最终回归。
- `npm run build` 通过。E 未修改前端；新 reading ID 已经真实 HTTP 来源预览验证。15 项 Docker executor 测试本轮跳过，D 的真实隔离验证保留，E 未修改执行器。

## 当前边界

仅原生文本；无 OCR。50 页上限保留，页内结构提示不是完整章节树，阅读坐标精度为整页。调用预算允许部分结果，已完成的部分结果不自动续费；更具体后续请求及 F 的跨轮记忆分开。

## 最终验收（2026-10-12）

### 测试

- Windows 全量：`.venv/Scripts/python.exe -m pytest -q --basetemp data/stage-e/final-windows-2`：**506 passed、15 skipped、10 subtests passed**，133.22 秒。
- Linux 全量：`docker build --target test -t siteco-phase-e-tests -f backend/Dockerfile .`：**506 passed、15 skipped、10 subtests passed**，90.77 秒。测试镜像 manifest `sha256:b03a800dc470a6c794a8ed7f64286cf78167835f26598d3251b52fca449c54fd`。
- 全量后最后增加了模型自行缩小页范围的完成守卫。Windows 定向 `.venv/Scripts/python.exe -m pytest -q backend/tests/test_pdf_analysis.py backend/tests/test_pdf_runs.py backend/tests/test_pdf_specialist.py --basetemp data/stage-e/final-coverage-guard`：**33 passed**；Linux 无网络非 root 测试容器只读挂载当前 backend，同三文件 **33 passed**。未把该新增测试算入前述 506。
- 已知 LangGraph 1.2.14 提示 `durability has no effect when no checkpointer is present`，任务内子图无 checkpoint 是既定设计；主图与成功响应回执持久化正常。没有引入新运行依赖。
- 前端构建通过；本阶段未重跑浏览器套件，D 的 9 项浏览器证据保留。新阅读引用通过真实 HTTP 预览与人工视觉核对，不能混称浏览器端到端。

### 真实环境

- 摘要通过：`data/stage-e/20261012T181602634638Z/receipt.json`，run `85169443235e4d6d8138788dd684c0c2`，4 次 Gemini 调用，4/4 单元、无遗漏，单位 mm² 正确。
- 单次汇总诊断：`data/stage-e/synthesis-20261012T182156980378Z/receipt.json`，复用真实阅读回执，1 次生成证明结构化 comparisons 能得到明确关系结论；**不是端到端验证**。
- 最终专题端到端：`data/stage-e/20261012T182246531995Z/receipt.json`，run `21782f89f2424467aec261dc179e6560`，5 次调用，两份文件各 4/4 阅读单元、零遗漏；明确比较共同光效、IP54 变体例外及 L80/B50/CLO 与 L85/Tmax 寿命条件。模型语义评估 limited，任务与用户答案正确显示 **partial**，不宣称完全语义充分。两源原页 p4 引用/预览、文件名及 SHA-256 已核对，详见同目录 review.md。
- Provider 为配置的 Gemini `gemini-3.5-flash-lite`、Voyage `voyage-4`；Groq/rerank 未在 E 实测。首次真实验证建立两份索引，后续从只读 SQLite backup 和原件副本复用，无重复 embedding。
- 全部排错及复验共 **29 次 Gemini 调用**（9+9+5+1+5）；单轮始终不超过 6 次。早期失败保留，没有改写为成功记录。临时 uvicorn 均由探针退出清理；仅新增独立 `data/stage-e/` 运行副本，不改原件及旧运行数据。

### 阶段审查

- **Standards：通过，无未解决阻塞项。** 空汇总误完成、模型缩小范围后认证完整两个问题已关闭；原件/会话范围、回执、取消及发布边界保持。最终提示也明确计划外页是模型提议范围，不代表用户确认排除。
- **Spec：通过。** 三路径、跨文件独立取证、机械与语义覆盖、引用、六次预算均有证据。比较新增独立结构且必须实际跨源；没有比较关系时不能仅靠事实列表标为完成。
- 保守的非阻塞限制：页范围尚无可信结构化用户输入，因此模型计划之外的页始终产生 partial，即使用户确实仅要求某页。该取舍优先防止虚假全文完成，未来可在 F/交互接口改进；不新增自然语言正则猜测或额外付费确认。
- 模型语义充分性仍是模型评估，跨源引用校验不证明任意比较文本正确；真实样本的条件对齐已人工核对。OCR、完整章节树、精细段落/表格坐标及跨轮增量阅读未实现。

## 下一步交接

最新工作区共 81 项 tracked/untracked 变更（含完整 D），无 commit/push。原 `document-chat-backend-1` 和 `document-chat-frontend-1` healthy，仍旧代码。下一阶段为 F（长会话与跨子图协作），本轮未开始。实现入口 `pdf_reading.py`、`pdf_analysis.py`、`pdf_specialist.py`、`documents.py` 和主图；设计权威在 decisions-design.md 第 18 节。可复用探针为 `scripts/probe_stage_e.py --reuse-runtime <阶段E目录/runtime> --topic-only`；单次诊断另见 `scripts/probe_stage_e_synthesis.py`，须明确区别重放和完整链路。
