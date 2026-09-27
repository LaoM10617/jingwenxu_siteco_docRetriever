# M3 实施交接

以下为M2.9时的历史交接快照；当前状态以logs/current.md和eval/results/m3_checkpoint.md为准。

2026-09-27。M2 已按最小闭环范围验收；代码检查点 `88ad778baf6b272ccd8151e67f6801e767dce24d` 已推送。M2.9 README 修复与验收/交接文档尚未提交；具体范围见 [M2.9](../eval/results/m29_checkpoint.md)。M3 未开始实施。

## 继承的已确认契约

先读 logs/current.md、P-026–P-029 和 docs/m28-chat-contract.md。问题提交完整范围先验证再冻结，每轮独立，跨 conversation 历史不送检索/指代。旧 ready 持续可查询；回答有来源不等于语义正确。CSV 精确未命中不模糊代替，重复来源保留；PDF 数值计算保持已确认的保守归属门槛。

保持 FastAPI+React/TypeScript、两个常驻容器、后端独占 SQLite。Voyage-4/1024、共享3RPM/10KTPM，真实调用少量串行，付费切换先通知；不调整检索参数或使用保留题调参。密钥仅后端运行时注入，D盘runtime、C盘Docker缓存不迁移。

## 建议执行顺序（交接建议，不新增决策）

1. 先把已确认契约映射到 M3 场景清单，标注已有测试、缺口和实际观测方式；新的接口、状态或测试边界统一讨论后实施。
2. 验证多文档选择与冻结：两份PDF、两份CSV、混合范围、重复上传；未选文档不参与，处理中/未知文档拒绝完整请求，后续切换选择不改变已提交问题。检查不同 conversation 不串结果。
3. 验证状态并发：上传/Embedding等待期间旧ready可问，健康/上传/轮询仍响应；队列满、刷新、模糊POST同ID恢复、超时晚到、重启中断。优先复用已确认替身边界，无需对每种错误消耗真实API。
4. 验证答案和来源：缺证据、部分答案、相邻产品归属、精确未命中、重复记录、分页总数和限定条件；无效引用不能成为有效结论。按解析/检索/规划/工具/生成/引用/交互分层记录失败并修复。
5. 汇总矩阵和实际剩余缺口，再按 AGENTS.md 固定 M3 基准/目标及未提交范围做 Standards/Spec 双轴审查。M3 开始时重新记录实际基准；不得把本建议直接当作所有场景已经通过。

不自动加入多轮指代、持久会话、SSE、取消API、认证、重排、OCR或高亮。相关新增范围仍需确认。

## 运行与复现导航

当前预览 http://127.0.0.1:18095/，后端18094，Compose `siteco-m28-smoke`，数据 `tmp/m28-clean/runtime`。PDF `7758b95074074557b8bd2a4b72ef4237`、CSV `eeb7e731107d4759b3dd1d84f0c870ab` 均ready；临时问题只保留24h。更早预览不是当前代码，勿据旧端口结果判断新版本。

后端回归：`backend/.venv/Scripts/python.exe -m pytest -q`；Linux测试使用 backend/Dockerfile 的 test target。前端静态代理检查以18095为目标（M24_BASE_URL、M24_REAL_PROXY），真实两路 smoke 位于 frontend/tests/chat-smoke.spec.mjs，必须按 README 新建独立空runtime，不能复制当前索引。M3若需要更多真实材料/外发，遵守已有授权范围，未授权材料先确认。

已有失败与风险：CSV模型曾两次空计划误判，通用提示修正只经少量复验；PDF布局/跨页信息可能缺失；引用身份校验不证明答案语义；单worker可能被超时网络调用暂时占用；conversation ID只是demo隔离而非认证。证据与具体耗时见 eval/results/m26_hybrid.md、m27_answers.md、m28_chat.md。


## M3/P-031后续变更（2026-09-27）

上文是M2.9交接时的范围，并非当前memory状态。用户随后确认同会话历史指代必做，
已实施previous_question_id、6轮/12000字符、首轮固定24h，跨范围仅识别话题，当前范围重新取证。
实现/验证和限制见docs/m3-memory-contract.md、logs/current.md与logs/m3.md。
M3.1–M3.4及memory受控检查通过；真实多轮组合验证、最终同固定范围双轴审查仍待M3.5。
