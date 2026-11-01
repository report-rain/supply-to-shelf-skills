# 07 评论与退货运营（review_ops.py）· 行为规格冻结

> 对象：`Agents/07_Review_Ops_Agent/scripts/review_ops.py`
> 实测环境：Windows PowerShell 5 + Python 3.12.0；基准日 2026-10-30。
> 本文只描述行为，不含实现细节；示例数值均来自实跑。

## 1. 范围与脚本（职责 + 依赖配置/前置模块）

- `reviews`：读取差评/评论 CSV，算评分分布、差评率、可修/不可修归因，输出 Top3 问题与证据，供 Listing/素材迭代。
- `returns`：读取退货 CSV，按原因码聚合件数与退款金额，识别可预防退货与不可映射原因；可选传入订单数算退货率。
- `health`：读取账号健康 JSON，按 ODR、迟发、发货前取消、差评、A-to-Z、政策违规给出 CRITICAL/WARN/OK 与动作。
- 边界：只读本地文件、只输出建议；不接平台 API、不改 Listing、不回写数据。
- 前置依赖：无外部配置文件；三份输入均由调用方提供。07 不依赖 02 费率、不依赖 06/08 产物。
- 所有百分比阈值、关键词、原因码映射均为脚本内常量（见 §3、§5）。

## 2. CLI 契约

通用规则：

- 必须给出 `reviews`、`returns`、`health` 之一；缺失或拼错由 argparse 报错，退出 2。
- `--json` 属于子命令，必须写在子命令之后；写在前面会被视为未知参数。
- argparse 错误在 argv 含 `--json` 时也输出 JSON 错误体，退出 2。
- 成功路径固定退出 0：即使账号 `CRITICAL`、差评率极高、退货全为可预防，也不会非零退出。

### 2.1 `reviews`

| 参数名 | 类型 | 必填 | 默认值 | 取值范围/枚举 | 说明 |
|---|---|---|---|---|---|
| `--file` | str | 是 | — | 存在的 CSV | 评论文件；相对路径按当前工作目录 |
| `--json` | flag | 否 | `false` | — | 结构化输出 |

### 2.2 `returns`

| 参数名 | 类型 | 必填 | 默认值 | 取值范围/枚举 | 说明 |
|---|---|---|---|---|---|
| `--file` | str | 是 | — | 存在的 CSV | 退货文件 |
| `--orders` | int | 否 | `None` | `> 0`（给出时） | 同期订单数；用于退货率；`0` 或负数失败 |
| `--json` | flag | 否 | `false` | — | 结构化输出 |

### 2.3 `health`

| 参数名 | 类型 | 必填 | 默认值 | 取值范围/枚举 | 说明 |
|---|---|---|---|---|---|
| `--file` | str | 是 | — | 存在的 JSON | 账号健康指标文件 |
| `--fail-on-critical` | flag | 否 | `false` | — | 新增（#9）：总等级为 `CRITICAL` 时以 exit 1 结束；默认关，不影响基线行为 |
| `--json` | flag | 否 | `false` | — | 结构化输出 |

冲突与隐式假设：

- `returns` 不传 `--orders` 时退货率为 `null`，并在 `missing` 提示「退货率需订单数」；不传不等于 0。
- `--orders` 为 argparse `int`，`abc` 或 `1.5` 在解析阶段退出 2。
- `health` 不读外部阈值配置，阈值与告警倍率写死。
- 三个子命令均无 locale/币种参数；金额单位按输入原样视为同一币种。

## 3. 输入契约

### 3.1 评论 CSV（reviews）

- 编码 UTF-8，允许单个 BOM；逗号分隔；首行表头；数据行从物理第 2 行计数。
- 列名去空白、大小写不敏感；中文别名精确匹配。
- 必需列只有 `rating` 与 `body`；其他列缺失不报错。
- `rating` 必填、可解析为数字、范围 `[1,5]`（含端点，允许小数）。越界或非数字整表失败。
- `body` 去空白后不得为空；空评论整表失败。
- `date`/`title`/`verified`/`variant` 被读取但**不进入任何输出**；`verified` 的真值集合仅用于内部标记，也不输出。
- 空文件（仅表头）按「没有数据行」失败，`missing=["file"]`。

