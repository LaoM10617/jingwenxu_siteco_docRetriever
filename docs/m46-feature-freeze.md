# M4.6 功能与决策冻结检查点

日期：2026-09-27。状态：功能冻结检查通过。双轴发现的同一P2已修复并独立复核；正式evaluation与M5交付重建仍待执行。

## 冻结对象与需求依据

阶段基准de8487dd25ce5f21127d59395e965686f0005a42，进入检查点HEAD为6bad97827fcb766e8f4aa613fb239e8cb2f34199。包括该提交后的HTTP413提示修复、测试、全部继承文档及untracked真实验收报告；不是只审HEAD。首轮审查快照a692ecabb28867c1ce3e970345ba4c7840960df8a207df1a46c30fa708536599，160个文件（包含本地只读需求来源）。临时副本tmp/m46/review-01，tracked.patch使用git diff --binary de8487d -- .；untracked完整内容和文件哈希另纳入manifest。

原case四页本轮重新提取核对，正式必做为自主前后端、界面上传、处理/索引、相关检索、基于文档聊天、Docker启动、GitHub源码历史和README/演示。原件留private，不进入交付。requirements_draft.md为本地需求映射；已确认决策P-031至P-038覆盖后续范围。原文中的任意模型自由选择不等于应用必须兼容任意服务。

## 必做功能与证据

- FR-01/02：浏览器多文件上传，单文件20MiB、实例10活动文档，PDF最多50页；queued/processing/ready/failed明确。PDF原生解析/分块/Voyage索引，价目CSV结构解析及精确订单索引。M2/M3既有真实证据，M4.5新PDF实际上传约5.473秒ready；本轮受控生命周期及平台回归通过。
- FR-03/04：按所选文档检索并生成带引用答案；PDF混合检索，CSV区分精确未命中/缺价格/重复记录，证据不足和执行失败分开。M4.1原失败、M4.2定向复验、M4.4对照均保留；M4.5两提供方在限定配置下真实问答及原页核对通过。不把引用存在等同语义正确，不宣称全题准确率。
- DR-01：React/TypeScript＋FastAPI自建；仅独立模块复用，来源和边界见docs/reuse.md，无完整聊天产品drop-in。
- DR-02/04：Compose容器和README启动/Key/技术取舍/后续方向齐备；本轮Linux测试镜像通过，当前Docker部署健康。M5仍须从最终提交和独立空runtime验证面试官路径，不能用现有容器替代。
- DR-03/05：源码历史已推送至6bad978，后续冻结版本另记录；未发送交付邮件。10分钟演示整理、最终仓库访问和M5复现留后续，不冒充本阶段已完成。

## 已确认追加能力

- P-031临时多轮：首轮起24h固定期限，最多6完整轮/12000序列化字符；历史只解析主体，每轮当前范围重新取证。刷新GET恢复、不自动重POST；新会话清空选择；重启中断未完成任务。受控测试及已有真实追问复验支持此范围，原失败保留。
- M4.2体验：恢复并重新校验ready选择、等待阶段和真实已等待时长、来源型号/价格字段与记录可核对；Session info明确临时记忆。
- P-033原文预览：本地PDF正确物理页及来源区域/标题上下文框、缩放和常见旋转/CropBox受控验证；无可靠坐标退回原页并说明。CSV定位逻辑记录，展示原始字段；不承诺逐词/逐字段语义归因。真实PDF点击已核对。
- P-036重排：Voyage rerank-2.5-lite，同候选排序，默认关闭、Settings可切换。5秒且受问题剩余预算约束、单在途、零重试，错误/忙/冷却/非法结果回退RRF并可见。8题开发对照及单题生成配对非正式benchmark，完整覆盖7/8未提高。
- P-037/038 Settings：Gemini/Groq模型与Key、Voyage同模型Key、Top K与重排、逐轮候选/选取/入上下文/遗漏计数；Key仅后端内存覆盖，刷新保留、重启恢复环境默认；清除不回退Key，恢复默认独立。问题/上传接受时冻结配置，换Key不绕过共享准入。拒绝任意base URL、Embedding模型/维度切换及索引重建。
- P-032正式数字evaluation已选，但按顺序M5.0执行；不属于本轮已完成项。多模型公平比较有条件，M4.5不同Top K/缓存下耗时不能充当比较结果。

## 实际模型、参数和依赖

