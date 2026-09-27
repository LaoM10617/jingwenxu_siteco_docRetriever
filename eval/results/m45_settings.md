# M4.5 Settings 与本机限流验证


## 2026-09-27 M4.5 实施检查点

用户确认仅调整本机限流及Settings，不扩展Embedding服务、不重建索引。按P-037实现读取/应用/测试/清除接口、Gemini/Groq模型与内存Key、Voyage同模型Key、Top K 1–20及重排开关。任务与上传在接受时冻结配置；配置变更不重置共享准入。前端测试已应用配置，草稿先应用；测试不会随加载/刷新自动运行。

本机启动参数已调整为60 RPM、200000 TPM、Embedding最少1秒间隔、重排成功后1秒间隔；仓库默认保持3 RPM/10000 TPM/20秒，错误冷却保留。账户截图不是当前Key/项目额度实测。Settings展示运行值，不承诺供应商延迟。

验证：Windows后端337 passed（73.57秒）；TypeScript及Vite构建通过；Docker重建后浏览器34 passed、12 opt-in skipped（32.6秒）。真实本地GET及同值PATCH验证代理、no-store和运行参数，原三份文档仍ready。受控测试覆盖凭据脱敏/清除/恢复、修订冲突、任务及上传冻结、重启、Top K诊断和浏览器操作。真实供应商连接/问答未复验；不能报告双模型验收或正式benchmark完成。探测错误无法可靠分类时返回provider_error。

开发测试曾因mock路径错误，让合成假Key/合成输入进入真实SDK并失败；没有使用项目真实Key或文档，不计成功验证。已修正mock并为Settings测试禁止非回环socket连接，保留此失败记录。

部署siteco-m28-smoke：http://127.0.0.1:18095（后端18094），沿用tmp/m28-clean/runtime；默认Top K 8、重排关闭。未commit/push，保留此前所有未提交工作。下一步获授权后做有限真实提供方验收，再M4.6冻结、M5.0正式evaluation、M5；不自动消费旧已耗尽授权。
