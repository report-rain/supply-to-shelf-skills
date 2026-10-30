# 06 广告投放指标（ads_metrics.py）· 行为规格冻结

> 对象：`Agents/06_Ads_Agent/scripts/ads_metrics.py`
> 实测环境：Windows PowerShell 5 + Python 3.12.0；基准日 2026-10-30。
> 本文只描述行为，不含实现细节；所有示例数值均来自实跑。

## 1. 范围与脚本（职责 + 依赖配置/上游）

- `calc`：由「售价、产品成本、Referral%、FBA 费、退货预留、计划广告预留、目标 ACOS」推算广告前贡献、盈亏线 ACOS/ROAS、目标 ROAS、可承受 CPC、TACOS。
- `diagnose`：在同一成本模型下读取 campaign 级广告报表 CSV，逐行算 CTR/CVR/CPC/ACOS/ROAS/净贡献，给出 P0/P1/P2/INFO 判定、主杠杆、单轮动作与「本轮不动」清单。
- 边界：只读本地文件、只输出建议；不接平台 API、不改预算/出价、不写回任何文件。
- 上游依赖：`Agents/02_Cost_Pricing_Agent/scripts/us_fees.json` 是唯一费率来源声明。06 只校验该文件存在、可解析为 JSON 对象，并读取 `_meta.updated` 与 `_meta.sources`；**不读取任何具体费率数值**，Referral/FBA 仍由 CLI 显式传入。
- 该配置缺失、不可读或非法 JSON 时，`calc` 与 `diagnose` 都会直接失败（退出码 2），即便本次计算并不需要费率。
- 路径按脚本位置解析为 `<repo>/Agents/02_Cost_Pricing_Agent/scripts/us_fees.json`，随仓库移动而移动。
- `_meta.updated` 缺失时输出字符串 `[INPUT_MISSING] _meta.updated`；`sources` 缺失时输出空数组。

## 2. CLI 契约

通用规则：

- 必须给出子命令 `calc` 或 `diagnose`；缺失或拼错由 argparse 报错，退出 2。
- `--json` 定义在子命令上，必须写在子命令之后；写在子命令之前会被当成未知参数（仍按 `--json` 出现在 argv 中处理错误输出）。
- 参数解析错误也遵循统一错误契约：argv 中任意位置出现 `--json` 时 stdout 输出 JSON，stderr 输出人类信息，退出 2。
- 成功路径固定退出 0，不因 P0、负毛利、亏损而返回非零。

### 2.1 `calc`

| 参数名 | 类型 | 必填 | 默认值 | 取值范围/枚举 | 说明 |
|---|---|---|---|---|---|
| `--platform` | str | 是 | — | `amazon_us` / `tiktok_us` | 只影响平台标签与平台提示，不改变公式 |
| `--price` | float | 是 | — | `> 0` | 售价 USD；`0`、负数失败 |
| `--product-cost` | float | 是 | — | `>= 0` | 单件产品成本/落地成本 USD |
| `--referral` | float | 是 | — | `0 < x <= 100` | 平台佣金百分比；`0` 也失败，与错误文案「0–100」不一致 |
| `--fba-fee` | float | 是 | — | `>= 0` | FBA/履约固定费 USD；TikTok 场景通常传 0 |
| `--target-acos` | float | 是 | — | `0 < x < 100` | 目标 ACOS%；`0` 与 `100` 均失败 |
| `--ads-pct` | float | 是 | — | `>= 0` | 计划广告预留%，只用于「计划广告后贡献」 |
| `--returns-pct` | float | 是 | — | `>= 0` | 退货预留%，计入广告前贡献 |
| `--cvr` | float | 否 | `None` | `0 < x <= 100` | 转化率%；给出才计算可承受 CPC；`0` 失败 |
| `--ad-spend` | float | 否 | `None` | 无独立校验 | 总广告花费 USD；需与 `--total-sales` 同时给 |
| `--total-sales` | float | 否 | `None` | 与 `--ad-spend` 同时给时 `> 0` | 总销售额 USD；单独给不产生 TACOS |
| `--json` | flag | 否 | `false` | — | 结构化输出 |

冲突与隐式假设：

