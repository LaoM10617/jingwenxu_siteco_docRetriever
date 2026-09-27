# 当前交接：M4.5 Settings实施与受控验证完成

2026-09-27。先读AGENTS.md、本文、docs/m4-handoff.md。当前决策P-037/P-038，契约docs/m45-settings-contract.md，证据eval/results/m45_settings.md；过程logs/m4.md。用户确认只调整本机限制和Settings，不扩展Embedding服务、不重建索引。

本机60 RPM/200000 TPM/Embedding间隔1秒/重排成功间隔1秒，仓库保守默认及错误冷却保留。Settings支持Gemini/Groq模型与Key、Voyage同模型Key、Top K 1–20、重排开关与诊断。内存覆盖刷新保留，后端重启恢复环境默认；清除与恢复分开，接受时冻结问题/上传配置。默认Top K 8、重排关闭。

验证：后端337通过，TypeScript/Vite构建通过，Docker浏览器34通过/12可选跳过。同源代理应用成功，原三份文档仍ready。无真实Key供应商复验；开发中假Key合成测试mock失效曾进入SDK失败，已修正并加非回环网络防护，详见证据。不得冒充双模型验收或正式benchmark。

Git main/HEAD及本地origin/main为2f3ad2de62d0be220d231cd7d800a02e4c1b0353；未fetch/commit/push。保留M4.4及本轮源码、测试、文档全部未提交改动（含untracked）。阶段审查基准de8487dd25ce5f21127d59395e965686f0005a42，冻结前审查必须包括未提交文件。

运行：Compose siteco-m28-smoke已重建部署，前端http://127.0.0.1:18095，后端18094，沿用tmp/m28-clean/runtime。SQLite仅经所属后端访问。原三份文档D01/D06/D09保留。本地.env仅调整四个非秘密参数，仍ignored。不得输出Key。Docker启动脚本tmp/m35/start.ps1；Python backend/.venv/Scripts/python.exe；Node D:/nodejs/node.exe。普通shell沙箱初始化失败时使用require_escalated。

下一步：M4.5.4真实提供方连接/问答复验须确定调用范围并获授权；此前M4.1/M4.2/M4.4额度全部耗尽，不重跑外发脚本。然后M4.6功能冻结、M5.0正式量化evaluation、M5重建演示。区域高亮不证明语义正确，小样本重排收益不外推准确率；保留题不调参。详细历史与原失败保留在logs/m4.md和eval/results。