| 内部字段 | 允许列名（按优先级） | 必填 | 说明 |
|---|---|---|---|
| rating | `rating`, `stars`, `score`, `评分`, `星级`, `分数` | 是 | 1–5，允许 4.5 |
| date | `date`, `review_date`, `日期`, `评论日期`, `时间` | 否 | 仅读取，不输出 |
| title | `title`, `review_title`, `标题`, `评论标题` | 否 | 用于证据摘录 |
| body | `body`, `review`, `text`, `content`, `内容`, `评论内容`, `评论` | 是 | 用于归因与证据 |
| verified | `verified`, `verified_purchase`, `已验证`, `验证购买`, `是否验证` | 否 | 仅读取，不输出 |
| variant | `variant`, `sku`, `规格`, `变体`, `款式`, `颜色/规格` | 否 | 仅读取，不输出 |

数字清洗（评论与退货共用一套）：

- 去 `$`、所有逗号、空格；空串、`-`、`—`、`N/A`、`n/a`、`nan` 视为缺失。
- 仅支持美式小数：`"1,234.56"→1234.56`；`"1.234,56"` 会被解析为 `1.23456`（错误但退出 0）。
- 负数可被解析，随后由业务范围拒绝。
- 评分分布使用 `int(rating)` 截断：4.5 → 4，4.9 → 4，2.5 → 2；平均值仍按原始小数计算。

### 3.2 退货 CSV（returns）

- 编码/分隔符/表头/行号规则同上；空文件 `missing=["file"]`。
- 必需列：`reason_code`、`qty`、`refund_amount`；`reason_text` 可选。
- `reason_text` 虽被读取，但**完全不参与原因归因**；归因只看 `reason_code`。
- `qty` 必须为整数且 `> 0`；`2.0` 可接受，`2.5` 失败，`0`/负数失败。
- `refund_amount` 必须 `>= 0`；负数失败。
- 任一数据行失败即中止整表，不输出部分聚合。

| 内部字段 | 允许列名 | 必填 | 类型/单位 |
|---|---|---|---|
| reason_code | `reason_code`, `return_reason_code`, `退货原因码`, `原因码`, `退货原因` | 是 | 文本/枚举 |
| reason_text | `reason_text`, `return_reason`, `reason`, `退货原因说明`, `原因说明`, `原因` | 否 | 文本（被忽略） |
| qty | `qty`, `quantity`, `units`, `退货件数`, `数量`, `件数` | 是 | 正整数 |
| refund_amount | `refund_amount`, `refund`, `amount`, `退款金额`, `退款总额`, `金额` | 是 | 非负金额 |

原因码归一化顺序（先命中先返回）：

1. 原值去空白并转大写，空格、`-`、`/` 替换为 `_`，去首尾 `_`。
2. 与 10 个标准码精确匹配。
3. 与中文别名精确匹配（不是包含匹配）。
4. 与中文标签或标准码做大小写不敏感匹配。
5. 仍未命中 → `OTHER`，并记录原始值到 `unmapped_codes` 与 `missing` 提示。

标准码与中文标签：

| 码 | 中文标签 | 中文别名（精确） | 可预防 |
|---|---|---|---|
| `DEFECTIVE` | 商品有缺陷 | 商品有缺陷/有缺陷/质量问题 | 否 |
| `NO_LONGER_NEEDED` | 不再需要 | 不再需要/不想要了 | 否 |
| `NOT_COMPATIBLE` | 不兼容/不适用 | 不兼容/不适用 | 是 |
| `UNAUTHORIZED_PURCHASE` | 未授权购买 | 未授权购买 | 否 |
| `MISSING_PARTS` | 缺少配件 | 缺少配件/缺件 | 是 |
| `ARRIVED_LATE` | 到货太晚 | 到货太晚/配送太晚 | 是 |
| `BETTER_PRICE` | 找到更低价格 | 找到更低价格/更低价格 | 否 |
| `QUALITY_UNACCEPTABLE` | 质量不可接受 | 质量不可接受 | 是 |
| `DAMAGED` | 运输损坏 | 运输损坏/破损 | 是 |
| `WRONG_ITEM` | 发错货 | 发错货/错发 | 是 |
| `OTHER` | 其他/未映射 | — | 否 |