- `--ad-spend` 与 `--total-sales` 必须成对；只给一个时 TACOS 为 `null`，并输出 `[INPUT_MISSING]` 提示，但退出 0。
- `--ad-spend` 没有非负校验，负值可产生负 TACOS。
- 未给 `--cvr` 时 `affordable_cpc` 为 `null`，并输出提示；未给 `--returns-pct` 的提示在 calc 中不可达（该参数必填）。
- `--referral` 必须严格大于 0，`--fba-fee` 可为 0。

### 2.2 `diagnose`

| 参数名 | 类型 | 必填 | 默认值 | 取值范围/枚举 | 说明 |
|---|---|---|---|---|---|
| `--file` | str | 是 | — | 存在的 CSV 路径 | campaign 报表；相对路径按当前工作目录 |
| `--platform` | str | 是 | — | `amazon_us` / `tiktok_us` | 同 calc |
| `--price` | float | 是 | — | `> 0` | 同 calc |
| `--product-cost` | float | 是 | — | `>= 0` | 同 calc |
| `--referral` | float | 是 | — | `0 < x <= 100` | 同 calc |
| `--fba-fee` | float | 是 | — | `>= 0` | 同 calc |
| `--target-acos` | float | 是 | — | `0 < x < 100` | 同 calc |
| `--ads-pct` | float | 否 | `None` | `>= 0`（隐式按 0） | 仅填充 cost_model，不参与盈亏线、ROAS 判定 |
| `--returns-pct` | float | 否 | `None` | `>= 0`（隐式按 0） | 未给时按 0% 预留并在 `missing` 留痕 |
| `--cvr` | float | 否 | `None` | `0 < x <= 100` | 基准 CVR；仅当某 campaign CVR 为 0 时用于可承受 CPC |
| `--json` | flag | 否 | `false` | — | 结构化输出 |

冲突与隐式假设：

- `diagnose` 不提供 `--ad-spend`/`--total-sales`，因此整体 TACOS 永远用「总花费 ÷ 总销售额」计算，与 calc 的 TACOS 输入无关。
- `--ads-pct` 不影响 `break_even_acos`、`break_even_roas`、分级或动作，只影响 `planned_ad_provision` 与 `contribution_after_planned_ads`。
- `--returns-pct` 省略即 0%，会抬高盈亏线 ROAS；`missing` 会提示，但退出 0。
- `diagnose` 的 `missing` 不会出现「TACOS 需 ad-spend」的提示（该提示只属于 calc）。

### 2.3 参数组合与冲突矩阵

| 组合 | 现状行为 |
|---|---|
| 只给 `--ad-spend` 或只给 `--total-sales` | TACOS 为 null；`missing` 追加「需同时给两者」提示；退出 0 |
| `--ad-spend` 与 `--total-sales` 都给 | 计算 TACOS；`total_sales<=0` 则退出 2 |
| 未给 `--cvr` | `affordable_cpc=null`；`missing` 一条；退出 0 |
| `--cvr 0` | 退出 2（范围 `(0,100]`，文案写 0–100） |
| diagnose 给 `--ads-pct` | 只改计划广告后贡献，不改盈亏线与分级 |
| `--json` 写在子命令前 | 视为未知参数；因 argv 含 `--json`，仍输出 JSON 错误体，退出 2 |
| `--referral 0` | 退出 2，尽管文案写「0–100」 |
| 行级错误与文件级错误同时存在 | 先报文件/列，后报行；只报第一个致命错误 |

## 3. 输入契约

### 3.1 campaign CSV

- 编码：UTF-8；允许文件头单个 BOM（按 `utf-8-sig` 读取）。UTF-8 BOM 重复或出现在列名中间时列名匹配会失败。
- 分隔符：逗号；引号内逗号由标准 CSV 解析处理；不支持分号/TSV。
- 首行为表头，数据行从第 2 行开始计数（错误信息里的行号即物理行号）。
- 列名匹配：去首尾空白、大小写不敏感；中文别名需精确匹配。
- 六类列全部必需；任一缺失即整表失败，错误信息列出缺失的英文类名与全部可用列。
- 空文件或只有表头：失败，`missing=["file"]`，信息为「广告报表没有数据行」。
- 空 campaign 名：保留为 `未命名`；重复 campaign 行不去重、不合并。

