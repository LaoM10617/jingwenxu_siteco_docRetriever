# M5.0 逐题审阅清单

状态：题集已按P-040批准用于A+B；批准时未执行。计分细则以 docs/m50-evaluation-protocol.md 为准。事实单元、原文单元及材料哈希的机器可读版本为 eval/cases/m50_protocol.json。

## E01 · development · 来源 P01

问题：Reicht nach den Einkaufsbedingungen der Eingang einer Rechnung aus, damit die Zahlungsfrist läuft? Welche Voraussetzungen und Zahlungsoptionen nennt der Text?

范围：terms；前轮：无，新会话；预期：answer。

分母：必要事实 7；PDF证据单元 2。

- E01-F1：仅收到发票不足以开始付款期限。
- E01-F2：货物/服务必须完整履行。
- E01-F3：货物/服务必须无缺陷。
- E01-F4：必须收到可审核发票。
- E01-F5：14个日历日内付款可扣2%折扣，或60个日历日净额付款。
- E01-F6：抵销或因缺陷适当扣留/减少付款时仍允许折扣。
- E01-F7：缺陷情形的期限从完全消除缺陷或声明减价后开始。

原文证据：

- E01-U1：terms 物理第2页，Artikel VII.2: Zahlungen erfolgen。
- E01-U2：terms 物理第2页，Artikel VII.3: Die Zahlungsfrist beginnt。

## E02 · development · 来源 P03

问题：Welche Aufbewahrungs- beziehungsweise Löschfristen nennt die Datenschutzerklärung für abgelehnte Bewerbungen und für das Karriereportal onlyfy? Bitte die beiden Abschnitte und ihre Einschränkungen getrennt wiedergeben, nicht zu einer einheitlichen Frist zusammenziehen.

范围：privacy；前轮：无，新会话；预期：answer。

分母：必要事实 5；PDF证据单元 4。

- E02-F1：一般申请管理章节：未订立雇佣合同的申请材料。
- E02-F2：该章节从拒绝通知起两个月后自动删除。
- E02-F3：保留其他合法利益例外，例如AGG程序中的举证义务。
- E02-F4：独立onlyfy章节写最长六个月，而非固定六个月或拒绝起六个月。
- E02-F5：明确两项期限各自章节归属，不合并或推断优先适用关系。

原文证据：

- E02-U1：privacy 物理第5页，7.3 Bewerbungsmanagement / Stellenbörse。
- E02-U2：privacy 物理第6页，zwei Monate nach Bekanntgabe der Absageentscheidung。
- E02-U3：privacy 物理第10页，11.2 Onlyfy / Karriere-Portal der New Work SE。
- E02-U4：privacy 物理第11页，Die Daten werden bis zu 6 Monate aufbewahrt。

## E03 · development · 来源 M41-04

问题：Compare Rondel order numbers 0MD5307L1830 and 0MD5307L0940.

范围：rondel；前轮：无，新会话；预期：answer。

分母：必要事实 10；PDF证据单元 2。

- E03-F1：0MD5307L1830: 3000 K
- E03-F2：0MD5307L1830: 1800 lm
- E03-F3：0MD5307L1830: 18 W
- E03-F4：0MD5307L1830: ON/OFF
- E03-F5：0MD5307L1830: 1.6 kg
- E03-F6：0MD5307L0940: 4000 K
- E03-F7：0MD5307L0940: 900 lm
- E03-F8：0MD5307L0940: 9 W
- E03-F9：0MD5307L0940: ON/OFF
- E03-F10：0MD5307L0940: 1.6 kg

原文证据：

- E03-U1：rondel 物理第2页，Rondel 21 order variants: 0MD5307L1830 row + column headings。
- E03-U2：rondel 物理第2页，Rondel 21 order variants: 0MD5307L0940 row + column headings。

## E04 · development · 来源 M41-05

问题：What are the colour temperature and power of the second luminaire?

范围：rondel；前轮：E03；预期：answer。

分母：必要事实 2；PDF证据单元 1。

- E04-F1：0MD5307L0940: 4000 K
- E04-F2：0MD5307L0940: 9 W

原文证据：

- E04-U1：rondel 物理第2页，Rondel 21 order variants: 0MD5307L0940 row + column headings。

## E05 · development · 来源 M41-06

