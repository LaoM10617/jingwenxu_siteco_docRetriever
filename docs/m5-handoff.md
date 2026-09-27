# M5交接：先正式evaluation，再干净重建与交付

2026-09-27。M4.6功能冻结已通过；冻结代码提交为7811243937e67e4e4d02854ffc616ad69736204d。本交接提交只更新文档，不改变被评估功能。接手先核对Git/运行状态，不以摘要替代代码与证据。

## 必读与已有证据

先读AGENTS.md、logs/current.md、本文、docs/m46-feature-freeze.md、milestones_and_execution_plan.md的M5.0/M5，以及decisions.md P-031–039。原case与requirements_draft.md在本机private/本地文件中，不纳入交付。

双轴审查及关闭项见eval/results/m46_review.md；源码/依赖/测试原始字节哈希见eval/results/m46_source_manifest.json，跨平台以Git提交复建。最终Windows/Linux各351项＋10子测试通过，前端构建通过，浏览器35通过/11真实外发opt-in跳过。原M4.1–4.5逐题结果及失败在eval/results，不能改称正式评估结果。

## 第一个工作块：M5.0协议与题集

1. 只读核对eval/materials.md、eval/cases及已有标注，明确开发材料和保留材料。此前已使用的采购条款、Rondel、价目CSV、隐私声明和业务伙伴守则不得称未见保留集；General Terms of Sale此前未使用，仍需实际记录核对。不要为准备阶段先向模型发送保留题。
2. 在冻结代码上拟定小型题集（原计划建议10–12题，不是已批准最终数量），覆盖PDF证据、CSV精确查询/未命中、证据不足、多轮指代和跨范围；先固定原文页/CSV逻辑记录、必要事实和限制条件、等价证据与指标分母。开发/保留分开汇总，评分细则集中确认，不反复逐题询问。
3. 固定模型、Top K、重排、上下文预算、提示和缓存策略；记录配置快照。PDF按计划比较词法/向量/RRF，报告Evidence Recall@8、完整证据命中率@8、MRR@8，重排已实现，可在获授权的同候选对照中加入。CSV记录集合Precision/Recall、精确未命中及重复来源单列。回答事实/归属/条件、引用支持和指代行为分别评分。
4. 形成具体可审阅的材料/题数/供应商/调用次数上限/失败处理/费用范围，再一次请求新的外发授权。既有Gemini、Groq、Voyage、重排授权均已用完；不得重跑旧脚本或因本机有Key视为无限授权。优先完成单模型正式结果，多模型仅在时间、额度及授权允许时，用同一固定证据/提示比较；不同Top K或缓存的耗时不能当公平模型比较。

## 第二个工作块：M5.0执行与证据

固定协议后串行运行并保留首次失败、逐题配置、实际输入范围/前轮、召回证据、答案/引用、评分与失败层。区分解析缺失、检索未命中、规划/指代、生成错误归属、显示问题。记录端到端、可测阶段、限流等待、缓存命中；仅给实测逐题值/中位数，不用小样本冒充稳定P95。输出机器可读逐题结果、数字汇总及失败分析，不引入LLM裁判作为唯一真值。

若暴露正式必做阻断：记录原成绩、缺陷、解冻理由和最小修复；按已确认边界回归、必要复审并重新冻结，再重跑受影响评估。不得根据保留题调优后仍宣称独立未见成绩，也不得悄悄降范围或用重试覆盖失败。

## 第三个工作块：M5干净重建、演示与交付

从明确冻结提交按README建立独立Compose项目/端口和空HOST_DATA_DIR，不影响现有演示。不得复制开发数据库、向量、缓存或答案；tokenizer按正常README准备。通过Settings配置获授权的真实凭据，重新上传材料，浏览器验证单/多文档、追问、来源/原文高亮、刷新和失败提示。需要新的真实调用授权，容器health成功不能替代端到端。

整理约10分钟本机演示和20分钟架构/取舍/失败/后续方向；核对README运行、实现、决策理由和下一步。按P-003清理面试官可见说明的语言、重复和私有路径，保留真实源码历史/复用来源；核对仓库访问、密钥排除、交付版本。实际发送邮件或消息仍需用户明确指令；交付后最终冻结约束不同于当前功能冻结。

## 运行与边界

现有siteco-m28-smoke：前端http://127.0.0.1:18095，后端18094，runtime tmp/m28-clean/runtime，4份ready。Gemini/Top K8/重排关闭，Groq Key内存override；重启恢复环境默认，Groq通常missing。运行SQLite只通过所属后端，不从Windows并发读取。新验收必须独立空runtime。

Gemini gemini-3.5-flash-lite＋Voyage voyage-4已真实跑通Top K8；Groq openai/gpt-oss-120b简单探测通过，但当前账户Top K8请求9097超过8000TPM而HTTP413，Top K1跑通。同一小PDF的单题成功不是通用准确率保证。模型名可编辑不等于支持任意模型/端点。

Embedding固定voyage-4/1024维；无替换服务或重建索引扩展。可选重排rerank-2.5-lite默认关闭。仓库准入默认3RPM/10000TPM/20秒，本机60RPM/200000TPM/1秒，重排成功间隔1秒；不要把本地值当账户额度。Key文件.env、Gemini_API_KEY.txt、grok.txt、voyage.txt均ignored，不打印或提交。

Python backend/.venv/Scripts/python.exe；Node D:/nodejs/node.exe；Docker CLI在LOCALAPPDATA/Programs/DockerDesktop/resources/bin/docker.exe。tmp/m35/start.ps1仅用于既有本机演示，并非M5交付复现步骤。更新logs/current.md维护接手摘要，详细执行写logs/m5.md（开始实施后创建）。本轮只交接，未启动evaluation或供应商调用。