| 内部字段 | 允许列名（按优先级） | 必填 | 类型/单位 |
|---|---|---|---|
| campaign | `campaign`, `campaign_name`, `广告名称`, `广告活动`, `广告组合`, `计划名称` | 是 | 文本 |
| impressions | `impressions`, `imps`, `曝光量`, `曝光`, `展示量` | 是 | 非负整数（件/次） |
| clicks | `clicks`, `点击量`, `点击数`, `点击` | 是 | 非负整数（次） |
| spend | `spend`, `cost`, `花费`, `消耗`, `花费金额` | 是 | 非负 USD |
| orders | `orders`, `conversions`, `订单数`, `订单`, `成交订单` | 是 | 非负整数（单） |
| sales | `sales`, `gmv`, `revenue`, `销售额`, `成交金额`, `广告销售额` | 是 | 非负 USD |

### 3.2 数字清洗规则（campaign CSV）

1. 先转字符串并去首尾空白；删除所有 `$`、`USD` 和空格（`USD` 仅删除大写字面）。
2. 空串、`-`、`—`、`N/A`、`n/a`、`nan` 视为缺失，返回 `None`。
3. 记录前导负号，剥掉负号后继续解析，最后再还原符号。
4. 同时含逗号与小数点：若最后一个逗号在小数点之后，按欧洲格式（删小数点、逗号变小数点）；否则删掉逗号按美式千分位。
5. 只含逗号：逗号后恰好 3 位视为小数逗号（`1,234` → 1.234）；否则视为千分位并删除逗号（`1,23` → 123）。
6. 仅含小数点：按普通小数解析（`1.234` 是 1.234，不是千分位）。
7. 解析失败返回 `None`；随后按字段类型校验。
8. 整数字段使用 Python `round()`（银行家舍入）：`0.5→0`、`1.5→2`、`2.5→2`（实跑确认）。

实跑样例：`"$122.00"→122.0`；`"1,234.56"→1234.56`；`"1.234,56"→1234.56`；`"USD 99.99"→99.99`。

### 3.3 行级校验与失败顺序

- 先解析列映射与必需列，再逐行解析；任何一行失败即中止整表，不输出部分结果。
- 整数字段（impressions/clicks/orders）为空、非法或 `< 0` → 失败，信息含行号与字段名。
- 金额字段（spend/sales）为空、非法或 `< 0` → 失败。
- 行错误 `missing=[]`；文件/列错误才填充 `missing`。

### 3.4 CLI 数值语义

- argparse 的 float/int 转换失败在解析阶段退出 2（如 `--price abc`）。
- 业务校验在解析后执行，错误信息 `[INPUT_MISSING]` 打头，JSON 中该前缀被剥离。
- 百分比参数一律按「百分数」传（`15` 表示 15%），公式内再除以 100。

### 3.5 文件与编码边界

- 只支持逗号分隔的 UTF-8 CSV；UTF-8 BOM 由 `utf-8-sig` 吞掉一次。
- 列名比较前会 trim 与转小写，但读取时仍用原表头键；表头含前后空格可正常取到值。
- 支持引号包裹的逗号与换行字段；不支持分号/制表符方言。
- 同名列/重复表头未做去重，行为依赖 CSV 解析器的「后者覆盖」语义，未冻结。
- 路径原样回显到 JSON `file`，不解析为绝对路径。

## 4. 输出契约

### 4.1 `calc` 成功 JSON

顶层：

| 字段 | 类型 | 单位/精度 | 说明 |
|---|---|---|---|
| `mode` | str | — | 固定 `calc` |
| `platform` | str | — | 回显枚举 |
| `platform_label` | str | — | `Amazon.com US` / `TikTok Shop US` |
| `currency` | str | — | 固定 `USD` |
| `metrics` | object | — | 见下表 |
| `missing` | str[] | — | 缺失输入提示；成功时也可能非空（退出仍 0） |
| `platform_note` | str | — | 平台口径提示 |
| `fee_config` | object | — | `path`、`updated`、`sources[]`、`shared_with` |
| `disclaimer` | str | — | 固定免责声明 |

`metrics`：

