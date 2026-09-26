# 当前交接：M2.6六步已验收，下一步M2.7

2026-09-26。M2.1–M2.6各自范围已验收；PDF可完整发布ready并混合检索。聊天/生成/引用工具编排未实施，M2整体和最终双轴审查未完成。

## 决策与下一步

P-026及docs/m26-retrieval-contract.md：FTS5/BM25+Voyage-4/FAISS+RRF；两路所选范围内全局20候选，等权k60，默认8。来源(document_id,evidence_id)，先校验全范围；无语义错误静默降级。参数为初始值，未调参。

新P-027：M2.7落实LLM生成经schema校验的结构化条件→确定性工具执行。Decimal/白名单字段、操作符、单位；保留原值/单位/来源/依据；不执行任意模型代码或SQL。PDF先确认产品/参数/限定条件归属，缺失/歧义明确说明。下一阶段实施前细化schema和新增测试边界；现有T-004/T-007已批准。

M2.7需接CSV精确查询、PDF证据、回答/引用和聊天范围，考虑warnings及上下文。处理额度等待的pending/流式传输：当前nginx同步120秒，入场等待上限180秒，不能直接用临时同步验收路由当最终聊天方案。

## 实际代码

- pdf_store.py：规范化一次的1024float32、每文档IndexFlatIP；证据/配置JSON、向量BLOB及digest持久化。校验完成后，与FTS/ready同事务发布；半成品不可查。启动重建FAISS/FTS，不解析/Embed；损坏artifact失败隔离，可重试。
- documents/processing/main：一个gateway和scheduler共享给摄入/查询；无网络/等待中的生命周期锁。完整PDF来源保留text/retrieval_text/context/source_spans/locator，read_evidence走ready门槛。CSV路径不改。
- retrieval/pdf.py：全范围验证→发布索引快照→query embedding→全局语义top20→重验发布/FTS全局top20→RRF。FAISS枚举文档全部行保证边界同分确定；两路分数后按doc/evidence ID排序。RRF复用词法先、语义后首次出现同分规则；不同上传不去重。无正式query HTTP。
- 缺Key仍在PDF解析后failed/retrieval_not_configured；缺固定tokenizer/非voyage-4为embedding_configuration_invalid。准备DATA_DIR/tokenizers/voyage-4-tokenizer.json并注入后端Key后重新上传。已ready本地恢复不需Key；执行retrieve需配置gateway（新问题需远程，重复问题可命中缓存）。
- 既有EmbeddingGateway/BudgetScheduler：3RPM/10KTPM至少20秒间隔、query优先、32待处理、每次等待180秒、4000tokens批次、3次有界尝试、30秒connect/read。持久预算/cooldown/cache，tokenizer固定SHA，无运行时下载；跨客户端额度仍可能429。

## 实际验证

- Windows/Linux最终各190 tests+10subtests通过（前三步179，本轮新增11）；前端10既有控制/真实代理检查+2新真实PDF检查通过。通用浏览器run跳过5个opt-in场景，两个PDF场景单独执行；旧真实CSV/旧PDF失败上传场景未重跑，后端回归已覆盖。
- 短开发Rondel原页渲染核对，真实Docker浏览器202→ready，2页17证据，1条layout_uncertain保留，成功预览与刷新通过，补验收M2.4真实PDF ready预览。
- 开发D06正确表格词法1/语义1/融合1；D07配件表词法2/语义1/融合1。记录标题/泛化候选噪声及宽bbox，未优化参数；未用保留题，非回答准确率评估。
- 本轮3次真实Voyage调用：摄入15唯一文本+2查询，usage980+31+13，间隔20.038/20.004秒。前三步另2次合成调用，共5次；无重试、生成或付费切换。
- 后端重建、禁止provider后结果/状态完全一致，调用0。再恢复正式compose入口，health200/验收路由404/原PDF仍ready。详情eval/results/m26_hybrid.md；原始截图/JSON在忽略的tmp/m26-docker。

## Git与运行环境

用户授权将整个M2.6提交并推送main，消息为“Initial completion of indexing.”；本交接随该检查点提交，具体SHA以git log核对，远端同步以git status与origin/main核对（避免在提交中自引用尚未生成的SHA）。提交覆盖模块、接线、测试、依赖锁、工具及文档，密钥/材料/runtime不纳入。M2.6起始基准7a542df896d124470744c9924c8042b4aaeefdc0；M2最终审查基准4307e22。后续阶段开始时以该检查点记录新基准。

最新预览：http://127.0.0.1:18091/，backend18090，Compose siteco-m26-acceptance，正式入口，无验收路由；1份ready Rondel（8989ca6429c14f908842ee8a92a8d995）。数据D:/Projects/Retrieval_SITECO/tmp/m26-docker/runtime。旧M2.5在18089/18088、M2.4在18087/18086，均未更新，不要混淆。

仅后端访问运行SQLite；状态检查HTTP。Docker镜像缓存C盘、数据D盘，不迁移。密钥根目录忽略文件，不输出/提交/入镜像。eval/run_m26_docker.py仅显式部署验收helper，需key-file；生产正常配置见README。官方tokenizer保存在忽略runtime，无模型权重。测试镜像siteco-backend:m26-test。

Shell/CUA默认沙箱曾初始化失败；已授权命令用exec_command require_escalated（自动审查未拒绝）。Python为backend/.venv/Scripts/python.exe。Docker CLI需LOCALAPPDATA/Programs/DockerDesktop/resources/bin。浏览器验收用项目Playwright+Edge。

保持20MiB/PDF50页/CSV20000条/10活跃文件，无OCR/视觉/本地模型；108页报告不在基线。下一步先读P-027、当前契约和M2.7入口；勿把检索分数、页面覆盖或ready等同信息完整或回答正确。

## 新对话交接范围

用户将于新对话推进M2.7到M2.9。仓库已明确M2.7入口，但未单独确认M2.8/M2.9细分；先核对milestones、decisions和实际代码，提出后三步分工与小验收，再按已确认范围实施。不要把通用聊天历史、完整多轮改写、流式方式或原文高亮默认为已批准。新接口/关键测试边界统一讨论，常规实现不重复确认。M2完成前仍需真实Docker浏览器新上传→问答及固定范围Standards/Spec双轴审查。
