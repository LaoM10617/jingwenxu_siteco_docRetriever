# 当前交接：M3通过，用户授权提交推送

2026-09-27。M3.1–M3.5及P-031临时memory已实现，受控与授权真实组合核验完成。
首轮双轴审查：Standards一项过时文档状态已修，Spec零发现；最终收尾两轴均零未关闭发现，结果见
`tmp/m35/review-final-receipt.json`。没有新增代码审查发现。
验收说明eval/results/m3_checkpoint.md，实际成功/失败证据eval/results/m35_integration.md，
详细过程logs/m3.md。进入M4前先按用户安排梳理：必做通过情况/紧急缺口、重要必做体验优化、原case选做项优先级、
原case建议库的对应情况。本轮只提交推送，不展开该评审或生成评审材料；M5重建演示尚未完成。

## Git与审查

M3审查冻结时main/HEAD与origin/main为88ad778baf6b272ccd8151e67f6801e767dce24d。
用户随后授权将已审查的28项变更提交到main并推送origin；提交消息为
Add multi-turn dialogue memory, clarify state and fault handling, and integrate and adapt more reusable code.
当前提交标识与推送状态以git log/status和远端核对为准。实际M3审查基准仍固定88ad778。
首轮review-1冻结27项变更+需求来源；最终review-final冻结全部staged/unstaged/untracked和收尾文档。
两轴审查同一快照。manifest、原字节、完整diff、哈希和最终收据都在tmp/m35。

继承六份M2.9文档保留并纳入：README、milestone、current、logs/m2.md、m29_checkpoint、m3-handoff。
接手五份匹配M2.9旧快照，logs/m2.md不同且不是换行差异；未回退，接手备份tmp/m3-intake。
requirements_draft.md是既有忽略文件，仍只作本地需求来源，未force-add。未把密钥或材料提交。
主要源码变更为processing.py额度恢复状态、question_tasks.py/answers.py/新memory.py、
前端useChat/App/ChatThread；新增多文档/状态/业务/失败/memory后端测试和聊天/真实集成浏览器测试。
另有CONTEXT、decisions、契约、里程碑/交接/验收文档。本次提交清单以git show及最终manifest为准；提交前只补充current/m3日志中的授权和下一步记录。

## 当前能力与边界

P-026–P-030继续适用：PDF全局20/20、等权RRF k60/final8未调参；CSV精确查询且原值/重复来源保留；
Decimal和PDF保守归属门槛。被调用路由覆盖当前所选全部同类型文档，一路供应商故障整任务失败。
202+轮询，240秒含排队，单worker/8等待、1000临时任务；超时后迟到不可覆盖，重启不自动重发。
同步SDK可能占worker直到网络返回；来源身份不证明答案语义。

P-031：previous_question_id关联同会话已完成前轮，冻结请求；后端最近最多6轮、12000序列化字符，
整轮保留。历史只辅助识别主题，当前范围重新取证，旧引用不进入新证据。原文词项须完整回查，
规划/生成明确接收resolved_subjects，不按新证据排列再次解释序数。缺失/歧义澄清，模型故障仍失败。
首轮固定24h不续期，额外解析共享240秒；刷新/重启保留期内继续，过期提示。模糊POST仅人工原请求
恢复，不自动重发。会话标签不是认证，无跨会话/长期记忆。原case未明列memory，依据为用户确认。

## 最终实际验证

- Windows完整308+10subtests/60.00s，Linux新m35-test同308+10/49.05s。
- 新版静态Docker浏览器28通过/6历史opt-in跳过/26.5s，含真实代理；build及镜像/前端密钥检查通过。
- 真实初始4问：条款+价格、CSV追问日期、PDF两型号+CSV精确未命中正确；第4问解析正确但生成
  错答“第二款”。原失败tmp/m35/real-results-initial-failure.json完整保留，不能当通过。
- 明确resolved_subjects传递/约束后，仅定向重问原CSV/PDF追问，正确返回01.06.2026与4000K/9W。
  其测试夹具刷新时覆盖storage导致后半失败，修夹具后用已有结果纯GET恢复/刷新2项通过、零POST。
  未声称初始完整真实脚本全绿；共6个新真实问题，没有循环重试掩盖失败。
- PDF原页和CSV授权首记录核对完成；条款2020、原价183,20、各型号归属正确，精确未命中不冒充PDF命中。
  首问真实Voyage限流retry_after60后82.219s成功，等待/健康/轮询正常，未改额度或付费。
- 运行容器23个后端源码文件与工作区逐字节匹配；HTTP三文档ready、两个修复结果completed不变。
  diff --check通过。受控重启为生命周期测试，不冒充Docker强杀；小样本不证明通用可靠率。

## 当前运行与注意事项

Compose siteco-m28-smoke双容器healthy，最新http://127.0.0.1:18095/，backend18094，已部署本次修复。
运行数据D:/Projects/Retrieval_SITECO/tmp/m28-clean/runtime；没有复制开发索引或迁移路径。
ready ID：Rondel7758b95074074557b8bd2a4b72ef4237；CSV eeb7e731107d4759b3dd1d84f0c870ab；
新条款f1338ce4cdc44f7d82e1ce5232e590ef。任务到期不等于文档丢失。旧18091/18089/18087未动。
运行SQLite仅后端访问，检查HTTP；Docker缓存/镜像C盘、数据D盘。没有额外常驻服务，临时Vite已关闭。
仅授权D01/D06/D09外发，Voyage共享3RPM/10KTPM、至少20秒间隔，少量串行；付费切换先通知。
密钥根目录ignore、仅后端运行时注入，不输出/提交/入镜像或前端。保留题不用来调参，108页报告不在基线。
不自动加入OCR/视觉/本地生成/长期历史/SSE/取消API/认证/原文高亮。
普通shell沙箱初始化失败，使用require_escalated；Docker CLI为LOCALAPPDATA/Programs/DockerDesktop/
resources/bin/docker.exe，Python backend/.venv/Scripts/python.exe，根目录pytest包含tracing/subtests。

## 剩余风险

真实ordinal错误已修并定向复验，但模型选错主题/自由文本错归属仍可能发生；不是确定性语义验证。
PDF布局/噪声、CSV规划可靠率和供应商等待风险保留。大历史轮次可能无法纳入12k预算而澄清。
旧任务迁移只能用最早保留任务推定首轮，已清理历史不能重建。最终收尾复核和快照收据不可遗漏。