注意：`包装破损` 不是任何别名，虽包含「破损」也会落到 `OTHER`（实跑确认）；空原因码也归 `OTHER`。

### 3.3 账号健康 JSON（health）

- 编码 UTF-8，允许单个 BOM；必须是 JSON 对象；顶层数组/标量失败并 `missing=["file"]`。
- 六个键全部必需，键名精确匹配，无别名：

| 字段 | 类型 | 单位 | 约束 | 说明 |
|---|---|---|---|---|
| `odr_pct` | number | % | `>= 0` | 订单缺陷率 |
| `late_shipment_pct` | number | % | `>= 0` | 迟发率 |
| `pre_fulfillment_cancel_pct` | number | % | `>= 0` | 发货前取消率 |
| `negative_feedback_pct` | number | % | `>= 0` | 差评率 |
| `a_to_z_claims` | integer | 件 | `>= 0`，必须是整数 | A-to-Z 索赔数 |
| `policy_violations` | integer | 件 | `>= 0`，必须是整数 | 政策违规数 |

- 布尔值不视为数字（`true` 失败）；字符串数字（`"1.0"`）失败；`1.5` 作为计数失败；`1.0` 作为计数通过。
- 多余键忽略。
- 缺失字段一次性列出全部缺失键；类型/范围错误只报当前键。
- 非法 JSON 退出 2，`missing=["file"]`，信息「不是合法 JSON」。

## 4. 输出契约

### 4.1 `reviews` 成功 JSON

| 字段 | 类型 | 单位/精度 | 说明 |
|---|---|---|---|
| `mode` | str | — | 固定 `reviews` |
| `file` | str | — | 回显路径 |
| `total_reviews` | int | 条 | 评论总数 |
| `average_rating` | number | 星，2 | 原始评分均值 |
| `rating_distribution` | object | — | 键 `"1"`…`"5"`，值为整数条数（按 `int()` 截断归桶） |
| `one_two_star_count` | int | 条 | 1–2 星总数 |
| `one_two_star_pct` | number | %，2 | 1–2 星 ÷ 总数 |
| `negative_rate_pct` | number | %，2 | 与 1–2 星百分比同值 |
| `negative_count` | int | 条 | 与 `one_two_star_count` 同值（rating < 3） |
| `negative_share_pct` | number | %，2 | 差评 ÷ 总数 |
| `three_star_pct` | number | %，2 | 分桶 `"3"` ÷ 总数 |
| `positive_pct` | number | %，2 | 分桶 `"4"`+`"5"` ÷ 总数 |
| `attribution` | object | 条 | 8 个分类键，值为该分类命中的差评条数（含 0） |
| `categories` | array | — | 8 个分类，顺序固定，见下 |
| `unclassified_count` | int | 条 | 未命中任何分类的差评数 |
| `fixable_count` | int | 条 | 落在可修分类的差评数 |
| `fixable_rate_pct` | number | %，2 | 可修 ÷ 差评 |
| `top_issues` | array | — | 最多 3 条，按条数降序、同数按分类顺序 |
| `negative_reviews` | array | — | 全部差评，按 CSV 顺序 |
| `rules` | object | — | `taxonomy[]`、`fixable[]`、`negative_definition`、`fixable_rate_definition` |
| `disclaimer` | str | — | 免责声明 |

`categories[]` 字段：`name`(str)、`fixable`(bool)、`listing_patch`(bool)、`creative_patch`(bool)、`matched_keywords`(str[]，该分类命中过的关键词去重)、`count`(int)、`share_of_negative_pct`(2)、`share_of_all_pct`(2)。

分类固定顺序与可修标记：