| 字段 | 类型 | 单位 | 精度 | 说明 |
|---|---|---|---|---|
| `price` | number | USD | 2 位显示 | 原样回显 |
| `product_cost` | number | USD | 2 位显示 | 原样回显 |
| `referral_pct` | number | % | 原样 | 输入百分比 |
| `referral_fee` | number | USD | 2 | 售价 × Referral% |
| `fba_fee` | number | USD | 2 | 输入值 |
| `returns_pct` | number | % | 原样 | 输入百分比 |
| `returns_provision` | number | USD | 2 | 售价 × 退货% |
| `planned_ads_pct` | number | % | 原样 | 输入百分比 |
| `planned_ad_provision` | number | USD | 2 | 售价 × 广告% |
| `pre_ad_contribution` | number | USD | 2 | 广告前单件贡献 |
| `pre_ad_margin_pct` | number | % | 2 | 广告前贡献 ÷ 售价 |
| `contribution_after_planned_ads` | number | USD | 2 | 扣除计划广告预留 |
| `break_even_acos` | number | 比率 | 4 | 盈亏线 ACOS 小数（负贡献时为负） |
| `break_even_acos_pct` | number | % | 2 | 盈亏线 ACOS 百分数（负贡献时为负） |
| `break_even_roas` | number\|null | 比率 | 2 | 广告前贡献 > 0 才有值 |
| `target_acos_pct` | number | % | 原样 | 输入值 |
| `target_roas` | number | 比率 | 2 | 100 ÷ 目标 ACOS |
| `cvr_pct` | number\|null | % | 原样 | 输入值 |
| `affordable_cpc` | number\|null | USD | 2 | 售价 × CVR × 目标 ACOS |
| `tacos` | number\|null | 比率 | 4 | 广告花费 ÷ 总销售额 |
| `tacos_pct` | number\|null | % | 2 | TACOS × 100 |
| `model_warning` | str\|null | — | — | 广告前贡献 ≤ 0 时的警示 |

### 4.2 `diagnose` 成功 JSON

顶层字段：`mode`（`diagnose`）、`platform`、`platform_label`、`currency`、`file`（回显原始路径）、`cost_model`（字段同 4.1 `metrics`）、`target_roas`、`total`、`priority_counts`、`campaigns[]`、`global_do_not_touch[]`、`discipline`、`missing[]`、`platform_note`、`fee_config`、`disclaimer`。

`total`：`campaigns`(int)、`impressions`(int)、`clicks`(int)、`spend`(USD,2)、`orders`(int)、`sales`(USD,2)、`roas`(比率,2\|null)、`tacos_pct`(% ,2\|null)、`net_contribution`(USD,2)。

`priority_counts`：固定四个键 `P0`、`P1`、`P2`、`INFO`，值为行数。

每个 `campaigns[]` 元素：

| 字段 | 类型 | 单位 | 精度 | 说明 |
|---|---|---|---|---|
| `campaign` | str | — | — | 列值或 `未命名` |
| `impressions` | int | 次 | — | — |
| `clicks` | int | 次 | — | — |
| `spend` | number | USD | 2 | — |
| `orders` | int | 单 | — | — |
| `sales` | number | USD | 2 | — |
| `ctr_pct` | number | % | 2 | 点击 ÷ 曝光，曝光 0 时为 0.0 |
| `cvr_pct` | number | % | 2 | 订单 ÷ 点击，点击 0 时为 0.0 |
| `cpc` | number\|null | USD | 2 | 花费 ÷ 点击，点击 0 时 null |
| `acos_pct` | number\|null | % | 2 | 花费 ÷ 销售额，销售额 0 时 null |
| `roas` | number\|null | 比率 | 2 | 销售额 ÷ 花费，花费 0 时 null |
| `affordable_cpc` | number | USD | 2 | campaign CVR 为 0 时可用 `--cvr` 兜底，否则 0.0 |
| `net_contribution` | number | USD | 2 | 广告前贡献率 × 销售额 − 花费 |
| `grade` | str | — | — | `P0`/`P1`/`P2`/`INFO` |
| `primary_lever` | str | — | — | 主杠杆文案 |
| `action` | str | — | — | 单轮动作文案 |
| `do_not_touch` | str[] | — | — | 本轮不动清单 |

`campaigns` 排序：先按等级 `P0<P1<P2<INFO`，同级按 ROAS 升序；ROAS 为 null 时按 -1 参与排序。

### 4.3 人类可读输出

