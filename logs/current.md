# 当前交接摘要：M2 对话入口

更新日期：2026-09-26。M0、M1 已完成；下一场对话启动 M2。

## 已确认目标

先阅读 AGENTS.md、decisions.md 的 P-008/P-009。主线是条款定位、产品参数对比、订单号查价；有文本层且归属明确的简单参数表纳入目标，CSV 精确查询/多订单号对比必做。有限筛选/统计后置；OCR、视觉推理、复杂表格、专用价格格式与 LDT 等不承诺。不要重开已确认范围。

## Git 检查点

main；M1 审查基准 b8421e72fd70fb8f62eca93ea39ab4bca8de9690。本摘要随 M1 提交保存，message 为 Confirm parsing targets, validate datasets, and define boundaries.；包含决策、来源结构、材料 manifest、16 题、解析报告与日志。M2 以包含本摘要的提交作为阶段基准，接手时用 git rev-parse HEAD 记录实际哈希并核对未提交内容。
用户授权本轮 commit，没有授权 push；origin/main 仍为 M0 检查点，接手时核实。原文档 data、private、tmp、需求草案和 .venv 保持忽略。

## 完成证据

- eval/materials.md 和 eval/material_manifest.json：样本、来源、文件哈希与已知限制。
- eval/cases/m1_questions.json、README.md：13 开发题和 3 保留题、答案要点、证据位置、执行与保留协议。全部 application_result 为 not_run；不将答案集摄入知识库。
- eval/results/m1_parsing.md：复用全量文本层/CSV 检查，仅补解析关系验证。默认表格提取漏表头/空表，布局文本保留开发题所需型号/参数关系，但有旋转文字、续行等缺陷。不能声称任意 PDF 表格可靠。
- docs/sources.md：document_id 与文件名分离；evidence_id 回溯存储证据；物理页码/CSV 记录号、原值与列名；选择文档后再检索或精确查询。
- 保留 Lunis R 全文和 CSV 末两记录；Apollon/英文销售条款为储备。已扫描/标注，非盲测；禁止后续调参使用，详细协议见 cases/README.md。

## M2 开场与实施顺序

1. 核对提交、文件和 M1 产物；无需重做全量材料盘点或已通过的标注检查。
2. 确认前后端框架、模型与凭据、最终解析库/依赖、Docker 组织、文件规模/语言限制及必要状态/接口。Python 3.12/pip/venv 已确定；pandas、pdfplumber 和 React 不能仅因讨论被视为已安装/最终选型。
3. 实现最小解析到证据结构，用开发题验证表头/型号/单位关系；按 AGENTS 确认新增测试接口再实施。fusion/lexical 接入时补正式测试，落实稳定 chunk ID 与 top_k 前范围过滤。
4. 实现浏览器上传、新文档处理、证据检索或 CSV 精确查询、基于文档回答与引用；验证 Docker 全流程。不要使用预置演示语料替代上传。
5. 保留题在固定版本后运行，不提前调参；M2 完成按 AGENTS 执行 Standards/Spec 双轴阶段审查。

## 环境与未验证项

项目独立 Python 3.12.10 venv 锁定 rank-bm25/NumPy；分析工具 pypdf 6.10.0、pdfplumber 0.11.9/Poppler 属于工具环境，不是项目依赖。步骤与 Python 补丁限制见 docs/development.md。本轮未启动应用服务、未新增依赖。Linux、完整解析适配器、检索/回答效果、前端与 Docker 应用均未验证。
详细过程见 logs/m1.md；M1 完成仅表示材料/边界/证据定位准备达到实现入口，不代表应用能力通过。