| 顺序 | 分类 | fixable |
|---|---|---|
| 1 | 质量做工 | 是 |
| 2 | 尺寸容量 | 否 |
| 3 | 功能故障 | 否 |
| 4 | 电池续航 | 否 |
| 5 | 清洁异味 | 是 |
| 6 | 物流包装 | 否 |
| 7 | 描述不符 | 是 |
| 8 | 使用门槛 | 是 |

`top_issues[]`：`name`、`count`、`share_of_negative_pct`、`fixable`、`listing_patch`、`creative_patch`、`evidence[]`（最多 2 条，标题/正文以 ` / ` 拼接、空白折叠、最多 180 字符）。

`negative_reviews[]`：`rating`(int 截断)、`title`(str，缺失为空串)、`category`(str，未归类为 `未归类`)、`matched_keywords`(str[])、`snippet`(str ≤180)。

### 4.2 `returns` 成功 JSON

| 字段 | 类型 | 单位/精度 | 说明 |
|---|---|---|---|
| `mode` | str | — | 固定 `returns` |
| `file` | str | — | 回显路径 |
| `returned_units` | int | 件 | qty 求和 |
| `orders` | int\|null | 单 | 回显，未传为 null |
| `return_rate_pct` | number\|null | %，2 | 退货件数 ÷ 订单数；未传订单为 null |
| `return_rate_definition` | str | — | 固定口径文案 |
| `total_refund` | number | 金额，2 | 退款合计 |
| `reasons` | array | — | 按件数降序、件数相同按退款降序 |
| `top_reason` | object\|null | — | `reasons[0]`，无行时为 null |
| `preventable` | object | — | 见下 |
| `unmapped_codes` | str[] | — | 归入 OTHER 的原始码去重 |
| `missing` | str[] | — | 提示（如未映射原因码、缺订单数） |
| `disclaimer` | str | — | 免责声明 |

`reasons[]`：`code`、`label_cn`、`label_en`、`qty`(int)、`refund_amount`(2)、`preventable`(bool)、`qty_share_pct`(2)、`refund_share_pct`(2)、`action`(str)。

`preventable`：`codes`(str[]，6 个可预防码的字典序)、`units`(int)、`share_pct`(2)、`refund_amount`(2)、`actions[]`（`code`/`label_cn`/`action`，只含可预防原因，按 `reasons` 顺序）。

可预防集合：`NOT_COMPATIBLE`、`MISSING_PARTS`、`QUALITY_UNACCEPTABLE`、`DAMAGED`、`WRONG_ITEM`、`ARRIVED_LATE`。

### 4.3 `health` 成功 JSON

顶层：`mode`（`health`）、`file`、`grade`（`CRITICAL`/`WARN`/`OK`）、`grade_label`（`生存线告警`/`接近阈值`/`正常`）、`critical_count`、`warn_count`、`metrics[]`、`context_metrics[]`、`actions[]`、`thresholds`、`disclaimer`。

`metrics[]`（3 条，顺序 ODR → 迟发 → 取消）：

| 字段 | 类型 | 单位/精度 | 说明 |
|---|---|---|---|
| `key` | str | — | `odr_pct` / `late_shipment_pct` / `pre_fulfillment_cancel_pct` |
| `label` | str | — | 中文名 |
| `value` | number | % | 原值，不四舍五入 |
| `unit` | str | — | 固定 `%` |
| `threshold` | number | % | 1.0 / 4.0 / 2.5 |
| `rule` | str | — | 规则文案 |
| `status` | str | — | `CRITICAL`/`WARN`/`OK` |
| `distance_to_threshold_pct` | number | 百分点，2 | 阈值 − 当前值，可为负 |
| `action` | str | — | 达标/警告/超限文案 |

`context_metrics[]`（3 条）：`negative_feedback_pct`（永远 `INFO`，0.55% 仅作背景）、`a_to_z_claims`（>0 为 `WARN`）、`policy_violations`（>0 为 `CRITICAL`）；字段为 `key`、`label`、`value`、`unit`、`status`、`note`。

`thresholds`：是「键 → 规则文案」的映射，不是数值：`{"odr_pct":"< 1%","late_shipment_pct":"< 4%","pre_fulfillment_cancel_pct":"< 2.5%"}`。

