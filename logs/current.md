# 当前交接：M5.0协议草案待批准，正式评估未运行

2026-09-27。先读AGENTS.md、本文、docs/m50-evaluation-protocol.md与docs/m50-casebook.md；上阶段背景见docs/m5-handoff.md、docs/m46-feature-freeze.md。P-032/P-039仍为已确认依据，v0.1协议未批准，未写入decisions为已确认。

Git实查：main/HEAD/远端main=6c6d9222b414ac1747c094536fa784b0aa19a3a5；产品冻结7811243937e67e4e4d02854ffc616ad69736204d。起始工作区干净；本轮未提交新增协议docs/m50-evaluation-protocol.md、逐题docs/m50-casebook.md、机器题集eval/cases/m50_protocol.json、logs/m5.md及本文更新。产品代码未变，未提交/推送。

用户要求先准备可审阅协议、决策时告知，未授权新的外发。草案12计分轮（9开发+2文档保留+1同文件弱保留）、40必要事实、7个PDF正例/12证据单元；A正式Gemini基线+词法/向量/RRF，B可选7题重排，C可选4题固定证据Gemini/Groq配对。A/B/C全部含Embedding既有重试最多169个外发attempt，拟申请USD2预算控制。细节和限制见协议，不把候选当确认。

实际准备验证：五份原件哈希一致；8张相关PDF原页提取/视觉核对；完整CSV11386行、4个目标记录及3个未命中精确核对；保留使用记录搜索未见H01–H03应用结果。只做本地原文标注，未模型调用、未跑正式benchmark、未改服务配置/运行数据库。详细记录logs/m5.md，临时材料tmp/m50 ignored。

运行状态本轮只读核对：Compose siteco-m28-smoke双服务healthy；前端http://127.0.0.1:18095，后端18094；tmp/m28-clean/runtime，4份ready（条款/Rondel/价格CSV/守则）。Gemini gemini-3.5-flash-lite、Top K8、重排关闭；Groq openai/gpt-oss-120b凭据内存override configured，重启通常missing；Gemini/Voyage来自环境。Voyage voyage-4，本机60RPM/200000TPM/1秒，重排间隔1秒。未探测供应商额度。

冻结验证沿用原收据：Windows/Linux各351 passed+10 subtests，前端构建通过，浏览器35通过/11真实外发opt-in跳过。此轮无源码变化不重复全量测试。M4.5 Gemini K8、Groq K1真实成功与Groq K8 HTTP413均保留，不能当公平模型对比。双轴审查eval/results/m46_review.md及源码manifest不变。

下一步：用户集中批准v0.1题集/评分/执行块与外发上限；记录批准到decisions.md并固定协议哈希/阶段提交。再准备独立evaluation runtime、最小预算计数与结果记录harness，受控检查后执行已批准块。保留题结果不用于无披露调参；阻断修复按P-039记录/重新冻结/另行评估。之后M5仍须按README独立空runtime重建，重新确定外发预算。

敏感文件.env、grok.txt、Gemini_API_KEY.txt、voyage.txt ignored，不输出/提交。运行SQLite只由所属后端访问，不Windows直接读写。Python backend/.venv/Scripts/python.exe；Node D:/nodejs/node.exe；Docker LOCALAPPDATA/Programs/DockerDesktop/resources/bin/docker.exe。普通shell沙箱启动失败，可require_escalated进行明确范围操作。既有真实外发授权已全部用完，不重跑旧脚本。
