# 卡片数据约定

排版脚本只消费已整理的数据，不判断图片内容或医嘱真伪。人工确认字段是一条工作流记录，不是自动完成专业审核的证明。

## 顶层

| 字段 | 类型 | 用途 |
| --- | --- | --- |
| person | 字符串 | 称呼，不必填真实姓名 |
| age | 整数或 null | 用户提供的年龄，不用于推算剂量 |
| date | 字符串 | 数据整理/卡片日期，建议 YYYY-MM-DD |
| plan_date | 字符串 | 个人用药方案日期，不清楚写“待确认” |
| demo | 布尔值 | 演示必须 true，所有页显示演示标记 |
| urgent | 布尔值 | 宿主已识别急症/危急值等则 true，脚本停止常规输出；false 不代表排除急症 |
| restrictions | 字符串数组 | 用户明确的忌口、过敏、医生限制；未提供填“不清楚” |
| reports | 对象数组 | 体检条目，见下表；可为空 |
| medications | 对象数组 | 用药条目，见下表；可为空 |

## reports 中每项

`metric_id`：knowledge.json 的准确 id；未知项目设为空。`name`、`value`、`unit`、`reference`、`flag`、`test_date`：全部保留原文，不填通用阈值；缺失使用空字符串。`source_id`（如“图1 第3行”）、`source_quote`（原文必要摘录）、`confirmed`（子女是否对照原文核对，布尔值）。confirmed 不为 true 或必填字段缺失时只进待确认区。没有原参考范围可解释项目含义，但不生成异常判断，脚本将其作为待确认条目。

不允许在输入中自由指定解释或疾病结论。排版解释从指标知识库取得，避免把模型猜测直接排进卡片。

## medications 中每项

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| name | 字符串 | 通用名 |
| form | 字符串 | 剂型，保留缓释/控释/肠溶等 |
| strength | 字符串 | 产品规格；不是个人剂量 |
| dose | 字符串 | 现行个人每次剂量及完整单位，如“每次 1 片” |
| events | 对象数组 | 每次的时段与原文时间，见下文 |
| source_type | 字符串 | prescription / pharmacy-label / pharmacist；其余类型均不可正式排表 |
| source_id | 字符串 | 可追溯的处方、药袋或药师确认记录编号 |
| source_quote | 字符串 | 上述个人用法的必要原文，不是网上通用用法 |
| confirmed | 布尔值 | 已对照现行个人用法核实才为 true |
| conflict | 布尔值 | 原文或不同材料有冲突则 true，阻止进入正式表 |
| pending_reason | 字符串 | 具体还需问医生/药师的问题 |

`events` 中每项：

- `slot` 取 `早饭前`、`早饭时`、`早饭后`、`午饭前`、`午饭时`、`午饭后`、`晚饭前`、`晚饭时`、`晚饭后`、`睡前`、`明确钟点` 之一。
- `timing` 为来源中的完整时间说明，例如“早餐后服用”。必须包含该 slot 的完整餐次与餐前后关系（允许“早餐/午餐/晚餐/随餐”同义表达）；明确钟点须有数字钟点原文。
- 只有频次、无具体安排的资料不得构造 events。尚待确认的 events 填空数组。
- 剂量、时间与 source_quote 必须由宿主和人工逐项对照；脚本无法证明自然语言引用确实支持填写值。

任一关键字段缺失、来源不合格、conflict 为 true、confirmed 不为 true，整种药进入“待确认清单”，其中不展示待确认剂量，避免草稿被当成服药指示。不会静默选择冲突来源。

## 最小示例

参阅 [example.json](example.json)。示例药名全部虚构，只用于演示排版，不可拿来服药。正式输入应设 demo=false 并换成经核对的真实来源。

生成：

```bash
python3 scripts/render_cards.py --input references/example.json --output /tmp/elder-card-example --font /path/to/ChineseFont.ttf
```

脚本用 UTF-8 读写。不记录真实证件号、住址或电话。不自动上传任何内容。
