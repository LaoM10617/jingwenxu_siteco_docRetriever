# M1 材料筛选与支持范围讨论

日期：2026-09-26。状态：首轮检查完成；三条主线及内容能力已由 P-008 确认。问题证据集、保留集和有限解析可行性检查已完成（P-009）；M1 已验收，应用效果尚未验证。

来源：用户从 https://www.siteco.com/metanavigation/downloads 下载到 data；本轮核对官方目录分类。可访问不代表可再分发，原文件继续忽略，不进入 Git。

## 实际库存与方法

- 32 PDF，共 501 页：Brochures 21 份、Legal Documents 10 份、piktograms 1 份。
- Price Lists 8 文件：1 CSV、3 DATANORM、2 ELDANORM 96、2 ELDANORM 2000；没有 xlsx 样本。eldanorm2000.001 为 0 字节，原因未确定。
- LDT 3,839 文件，只读取一个文件头，未完成格式/数值验证，不逐个解析。
- 使用现成工具环境 pypdf 提取全部 PDF 文本；Poppler 渲染并人工核对 8 个代表页面。未 OCR，未调用外部模型，未选择或安装项目解析器。临时提取与页面图在 tmp/m1，不能当正式可复现验收套件。
- CSV 按 UTF-8、分号解析：18 列，11,386 数据行，订单号唯一，价格无空值，日期均为 01.06.2026。价格使用小数逗号；EAN/订单号应保留字符串。文件未自带明确币种列，不根据数字自行补币种、税率或折扣。

## 首轮分析（历史建议，最终确认见 P-008）

用户提出条款协议 PDF、产品宣传册 PDF、价格列表作为必选基线；具体能力边界仍讨论中。

1. 条款 PDF：建议支持有文本层的章节、正文、列表和条件限定。采购条款第一页是清晰单栏分节文本；答案需保留对象和例外，不承诺法律有效性判断。
2. 产品册 PDF：建议支持文本层中的产品介绍、型号和经过验证的参数表。Rondel 第 2 页含多表及附件；Highbay 第 18 页含 midi/maxi 和共同参数。pypdf 能提取大量内容，但阅读顺序、分段和型号归属仍需候选解析器验证。图片多并不自动需要视觉模型；纯图片信息和配光曲线解释暂不承诺。
3. CSV：建议支持平面带表头的数据和按订单号定位记录，保留列名、原值和记录位置；完整 CSV 的索引成本尚未测量。范围筛选、全表聚合、最便宜/所有符合条件产品等题型不能仅靠 top-k RAG 保证，单独决定是否支持。xlsx 无现有样本，暂不由 CSV 支持推导为支持任意 Excel。
4. 符合性声明：5/6 份全部页面无可提取文本，74010623 第 1 页肉眼可见勾选和手写签名；CE_83610824 有文本层及两个 /Sig 字段，但普通提取遗漏勾选标记。读取名称/编号与核验勾选、签名真实性、外部标准不是同一能力。建议扫描声明作为限制样本；文本版仅候选，不承诺合规核验或外部文件自动获取。
5. 图标说明：11 页，是图标、编号、德文、英文组成的表格。按文字名称解释可作为后续低成本候选；图像输入识别及未知图形匹配不加入首版。
6. EPD：单列为复杂表格候选。SL11 第 7 页出现单位、生命周期阶段、多层表头与科学计数法；普通段落问答可能可行，跨型号环境指标比较暂不承诺。
7. DATANORM/ELDANORM：官方目录单独列为价格数据格式；本地文件有版本、记录类型、跨记录数据或定长布局。CSV 已覆盖价格演示主线，建议首版排除这些专用导入格式。
8. LDT：官方将其列为产品系列规划数据；本地样本是逐行型号/参数/数值数据。完整配光解释需要格式映射、单位/角度关系和专门验证；与当前文档问答演示相比投入较高，建议首版排除。该成本判断为工程推断，不代表已完成 LDT 解析研究。

## 建议第一轮工作样本

- 德文采购条款（4 页）：章节与条件事实。
- 英文 General Terms of Sale（10 页）：另一语言的条款；目前仅文本扫描，需进一步核对选定题目页面。
- Rondel 21（2 页）：参数、订单变体、附件归属。
- Highbay 11/21（22 页）：同页近似型号与共享参数，重点第 18 页。
- 完整价格 CSV：按订单号查询与同类条目区分；不能用只含目标行的裁剪样本冒充完整检索效果。
- 74010623 扫描声明：不支持/无文本的边界反馈样本。

