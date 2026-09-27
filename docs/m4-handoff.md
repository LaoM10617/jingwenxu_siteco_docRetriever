当前权威状态：M4.6功能冻结通过，下一步M5.0→M5。先读logs/current.md与docs/m46-feature-freeze.md；以下为保留的阶段交接历史。

# M4交接：开发验证先行，正式benchmark在功能冻结后

2026-09-27。先读AGENTS.md、logs/current.md、本文，再读P-032、milestones_and_execution_plan.md及相关契约/验收。

## 当前执行入口（2026-09-27 M4.4完成）

M4.1–M4.3已提交并推送2f3ad2d。M4.4正文对照及P03生成配对完成，单题期限及例外回答改善但章节开头仍缺。用户已确认P-036，后端重排开关已实现默认false，固定模型/5秒预算/失败回退RRF；329项Windows后端测试通过。未重建或启用18094/18095部署，未做真实接入冒烟。Settings没有用户端开关，M4.5统一讨论配置入口。实验、源码、测试及交接均未提交。详见eval/results/m44_prose_comparison.md及P-036。

M4.5.1统一契约已形成：docs/m45-settings-contract.md、P-037；用户已确认Gemini/Groq、Top K/重排/诊断与Voyage最小展示/Key范围和内存生命周期，具体新HTTP/测试边界已由用户确认。随后M4.5.2核对额度/Embedding扩展成本，M4.5.3实现Settings，M4.5.4验收。现有真实外发额度已用完。

M4.3预览契约与证据见docs/m43-preview-contract.md、eval/results/m43_preview.md。运行18094/18095未改，无新增服务；正式benchmark与功能冻结尚未开始。下文准备记录为历史。

## 已确认顺序

修正文档矛盾 → M4代表性质量与耗时验证/错误分析 → 补最影响追问和核对的体验 → 原文预览/高亮 → 根据评估决定重排 → 自定义提供方配置 → 检查决策并冻结大致功能 → M5.0带数字的检索evaluation/有条件的多模型比较 → M5重建、演示及最终交付。

M4用于找问题并改进；M5.0用于冻结后的可复核成绩。正式量化评估必做，多模型比较有时间且授权/配置允许再做。指标方案、人工标准和保留集规则集中见P-032，具体题数/门槛/评分细则尚未锁定。截图建议不是已执行结果，也不自动批准评估框架。

## 历史起点与先做事项（交接准备时记录）

- main及本地origin/main均为de8487dd25ce5f21127d59395e965686f0005a42；M4审查起点记录为该提交，接手复核。M3历史双轴审查基准仍为88ad778，不覆盖本轮新文档。
- 本轮只更新决策/计划/需求/交接，无功能实现、benchmark运行或新模型调用；新文档尚未提交。requirements_draft.md原本被忽略，保留本地，不force-add。
- 首项修复：README第45行独立问题说明、第210–212行多轮未实现说明与P-031/末尾memory章节矛盾。本轮尚未修README，不要误报完成。
- Windows/Linux各308测试+10subtests是既有M3证据，本轮未重跑；浏览器28通过/6历史opt-in跳过。详见eval/results/m3_checkpoint.md与m35_integration.md。
- 真实首轮4问有一问指代解析正确、生成错归属；修复后仅定向复验成功。保留失败，不宣称全套真实脚本全绿。首问真实限流后82.219秒，作为质量/耗时调查线索，不当作总体可靠率。
- 体验重点：产品归属与限定条件、等待说明、刷新后文档选择连续性、来源可读性。具体改动按证据推进，不能把所有建议自动列成已确定接口。
- Settings现在只是占位说明。P-014自带Key方案仍需落实接口/生命周期；已有提供方配置与任意base URL是不同范围。不可将任意endpoint或Embedding切换视为已批准。

## 运行、授权与收尾

最新前端18095、后端18094，Compose siteco-m28-smoke；runtime为tmp/m28-clean/runtime。运行状态接手用HTTP复核，SQLite只允许所属后端访问。旧18091/18089/18087不动；Docker镜像/缓存C盘，数据D盘。
Gemini/Voyage仅D01/D06/D09已授权范围；新增材料或供应商接收方先确认，付费切换先通知。Voyage共享3RPM/10KTPM、至少20秒间隔，真实调用少量串行。Key仅后端运行时注入；保留题不调参，108页报告不在基线。
遵循AGENTS技能与审查规则：新公共接口/支持范围/测试边界统一确认；已确认边界内修复验证无需重复询问。M5冻结前Standards/Spec按同一固定范围并行审查，显式覆盖全部未提交文件，更新交接。