`actions[]`：任一 CRITICAL/WARN 硬指标各一条；A-to-Z >0 追加一条；政策违规 >0 追加一条；全部未触发时输出「维持周检：ODR、迟发、取消率连续 4 周在阈值内再谈放量」。

### 4.4 人类可读输出

- `reviews`：标题与总数、平均分、分布、1–2 星/3 星/4–5 星占比、可修率、8 个分类计数、Top3 问题与证据、差评逐条（评分/分类/标题/摘要）、规则口径、免责声明。
- `returns`：标题、退货件数/订单数、退货率、退款合计、可预防件数与占比、按原因列表（件数/占比/退款/是否可预防）、Top 原因与动作、未映射原因、口径、免责声明。
- `health`：标题与等级、三条硬指标（值/阈值/状态/距阈值）、三条背景指标、动作、阈值口径、免责声明。
- 百分比人类输出 2 位；缺值显示 `-` 或「未提供」。

`reviews` 人类输出实跑样例（命令见 §7.1，节选）：

```text
评论归因 · 24 条评论 ｜ 平均分 3.21
1–2 星 10 条（41.67%，负面率）｜ 3 星 12.50% ｜ 4–5 星 45.83%
可修复率 5/10 = 50.00%（质量做工/描述不符/清洁异味/使用门槛）

八类归因：
- 质量做工：2 条（占负面 20.00%，占全部 8.33%）｜可修复
- 尺寸容量：1 条（占负面 10.00%，占全部 4.17%）｜不可修复
...
Top3 问题与修补建议：
1. 质量做工（2 条，占负面 20.00%）
   原文：Leaks every time / The lid leaks every time I tilt the cup...
```

`returns` 人类输出实跑样例（命令见 §7.2，节选）：

```text
退货归因 · 37 件 ｜ 退款 1109.63 USD
退货率 11.56%（37 ÷ 320 订单）
可预防退货 24/37 = 64.86%（退款 719.76 USD）

Top 原因：
- 质量不可接受 [QUALITY_UNACCEPTABLE]：7 件（18.92%），退款 209.93｜可预防
- 商品有缺陷 [DEFECTIVE]：6 件（16.22%），退款 179.94｜不可预防
```

### 4.5 失败契约与退出码

失败时：

- `--json`：stdout `{"status":"INPUT_MISSING","missing":[...],"message":"..."}`；stderr `[INPUT_MISSING] ...`。
- 非 `--json`：仅 stderr 人类信息。
- `ERROR` 枚举在公共契约中存在，但本脚本所有可预期错误都归为 `INPUT_MISSING`。

| 场景 | `missing` | 退出码 |
|---|---|---|
| 文件不存在/不可读 | `["file"]` | 2 |
| CSV 只有表头 | `["file"]` | 2 |
| 缺必需列 | 缺失类名数组（如 `["body"]`） | 2 |
| 行内 rating/body/qty/refund 非法 | `[]` | 2 |
| health 缺字段 | 全部缺失键 | 2 |
| health 类型/范围错误（布尔/字符串/负值/非整数计数） | `[]`（`message` 指明字段） | 2 |
| health JSON 非法/顶层非对象 | `["file"]` | 2 |
| `--orders<=0` | `[]`（`message` 说明需大于 0） | 2 |
| 空 `file` 参数/文件不可读 | `["file"]` | 2 |
| argparse 错误（类型/未知参数/缺子命令） | `[]` | 2 |
| 成功（含 CRITICAL、全差评、未映射原因） | — | 0 |

## 5. 计算规则

### 5.1 评论评分与占比

- 总数 = 数据行数。
- 平均分 = 原始评分算术平均，保留 2 位。
- 分桶 = `int(rating)` 截断到 1–5：4.5 归 4，2.5 归 2，4.9 归 4；`"5"` 桶只含恰好 5（及 5.0）。
- 差评定义（计数）：`rating < 3`（因此 2.5 计入差评，归入 2 星桶）。
- 差评归因：只对 `rating <= 2` 的评论做分类，2.5 这类小数评分不参与归因（基线口径，已实测）。
- 1–2 星占比 = `one_two_star_count / total ×100`；`negative_rate_pct` 取同值。
- 3 星占比 = 桶 `"3"` / 总数；4–5 星占比 = (`"4"`+`"5"`) / 总数。
- 所有分母为 0 时（无评论）返回 0.0，但空文件已先失败，正常路径不会出现。

