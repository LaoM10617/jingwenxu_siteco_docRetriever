# 阶段 F：长会话与跨子图协作

日期：2026-10-12。状态：阶段 F 既定范围代码已实现、测试已通过、真实恢复链路已验证、双轴审查完成。无 commit/push；旧容器未部署新代码。失败与修复过程保留如下，不能把最终续跑写成一次无失败的新运行。

## 接手事实

- 已读取本地 Git 忽略的 AGENTS.md、decisions-design.md、plan.md、stage-d-log.md、stage-e-log.md。
- main / `816211b81886e0fd17263c7da25b2bc5bfb7981b`，本地 origin/main 同值，初始工作区干净；用户确认已推送。本轮未 fetch。
- 旧日志中的 e389512、D/E 未提交是历史状态，不能作为当前状态。计划页首已修正。
- Python 3.12.10；旧 `document-chat-backend-1`（image 4b31263d4424）及 `document-chat-frontend-1` healthy，未重建。
- 沙箱读取 Docker pipe 被拒绝，宿主只读查询成功。Windows faiss DLL 在沙箱偶发 0xc0000008；宿主基线命令正常，未修改依赖来掩盖环境问题。

## 执行安排

1. 持久交互摘要、近期消息、来源/产物适用性；复用意图模型调用，不增加固定摘要调用。
2. 有证据产品标识的 PDF→CSV 顺序任务、不同用途来源、后续筛选/改图及更新价格。
3. 停止、澄清、显式恢复、部分结果及发布幂等；同一轮六次上限，审计保留累计调用。
4. 相关及全量回归，小规模真实 Gemini/Voyage/宿主 worker/pandas 验证，独立 Standards/Spec 审查。

## 已有测试证据

- 接手基线：`.venv/Scripts/python.exe -m pytest -q backend/tests/test_conversation_runs.py backend/tests/test_csv_runs.py backend/tests/test_pdf_runs.py --basetemp data/stage-f/baseline-host`：20 passed；7 条既有临时子图 durability 提示。
- 接手基线仅验证既有能力；F 最终全量结果见下文。

## 真实验证计划与数据边界

- 使用原始 Rondel PDF；已渲染核对第 2 页，3000 K、ON/OFF 两行编号为 `0MD5307L1830`、`0MD5307L0930`。原件不修改。
- C/D 价格 CSV 为明确标注的人工验证数据，不是实际 SITECO 报价；用于独立断言编号、数值与用途切换。
- 独立目录 `data/stage-f/`、临时后端及宿主 worker，沿用固定 pandas 镜像；不迁移旧运行数据，不挂 Docker socket，不进行批量评估。
- 探针为 `scripts/probe_stage_f.py`。最终真实续跑已通过，具体范围与早期失败见下文。

## 代码已实现

- `conversation_context.py`：同一次意图调用压缩交互；六条近期用户消息、有限旧消息批次和摘要水位。澄清答复以稳定消息身份持久化。摘要与业务发布同事务，迟到旧摘要不覆盖新状态；错误出处、全空摘要不推进水位，以独立开发事件记录延期。
- 主图与协议：依赖 PDF→CSV 顺序执行，带证据的精确产品标识；PDF/CSV 独立用途快照及完整依赖发布；已有 PDF 选品通过精确历史结果身份跨轮复用。同轮澄清改变条件默认重新取证，明确保留选品才复用上游。
- CSV：完整原值表精确匹配产品键；重复键默认澄清，明确 `all_matches` 保留重复行。后续结果表筛选/改图继承 PDF 依赖；不同用途、版本、过滤及删除后拒绝复用。
- 停止/恢复/部分结果：成功任务与证据回执保留；下游失败或澄清可显示 `partial_answer`，不伪装最终完成。CSV 复核额度不足且已有有效表时完成为 partial；未完成复核的局限随后续复用传递。
- 预算仍为每交互轮六次实际 provider 调用。CSV 局部四次以使用 PDF 剩余额度，主图硬限不变；新澄清回复只一次刷新预算，幂等重放不额外授予，普通停止/恢复不刷新。累计调用审计保留。
- 普通确认/规则回复不覆盖讨论对象。前端仅补未完成任务的部分结果展示与明确继续入口，未进行视觉重构。

