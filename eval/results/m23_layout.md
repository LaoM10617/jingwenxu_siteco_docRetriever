# M2.3.3–4 布局和切块开发验收

2026-09-26；解析版本 `layout-chunks-v2/pdfplumber-0.11.10`。
只验证开发材料及公共 `parse_document` 接口，没有模型调用或端到端问答。

## 可重复执行

在仓库根目录运行 `backend/.venv/Scripts/python.exe eval/check_m23_pdf.py`。
脚本要求本地开发材料；不会搜索或读取保留题材料。样本不进入镜像。
Linux 验证使用 `siteco-backend:m23-layout-test`，只读挂载 data 和该脚本，`--network none --rm`。

## 实际结果

- 采购条款：4页正常提取，29块，最长检索文本2136字符。物理第1页 Artikel II 中 Incoterms 2020、电子PDF交付、对方条款须明确书面同意保留在同一条款区域。
- Rondel：2页保留文本，17块，最长771字符；第2页因旋转文字等复杂布局带降级警告。左侧 Key Specifications 与右侧 order variants / accessories 分开；订单号、色温、功率、重量在整行中，HF movement sensor 对应附件号未串入灯具订单号。页面大标题作为有坐标的上下文保留。
- Highbay：22页中11页正常提取、7页降级提取、4页无可用原生文本，101块，最长1047字符。物理第18页 midi / maxi / all sizes 分成独立区域；midi 为474×442×72 mm、3.7kg、最高+70°C；maxi 为946×442×72 mm、7.2kg、最高+65°C；IP66/IK08属于all sizes。
- Windows与Linux真实样本检查均通过，覆盖/块数/最大长度一致；各平台重复解析返回相同证据结构和ID。脚本验证检索文本可由上下文与原文段重建、字符硬上限及关键关系。
- Windows与Linux全量各64测试、10subtests通过；解析12测试涵盖分栏、整行切块、标题来源、条款续行、内容故障有限降级、超长单元显式舍弃及既有页级隔离。1条既有Starlette/httpx弃用提示。

## 视觉依据与局限

按PDF技能重新查看了M1已渲染的采购条款第1页、Rondel第2页、Highbay第18页完整页图，并与本轮坐标及解析输出逐项核对。源文件未修改，不需重新渲染。

规则利用横线、留白、字号、粗体及编号，生产代码无样本名称、型号或固定裁剪区域。页内明确表格使用完整行；复杂未判明区域保留较大的原生文本并警告。旋转标注仍可能阅读方向不佳，图像信息不提取，无线表格及跨页关系不保证准确重建。正常提取标志不等于无遗漏，降级页上的清晰区域仍可提供证据。

字符目标2400、硬上限6000是内部初始参数；不可安全拆开的超长单元舍弃并警告，而非裁剪出失去条件的片段。本轮三个样本没有触发舍弃。Embedding token限制后续另行处理。

以上是M2.3.3–4的验收记录。未使用保留题调参；D01–D08只检查解析证据，没有将application_result改成问答通过。

## M2.3.5–6：阶段验收通过

2026-09-26，复用上述原页图核对与开发材料脚本，Windows/Linux同一锁定依赖再次通过；没有更改解析规则，也没有读取保留题。核心开发页均保留目标证据，未以部分成功为由绕过条款或型号关系要求。

生产PDF处理器已接入上传工作线程。SQLite独立document_parses表事务保存完整证据、源位置/上下文、物理页记录、warnings和版本；列表/详情仅开放覆盖摘要和警告。解析检查点与ready检索artifact分离，解析成功以retrieval_not_configured明确结束，证据HTTP仍409。无文本、损坏和页数超限有明确错误；未知页数为null。重试清除旧解析记录，处理被中断时保留已提交检查点，迟到报告不能写入。

最终Windows/Linux各69测试+10subtests通过，既有httpx弃用提示1条。真实Linux运行镜像siteco-backend:m23-accept经127.0.0.1:18085上传Highbay：202接收，解析22页/101块，11正常+7降级+4无文本、11条warning，failed/retrieval_not_configured；重启后列表、详情与warnings完全一致，证据继续409。运行数据绑定D盘tmp/m23-acceptance/runtime，验收全程只用HTTP访问运行状态；容器已停止删除。

M2.3按“PDF→可追溯证据与持久覆盖记录”范围验收通过。没有真实Embedding/FAISS、问答或ready验收；无API Key读取/模型调用。覆盖计数不是准确率，coverage_limited=false也不承诺信息完整。