### 5.2 归因规则

- 对每条差评，把 `title + " " + body` 转小写、折叠空白，作为匹配文本。
- 对 8 个分类逐个统计关键词子串命中数；命中数 > 0 才参与竞争。
- 取命中数最多的分类；**并列时保留先出现分类**（分类顺序即上表），不做二次加权。
- 一条差评最多归一个分类；未命中任何关键词 → `unclassified_count +1`，`negative_reviews.category=未归类`。
- `categories[].count` 与 `attribution` 均只统计差评；好评不参与归因。
- `fixable_count` = 4 个可修分类的 count 之和；`fixable_rate_pct = fixable_count / negative_count`。
- `top_issues`：count>0 的分类按 count 降序、并列按分类顺序，取前 3；每条证据取该分类命中差评的前 2 条。
- 证据摘要：标题与正文拼接、空白折叠、截断到 180 字符；标题缺失时只用正文。

### 5.3 退货率与损失

- `returned_units` = Σqty（整数）；`total_refund` = Σrefund（2 位）。
- 退货率 = `returned_units / orders × 100`，只在给出订单时计算；orders 必须 > 0。
- 每个原因的 `qty_share_pct = qty / returned_units ×100`；`refund_share_pct = refund / total_refund ×100`；分母为 0 时取 0.0。
- `preventable.units`/`refund_amount` 只累加 6 个可预防码。
- `preventable.share_pct = units / returned_units ×100`。
- 原因排序：qty 降序 → refund 降序。
- `unmapped_codes` 去重保序；每个未映射码在 `missing` 写一条「未映射原因码：X；已归入 OTHER。」
- 退货率缺失只提示，不影响成功。

### 5.4 账号健康阈值

- 单项状态：`value >= threshold` → `CRITICAL`；`value >= threshold × 0.8` → `WARN`；否则 `OK`。等号归入更严重档。
- 阈值：ODR 1.0%、迟发 4.0%、发货前取消 2.5%。
- 负向反馈率 0.55%（示例）没有阈值，永远 `INFO`，不参与分级。
- A-to-Z：`> 0` → `WARN`，否则 `OK`。
- 政策违规：`> 0` → `CRITICAL`，否则 `OK`。
- 总等级：6 个项中任一 `CRITICAL` → `CRITICAL`；否则任一 `WARN` → `WARN`；否则 `OK`。
- `critical_count`/`warn_count` 统计全部 6 项（含 A-to-Z 与政策违规）。
- `distance_to_threshold_pct = threshold − value`，可为负；保留 2 位。
- 动作在超限/警告时给出具体整改方向；全部达标时给「维持周检」文案。

## 6. 已知行为与坑（现状）