## 测试已通过（最终代码）

- Windows：`.venv/Scripts/python.exe -m pytest -q --basetemp data/stage-f/final-windows-2` → **554 passed、15 skipped、10 subtests passed**，103.56 秒。
- Linux：`docker build --target test -t siteco-phase-f-tests -f backend/Dockerfile .` → **554 passed、15 skipped、10 subtests passed**，94.55 秒。测试镜像 manifest `sha256:367731eb4965be09d032fc8564f5d65b08bab51257c7063c4be23e06b59e156c`，manifest list `sha256:8d6e30d2c4473b2ee52eae15be4dab4b65801235051b9244a7d0a1b24e48a1ae`。
- 两端各 85 条既有 LangGraph 临时子图无 checkpoint 的 durability 提示；主图仍持久 checkpoint。15 项 opt-in Docker 隔离测试此次未单独重跑，D 的真实隔离证据保留；F 未更改 worker/执行器，实际 pandas 计算在下列探针运行。
- 前端 `npm run build` 通过；`M24_BASE_URL=http://127.0.0.1:18188 npx playwright test tests/graph-chat.spec.mjs tests/settings.spec.mjs` → **10 passed**。浏览器为模拟后端 UI 验证，不能与真实 HTTP/provider 链路混称。
- 首次浏览器访问沙箱 Vite 服务失败（连接超时）；宿主临时 Vite 18188 后全部通过，服务已停止。`git diff --check` 通过，仅 CRLF 提示。
- 针对审查问题均先复现再修复：过时摘要、错误/空摘要、依赖用途复用、澄清改变选品、重复键保留、全轮六次硬限、未完成 review 的 partial 传播、普通确认保持 focus。

## 真实环境已验证

最终回执：`data/stage-f/20261012T190430617383Z/receipt.json`，**passed**。其来源为第三次真实会话的独立 SQLite/checkpoint/原件副本，session `65f6c928f5fb4fd09f8e71992f0b6d77`；显式继续已成功步骤，不重复调用模型。这是跨修复恢复链路验收，不是最终版本从空目录一次运行通过。

- 真实 Gemini `gemini-3.5-flash-lite`、Voyage `voyage-4`；真实 HTTP → 主图 → PDF/CSV 图 → 宿主主动领取 → 固定隔离 pandas。无 mock 模型/执行器。Groq、rerank 本阶段未实测。
- 原 Rondel PDF 第 2 页：3000 K、ON/OFF 对应 `0MD5307L1830` 和 `0MD5307L0930`，与原页表格及实际引用逐项核对，前导零保留。原件 SHA-256 `78a20a04658b46ad947eccce4d96e08f757f348e721b0d8159e5f9f1b7bff561` 前后不变；页面渲染留在 `data/stage-f/rondel-page2.png`。
- 测试 C 的两行价格 150.00 / 250.00 正确；继续筛选 `<200` 仅留第一行；改为柱状图时没有新增执行任务。
- 上传测试 D 后明确切换报价用途，更新得到 175.00 / 225.00，新表依赖含 PDF+D、排除 C；PDF task diagnostics 的 `reused_pdf_from` 指向原比较回答，更新轮无新 PDF 模型调用，仅 intent/CSV 共三次。
- 等待/停止的澄清在重启后保留，显式回复后对更新后的完整两行表排序；超过旧六轮窗口，持久非空摘要后，最后正确回答初始项目代号“蓝桥”。原始用户偏好、选品原文及用途指令保持在有用户消息身份的摘要中。
- 单轮实际调用没有超过六次。第一轮依赖任务五次；滤表/改图各两次；用途切换一次；更新三次。澄清回复作为新交互轮，累计审计没有清零。
- 整个 F 调试与验证累计 **35 次新 Gemini 调用尝试**。按每个独立数据库相对复制来源的 `sum(model_calls)` 差值统计，不把复制的旧记录再计费；35=6+5+15+1+2+0+3+3。仅第一次创建 PDF 索引，后续复用只读 backup 和原件副本；没有重新 embedding 同一 PDF。