M4.5.2已完成只读核对，限流建议与Embedding改造成本见docs/m452-voyage-embedding-assessment.md；本机候选参数和暂不扩展建议待用户取舍，尚未改运行参数。下一步M4.5.3。


## 2026-09-27 M4.5 实施检查点

用户确认仅调整本机限流及Settings，不扩展Embedding服务、不重建索引。按P-037实现读取/应用/测试/清除接口、Gemini/Groq模型与内存Key、Voyage同模型Key、Top K 1–20及重排开关。任务与上传在接受时冻结配置；配置变更不重置共享准入。前端测试已应用配置，草稿先应用；测试不会随加载/刷新自动运行。

本机启动参数已调整为60 RPM、200000 TPM、Embedding最少1秒间隔、重排成功后1秒间隔；仓库默认保持3 RPM/10000 TPM/20秒，错误冷却保留。账户截图不是当前Key/项目额度实测。Settings展示运行值，不承诺供应商延迟。

验证：Windows后端337 passed（73.57秒）；TypeScript及Vite构建通过；Docker重建后浏览器34 passed、12 opt-in skipped（32.6秒）。真实本地GET及同值PATCH验证代理、no-store和运行参数，原三份文档仍ready。受控测试覆盖凭据脱敏/清除/恢复、修订冲突、任务及上传冻结、重启、Top K诊断和浏览器操作。真实供应商连接/问答未复验；不能报告双模型验收或正式benchmark完成。探测错误无法可靠分类时返回provider_error。

开发测试曾因mock路径错误，让合成假Key/合成输入进入真实SDK并失败；没有使用项目真实Key或文档，不计成功验证。已修正mock并为Settings测试禁止非回环socket连接，保留此失败记录。

部署siteco-m28-smoke：http://127.0.0.1:18095（后端18094），沿用tmp/m28-clean/runtime；默认Top K 8、重排关闭。未commit/push，保留此前所有未提交工作。下一步获授权后做有限真实提供方验收，再M4.6冻结、M5.0正式evaluation、M5；不自动消费旧已耗尽授权。


## 2026-09-27 真实配置验收检查点（尚未全部通过）

先按用户指定消息“Add frontend model, retrieval, and embedding settings.”提交并推送6bad97827fcb766e8f4aa613fb239e8cb2f34199至origin/main，远端已核对。首次push被自动审批要求确认具体远端；用户明确确认后成功。凭据文件未提交。

用户授权通过Settings真实配置、上传小PDF、分别验证Gemini/Groq。通过实际页面输入本机Gemini_API_KEY.txt、voyage.txt和用户指定grok.txt，未打印Key。Cua初始化失败，改用现有Playwright驱动真实页面，无mock。首次脚本控件定位失败发生在任何应用/供应商调用之前，修正定位后继续。

固定开发材料SITECO_Verhaltenskodex-Geschäftspartner.pdf，611293字节/6页，非保留材料；问题、哈希及第6页预期先固定于tmp/m45-live/protocol.json。询问举报渠道与电话处理：邮箱、电话、完整邮寄地址及自动录音转交条件。两轮独立会话、只选该PDF、Top K 8、重排关闭。

Gemini gemini-3.5-flash-lite连接/简单JSON探测通过（1.377秒）；Voyage voyage-4探测通过（0.810秒），页面新上传到ready约5.473秒，真实文档Embedding两批（3020/2485供应商tokens），未重建原索引。Gemini一次问答完成，观测端到端51.173秒，其中生成日志47.967秒；预设事实全部符合第6页，引用S1、零拒绝片段，实际页面原页高亮打开成功（1区域）。系统outcome=partial：8候选选中，4进入上下文/4遗漏，不能改报完整覆盖。

Groq openai/gpt-oss-120b连接/简单JSON探测通过（0.765秒），真实问答失败generation_provider_error，观测2.576秒，生成阶段日志0.249秒。查询使用前轮同问题Embedding缓存。原失败question_id=e5a9f6298e874c34a5ef27c7c65c18ba保留，不把连接测试冒充全链路验收。现有日志没有供应商HTTP状态，尚不能认定为schema、账户请求大小限制或其他原因。已请求最多2次额外Groq诊断/复验授权，未获答复前不重发。