| 现象 | 触发条件 | 现状行为（含实测退出码/输出） | 建议保留/修正 |
|---|---|---|---|
| 行级错误中止整表 | 第 2 行合法、第 3 行 rating=7 | 退出 2，stdout 只有错误体，无部分统计；`missing=[]` | 保留严格失败；建议信息带行号与原值 |
| 空 CSV | 只有表头 | 退出 2；`missing=["file"]`；信息「没有数据行」 | 修正：`missing` 不应称为文件缺失 |
| 缺必需列 | 评论缺 `body` | 退出 2；`missing=["body"]`；列出可用列 | 保留 |
| 可选列缺失 | 无 title/date/verified/variant | 不报错；title 用空串，其余不输出 | 保留；但 date/verified/variant 读了不用，属死字段 |
| 评分小数 | rating=4.5 | 平均 4.5；分桶 `"4"` 为 1；差评不增加（实跑） | 修正或明确：分桶截断会低估 5 星 |
| 差评小数 | rating=2.5 | 计入 `one_two_star_count`（条件为 <3）、分桶 `"2"`；但不参与归因（`attribution=0`、`negative_reviews=[]`），`fixable_rate` 分母仍为 1（实跑） | 保留基线行为；口径已写入 §5.1 |
| 零差评 | 全部 5 星 | 退出 0；negative=0、negative_share=0、fixable_rate=0、top_issues=[]、negative_reviews=[] | 保留；需避免下游除以 0 |
| 归因并列 | 同时命中「质量」与「清洁」且次数相同 | 取分类顺序更靠前者（质量做工），无警告 | 保留确定性；可在 `rules` 说明 |
| 关键词子串误判 | `clean` 出现在「clean design」 | 归入「清洁异味」，可能误判 | 修正：需要词边界或短语白名单 |
| 原因码精确匹配 | `包装破损` | 落 `OTHER`，`unmapped_codes=["包装破损"]`，`missing` 一条，退出 0（实跑） | 保留严格；补别名或改包含匹配 |
| `reason_text` 无效 | 退货原因说明写清原因但码未知 | 仍归 `OTHER`；该列完全不参与归因 | 修正：说明列或参与归因 |
| 欧洲金额 | refund=`"1.234,56"` | 解析为 1.23456，输出 `total_refund=1.23`，退出 0（实跑） | 修正：与 06 的清洗规则统一 |
| 退货件数小数 | qty=2.5 | 退出 2，`missing=[]`；`2.0` 可接受 | 保留；信息应提示整数件 |
| 订单数缺失/为 0 | 不传 `--orders` / 传 0 | 不传：退货率 null + 提示，退出 0；传 0：退出 2，`missing=[]`，`message` 要求大于 0 | 保留区分 |
| health 缺字段 | 缺 `policy_violations` | 退出 2；`missing=["policy_violations"]` | 保留；一次列全缺失键 |
| health 类型错误 | `policy_violations=true`、`a_to_z_claims=1.5`、`odr_pct=-1`、`odr_pct="1.0"` | 均退出 2；`missing=[]`，`message` 指明字段（如「字段 odr_pct 必须是数字」）；布尔不当作数字（实跑） | 保留严格校验；建议把字段名放进 `missing` 便于程序处理 |
| health 等号边界 | ODR 恰为 1.0 | 判 `CRITICAL`；WARN 起点为阈值 80% | 保留；文档需写明含端点 |
| A-to-Z 单项升级 | 其他全 OK、A-to-Z=1 | 总等级 `WARN`，warn_count=1（实跑） | 保留 |
| 负向反馈率不参与分级 | 差评率任意高 | 永远 `INFO`，不影响等级 | 修正或说明：当前模型忽略差评率 |
| 成功恒 0 | `grade=CRITICAL` | 退出 0（实跑） | 保留；下游按 grade 判定 |

## 7. 差分测试基准（必须可复现）

工作目录：`Agents/07_Review_Ops_Agent`。

### 7.1 reviews

```bash
python scripts/review_ops.py reviews --file examples/sample-reviews.csv --json
```

期望（退出 0）：

- `total_reviews=24`、`average_rating=3.21`。
- `rating_distribution={"1":4,"2":6,"3":3,"4":3,"5":8}`。
- `one_two_star_count=10`、`one_two_star_pct=41.67`、`negative_count=10`、`negative_share_pct=41.67`、`three_star_pct=12.5`、`positive_pct=45.83`。
- `attribution={"质量做工":2,"尺寸容量":1,"功能故障":2,"电池续航":1,"清洁异味":1,"物流包装":1,"描述不符":1,"使用门槛":1}`。
- `unclassified_count=0`、`fixable_count=5`、`fixable_rate_pct=50.0`。
- `top_issues` 依次为「质量做工」2 条（占负面 20.00%）、「功能故障」2 条（20.00%）、「尺寸容量」1 条（10.00%）；前两者同数，按分类顺序排列。
- `negative_reviews` 共 10 条，按 CSV 顺序。

### 7.2 returns

```bash
python scripts/review_ops.py returns --file examples/sample-returns.csv --orders 320 --json
```

期望（退出 0）：

