# 当前交接摘要：M2.3验收完成

2026-09-26。M2.3.1–6已完成，验收范围为PDF→可追溯证据、页覆盖及warnings持久化。M2整体尚未完成：CSV解析、Embedding、FAISS、问答和前端仍待后续实施。

## 依据与范围

P-010至P-023及实施补充；docs/m2-first-contracts.md；T-002至005已批准。FastAPI/React+TS最小双容器；SQLite/D盘运行数据；按文档FAISS CPU IndexFlatIP选定未安装。20MiB、PDF50页、CSV20,000记录、10活跃文件；108页报告退出基线。Voyage4 1024维3RPM/10KTPM、Gemini/Groq免费优先。本轮无模型/Key调用。无OCR/视觉推理，不用保留题调参。

## 实现

- M2.1配置/健康/非root单worker Linux镜像/Compose挂载；M2.2独立上传ID、限额、SQLite状态、有界单线程队列、发布门槛、重试及中断、HTTP接口已完成。
- parsing.py/pdf_layout.py：pdfplumber0.11.10锁定依赖，逐页原生文本、横线/留白/标题分组、完整行/条款切块；无文件名/型号/固定裁剪框。版本layout-chunks-v2；内部2400目标/6000硬字符上限，超长不可安全分割单元明确舍弃warning。source_spans/context保留原文与同页bbox，retrieval_text可重建，ID稳定。复杂/旋转文本有限降级；全无证据失败，非内容错误传播。
- PdfParsingProcessor已接生产摄入线程，report提交完整ParsedDocument到document_parses表，与ready检索artifact分离。get内部返回parse_result，HTTP白名单不暴露原文；列表/详情公开parsing（version/page_count/coverage/evidence_count/coverage_limited）和warnings。未知页数null；progress仍null，不是提取准确率。
- PDF解析成功当前结束为failed/retrieval_not_configured，CSV仍processing_not_configured；不是假ready。损坏、超页数、无证据固定错误。retry清空旧解析结果；中断保留已提交检查点，stop后迟到报告禁止写入，重启不重跑。证据HTTP未ready仍409。

## 实际验证

Windows/Linux全量各69测试+10subtests通过；1条既有Starlette/httpx弃用提示。新增HTTP解析成功/失败摘要持久化、重试清理/中断检查点测试。

开发样本脚本eval/check_m23_pdf.py两平台通过，完整原页图已按PDF技能核对：条款第1页责任主体/书面条件、Rondel第2页左右参数/订单及附件、Highbay第18页midi/maxi/all sizes。条款4页29块；Rondel2页17块（1降级）；Highbay22页101块（11正常/7降级/4无文本）。见eval/results/m23_layout.md，不等于完整信息恢复或问答通过。

真实Docker运行镜像siteco-backend:m23-accept，127.0.0.1:18085，D盘tmp/m23-acceptance/runtime：实际Highbay上传202，解析覆盖和101证据持久化，failed/retrieval_not_configured，证据409；重启后列表/详情/warnings逐字段一致。验收仅通过HTTP访问运行状态，不跨系统打开SQLite。容器已stop/rm；验收数据保留在忽略tmp中。

## Git/环境

main；本次M2.3检查点的父提交为73c58ca，M2最终审查基准4307e22ceb08b70d6dca459137355b0551f2e6c1。用户已授权将M2.3代码、依赖锁、测试、开发脚本及相关文档提交并推送，消息为“Implement preliminary PDF parsing.”。本摘要随该检查点提交；最终提交ID、推送与工作区状态以Git为准。密钥/原材料/运行数据保持忽略。

Docker29.8.0 Linux/amd64，镜像/缓存在C盘；必要时PATH加LocalAppData/Programs/DockerDesktop/resources/bin。测试镜像siteco-backend:m23-accept-test。无本轮遗留运行服务。标准shell有环境启动限制，本轮经沙箱升级执行，无审批拒绝。

## 下一步

进入后续CSV或Embedding/检索阶段前按阶段计划拆解确认；不要把PDF解析完成当作ready完成。CSV仍未实现，远程Embedding token预算/限流、FAISS持久向量、检索问答与前端仍待完成。旋转文本、复杂无线表格及跨页关系有已记录限制。M2最终Docker浏览器端到端与双轴审查待整个M2完成，M2.3无需提前声称M2完成。
