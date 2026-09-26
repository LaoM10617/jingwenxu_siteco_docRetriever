# 当前交接：M2.8聊天与空状态Docker冒烟完成，待M2.9最终审查

2026-09-27。M2.1–M2.8已按各自范围实施/验证。用户明确把两路真实浏览器闭环前移至M2.8。
M2.9固定范围Standards/Spec审查与修复仍待做；M2尚未最终验收。M3多文档/状态/失败矩阵独立。

## 已确认范围与实际实现

P-026：PDF FTS5/BM25+Voyage-4/1024+每文档FAISS+RRF；两路全局20、等权k60/final8，未调参。
P-027/P-028：结构化条件→范围/schema→确定性工具→证据回答与引用，禁任意SQL/Python。
Decimal保留原值/单位/条件；PDF计算仍仅独立显式单span、无额外context的安全子集，表格参数
可以带来源列举，但不自动扩大数值归属计算。引用身份验证不是全部语义正确性的证明。

新P-029和docs/m28-chat-contract.md：POST /api/questions立即202；GET任务状态；任务绑定
CSV分页。完整范围先验证，conversation/request_id幂等，异内容409；每轮范围冻结、独立求解。
不发跨conversation历史，不做多轮指代、持久聊天、SSE、前端自带Key或原文高亮。
QuestionTasks在现有后端/SQLite：单worker、8等待、1000临时任务、24h保留；240秒总截止含排队，
独立monitor/读取/发布控制终态。重启未完成任务interrupted，不自动重发；超时不能被迟到覆盖。
同步SDK仍协作取消，超时worker可占用执行位直到网络返回。每次生成min(60s,剩余时间)，不重试。

useChat/ChatThread接原布局：消息、scope快照、真实阶段、分片来源/上下文、警告/省略/CSV分页。
浏览器当前tab最多50轮临时元数据，刷新只GET；不明POST由用户同ID/内容重发，新会话清空范围。
conversation标签是本地demo隔离，不是认证。API/任务记录与完整返回字段见契约。

app.prepare_tokenizer可在普通backend镜像一次性下载校验固定公开tokenizer；宿主helper委托
同一实现。README写明无宿主Python/Node的Docker流程。双常驻容器和nginx复用，无额外服务。
密钥仅backend运行时env，白名单构建context不含根Key/材料/runtime；provider日志仅阶段/
状态/耗时/usage，不记录问题或原文。Embedding等待放行后恢复retrieving阶段。

## 实际验证与保留失败

Windows261tests+10subtests(44.31s)，Linux Docker261+10(36.79s)，镜像siteco-backend:m28-test。
TypeScript/Vite和两runtime镜像构建通过。最终静态Docker前端13浏览器检查通过、5旧真实
opt-in跳过；独立新两路真实smoke1项通过(31.7s)。git diff --check通过。
真实任务/SQLite/HTTP、外部模型与时钟替身覆盖去重/越界/截止/队列/重启/分页/响应性；浏览器
覆盖等待、引用、刷新、同请求重发、部分结果、警告和重复来源。不是M3完整失败矩阵。

首轮空tmp/m28-docker/runtime中PDF成功、CSV空计划误判需澄清，smoke正确失败；保留记录。
单次probe支持提示语歧义：已补通用JSON计划/未知订单存在性由精确查询判断的说明，无样本
硬编码、无改检索参数。不能据少量结果承诺模型规划稳定。随后另建空runtime重做两路成功：
- PDF ready2.344s/问答20.693s，0MD5307L1830=3000K/18W/1.6kg，第2页引用，布局警告保留。
- CSV ready2.453s/问答3.177s，51DB11EC11B1D=183,20/01.06.2026，逻辑记录1，浏览分页通过。
两路均从浏览器新上传/现场建索引/真实模型回答，引用展开与刷新通过，截图已核对原文。
没有读取保留题或复制开发索引/答案集，使用用户已授权原材料/Gemini+Voyage。
两轮加probe共Voyage4calls/2032tokens、Gemini6calls；无provider失败/重试，首轮CSV为质量失败。
最终PDF等待观察约16.8秒（1.5秒轮询），成功SDK调用<2秒，主耗时为20秒共享调用间隔。
详见eval/results/m28_chat.md，原报告和截图在tmp/m28-docker与tmp/m28-clean（忽略）。
本地核对真实Key未出现在image配置/history或前端静态产物，frontend环境无provider Key。

## Git与运行

main/origin/main仍29b308978783d3f214174900eb1ed84f1919b4cf，Implemented model answer，前轮已push。
本轮M2.8未commit/push。改动含任务模块/HTTP/阶段、规划提示、provider日志、前端聊天/来源、
Docker内tokenizer入口、README/dockerignore、后端及浏览器测试、P-029/契约/验收/日志。
M2.8基准29b3089；M2最终审查基准4307e22，必须固定目标且纳入staged/unstaged/untracked，
按AGENTS/code-review双轴并行子代理。当前未进行该阶段审查，不声称M2最终完成。

最新预览 http://127.0.0.1:18095/，backend18094，Compose siteco-m28-smoke，两个healthy。
数据D:/Projects/Retrieval_SITECO/tmp/m28-clean/runtime。PDF7758b95074074557b8bd2a4b72ef4237，
CSV eeb7e731107d4759b3dd1d84f0c870ab，均ready。task保留24h，过期后来源文档仍在。
首轮siteco-m28-acceptance(18093/18092)已停止，tmp/m28-docker/runtime保留失败取证。
旧siteco-m26-acceptance(18091/18090)未改；不访问运行中SQLite，检查走HTTP。
Docker镜像/缓存C盘，runtime D盘；不迁移。Key根目录忽略，不输出/提交/入镜像。
Voyage共享3RPM/10KTPM、至少20秒间隔、query优先；真实调用少量串行，切付费前先通知用户。
20MiB/PDF50页/CSV20000条/10活跃文档；无OCR/视觉推理/本地模型，108页报告不在基线。

默认shell沙箱初始化失败，命令使用require_escalated。本轮真实验收授权沿用用户明确确认，
无需再询问同范围外发。Python backend/.venv/Scripts/python.exe；Docker CLI在
LOCALAPPDATA/Programs/DockerDesktop/resources/bin。临时启动/密钥检查脚本位于tmp，均不含密钥值。

## 下一步

M2.9：按固定基准4307e22和明确全工作区范围做Standards/Spec双轴审查、修复、必要回归，
再确定M2最终验收。两路smoke不能替代M3多文档/处理状态/来源及失败矩阵，不新增候选范围。