- `calc`：标题行、售价/成本/Referral/FBA 行、退货与广告预留行、广告前贡献及占售价、盈亏线 ACOS/ROAS、目标 ACOS/ROAS、可选可承受 CPC 与 TACOS、逐条 `missing`、平台提示、口径、费率来源路径与 `_meta.updated`。
- `diagnose`：标题（含 campaign 数）、盈亏线/目标 ROAS/ACOS、整体 ROAS/TACOS/净贡献、分级计数、`missing`、空行；每个 campaign 四行（等级/名称/ROAS/ACOS/花费/订单、杠杆、动作、本轮不动）；末尾全局不动清单、纪律、平台提示、口径、费率来源。
- 数值为 null 时人类输出用 `-`；百分比固定 2 位，金额 2 位。

`calc` 人类输出实跑样例（命令见 §7.1）：

```text
广告盈亏线 · Amazon.com US · USD
售价 29.99 ｜ 产品成本 7.99 ｜ Referral 15.00% = 4.50 ｜ FBA 5.93
退货预留 3.00% = 0.90 ｜ 计划广告预留 10.00% = 3.00
广告前贡献 10.67 （占售价 35.58%）
盈亏线 ACOS 35.58% ｜ 盈亏线 ROAS 2.81
目标 ACOS 25.00% ｜ 目标 ROAS 4.00
可承受 CPC 0.60（售价 × CVR 8.00% × 目标 ACOS）
TACOS 34.61%（总广告花费 ÷ 总销售额）
平台提示：Amazon US：Referral 与 FBA 费用须与 02 的 us_fees.json、卖家中心费率卡一致。
口径：费率/阈值口径为编写时公开口径，发布前请到卖家中心与官方费率卡复核。
费率来源：.../Agents/02_Cost_Pricing_Agent/scripts/us_fees.json (_meta.updated=2026-10-30)
```

### 4.4 失败契约与退出码

失败时：

- `--json`：stdout 输出 `{"status": "...", "missing": [...], "message": "..."}`；stderr 输出 `[INPUT_MISSING] ...`。
- 非 `--json`：仅 stderr 输出 `[INPUT_MISSING] ...`。
- `status` 实际只会出现 `INPUT_MISSING`；`ERROR` 在公共契约中已定义但本脚本没有触发路径。

| 场景 | `missing` | 退出码 |
|---|---|---|
| 费率配置缺失/不可读/非对象 | `[]` | 2 |
| 广告报表文件不存在/不可读 | `["file"]` | 2 |
| 广告报表只有表头 | `["file"]` | 2 |
| 缺列 | 缺失的类名数组，如 `["sales"]` | 2 |
| 行内数字缺失/非法/负数 | `[]` | 2 |
| 业务参数越界（价格、百分比等） | `[]` | 2 |
| argparse 错误（枚举、类型、未知参数） | `[]` | 2 |
| 成功（含 P0、负毛利、missing 非空） | — | 0 |

## 5. 计算规则

### 5.1 成本模型（calc / diagnose 共用）

- Referral 费 = 售价 × Referral% ÷ 100。
- 退货预留 = 售价 × 退货% ÷ 100。
- 计划广告预留 = 售价 × 广告% ÷ 100。
- 广告前贡献 = 售价 − 产品成本 − Referral 费 − FBA − 退货预留。
- 广告前贡献率 = 广告前贡献 ÷ 售价；百分数再 ×100。
- 计划广告后贡献 = 广告前贡献 − 计划广告预留。
- 盈亏线 ACOS = 广告前贡献 ÷ 售价（小数 4 位、百分数 2 位）。
- 盈亏线 ROAS = 售价 ÷ 广告前贡献，仅在广告前贡献 > 0 时有值；否则 null（此时 ACOS 仍可能为负值并输出）。
- 目标 ROAS = 100 ÷ 目标 ACOS。
- 可承受 CPC = 售价 × (CVR÷100) × (目标 ACOS÷100)；未给 CVR 为 null。
- TACOS = 广告花费 ÷ 总销售额；两者缺一为 null；总销售额 ≤ 0 直接失败。
- 广告前贡献 ≤ 0 时写入 `model_warning`，退出码仍为 0。

### 5.2 campaign 派生指标

- CTR = 点击 ÷ 曝光 ×100；曝光 0 → 0。
- CVR = 订单 ÷ 点击 ×100；点击 0 → 0。
- CPC = 花费 ÷ 点击；点击 0 → null。
- ACOS = 花费 ÷ 销售额 ×100；销售额 0 → null。
- ROAS = 销售额 ÷ 花费；花费 0 → null。
- 可承受 CPC：优先用 campaign CVR；若 campaign CVR 为 0 且给了 `--cvr`，用全局 CVR；否则 0.0。
- 净贡献 = 广告前贡献率 × 销售额 − 花费；零订单时为负花费。