调用计数依据：各目录 `runtime/app.sqlite3` 的 `SELECT SUM(model_calls) FROM conversation_runs` 依次为 6、11、21、22、24、24、27、27。第二、第三个目录均复制首个目录（基数 6）；其余复制来源见 receipt 的 `continued_from`。因此增量为 6、5、15、1、2、0、3、3。回执 `(run_id, call)` 去重仅 33 条，未完整捕获失败调用，不能据回执单独推算 35；数据库计数为调用前记账，不代表供应商账单。

历史 dependent/update 回答仍为 partial，保留早期 PDF 子任务误报“CSV 缺席”的缺口提示；表中数字及来源已核对，但修正该提示的最终版本未重新执行这两个模型步骤。最终成功续跑不抹去这一限制。

### 失败与修复的真实证据

| 目录（均在 data/stage-f） | 新调用数 | 结果与原因 |
| --- | ---: | --- |
| 20261012T184901301303Z | 6 | PDF→价格正确；纯 CSV 筛选误填 PDF reuse 字段，被协议拒绝；明确字段适用提示。 |
| 20261012T185115128905Z | 5 | CSV plan 漏 import，经修复后原局部二次额度无法复核；修改额度分配，保持全轮六次硬限及明确 partial。 |
| 20261012T185528255282Z | 15 | 到新版报价更新均正确；非法摘要消息出处导致普通确认发布失败；加入允许 ID schema 与可诊断的延后压缩。 |
| 20261012T185810540981Z | 1 | 显式恢复确认成功；模型把“先问并等待”写成已完成直接回答；修正路由提示。 |
| 20261012T185906119559Z | 2 | 等待成功；回复后再次询问；明确已回答澄清应继续执行。 |
| 20261012T190046487284Z | 0 | 探针对 stopped+clarification 错误使用无回复 resume；修正探针控制顺序，无新增模型调用。 |
| 20261012T190109759860Z | 3 | 重启/排序成功；空摘要推进水位，初始项目代号错答 Rondel；加入空摘要不推进水位守卫。 |
| 20261012T190430617383Z | 3 | 修复后续跑通过，持久非空摘要及项目代号“蓝桥”正确。 |

## 阶段审查

- **Standards：通过，无未解决阻塞项。** 独立审查发现旧水位恢复、公共产物依赖用途比较、重复键澄清无执行入口，均已修复并复核。
- **Spec：通过，无未解决阻塞项。** 澄清后旧选品复用和普通 CSV 表在混合资料集误判不可用已修；真实验证驱动的预算、摘要与交互修复亦已复核。
- 审查基准为 `816211b` 至当前工作区及新增文件。没有把简单 mock 通过当作实际模型语义通过，失败过程完整保留。

## 已知限制与下一步

- 非空摘要仍可能遗漏或错误归纳用户意图；程序可验证消息出处、非空与水位，不能证明语义无损。此次真实长会话样本正确，不是批量质量或压力评估。
- 产品标识在证据中存在、CSV 精确匹配与数字执行可校验；自然语言选品条件、版式归属、业务键含义仍依赖模型解释。原 PDF 页面有 layout_uncertain 提示，实测对应行已人工核对。任意新 PDF/CSV 的语义正确性不获保证。
- 跨轮复用为显式结果身份和匹配范围的选品复用；未做任意历史自动语义缓存、跨轮正文增量续读或完整对话全文召回。目录最多 24 产物 / 8 既有 PDF 选择；超大历史增量压缩，持久原历史不删。
- CSV 缺少对应编号继续要求澄清，不暗中仅统计命中子集；复杂模糊匹配需用户提供明确业务映射。文件/表规模、编码、OCR、图表展示限制沿用 D/E。
- 每用户回复/显式失败重试可获得新有界尝试；用户可多次主动继续，累计总费用不是六次上限。无后台自动付费恢复。
- 分支仍 main / `816211b`，F 变更全部未提交。没有修改原始资料、旧 `data/docker-e2e` 或旧运行部署；临时 server/worker/Vite 已停止，宿主 Docker 仅剩原两个 healthy 容器。
- 下一步入口：G 的后台探索与集成交接；F 不提前实现 G，也未部署新架构。启动仍参见 runner/README.md，关键配置名 `EXECUTION_IMAGE`、`EXECUTION_WORKER_TOKEN`，凭据不落交接文档。
