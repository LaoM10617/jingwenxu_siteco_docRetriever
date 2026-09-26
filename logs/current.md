# 当前交接摘要：M2.5全部六步已验收

2026-09-26。M2.1基础运行、M2.2上传生命周期、M2.3 PDF证据、M2.4前端/双容器、M2.5 CSV解析与精确查询已验收。M2整体问答闭环尚未完成。

## 已确认依据与约束

P-010至P-025及实施补充、docs/m2-first-contracts.md、docs/m25-csv-contract.md。T-002至005沿用；T-006 lookup_orders(order_ids, document_ids, offset=0, limit=50)已获用户批准并实现，无需重复确认。用户依次授权M2.5前三步及后三步，本轮完成后三步。

CSV演示/eval限price_list格式：UTF-8可带BOM、分号、固定18列。订单只trim首尾，保留大小写/内部空格/标点/前导零，重复不合并。原值保留，非法/缺失价格无数值，不补零/币种/税率/折扣。SQLite精确索引，无pandas；正式查询HTTP/统一聊天及结果表单留M2.7。不理想查询先记录，不改模糊回退。

仍保持20MiB、PDF50页、CSV20,000记录、10活跃文件；无OCR/视觉/本地生成模型。保留题不调参，108页报告不在基线。Voyage-4/1024维/3RPM+10KTPM共享预算，付费由用户切换；FAISS按文档IndexFlatIP选定未安装。数据D盘，Docker镜像/缓存C盘；仅后端访问运行中SQLite。

## 实际实现

- 前三步csv_parsing.py通过parse_document(text/csv)分派：固定schema、原值/逻辑记录号/稳定ID、Decimal与warnings，结构错误整份失败。
- 后三步DocumentProcessor接CSV；CsvStore保存csv_documents/csv_records及(document_id,order_id) BINARY索引，价格无损字符串。摘要与全记录分开，不在状态轮询加载整份CSV。
- 记录/元数据事务完成，校验版本、数量、连续记录号、digest及摘要后才ready；半成品不可查询，已ready文档保持可读。stop拒迟到发布，retry清旧数据；重启校验持久快照，无解析/模型调用，损坏明确index_restore_failed。
- 全缺订单号文件csv_no_order_ids失败并保留摘要/warnings；混合缺键记录在证据中保留但不参与订单命中。非法金额可命中并显示原值/状态，不影响其他记录。
- lookup_orders先检查全部指定文档ready/CSV，精确匹配、多订单顺序/去重、完整计数、明确未命中、来源与稳定分页，limit1–100。重复来源全留，source identity=(document_id,evidence_id)。无通配或近似补结果。
- 前端CSV显示记录数/可索引数/金额状态和记录warnings，不伪造PDF页数；ready证据分页已补真实成功预览。聊天发送、持久历史、自定义Key仍未开放。

## 实际验证

- Windows/Linux最终全量各132 tests + 10 subtests通过；既有1条Starlette/httpx弃用提示。两平台前端TypeScript/生产构建通过，无新增依赖。
- 第一条真实CSV生命周期测试先红后绿；随后验收查询范围、前导零/大小写/标点、SQL样式字面量、多订单、重复/分页、注入写后失败与retry、停止/损坏/无解析重启。205重复记录分页100/100/5，无遗漏；高精度金额/带引号换行原值保留。
- Edge/Playwright共12项独立检查：9受控UI、1真实CSV上传查询、1后端重建一致性、1nginx代理。未重跑旧M2.4真实PDF浏览器测试；后端PDF回归已跑。
- 完整manifest价格表11386条/18列，0warnings→ready，浏览器证据前两页/选择/刷新通过；只查询开发订单记录1/2与明确不存在sentinel，总命中2、两页各1条，原价183.20。容器重建后状态及查询逐字段一致。未查询/展示保留记录或读取保留题答案。
- 临时eval/m25_acceptance_app.py只通过验收覆盖挂载、在后端进程内部调用T-006；验收后已按正式Compose移除路由/挂载，HTTP确认404且CSV仍ready。没有正式新增查询API。
- 验收/复现/局限：eval/results/m25_csv.md。开发订单没有观察到错误命中/漏行；精确变体故意不匹配，未来真实问题先记录。20条完整CSV证据页较长，紧凑聊天结果表单后续实现。

## Git与运行状态

main，HEAD047ccf9e943f0b51601d1d60e2cfdb5e5e50d776（M2.4已push）；M2最终审查基准4307e22ceb08b70d6dca459137355b0551f2e6c1。当前未提交包含M2.5前三步既有改动及本轮后三步：CSV解析/存储/查询/接入、前端摘要、测试、eval夹具、契约/README/决策/日志。未commit/push。git diff --check通过（只有已有CRLF转换提示）。

新预览Compose siteco-m25-acceptance：frontend http://127.0.0.1:18089，backend18088，D:/Projects/Retrieval_SITECO/tmp/m25-acceptance/runtime，两个健康容器，正式路由，1份完整ready CSV。旧siteco-m24-acceptance仍在18087/18086、原版本、独立runtime；勿把旧预览当新代码。新测试镜像siteco-backend:m25-csv-test。截图/开发记录验收JSON在忽略的tmp/m25-acceptance。

PDF仍成功解析后failed/retrieval_not_configured；Embedding、FAISS、回答未实施。本轮无模型调用、密钥读取、运行中SQLite外部打开、数据盘迁移。标准shell需审批升级处理sandbox初始化限制，升级正常，无审批拒绝；浏览器沿用Playwright/Edge。

## 下一步

按既有顺序进入M2.6 PDF检索/Embedding共享额度调度，再M2.7回答与引用/聊天、M2.8完整闭环、M2.9双轴阶段审查。CSV内部精确方法已可被后续经校验的查询计划调用；不能把当前CSV ready当整个M2或问答验收。用户本轮已授权以“Implemented precise CSV lookup.”提交并push；提交结果以Git历史及后续交接更新为准。
