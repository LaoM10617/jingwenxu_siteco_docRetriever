# 当前交接摘要：M2.4已验收

2026-09-26。M2.1基础运行、M2.2上传生命周期、M2.3 PDF证据与覆盖、M2.4最薄前端和双容器均完成各自范围。M2整体问答闭环尚未完成；下一步按原顺序M2.5 CSV。

## 依据与约束

P-010至P-024及实施补充，docs/m2-first-contracts.md；T-002至005已批准。用户确认保留ready证据门槛，M2.4先上传/状态，生产成功证据预览后补；本阶段接第二容器。配额等待如实展示，免费额度影响体验时由用户切换付费，不自动计费。主界面简洁chat，设置/材料/历史/错误详情放可隐藏侧栏。

FastAPI + React/TypeScript/Vite；SQLite和文件持久化，单后端进程/有界摄入线程，无数据库/Redis/任务容器。20MiB/50页/CSV20,000记录/10活跃文件；108页报告不在基线，无OCR/视觉推理/本地生成模型，保留题不调参。Voyage-4、1024维、3RPM/10KTPM查询与摄入共享预算；FAISS CPU按文档IndexFlatIP已选但未安装。

## 实现与未完成项

- 后端现有上传、ID/限额、重试/中断、HTTP状态与发布门槛保留。本轮未修改后端代码。
- PDF layout-chunks-v2/pdfplumber0.11.10，来源片段/上下文/同页bbox、稳定ID、逐页覆盖和warnings已持久化。解析成功仍failed/retrieval_not_configured；CSV仍processing_not_configured。解析完整率未保证，不把页覆盖当准确率。
- 前端真实多文件/拖放、文件夹清单确认、串行上传、列表恢复/轮询、错误/重试、覆盖/warnings、按ID选择、仅ready证据分页已接。上传失败不自动重传；同名不同ID；刷新不重新上传，选择仅当前页。文件夹拖放不承诺，目录选择依浏览器支持。
- 聊天发送禁用；历史/设置仅展示未开放说明，不收集Key。当前材料列表是工作区列表，不冒充已有会话归属。多轮上下文、持久历史、自定义Key协议仍待后续定义。
- 前端Node构建+nginx静态容器，固定digest及npm锁；同源/api代理、21MiB代理请求限制给20MiB文件留封装余量、无上游自动重试、Docker DNS重连。前端不挂运行数据/不接Key，后端仍loopback暴露供开发兼容。
- CSV、Embedding共享调度/缓存、向量BLOB/FAISS、问答和真实ready预览仍待实施。受控测试ready不能作为生产成功证据。

## 本轮实际验证

- Windows后端69测试+10subtests通过，pip check在接手核对通过；1条既有httpx弃用提示。Linux后端69+10沿用M2.3记录，本轮未重跑。
- Windows与Linux Docker前端类型检查/生产构建通过，同npm锁。Windows Node24.19.0，容器Node24.21.0/nginx1.30.5。Vite开发5173→真实后端8000 health通过。
- 9项Edge/headless浏览器测试通过：真实Rondel两次上传202/独立ID，2页17证据/1warning，failed/retrieval_not_configured，证据409，刷新无POST；受控HTTP验证ready分页/范围、等待额度、retry、失败恢复、目录确认/拖放、新上传保留选择等。另1项真实代理health/404/415/20MiB超限413通过。
- Escape关闭缺口经失败用例定位后修复，复验通过；桌面1440px和窄屏390px截图已核对，无横向溢出。截图在忽略tmp/m24-acceptance。
- 替换后端容器后，前端代理恢复、HTTP列表全部元数据与warnings一致。全程只经HTTP访问运行状态，未从Windows打开运行中SQLite。无模型调用/密钥内容读取/保留题使用。

## Git与运行服务

main，HEAD c6376569e4e2e102334b6beff380a63de49b805b；M2最终审查基准4307e22ceb08b70d6dca459137355b0551f2e6c1。开始时已有本聊天决策/交接修改；现未提交包含frontend源码/锁/测试/Dockerfile/nginx、Compose、dockerignore、env示例、README/development、阶段/决策/交接文档。用户已授权本检查点commit和push，消息为“Minimal frontend built and tests passed.”；本摘要随检查点提交，最终提交ID及推送结果以Git为准。

保留预览：Compose项目siteco-m24-acceptance，frontend http://127.0.0.1:18087，backend18086；D:/Projects/Retrieval_SITECO/tmp/m24-acceptance/runtime持久化。两容器healthy；临时Vite和开发后端已停止移除。停止方法见docs/development.md。Docker镜像/缓存仍C盘，未迁移或清理无关资料。

标准shell及浏览器控制插件遇到sandbox helper初始化失败；经审批升级的shell正常，无自动审批拒绝。浏览器验收使用项目Playwright驱动已安装Edge。密钥、原材料、运行数据/截图和node_modules/dist保持忽略，白名单构建不带入。

## 下一步

进入M2.5 CSV：复用已批准T-003解析边界，落实原始列值/记录号/字符串订单号/Decimal规则；lookup_orders等第二批公共测试接口按契约先确认。之后M2.6 PDF检索、M2.7回答引用、M2.8真实双路径闭环、M2.9 Standards/Spec审查。保持既有ready可查和完整发布，不以本阶段完成代替完整M2验收。