结论：Gemini＋Voyage本次真实页面链路通过；Groq尚未通过完整问答。M4.5不能标为全部验收完成，M4.6尚未开始。当前内存选中Groq且三项Key为override；后端重启恢复环境默认、Groq环境默认缺Key。不要让下一任务误以为Groq已可演示。本轮没有更改产品代码；验收报告/日志为提交后新增未提交记录。

证据：eval/results/m45_live_settings.json，原始脱敏响应及截图tmp/m45-live。正式evaluation和M5干净启动复现未开展。


## 2026-09-27 M4.5真实验收完成（有明确账户/配置边界）

用户追加授权2次Groq诊断/复验，均已使用。通过所属后端SQLite在线备份创建隔离副本，原AnswerService＋已缓存query向量重建同一生成输入；没有重复上传或新增Voyage调用。第1次取得HTTP413：账户TPM上限8000、请求9097，类型tokens/rate_limit_exceeded。排除本次Key或schema拒绝假设；此前generic错误掩盖了请求额度原因。

按已确认SDK测试边界先红后绿：Gemini/Groq各一例HTTP413，修复映射到既有generation_context_too_large，明确建议减少PDF Top K/所选材料并检查账户限制；不重试、不自动截断、不输出原始供应商错误。生成＋Settings相关25测试通过（6.74秒），Docker已重建健康。

第2次通过Settings重新填Groq Key、将Top K明确调为1，再从页面提交同一PDF/问题的新会话。Groq openai/gpt-oss-120b成功：约4.647秒端到端，生成日志2.456秒，outcome=answered，零拒绝片段，候选8/选取1/上下文1/遗漏0。全部预设事实与第6页一致，实际原页预览与1个来源区域高亮通过。原Top K8失败及诊断永久保留；不能把本次配置缩减说成所有Groq请求都可用，也不能用51.173秒与4.647秒作公平模型速度比较（Top K/上下文及缓存不同）。

验收结论：已达到本轮“Settings有明确配置方式，Gemini或Groq配合Voyage至少一条真实PDF问答/来源核对路径跑通”的最低目标。当前用户要求的M4.5验收完成，可进入M4.6功能冻结检查；这不是通用准确率、所有账户额度、复杂schema/多轮全面覆盖或M5干净构建验收。Groq小额度账户README明确从小Top K开始，降低Top K可能损失跨段证据，不承诺保证成功。

本轮合计：Gemini探测1＋问答1；Groq探测1＋原失败问答1＋诊断1＋复验1；Voyage探测1＋文档2批＋query1，其他相同问题查询命中缓存；重排0。未更换套餐或付款方式。四份ready文档保留。

验收后恢复演示选择Gemini/Top K8/重排关闭；Groq Key仍在内存，可切换使用，重启后需重新输入Groq Key。当前HEAD/远端仍6bad978；此后HTTP413修复、两项回归测试及验收记录未提交/未推送。凭据和临时诊断数据库均ignored。


## 2026-09-27 M4.6冻结完成

原case四页及P-031–038核对，README残留只读Setup/无Key控制和.env.example无UI开关说明已纠正。Standards/Spec同固定快照审查，两轴各发现同一P2：Embedding探测本地冷却超时误报连接timeout。受控零外发复现后最小修复，保留在途锁并新增2项HTTP回归，两轴第二快照各自复验通过，0未解决阻断。

最终Windows351＋10子测试（71.56秒）、Docker/Linux351＋10（61.16秒）；前端tsc/Vite通过，浏览器35通过/11外发opt-in跳过（33.9秒）。已重新部署，无新模型调用；4份ready保留，Gemini/Top K8/重排关闭，Groq内存Key重新经UI恢复。先前M4.5真实证据与Groq413失败保留，不重跑已耗尽授权。

冻结范围docs/m46-feature-freeze.md，双轴收据eval/results/m46_review.md，已审源码哈希eval/results/m46_source_manifest.json。基准de8487d、首快照a692ec…6599、复核0e7335…4dcb8。建立本地冻结提交（包含以上工件的提交），不push；远端仍6bad978。下一步M5.0正式evaluation，后续M5空runtime重建/演示；不可把M4冻结当作最终交付验收。