推理默认Gemini gemini-3.5-flash-lite，另支持Groq openai/gpt-oss-120b；模型字段可编辑不保证任意模型可用，必须支持适配器的结构化模式。M4.5 Gemini Top K8完成；当前Groq账户Top K8请求9097 tokens超过8000TPM而HTTP413，Top K1复验成功。保留失败和明确处理提示，不升级付费、不静默裁剪。

Embedding固定Voyage voyage-4/1024维/float，持久化L2向量/FAISS IndexFlatIP；固定公开tokenizer校验后使用。PDF词法/向量各20候选，等权RRF k60，Top K默认8可设1–20，上下文证据预算28000字符。来源几何和上下文也占预算，选中不保证全部进入生成。

Embedding准入仓库默认3RPM/10000TPM/20秒，本机60RPM/200000TPM/1秒；重排成功间隔仓库20秒/本机1秒，异常冷却保留。Embedding错误可最多3次尝试（原网关行为），生成/重排不自动重试。问题总预算240秒含排队、单次生成至多60秒；Settings简单探测至多20秒、实例单在途。

主要直接依赖：Python3.12、FastAPI0.141.1、Pydantic2.13.5、pdfplumber0.11.10、FAISS1.15.1、Voyage SDK0.5.0、google-genai2.25.0、Groq SDK1.7.0；React19.3.0、TypeScript7.0.2、Vite8.3.1、Playwright1.63.0。全部传递版本以backend/requirements.lock.txt和frontend/package-lock.json为准；Docker基镜像摘要已固定。本轮无新增核心依赖。

## 支持边界与剩余工作

单用户本地实例，无身份认证或安全多租户。PDF原生文字优先，无OCR/视觉模型，不保证复杂跨页布局/原子长段完整提取；CSV是已确认价目字段格式，不是任意CSV分析。无文档更新/删除、永久会话、任意模型端点或Embedding替换。没有预存答案冒充实时、无自动付费切换。

结构化schema/引用校验不证明所有事实正确；小Top K可能丢失条件，多轮模型仍可能错误归属。真实运行依赖面试官的Key、模型权限、额度和网络；README给出已验证路径与明确错误反馈。没有通用延迟/P95/准确率承诺。

下一顺序：本检查点解决审查阻断并冻结→M5.0固定题集/标准/授权后正式数字evaluation→M5从冻结代码空runtime重建和演示。冻结后仅记录明确阻断修复，保留旧结果、重新冻结并复验受影响范围。

## 本轮验证与审查

Windows：python -m pytest -q，349 passed、10 subtests passed，73.13秒。Docker test target：相同349＋10，64.38秒。前端npm run build（tsc＋Vite）通过；Playwright针对18095实际代理，35 passed、11 opt-in skipped，33.9秒。跳过真实模型/上传类测试避免消耗已用尽外发授权；本轮未调用供应商。源码构建和受控回归不是M5空runtime验收。

修复后最终全量：Windows 351 passed＋10 subtests passed（71.56秒）；Docker/Linux同样351＋10（61.16秒）。前端源码未变，沿用本轮构建和35通过/11跳过结果。部署runtime_settings.py SHA256=6cd9df94181dac80caf9be8d21f03c4237c4d45b7253ca2aaad37b4ed492646e，与已审源码一致；四份文档ready，Gemini/Top K8/重排关闭，Groq内存Key重新通过UI恢复，仅应用配置、无模型请求。

两轴首轮各1项P2，指向同一问题：Settings探测在本地冷却超过20秒时误报timeout，实际零外发，违反local_rate_limited契约。修复以线程安全事件区分准入等待/请求已开始，保留后台退出前的在途锁；未增接口或改变20秒生产预算。两项HTTP回归先红后绿。第二轮固定快照0e7335bcad31ece0f6abd069fd240069fa29e3d455e897e8f65f6a615784dcb8，两轴均判已关闭/无新阻断，并各自独立跑通2项对应测试。

完整双轴收据见eval/results/m46_review.md。运行源码/依赖/测试文件哈希见eval/results/m46_source_manifest.json；后续文档收尾仅记录真实结果，不再改动已审代码。冻结版本是包含本检查点、收据和清单的本地Git提交（可用git log -- docs/m46-feature-freeze.md定位），本轮不推送。首轮和复核完整工作区副本及manifest留tmp/m46；私有需求PDF和Key未纳入提交。

出口：当前已确认功能无未处理审查阻断项；已有真实路径和受控验证边界清楚，原失败未覆盖。此为M4功能冻结，不是最终对外提交冻结。M5.0评估可以揭示新阻断；仅在记录问题/修复/新版本并重跑受影响验证后重新冻结。