### 5.3 判定顺序（严格按此顺序，先命中先返回）

1. 曝光 < 1000 → `INFO`（数据不足）。
2. 花费 ≤ 0 → `INFO`（无有效花费）。
3. 点击 ≥ 30 且订单 = 0 → `P0`（零订单止血）。
4. 盈亏线 ROAS 为 null，或 ROAS < 盈亏线 ROAS × 0.5 → `P0`。
5. ROAS < 盈亏线 ROAS → `P1`。
6. ROAS < 目标 ROAS → `P1`。
7. 其余 → `P2`。

要点：

- 曝光不足优先于零花费，因此「曝光 <1000 且花费 0」仍走「数据不足」文案。
- ROAS 为 null 时按 0 参与第 4 步；若盈亏线 ROAS 为 null（广告前贡献 ≤ 0），所有非 INFO 行直接 P0。
- 边界为严格小于：ROAS 恰好等于盈亏线 → P1 的第 6 步或 P2；ROAS 恰好等于目标 → P2。
- 点击 30 是含端点的零订单阈值；点击 29 且订单 0 时 ROAS = 0，会落到第 4 步变 P0。

判定场景表（盈亏线 ROAS=2.81、目标 ROAS=4.00 时）：

| 场景 | 命中步骤 | 结果 |
|---|---|---|
| 曝光 500、花费 10 | 1 | `INFO`（数据不足） |
| 曝光 2000、花费 0 | 2 | `INFO`（无有效花费） |
| 点击 30、订单 0、花费 50 | 3 | `P0`（零订单） |
| 点击 29、订单 0、花费 50 | 4（ROAS 0 < 1.4） | `P0` |
| 花费 100、销售额 200（ROAS 2.0） | 5 | `P1` |
| 花费 100、销售额 350（ROAS 3.5） | 6 | `P1` |
| 花费 100、销售额 400（ROAS 4.0） | 无 | `P2` |
| 广告前贡献 ≤0（盈亏线 ROAS null） | 4 | `P0` |

### 5.4 动作生成

- INFO：曝光不足文案或「无有效花费」；主杠杆「不动（数据不足）」。
- P0 零订单（点击≥30）：主杠杆「转化承接」；压预算、查 Listing/价格/评论，暂停新增关键词。
- P0 其他：主杠杆「出价/预算」；预算最低档、出价压到可承受 CPC 以内、否定高花费零单词。
- P1 且 ROAS < 盈亏线：主杠杆「关键词/出价」；出价下调 10–15%，总预算不动。
- P1 且 ROAS ≥ 盈亏线但 < 目标：主杠杆「转化率」；预算与出价不动，只优化承接，3–7 天复测。
- P2：主杠杆「预算」；预算 +20%，出价最多 +10%，观察 3 天。
- 文案中的可承受 CPC 若为 null，显示「无法计算」。

### 5.5 整体汇总与除零

- 总曝光/点击/订单为整数求和；总花费/销售额为浮点求和后保留 2 位。
- 整体 ROAS：总花费为 0 → null；整体 TACOS：总销售额为 0 → null。
- 整体净贡献 = 广告前贡献率 × 总销售额 − 总花费，不做逐行求和，避免四舍五入误差。
- `priority_counts` 覆盖四个等级，未出现的等级计 0。

### 5.5 手算校核样例

| 项目 | 算式 | 结果 |
|---|---|---|
| Referral 费 | 29.99 × 15% | 4.50（4.4985 四舍五入） |
| 退货预留 | 29.99 × 3% | 0.90 |
| 广告前贡献 | 29.99 − 7.99 − 4.50 − 5.93 − 0.90 | 10.67 |
| 盈亏线 ACOS | 10.67 ÷ 29.99 | 35.58% |
| 盈亏线 ROAS | 29.99 ÷ 10.67 | 2.81 |
| 可承受 CPC | 29.99 × 8% × 25% | 0.5998 → 0.60 |
| 单行净贡献 | 0.3558 × 719.76 − 122 | 134.08 |
| 整体 TACOS | 799.27 ÷ 2309.23 | 34.61% |

## 6. 已知行为与坑（现状）