问题：What is its power? Use only the currently selected price list; if it does not provide this, say so.

范围：prices；前轮：E04；预期：exact_not_found_no_power。

分母：必要事实 0；PDF证据单元 0。


CSV精确订单：0MD5307L0940；正确记录集合：[]。空集合已对完整11,386行逐项精确核对。

## E06 · development · 来源 D09

问题：Welchen Listenpreis und welches Gültigkeitsdatum hat 51DB11EC11B1D?

范围：prices；前轮：无，新会话；预期：answer。

分母：必要事实 2；PDF证据单元 0。

- E06-F1：51DB11EC11B1D: Listenpreis 183,20
- E06-F2：51DB11EC11B1D: gültig ab 01.06.2026

CSV精确订单：51DB11EC11B1D；正确记录集合：[1]。空集合已对完整11,386行逐项精确核对。

## E07 · development · 来源 D10

问题：Vergleiche Preis und EAN von 51DB11EC11B1D und 51DB11EC11D1D.

范围：prices；前轮：无，新会话；预期：answer。

分母：必要事实 4；PDF证据单元 0。

- E07-F1：51DB11EC11B1D: Listenpreis 183,20
- E07-F2：51DB11EC11D1D: Listenpreis 183,20
- E07-F3：51DB11EC11B1D: EAN 4069025783196
- E07-F4：51DB11EC11D1D: EAN 4069025783219

CSV精确订单：51DB11EC11B1D, 51DB11EC11D1D；正确记录集合：[1, 2]。空集合已对完整11,386行逐项精确核对。

## E08 · development · 来源 D11

问题：What is the exact price of NOT-A-SITECO-ORDER-000?

范围：prices；前轮：无，新会话；预期：exact_not_found。

分母：必要事实 0；PDF证据单元 0。


CSV精确订单：NOT-A-SITECO-ORDER-000；正确记录集合：[]。空集合已对完整11,386行逐项精确核对。

## E09 · development · 来源 M41-07

问题：Welche Incoterms-Fassung ist maßgeblich, und welchen Listenpreis hat 51DB11EC11B1D-NOT-FOUND? Bitte getrennt beantworten.

范围：terms, prices；前轮：无，新会话；预期：partial_answer_exact_miss。

分母：必要事实 1；PDF证据单元 1。

- E09-F1：Incoterms 2020

原文证据：

- E09-U1：terms 物理第1页，Artikel II.3: Für Incoterms ist der Stand von 2020 maßgeblich。

CSV精确订单：51DB11EC11B1D-NOT-FOUND；正确记录集合：[]。空集合已对完整11,386行逐项精确核对。

## E10 · holdout_document · 来源 H01

问题：What are the Lunis R diameter, weight and luminous flux range?

范围：lunis_holdout；前轮：无，新会话；预期：answer。

分母：必要事实 3；PDF证据单元 1。

- E10-F1：直径380 mm
- E10-F2：重量2 kg
- E10-F3：光通量范围2020–4800 lm

原文证据：

- E10-U1：lunis_holdout 物理第4页，Technical data: Diameter / Weight / Luminous flux。

## E11 · holdout_document · 来源 H02

问题：Is recessed Lunis R offered in every listed housing colour?

范围：lunis_holdout；前轮：无，新会话；预期：answer。

分母：必要事实 2；PDF证据单元 1。

- E11-F1：外壳总体列有白、黑、银色。
- E11-F2：嵌入式仅银色，因此不是所有列出颜色均适用。

原文证据：

- E11-U1：lunis_holdout 物理第4页，Technical data: Housing (recessed only silver)。

## E12 · holdout_same_file · 来源 H03

问题：Vergleiche die Listenpreise und Gültigkeitsdaten von B01S6B4A07145E und B01S7B4A07150E.

范围：prices；前轮：无，新会话；预期：answer。

分母：必要事实 4；PDF证据单元 0。

- E12-F1：B01S6B4A07145E: Listenpreis 2075.10
- E12-F2：B01S7B4A07150E: Listenpreis 2513.30
- E12-F3：B01S6B4A07145E: gültig ab 01.06.2026
- E12-F4：B01S7B4A07150E: gültig ab 01.06.2026

CSV精确订单：B01S6B4A07145E, B01S7B4A07150E；正确记录集合：[11385, 11386]。空集合已对完整11,386行逐项精确核对。
