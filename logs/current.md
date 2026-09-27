# 当前交接：M5.0首次A+B完成；P-041句号缺陷本地修复完成

2026-09-27。先读AGENTS.md、本文、logs/m5.md、eval/README.md。协议docs/m50-evaluation-protocol.md；P-040批准A+B，C未批准。P-041仅批准订单号句末句号校验最小修复和本地回归。

Git：main，原产品冻结7811243、交接6c6d922；评估提交859447f、结果提交c5421f2。当前P-041修复检查点以git log核对提交，未推送。生产仅backend/app/questions.py一处正则边界改变，其他冻结范围保留；本检查点不是M5最终冻结/交付验收。

首次结果eval/results/m50/run-20260927-ab-01保持不变：严格3/12、必要事实及支持引用10/40；7题PDF词法9/12、向量12/12、RRF10/12、重排11/12。纯文本7单元分别4/7、7/7、5/7、6/7；表格PDF5单元各5/5。小样本且同文档相关，不能外推策略优劣。E01遗漏已有证据限定；E02遗漏+错误归属；E03/E06约60秒provider_unavailable，原因未确定；E04/E05依赖阻断。CSV正例未成功到查询，不是索引查错。E11直接回答正确但漏rubric枚举。

P-041：E07/E12正确订单因句末点被拒已修，内部点/斜杠/连字符及字面完整性保留。4新正例先失败；QuestionTools 24通过；后端全量345通过71.79秒；diff --check通过。收据eval/results/m50/period-validation-fix.md。固定本地planner+真实CSV发布/查询的合成数据回归，不是模型/原目录真实复测。旧punctuation-repro及脚本保留，需原859447f checkout。

真实A+B已用33attempt/260.922秒；reserve USD0.22363244，成功usage牌价USD0.01861124，失败计费未知。本次修复零外发。不得使用旧153上限余量自行复测；新基准/协议/预算先批准。C仍待决定。E07/E12已见，后续称回归；新未见材料另定。原runner冻结检查会拒绝当前产品差异，不绕过。

输出HTML/Markdown报告、JSON/CSV汇总、评分和原始JSONL。离线summarize无需Key，仅复算已有review。真实重跑需要原提交、材料哈希、自有Key/额度。原报告浏览器检查、密钥扫描及离线字节一致验证通过。M5按README独立空runtime重建/Docker浏览器演示未执行。

运行：原siteco-m28-smoke本轮未触碰/重启；原端口18095/18094状态沿用上轮，未重新探测。评估进程及临时18096服务上轮已结束。SQLite只由所属进程访问。根目录Gemini_API_KEY.txt/grok.txt/voyage.txt及.env ignored，禁止打印提交；本轮未读取。Python backend/.venv/Scripts/python.exe；普通shell沙箱helper失败时require_escalated。

下一步：用户决定纯文本证据覆盖/回答完整性改进范围与受影响真实复测预算；不自动更换检索策略。完成M5冻结前需按AGENTS固定范围双轴审查及独立重建验收。