| 现象 | 触发条件 | 现状行为（含实测退出码/输出） | 建议保留/修正 |
|---|---|---|---|
| 缺费率配置即全失败 | 删除/移走 `02/.../us_fees.json` | calc 与 diagnose 都在读数据前失败：JSON `status=INPUT_MISSING`、`missing=[]`、退出 2；提示「未找到 02 模块费率配置」 | 保留存在性校验；但 06 实际不使用费率数值，建议明示「仅校验元数据」 |
| 缺列整表失败 | 报表缺 `sales` 等任一必需列 | 退出 2；`missing=["sales"]`；信息列出缺失类名与可用列 | 保留；可考虑一次列出全部缺失列（现已列出） |
| 空 CSV | 只有表头 | 退出 2；`missing=["file"]`；信息「广告报表没有数据行」 | 修正：空 CSV 并非文件缺失，`missing` 应改为 `["rows"]` 或 `[]` |
| 空白单元格 | 花费写 `-`/`N/A`/空 | `_num` 返回 None，按行失败退出 2；`missing=[]` | 保留；可增加行号+列名+原值 |
| 千分位/货币符号 | `"1,234.56"`、`"$122.00"`、`"USD 99.99"` | 正确清洗为 1234.56 / 122 / 99.99（实跑） | 保留 |
| 欧洲小数 | `"1.234,56"` | 识别为 1234.56（实跑） | 保留；注意 `1,23` 会被当成 123 |
| 负号 | `-1.00` | 清洗后仍为负，spend/sales 校验失败，退出 2；错误信息不含字段级原值 | 保留拒绝；建议信息带列名 |
| 整数字段小数 | `impressions=2.5` | `round()` 银行家舍入：2.5→2、1.5→2、0.5→0（实跑）；不报错 | 修正或明确文档：建议显式「四舍五入」而非银行家舍入 |
| 数据不足 | 曝光 <1000 | 行级 `grade=INFO`，动作文案「曝光 N < 1,000，数据不足」；无 notes 字段 | 保留；可把数据不足原因结构化输出 |
| 零花费但曝光足 | 曝光≥1000、spend=0 | `grade=INFO`，动作「无有效花费，无法判断」；ROAS 为 null | 保留 |
| 零订单判定 | 点击≥30 且订单=0 | `grade=P0`，转化承接文案（实跑 PB-Longtail 点击 96、订单 0） | 保留 |
| 盈亏线 ROAS 为 null | 广告前贡献 ≤ 0 | 所有非 INFO 行 P0；`break_even_roas=null` 但 `break_even_acos_pct` 可为负（实跑 -4.46） | 保留警示；建议同时输出「不可投放」结构化标记 |
| calc 缺失提示 | 未给 `--cvr` / 未给 `--ad-spend`+`--total-sales` | `missing` 含两条 `[INPUT_MISSING]` 文本，退出 0（实跑） | 保留；建议分离 `notes` 与 `missing` |
| diagnose 缺退货率 | 未传 `--returns-pct` | 按 0% 计算，盈亏线由 35.58% 升至 38.58%，ROAS 2.81→2.59（实跑），退出 0 | 保留；但应默认建议值或显式标红 |
| diagnose 的 TACOS 提示缺失 | 未传 ad-spend（该子命令无此参数） | `missing` 只有退货提示，不提示 TACOS | 修正：说明 TACOS 由报表整体计算 |
| `--ads-pct` 在诊断中无效 | diagnose 传任意 `--ads-pct` | 只改 `planned_ad_provision`/`contribution_after_planned_ads`，分级与盈亏线不变 | 保留但文档需写明 |
| Referral=0 被拒 | `--referral 0` | 退出 2，信息「必须是 0–100 的百分比」，与文案范围不符 | 修正文案为「(0,100]」 |
| `--cvr 0` 被拒 | `--cvr 0` | 退出 2 | 保留（0 无意义），修正文案 |
| 参数错误 JSON 化 | `--platform ebay_us --json` | stdout JSON「参数错误：invalid choice...」，退出 2（实跑） | 保留 |
| 成功恒 0 | 任意 P0/负毛利 | 退出 0（实跑负毛利 calc） | 保留；下游需读字段而非退出码 |

## 7. 对拍基准（必须可复现）

工作目录：`Agents/06_Ads_Agent`。以下命令在 PowerShell 5 中可直接执行。

