# 当前交接：M4.3完成，下一步M4.4

2026-09-27。先读AGENTS.md、本文、docs/m4-handoff.md；详细执行顺序见milestones_and_execution_plan.md第6节。需求来源requirements_draft.md（既有ignored，不force-add），已确认决策P-026–P-033；过程见logs/m3.md及logs/m4.md。

## 当前结果与证据

M4.1完成8轮开发+1缓存验证，真实M41-06错误把“第二款”当CSV键；原失败保留在eval/results/m41_development.md/json及tmp/m41-live-20260927。M4.2修复链式主题身份、刷新范围、等待和来源可读性；2次授权复验通过，见eval/results/m42_experience.md。不是通用可靠率。

M4.3已按用户确认的P-033实现GET /api/documents/{document_id}/evidence/{evidence_id}/preview。PDF原页在本地渲染，证据/上下文区域分别标示，支持缩放；CSV回查逻辑记录和全部原字段，不声称逐字段语义归属。未知/非ready/旧证据/原件缺失或变化明确报错，文本来源保留；无可靠坐标显示原页和限制、不画猜测框。每次展开重新GET；已打开预览不持续轮询。契约docs/m43-preview-contract.md，验收eval/results/m43_preview.md。

实际本轮验证：Windows相关后端54 passed（12.42s）；最后preview子集17 passed（4.85s）；Linux离线preview17 passed（5.44s）。TS/Vite及Docker构建通过。Docker完整浏览器32 passed/12 opt-in skipped（30.2s），最终重新展开失效回查修复后preview3 passed（2.2s）。未重跑完整后端；历史308测试不能当作本轮证据。

真实GET-only回放：D01页1（4证据区域+1上下文）、D06页2（5+2）、D09逻辑记录1；桌面和390px截图已目视核对，缩放同步，零写请求/页面错误，最终构建重放通过。tmp/m43存原始响应/截图/脚本/最终哈希。24份运行后端源码与工作区匹配，3文档ready，部署后供应商事件0。开发时旋转裁剪错位和重开缓存失效均已复现、修复、回归，日志保留。

## Git与运行

本次提交前main/HEAD及本地origin/main为de8487dd25ce5f21127d59395e965686f0005a42；M4审查基准仍为该提交。用户已授权commit及push，消息为“Fixed bugs related to history, context references, and refreshing; added source highlighting.”；当前提交与远端结果接手时以git log/status核对。M3历史审查基准88ad778不覆盖本轮改动。继承交接/README、M4.1/4.2代码和证据全部保留并纳入本次提交。新增previews.py、test_source_preview.py、SourcePreview.tsx、m43-preview.spec.mjs、预览契约/报告；修改documents/uploads/ChatThread/style及阶段文档。完整清单接手以git status为准。

Compose siteco-m28-smoke双容器已部署M4.3，前端http://127.0.0.1:18095/，后端18094。数据tmp/m28-clean/runtime；运行SQLite只通过所属后端访问。无新增常驻服务，旧临时Vite18096已关闭；旧18091/18089/18087未动。Docker镜像/缓存C盘、runtime D盘。

ready IDs：D01 f1338ce4cdc44f7d82e1ce5232e590ef；D06 7758b95074074557b8bd2a4b72ef4237；D09 eeb7e731107d4759b3dd1d84f0c870ab。

普通shell沙箱初始化曾失败，使用require_escalated。Docker CLI为LOCALAPPDATA/Programs/DockerDesktop/resources/bin/docker.exe；Python backend/.venv/Scripts/python.exe；Node D:/nodejs/node.exe。已有tmp/m35/start.ps1按原runtime重建并安全注入后端Key，不输出密钥。密钥不得提交、入镜像/前端或日志。

## 后续与限制

下一步M4.4：依据M4.1失败层次和现有证据决定采用/不采用重排。不得把指代或生成错误当排序错误，无依据不引入reranker。其后M4.5提供方配置须集中确认接口、凭据留存/清除/任务配置冻结及测试边界，再实施；随后M4.6冻结、M5.0正式量化评估、M5重建演示。

本轮无模型调用/新上传/新Key。M4.1 8+1和M4.2 2次授权均已用完；额外真实问题或新材料/供应商外发须扩展授权，不改付费。Voyage共享3RPM/10KTPM、至少20秒间隔；保留题不调参。

高亮只证明区域定位，不证明回答正确；最高144dpi且长边1600px，放大不增加清晰度。PDF布局/自由文本产品归属风险、保守澄清限制仍在；不承诺OCR/逐字语义高亮。CSV为已支持价表schema和记录级引用。单用户本地无认证，不扩成任意路径或公共文件服务。P-031仍为6整轮/12000字符、首轮24h固定、不自动重POST；原任务范围不变。

正式benchmark、提供方配置、功能冻结和M5从提交源码重建均尚未完成。冻结前按AGENTS执行同一固定范围Standards/Spec双轴审查，覆盖未提交文件。