保留材料及污染边界已固定在 [问题集说明](cases/README.md)；文件身份和 CSV 哈希见 [manifest](material_manifest.json)。全部 PDF 已做机器扫描，不称完全未见。此前建议为历史讨论，当前确认以 P-008/P-009 为准。

## M1 完成证据与 M2 入口

- [问题集](cases/m1_questions.json)：13 开发题、3 保留题，参考要点和证据位置齐全，应用结果均未运行。
- [解析验证](results/m1_parsing.md)：复用既有检查，仅补表格/布局关系与保留题标注；默认表格提取有明确失败，布局文本可作为有限起点。
- [最小来源结构](../docs/sources.md)：文档身份、证据、PDF 页码/CSV 记录定位与查询范围。
- 具体解析库安装、运行框架/模型、规模限制与端到端效果在 M2 实施时确认和验证，不把 M1 结果推广为任意 PDF 表格支持。

## PDF 文件清单

以下页数来自本地读取，哈希用于固定本轮样本，不表示每页已人工审查。

- `data/Brochures/Connect/SIT_Flyer_Connect_City_2023_EN.pdf` — 20 页；SHA256 `b19a767dcbad85f1f30a832e027b7317555d0f94b59e23516d29ed76f93c5d0f`。
- `data/Brochures/Connect/SITECO__Connect_Sports_EN.pdf` — 6 页；SHA256 `d015851d6e03079cd28f5bb8823d6938203b65225eb5f14624aeed94fce7acca`。
- `data/Brochures/EPD/EPD-SL11_SITE-00001-V01.01-EN.pdf` — 11 页；SHA256 `a36cca158529d15ef47dd77d15e67473a65353bafcfe3741fc60c348ebc5188a`。
- `data/Brochures/EPD/EPD_FL11_SITE-00003-V01.01-EN.pdf` — 14 页；SHA256 `53f40f443810dbc93a8b2f16a5044d903dbd5645a27bd84a793dff72242cf71a`。
- `data/Brochures/EPD/EPD_SL21_SITE-00002-V01.01-EN-2.pdf` — 24 页；SHA256 `c6b4994b0f42200b3ed5111d10f626b10be06ca4cda882ae056b0f416b20b9e9`。
- `data/Brochures/EPD/EPD_SL_31_SITE-00004-V01.01-EN.pdf` — 27 页；SHA256 `90cea134d3ab6244c8d3f4a2e935208d4eecd4120c117d37911a3f005e1e37cc`。
- `data/Brochures/Indoor Lightening/SIT_Flyer_21_Office_EN.pdf` — 48 页；SHA256 `d6cd589c37b88c7f5e49ee816d019420257dc0dfd7b27201441be3201ccd9eb6`。
- `data/Brochures/Indoor Lightening/SIT_Four_Pager_Connect_Indoor_EN.pdf` — 4 页；SHA256 `6791a7c6aaa0d7b08ac219b5f9f2b2084fe3e15a5f08229bc53269cdbd435314`。
- `data/Brochures/Indoor Lightening/SIT_Highbay_11_Broschuere_V_25-132_Update_06_25_EN_RZ_web.pdf` — 22 页；SHA256 `0c8cdbdf8be2f2fb97065ddb1ebcaa62566cc26150f0a07454df60cc8836fb0a`。
- `data/Brochures/Indoor Lightening/SIT_Kurzflyer_Silica_21_Round_EN.pdf` — 4 页；SHA256 `99dc47633e9d6c785bbc23a887adb35467b34f0aa5b696ac5b4b15fbdc177e71`。
- `data/Brochures/Indoor Lightening/SIT_Lunis_Launchflyer_A4_EN_RZ_web.pdf` — 12 页；SHA256 `0396879ceb1e10bf6ffe03257b60c2bb0aab18de148e7d3135e4125e59d3a73c`。
- `data/Brochures/Indoor Lightening/SIT_Silica-Familienflyer_A4_EN.pdf` — 21 页；SHA256 `fd9f5e408091323daa83fce48f6ec77b44f43935e624f7275dd95314adbd279f`。
- `data/Brochures/Indoor Lightening/SIT_Teaser-Flyer_Silica_21_Prismatic_EN.pdf` — 4 页；SHA256 `79419adcff47bb3e5dec4ae12cef44036b1236084eff63b3746ed9b24006e1ae`。
- `data/Brochures/Indoor Lightening/SIT_Teaser_Flyer_Apollon_21_V_25-386_EN_RZ_web.pdf` — 4 页；SHA256 `6d4f25847b975c5b1d17c3d962d566d0216efe6024d540d8c4abe7225e4fe5b8`。
- `data/Brochures/Indoor Lightening/SIT_Teaser_Flyer_Lunis_R_V_25-486_RZ_WEB_EN.pdf` — 4 页；SHA256 `f94f484feee79dd5eeea8cf58a622441e8c33ddea0a4e4d27c2c09f898d2e6f4`。
- `data/Brochures/Indoor Lightening/SITECO_CL31_EN_webversion_final.pdf` — 12 页；SHA256 `85c2dd17f3601132dc831904529466ff7cd19754f52df73a7577be11f9910cae`。
- `data/Brochures/Indoor Lightening/SITECO_Rondel_21_Product_Flyer.pdf` — 2 页；SHA256 `78a20a04658b46ad947eccce4d96e08f757f348e721b0d8159e5f9f1b7bff561`。
- `data/Brochures/Indoor Lightening/SITECO_Silica_21_EN.pdf` — 40 页；SHA256 `2f39bc9a4f56c17c9c1a4ca299a1a1ea0cc8e94177aae176da2e9bff52ba2a6a`。
- `data/Brochures/Indoor Lightening/SITECO_Trunking_Systems_EN.pdf` — 30 页；SHA256 `0ff906d2f1fd80e6d5cf0810ec87eaa6ece1ef7267237a1e76b7e0804df526df`。
- `data/Brochures/SIT_Sustainability_Report_2023_RZ.pdf` — 108 页；SHA256 `573ec35d266f809ad57a9bcf0f023faa31c758da63d77f40547786556cb7eb47`。
- `data/Brochures/SITECO_Turkey_Solution_EN.pdf` — 20 页；SHA256 `f877b8632c762c03a91dca4ae278a769c233521de8fdc75a3c4a067053ac88bb`。
- `data/Legal Documents/Allgemeine_Einkaufsbedingungen_Siteco-Gruppe_April_2025.pdf` — 4 页；SHA256 `861a1c09f3eac9b85fbb4e430571a4279df9c4211b1d287eab1a0f669cb8cb59`。
- `data/Legal Documents/Declaration of Conformity(according to Directive 201453EU)/74010623.pdf` — 3 页；SHA256 `440b87c772d2a445c2fdbdf91d9c7997aa6b28e1b5f8c2dcec85c4b77fa672a7`。
- `data/Legal Documents/Declaration of Conformity(according to Directive 201453EU)/76220523.pdf` — 3 页；SHA256 `ce841bcdc4fa7677bf64683ef458c7e16f88d7ee526add49e02bfbc299f63b06`。
- `data/Legal Documents/Declaration of Conformity(according to Directive 201453EU)/76820823.pdf` — 4 页；SHA256 `df47b29b01f6c20de74a1307f9a5447fa9f3c3b4fcf962fc15b068769172ab7b`。
- `data/Legal Documents/Declaration of Conformity(according to Directive 201453EU)/789_0323.pdf` — 3 页；SHA256 `4db49cb127da370481e364deffa733f614c3dc79d2cf7a9a65ff1b104b7d700f`。
- `data/Legal Documents/Declaration of Conformity(according to Directive 201453EU)/796_0523.pdf` — 3 页；SHA256 `1f7bd3b564d0ef0acc15633e9c5e2234fd6a32df3992816f3b45d2a846daae01`。
- `data/Legal Documents/Declaration of Conformity(according to Directive 201453EU)/CE_83610824.pdf` — 5 页；SHA256 `922298f8c5ab7241ad29dc4cf8d8ed96789c5bade99ea251a0e1a293201e19e2`。
- `data/Legal Documents/SITECO_Datenschutzerklaerung.pdf` — 12 页；SHA256 `41fcdc6fb9632f52cd667ed7e14ac4910135cd94e3204553e5c97b16c6e4b7ac`。
- `data/Legal Documents/Siteco_GmbH_General-Terms-of-Sale.pdf` — 10 页；SHA256 `1e8d3fc4fad9c6fff53e8910a9cf5a00cbbc10bbfeca87e8962b6ebee5f5fa29`。
- `data/Legal Documents/SITECO_Verhaltenskodex-Geschäftspartner.pdf` — 6 页；SHA256 `9275b4524703eea89e467f7f8a1810d2f7538b83b4a2a1932c8a347af5e2a3b0`。
- `data/piktograms/SITECO_Piktogrammuebersicht.pdf` — 11 页；SHA256 `8167530b509012395db0b94ffc756397c8a1ab87f7551c8d82648124e86cd7fc`。