### 7.1 calc（完整输入）

```bash
python scripts/ads_metrics.py calc --platform amazon_us --price 29.99 ^
  --product-cost 7.99 --referral 15 --fba-fee 5.93 --ads-pct 10 ^
  --returns-pct 3 --target-acos 25 --cvr 8 --ad-spend 799.27 ^
  --total-sales 2309.23 --json
```

期望（退出 0）：

- `referral_fee=4.5`、`returns_provision=0.9`、`planned_ad_provision=3.0`。
- `pre_ad_contribution=10.67`、`pre_ad_margin_pct=35.58`、`contribution_after_planned_ads=7.67`。
- `break_even_acos=0.3558`、`break_even_acos_pct=35.58`、`break_even_roas=2.81`。
- `target_roas=4.0`、`affordable_cpc=0.6`、`tacos=0.3461`、`tacos_pct=34.61`、`missing=[]`。

### 7.2 calc（最小输入）

```bash
python scripts/ads_metrics.py calc --platform amazon_us --price 29.99 ^
  --product-cost 7.99 --referral 15 --fba-fee 5.93 --ads-pct 10 ^
  --returns-pct 3 --target-acos 25 --json
```

期望（退出 0）：核心数值同上；`affordable_cpc=null`、`tacos=null`、`tacos_pct=null`；`missing` 两条（可承受 CPC、TACOS）。

### 7.3 diagnose（示例报表）

```bash
python scripts/ads_metrics.py diagnose --file examples/sample-campaign.csv ^
  --platform amazon_us --price 29.99 --product-cost 7.99 --referral 15 ^
  --fba-fee 5.93 --returns-pct 3 --target-acos 25 --json
```

期望（退出 0）：

- `total.campaigns=9`、`impressions=96940`、`clicks=2485`、`spend=799.27`、`orders=77`、`sales=2309.23`。
- `total.roas=2.89`、`total.tacos_pct=34.61`、`total.net_contribution=22.32`。
- `priority_counts={"P0":2,"P1":4,"P2":2,"INFO":1}`。
- 逐行关键值：`PB-Longtail-Phrase` 点击 96、订单 0、ROAS 0.0、ACOS null、P0；`PB-Broad-Cheap` ROAS 1.25、ACOS 79.75、P0；`PB-Core-Exact` ROAS 5.9、ACOS 16.95、P2；`PB-New-Video` 曝光 640、INFO。
- 本命令未传 `--cvr`，故零订单行 `affordable_cpc=0.0`；`missing=[]`（退货预留已给）。

### 7.4 失败与边界对拍

| 命令要点 | 期望 |
|---|---|
| diagnose `--file` 指向不存在的文件，`--json` | JSON `missing=["file"]`，退出 2 |
| diagnose 表头只有 5 列（缺 sales） | `missing=["sales"]`，退出 2 |
| diagnose 花费 `-1.00` | 退出 2，`missing=[]`，信息含「第 2 行 spend」 |
| calc `--referral 0` | 退出 2，`missing=[]` |
| calc `--price 0` | 退出 2，信息「--price 必须大于 0」 |
| calc 产品 20、售价 29.99（负贡献） | 退出 0；`pre_ad_contribution=-1.34`、`break_even_acos_pct=-4.46`、`break_even_roas=null` |
| 未给 `--returns-pct` 的 diagnose | 退出 0；盈亏线 ACOS 38.58%、ROAS 2.59；`missing` 一条 |

## 8. 未完整刻画/待确认

- `status="ERROR"` 在本脚本无触发路径，无法给出可复现实例；是否应保留该枚举待定。
- 06 仅校验 02 费率的元数据，实际 Referral/FBA 由 CLI 传入；二者长期可能漂移，是否应改为读取 `us_fees.json` 费率值待产品确认。
- UTF-8 以外的编码（如 GBK）未测试；CSV 分隔符仅支持逗号。
- 表头重复、全角逗号、全角负号、`USD` 小写等清洗边界未逐一实跑。
- 曝光/点击/订单的银行家舍入是否就是期望口径未确认；若业务要求四舍五入需改。
- 负数 `--ad-spend` 可产生负 TACOS，是否应拒绝未确认。
- 06 对「点击 ≥30 且零订单」的阈值 30 是常量，未给出业务出处。
- 人类输出的换行宽度随终端变化，未冻结列宽。
