# 当前交接：M5.0 A+B首次评估已完成，发现阻断候选待决策

2026-09-27。先读AGENTS.md、本文、eval/results/m50/run-20260927-ab-01/report.md、eval/README.md、logs/m5.md。协议docs/m50-evaluation-protocol.md、题集eval/cases/m50_protocol.json；P-040批准A+B，C未批准。

版本：产品冻结7811243937e67e4e4d02854ffc616ad69736204d；交接6c6d922；正式评估基准提交859447f9b42e999cc07c603c6a88634b5c1d9984。本轮结果、离线汇总/复现说明与本摘要待本轮结果提交（以git log实查）；未推送。backend/app和依赖锁仍与7811243一致。

A+B结果目录eval/results/m50/run-20260927-ab-01，真实运行260.922秒，共33attempt（Gemini11、文档embedding8、query7、rerank7）；无人工重试/切模型，C零调用。严格通过3/12，必要事实及其支持引用10/40。PDF证据单元词法9/12、向量12/12、RRF10/12、重排11/12；完整题6/7、7/7、6/7、6/7。不把小集结果升级为通用模型/策略结论。

失败：E01漏已提供的付款限定；E02检索遗漏+onlyfy错误归属/否认。E03/E06约60秒generation_provider_unavailable，远端原因未确定；E04/E05依赖未执行。E07/E12订单号句末句号被字面校验拒绝，模型订单正确；独立零外发QuestionTools复现'.'失败，'?'、','或无标点成功2条。E11直接回答正确，但缺预批rubric中白/黑/银完整枚举，严格失败单独说明。源码未修、原问题未改、旧成绩保留。

待决策：按P-039讨论仅修复QuestionTools订单号句末标点边界（保持内部标点/精确匹配防截断），受控回归后重新冻结；受影响真实复测需要新范围/预算授权，E12已用于诊断须称回归材料。C仍等待用户时间决定。不能拿本次153上限未用完的余量自行重跑、加题或执行C。USD2为本次估算控制；已占用保守reserve USD0.22363244，已知成功usage按牌价USD0.01861124，失败计费用量未知，不是实付。

成果：report.html（离线可筛选/展开）/report.md、summary.json/CSV、scores.jsonl、人工标准对应的assistant_source_review review.json及全部安全原始JSONL。离线python eval/summarize_m50.py <run-dir>重算无需Key，结果逐字节一致。语义判断不是独立人工双盲/全自动裁判。eval/README.md给出真实重跑与材料哈希/自有Key要求；eval/reproduce_m50_boundary.py可零外发复现句号问题。

验证：4项预算边界测试通过；脚本编译；报告Edge/Playwright桌面/手机、筛选/展开通过、无页面错误/整体溢出；密钥扫描通过。未跑产品全量测试，因为产品无改动；冻结351+10、浏览器35通过/11跳过沿用M4.6收据。本次不等于M5 Docker/浏览器独立空runtime交付验收。

运行：原siteco-m28-smoke未改，18095/18094与4ready保持；本轮独立eval进程已结束、tmp/m50-ab-01/runtime保留，不是共享生产库；本地报告临时18096服务已停止。截图/准备页图在tmp/m50。M5重建仍需新空runtime与新外发授权。

凭据Gemini_API_KEY.txt、grok.txt、voyage.txt、.env ignored，禁止打印或提交。本轮只读取Gemini/Voyage用于已批准调用；Groq未读未调用。运行SQLite只由所属进程访问。Python backend/.venv/Scripts/python.exe；Node D:/nodejs/node.exe；普通shell沙箱启动失败时require_escalated。无需重复请求已批准A+B的权限，但修复后复测/C不在授权中。
