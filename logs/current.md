# 当前交接：M4.6功能冻结通过，下一步M5.0

2026-09-27。先读AGENTS.md、本文、docs/m46-feature-freeze.md。P-039冻结纪律，P-031–038确认功能范围；原case与需求核对详见冻结文档。正式evaluation/M5尚未完成。

版本：本轮本地冻结提交为包含docs/m46-feature-freeze.md及eval/results/m46_source_manifest.json的提交（git log -1可定位）。父提交与远端main仍6bad97827fcb766e8f4aa613fb239e8cb2f34199；本轮不push。原M4.5未提交HTTP413提示修复/2项测试/真实验收记录纳入本次冻结，凭据及private材料不纳入。后续接手仍需实际git status核对。

审查基准de8487dd25ce5f21127d59395e965686f0005a42，首固定快照a692ecabb28867c1ce3e970345ba4c7840960df8a207df1a46c30fa708536599，二次复核0e7335bcad31ece0f6abd069fd240069fa29e3d455e897e8f65f6a615784dcb8，全部未提交/untracked及继承文件纳入。Standards/Spec各自确认同一P2已关闭，无未解决阻断，收据eval/results/m46_review.md。临时完整副本tmp/m46。

本轮修复：Settings Embedding探测本地准入等待超过20秒须报local_rate_limited，已发送超时报timeout；保留后台结束前的单在途锁。2项受控HTTP回归先红后绿，生产预算20秒不变。README/环境模板的只读Setup/无Key控制旧说明已更正。

最终验证：Windows全量351 passed＋10 subtests passed（71.56秒），Docker/Linux同351＋10（61.16秒）；前端tsc/Vite通过，浏览器35通过/11外发opt-in跳过（33.9秒）。未新增模型调用、未跑正式benchmark。此前M4.5真实Gemini Top K8＋Voyage/Groq Top K1＋Voyage的PDF问答和第6页高亮通过；原Groq Top K8 HTTP413（8000TPM/请求9097）保留。所有既有外发授权已用完，不重跑脚本。

运行：Compose siteco-m28-smoke已部署冻结代码，前端http://127.0.0.1:18095，后端18094，runtime tmp/m28-clean/runtime，4份ready保留（D01/D06/D09＋fb62333d98e944dfbab887353e5f8cd1守则）。Gemini/Top K8/重排关闭；Groq内存override重新经Settings恢复。重启后Groq为missing需重填，Gemini/Voyage沿启动环境。runtime_settings.py部署哈希6cd9df94181dac80caf9be8d21f03c4237c4d45b7253ca2aaad37b4ed492646e。本机限流60RPM/200000TPM/1秒，重排成功间隔1秒；仓库默认仍3/10000/20秒。

禁止输出或提交.env、grok.txt、Gemini_API_KEY.txt、voyage.txt（均ignored）。运行SQLite仅所属后端访问，不从Windows直接读写。Docker启动脚本tmp/m35/start.ps1；Python backend/.venv/Scripts/python.exe；Node D:/nodejs/node.exe；普通shell沙箱失败时require_escalated。

下一步M5.0：先固定题集/证据标准/指标分母和配置，再一次确认新的真实外发范围；不以开发题冒充保留题，不引入LLM裁判唯一真值。之后M5从明确提交和独立空runtime按README构建/上传/追问/来源核对，整理演示与交付。功能冻结后仅记录明确阻断修复，保留旧结果、重新冻结并重跑受影响验证。不要继续加候选功能。