- `returned_units=37`、`orders=320`、`return_rate_pct=11.56`、`total_refund=1109.63`。
- `reasons[0]={code:"QUALITY_UNACCEPTABLE",label_cn:"质量不可接受",qty:7,refund_amount:209.93}`，`qty_share_pct=18.92`、`refund_share_pct=18.92`。
- `reasons` 共 10 个原因码，排序按件数降序。
- `preventable.units=24`、`share_pct=64.86`、`refund_amount=719.76`；`preventable.codes` 为 6 个码的字典序。
- `unmapped_codes=[]`、`missing=[]`。

### 7.3 health

```bash
python scripts/review_ops.py health --file examples/sample-health.json --json
```

期望（退出 0）：

- `grade=CRITICAL`、`critical_count=1`、`warn_count=2`。
- `metrics[0]={"key":"odr_pct","value":1.35,"threshold":1.0,"status":"CRITICAL","distance_to_threshold_pct":-0.35}`。
- `metrics[1]={late_shipment_pct:3.6,threshold:4.0,status:WARN,distance:0.4}`。
- `metrics[2]={pre_fulfillment_cancel_pct:1.9,threshold:2.5,status:OK,distance:0.6}`。
- `context_metrics`：负向反馈 0.55 `INFO`；A-to-Z 5 `WARN`；政策违规 0 `OK`。

### 7.4 边界与失败差分测试

| 命令要点 | 期望 |
|---|---|
| reviews 第 3 行 rating=7（前一行合法） | 退出 2，无部分输出；`missing=[]` |
| reviews 全部 5 星（3 条） | 退出 0；平均 5.0、`"5":3`、negative=0、`top_issues=[]` |
| reviews rating=4.5（1 条） | 退出 0；平均 4.5、`"4":1`、negative=0 |
| reviews rating=2.5（1 条） | 退出 0；`one_two_star_count=1`、桶 `"2"`、`attribution` 全 0、`negative_reviews=[]` |
| reviews `body` 为空 | 退出 2，`missing=[]` |
| returns qty=2.5 | 退出 2，`missing=[]` |
| returns 退款 -5 | 退出 2，`missing=[]` |
| returns 不传 `--orders` | 退出 0；`return_rate_pct=null`，`missing` 含订单提示 |
| returns `--orders 0` / `-5` | 退出 2；`missing=[]`，`message`「--orders 必须大于 0」 |
| returns 原因码「包装破损」 | 退出 0；该行归 `OTHER`，`unmapped_codes=["包装破损"]`，`missing` 一条 |
| returns 退款 `"1.234,56"` | 退出 0；`total_refund=1.23`（错误解析） |
| health 缺 `policy_violations` | 退出 2；`missing=["policy_violations"]` |
| health `policy_violations=true` | 退出 2；`missing=[]`，`message` 指明该字段必须是数字 |
| health `a_to_z_claims=1.5` | 退出 2；`missing=[]`，`message` 指明必须是整数 |
| health `odr_pct=-1` | 退出 2；`missing=[]`，`message` 指明不能为负 |
| health 自定义 JSON，A-to-Z=1、其余达标 | 退出 0；`grade=WARN`、`warn_count=1` |
| health 传入 CSV 当 JSON | 退出 2；`missing=["file"]`，信息「不是合法 JSON」 |
| health + `--fail-on-critical`，等级 CRITICAL | 退出 1（默认不带该参数时仍为 0） |

## 8. 未完整刻画/待确认

- 2.5 分评论「计入差评计数但不参与归因」的基线口径已按实测保留（§5.1、§6），是否属业务预期待产品确认。
- 关键词匹配是子串匹配，误判率未量化；是否需要词边界/否定词处理未确认。
- 07 没有外部阈值/关键词配置，修改必须改代码；是否应外置未确认。
- `date`/`verified`/`variant` 读取但不输出，是否应参与输出未确认。
- 非 UTF-8 编码、分号/TSV、中文全角标点未测试。
- `status="ERROR"` 无触发路径；是否保留未确认。
- health 的整数计数允许 `1.0`，是否应只接受 JSON 整数未确认。
- 负向反馈率永远 INFO，是否应纳入分级未确认。
