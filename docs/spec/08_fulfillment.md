# 08 补货与空海运（inventory_plan.py）· 行为规格冻结

> 对象：`Agents/08_Fulfillment_Agent/scripts/inventory_plan.py`
> 实测环境：Windows PowerShell 5 + Python 3.12.0；基准日 2026-10-30。
> 本文只描述行为，不含实现细节；示例数值均来自实跑。

## 1. 范围与脚本（职责 + 依赖配置/前置模块）

- `calc`：按日均销量、生产交期、安全天数、当前库存、MOQ、发运间隔、单件成本，算补货点、可售天数、预计断货日、下单截止日、目标水位、建议下单量、下单后覆盖、资金占用与断货风险。
- `compare`：按批量、单件实重/体积、海空费率与时效，算总实重、CBM、密度、体积重、计费重、海运费、空运费、差额、每天买时间成本、在途资金成本差，并给运输建议。
- 边界：纯计算器；不读订单/库存系统、不生成采购单、不写文件。
- 前置依赖：无配置文件、无 02/06/07 依赖；`compare` 的毛利判断只引用「毛利数据来自 02 成本模型」的口径文案，不读取 02 数据。
- 所有参数由 CLI 提供，没有默认库存/费率文件；唯一的隐式默认是 `--today` 取本机当天。

## 2. CLI 契约

通用规则：

- 必须给出子命令 `calc` 或 `compare`。
- 无子命令时：退出 2；stdout 打印帮助，stderr 输出 `[INPUT_MISSING] 缺少子命令：calc 或 compare`。
- `--json` 定义在各子命令上，必须写在子命令之后；写在子命令之前会被顶层解析器当作未知参数（仍退出 2，且因 argv 含 `--json` 会输出 JSON 错误体）。
- argparse 类型错误（如 `--units 1.5`、`--stock 1.5`）在解析阶段退出 2。
- 成功路径固定退出 0：HIGH 风险、错过下单窗口、空运无时效优势都不会返回非零。

### 2.1 `calc`

| 参数名 | 类型 | 必填 | 默认值 | 取值范围/枚举 | 说明 |
|---|---|---|---|---|---|
| `--daily-sales` | float | 是 | — | `>= 0` | 日均销量（件/天）；0 合法，负数失败 |
| `--lead-time-days` | int | 是 | — | `> 0` | 生产/采购交期（天）；0 失败 |
| `--safety-days` | int | 否 | `0` | `>= 0` | 安全库存天数 |
| `--stock` | int | 否 | `0` | `>= 0` | 当前可售库存（件）；负数失败 |
| `--moq` | int | 是 | — | `> 0` | 最小起订量（件）；0/负数失败 |
| `--inbound-interval-days` | int | 否 | `0` | `>= 0` | 两次发运间隔（天），用于抬高目标水位 |
| `--unit-cost` | float | 否 | `None` | `> 0`（给出时） | 单件采购成本；0/负数失败，未给则不算资金占用 |
| `--currency` | str | 否 | `USD` | 任意字符串 | 仅回显与展示，不校验 ISO 代码 |
| `--today` | str | 否 | 本机当天 | ISO `YYYY-MM-DD` | 基准日；必须是零填充日期 |
| `--json` | flag | 否 | `false` | — | 结构化输出 |

冲突与隐式假设：

- `--daily-sales 0` 是合法输入，输出 `risk_level=N/A`、日期与覆盖类字段为 null、建议量 0。
- `--lead-time-days`、`--moq` 必须严格大于 0；`--safety-days`、`--stock`、`--inbound-interval-days` 允许 0。
- 未给 `--unit-cost` 时 `capital_required=null` 且不输出资金提示；给了 0 则直接失败。
- 所有数量参数都是「件」，金额参数都是「每件该币种」，不做单位换算。
- `--today` 只影响日期字段，不改变任何数值公式。

### 2.2 `compare`

| 参数名 | 类型 | 必填 | 默认值 | 取值范围/枚举 | 说明 |
|---|---|---|---|---|---|
| `--units` | int | 是 | — | `> 0` | 批量件数；小数/字符串解析失败 |
| `--weight-kg` | float | 是 | — | `> 0` | 单件实重 kg（含包装） |
| `--cbm-per-unit` | float | 否 | `0` | `>= 0` | 单件体积 CBM；0 合法 |
| `--sea-rate-per-kg` | float | 否 | `None` | `> 0`（给出时） | 海运 USD/kg；与 CBM 费率至少给一个 |
| `--sea-rate-per-cbm` | float | 否 | `None` | `> 0`（给出时） | 海运 USD/CBM；LCL 最低 1 CBM |
| `--air-rate-per-kg` | float | 是 | — | `> 0` | 空运 USD/kg（按计费重） |
| `--sea-days` | int | 是 | — | `> 0` | 海运时效（天） |
| `--air-days` | int | 是 | — | `> 0` | 空运时效（天）；可大于海运天数，不做校验 |
| `--unit-cost` | float | 否 | `None` | `> 0`（给出时） | 单件货值；用于在途资金占用 |
| `--carrying-rate-pct` | float | 否 | `12` | `0–100` | 年化资金成本%；0 合法，超过 100 失败（#10） |
| `--currency` | str | 否 | `USD` | 任意字符串 | 仅展示 |
| `--today` | str | 否 | 本机当天 | ISO `YYYY-MM-DD` | 基准日，用于 ETA |
| `--json` | flag | 否 | `false` | — | 结构化输出 |

冲突与隐式假设：

- `--sea-rate-per-kg` 与 `--sea-rate-per-cbm` 至少给一个；都缺时退出 2，`missing=["sea_rate_per_kg|sea_rate_per_cbm"]`。
- 两个都给了：**CBM 费率优先**，kg 费率被静默忽略（但仍回显在 `inputs` 中）。
- 即便已给 CBM 费率，只要 `--sea-rate-per-kg` 显式给出且 ≤0，仍会先报错退出 2；「被忽略」发生在校验之后。
- 同理，`--sea-rate-per-cbm` 显式给出且 ≤0 也会报错，不会回退到 kg 费率。
- `--sea-rate-per-cbm` 不会出现在输出的 `inputs` 中（审计缺口，见 §6）。
- `--cbm-per-unit` 为 0 且使用 CBM 费率时，仍按最低 1 CBM 计费。
- `--sea-days`/`--air-days` 只要求大于 0，不要求空运快于海运；空运更慢时 `days_saved` 为负。
- `--weight-kg` 是单件实重，不是总重；总重由脚本乘批量。

## 3. 输入契约

### 3.1 输入形态

- 08 不读任何文件，全部输入来自 CLI 参数；因此没有编码、列名别名、BOM 问题。
- 参数名均为 kebab-case；数值中的千分位、货币符号、百分号不被接受（argparse 直接失败）。
- 日期参数用 `YYYY-MM-DD`；本机时区为 `Asia/Shanghai`，`--today` 缺省取本机日历日。
- `--currency` 只是字符串，`USD`、`CNY`、`RMB` 均可，不参与计算。

### 3.2 数值语义

| 参数 | 语义 | 单位 | 边界行为 |
|---|---|---|---|
| `daily_sales` | 日均销量 | 件/天 | 0 → N/A；负数 → 失败 |
| `lead_time_days` | 下单到可售的生产/运输前置期 | 天 | 0 → 失败 |
| `safety_days` | 额外安全缓冲 | 天 | 0 允许 |
| `stock` | 当前可用库存，不含在途 | 件 | 0 允许；负数失败 |
| `moq` | 最小起订量，建议量按其整数倍向上取 | 件 | 0/负 → 失败 |
| `inbound_interval_days` | 两次发运间隔，目标水位额外覆盖 | 天 | 0 允许 |
| `unit_cost` | 单件采购成本，仅用于资金占用 | 金额/件 | 0/负 → 失败；缺省 → null |
| `units` | 本批总件数 | 件 | 0/负 → 失败 |
| `weight_kg_per_unit` | 单件实重（含包装） | kg/件 | 0/负 → 失败 |
| `cbm_per_unit` | 单件体积 | CBM/件 | 0 允许；负 → 失败 |
| `sea_rate_per_kg` | 海运公斤价 | 金额/kg | 0/负 → 失败 |
| `sea_rate_per_cbm` | 海运立方价（LCL） | 金额/CBM | 0/负 → 失败；优先于 kg 价 |
| `air_rate_per_kg` | 空运公斤价（按计费重） | 金额/kg | 0/负 → 失败 |
| `sea_days` / `air_days` | 运输时效 | 天 | 0/负 → 失败 |
| `carrying_rate_pct` | 年化资金成本 | %/年 | 0 允许；负或 >100 → 失败 |

### 3.3 日期口径

- `today` 是纯日期，不含时间与时区；所有日期都是 `YYYY-MM-DD` 字符串。
- `expected_stockout_date = today + floor(days_of_cover)`，向下取整到整天。
- `order_deadline = expected_stockout_date − lead_time_days`（日历日）。
- `days_until_deadline = (order_deadline − today).days`，可为负；**等于 0 不算已过**。
- `eta = today + sea_days / air_days`（海运、空运分别算）。
- `--today` 非法（格式错、月份越界、未零填充的 `2026-1-1`）→ 退出 2，信息统一为 `--today 需为 YYYY-MM-DD，收到：<原值>`。

## 4. 输出契约

### 4.1 `calc` 成功 JSON

| 字段 | 类型 | 单位/精度 | 说明 |
|---|---|---|---|
| `tool` | str | — | 固定 `inventory_plan` |
| `mode` | str | — | 固定 `calc` |
| `today` | str | 日期 | 回显生效基准日 |
| `inputs` | object | — | `daily_sales`(float)、`lead_time_days`(int)、`safety_days`(int)、`stock`(int)、`moq`(int)、`inbound_interval_days`(int)、`unit_cost`(float\|null)、`currency`(str) |
| `reorder_point` | number | 件，1 | 补货点 |
| `days_of_cover` | number\|null | 天，1 | 当前库存可售天数 |
| `expected_stockout_date` | str\|null | 日期 | 预计断货日 |
| `order_deadline` | str\|null | 日期 | 下单截止日 |
| `order_deadline_passed` | bool | — | 是否已过截止日 |
| `days_until_deadline` | int\|null | 天 | 距截止日天数，可为负 |
| `target_stock` | number | 件，1 | 目标水位 |
| `suggested_order_qty` | int | 件 | 建议下单量（MOQ 整数倍） |
| `coverage_after_order_days` | number\|null | 天，1 | 下单后覆盖天数 |
| `capital_required` | number\|null | 金额，2 | 建议下单量 × 单件成本 |
| `risk_level` | str | — | `HIGH`/`MEDIUM`/`LOW`/`N/A` |
| `notes` | str[] | — | 提示，按固定顺序 |

### 4.2 `compare` 成功 JSON

| 字段 | 类型 | 单位/精度 | 说明 |
|---|---|---|---|
| `tool` | str | — | 固定 `inventory_plan` |
| `mode` | str | — | 固定 `compare` |
| `today` | str | 日期 | 基准日 |
| `inputs` | object | — | `units`、`weight_kg_per_unit`、`cbm_per_unit`、`sea_rate_per_kg`、`air_rate_per_kg`、`sea_days`、`air_days`、`unit_cost`、`currency`；**无 `sea_rate_per_cbm`、无 `carrying_rate_pct`** |
| `cargo` | object | — | 见 cargo 子表 |
| `sea` | object | — | 见 sea/air 子表 |
| `air` | object | — | 同 sea，`charge_basis` 固定为计费重口径 |
| `diff` | object | — | 见 diff 子表 |
| `capital` | object\|null | — | 未给 `unit_cost` 时为 null；否则见 capital 子表 |
| `recommendation` | str | — | 运输建议 |
| `notes` | str[] | — | 提示，按固定顺序 |

`cargo`：

| 字段 | 类型 | 单位 | 精度 | 说明 |
|---|---|---|---|---|
| `total_weight_kg` | number | kg | 1 | 件数 × 单件实重 |
| `total_cbm` | number | CBM | 3 | 件数 × 单件 CBM |
| `density_kg_per_cbm` | number\|null | kg/CBM | 1 | 实重 ÷ CBM；CBM=0 时 null |
| `air_volumetric_kg` | number | kg | 1 | 总 CBM × 167 |
| `air_chargeable_kg` | number | kg | 1 | max(实重, 体积重) |

`sea` / `air`：

| 字段 | 类型 | 单位 | 精度 | 说明 |
|---|---|---|---|---|
| `total` | number | 金额 | 2 | 总运费 |
| `per_unit` | number | 金额/件 | 3 | 总运费 ÷ 件数 |
| `transit_days` | int | 天 | — | 回显输入 |
| `eta` | str | 日期 | — | 基准日 + 时效 |
| `charge_basis` | str | — | — | 计费口径文案 |

`diff`：

| 字段 | 类型 | 单位 | 精度 | 说明 |
|---|---|---|---|---|
| `total` | number | 金额 | 2 | 空运 − 海运，可为负 |
| `per_unit` | number | 金额/件 | 3 | 单件差额，可为负 |
| `premium_pct` | number | % | 1 | 差额 ÷ 海运费 ×100，可为负 |
| `days_saved` | int | 天 | — | 海运天数 − 空运天数，可为负 |
| `cost_per_day_saved` | number\|null | 金额/天 | 2 | 差额 ÷ 时效差；时效差 ≤0 时 null |

`capital`：`inventory_value`(2)、`carrying_rate_pct`(回显，1)、`sea_capital_cost`(2)、`air_capital_cost`(2)、`capital_diff`(2，海运 − 空运)、`currency`。

`charge_basis` 三种取值：

- `按重量（kg）`：海运按 kg 价。
- `按体积重（CBM，LCL 最低 1 CBM 起算）`：海运按 CBM 价。
- `按计费重（实重与体积重取大）`：空运。

### 4.3 人类可读输出

- `calc`：标题含基准日；参数行（日均/交期/安全天数/库存/MOQ/发运间隔）；补货点；当前可售天数；预计断货日；建议下单量（注明按 MOQ 向上取整）；下单截止日（仅当已过时追加「（已过 N 天，需立即下单）」，未过时无后缀）；下单后覆盖天数；资金占用（有 unit-cost 时）；风险等级；提示；口径说明。
- `compare`：标题；单件重量/CBM、合计重量/CBM、密度；海运金额/单件/时效/ETA/计费口径；空运同构；差额/单件/百分比/时效差；每天买时间成本；资金占用（有 unit-cost 时）；建议；提示；口径。
- 缺值（null）在人类输出中不显示对应日期/资金行或显示 `-`。

`calc` 人类输出实跑样例（命令见 §7.1）：

```text
=== 补货测算（基准日 2026-10-30）===
日均销量 20.0｜生产交期 45 天｜安全天数 21 天｜当前库存 300｜MOQ 500｜发运间隔 30 天

补货点（reorder_point）：1320.0 件
当前可售天数：15.0 天
预计断货日：2026-11-14
建议下单量：2000 件（按 MOQ 500 向上取整）
下单截止日：2026-09-30（已过 30 天，需立即下单）
下单后覆盖天数：115.0 天
下单资金占用：USD 15980.00
断货风险等级：HIGH
```

### 4.4 失败契约与退出码

失败时：

- `--json`：stdout `{"status":"INPUT_MISSING","missing":[...],"message":"..."}`；stderr `[INPUT_MISSING] ...`。
- 非 `--json`：仅 stderr 人类信息。
- `ERROR` 枚举在公共契约中存在，但本脚本所有可预期错误均为 `INPUT_MISSING`。

| 场景 | `missing` | 退出码 |
|---|---|---|
| `daily_sales < 0` | `["daily_sales"]` | 2 |
| `lead_time_days <= 0` | `["lead_time_days"]` | 2 |
| `safety_days < 0` | `["safety_days"]` | 2 |
| `stock < 0` | `["stock"]` | 2 |
| `moq <= 0` | `["moq"]` | 2 |
| `inbound_interval_days < 0` | `["inbound_interval_days"]` | 2 |
| `unit_cost <= 0`（给出时） | `["unit_cost"]` | 2 |
| `units <= 0` | `["units"]` | 2 |
| `weight_kg <= 0` | `["weight_kg"]` | 2 |
| `cbm_per_unit < 0` | `["cbm_per_unit"]` | 2 |
| 海运两个费率都缺 | `["sea_rate_per_kg|sea_rate_per_cbm"]` | 2 |
| `air_rate_per_kg <= 0` | `["air_rate_per_kg"]` | 2 |
| `sea_days/air_days` 任一 <= 0 | `["sea_days","air_days"]` | 2 |
| `carrying_rate_pct < 0` | `["carrying_rate_pct"]` | 2 |
| `carrying_rate_pct > 100`（#10） | `["carrying_rate_pct"]` | 2 |
| `--today` 非法 | `["today"]` | 2 |
| argparse 类型/未知参数 | `[]` | 2 |
| 无子命令 | `["command"]` | 2 |
| 成功（含 HIGH/错过窗口/负时效差） | — | 0 |

## 5. 计算规则

### 5.1 calc

- 补货点 = `daily × (lead + safety)`。
- 目标水位 = `daily × (lead + safety + interval)`。
- 可售天数 = `stock ÷ daily`，保留 1 位；`daily=0` → null。
- 预计断货日 = `today + floor(stock ÷ daily)` 天；`daily=0` → null。
- 下单截止日 = 预计断货日 − `lead` 天；可售天数不足 lead 时为过去日期。
- `days_until_deadline = 截止日 − today`（整数天）；`< 0` 才算已过，`= 0` 表示今天必须下单但 `order_deadline_passed=false`。
- 缺口 = `target_stock − stock`；缺口 ≤ 0 → 建议 0；否则建议 = `ceil(缺口 ÷ moq) × moq`（整数）。
- 下单后覆盖 = `(stock + suggested) ÷ daily`，1 位；`daily=0` → null。
- 资金占用 = `suggested × unit_cost`，2 位；未给 unit_cost → null；给了且 daily=0 → 0.0。
- 风险：
  - `daily=0` → `N/A`。
  - 可售天数 `< lead` → `HIGH`（补货未到就断货）。
  - 否则可售天数 `< lead + safety` → `MEDIUM`。
  - 否则 → `LOW`。
  - 全部使用严格小于；可售天数恰好等于 lead 时是 `MEDIUM`（实跑 900 件/45 天确认）。
- `notes` 固定顺序：
  - `daily=0`：先「日均销量为 0」，若 `stock=0` 再「库存为 0 且无销量」。
  - `daily>0`：先风险档（HIGH/MEDIUM/LOW），再 `stock=0`，再「建议为 0（库存已高于目标水位）」，最后「截止日已过 N 天」。
  - 每条最多出现一次，不因多个条件重复堆叠。
- 边界：`stock` 可以大于 `target_stock`，不截断库存；建议 0，但风险仍按可售天数计算。

### 5.2 compare

- 总实重 = `units × weight_kg`；总 CBM = `units × cbm`。
- 密度 = 总实重 ÷ 总 CBM，1 位；CBM=0 → null。
- 体积重 = 总 CBM × 167 kg/CBM，1 位。
- 空运计费重 = `max(总实重, 体积重)`，1 位；CBM=0 时等于总实重。
- 海运：
  - 给了 CBM 费率 → 计费量 = `max(总 CBM, 1)`，运费 = 计费量 × CBM 费率；kg 费率忽略。
  - 只给 kg 费率 → 运费 = 总实重 × kg 费率。
- 空运费 = 计费重 × kg 费率。
- 单件运费 = 总运费 ÷ units，3 位。
- 差额 = 空运 − 海运；`premium_pct = 差额 ÷ 海运费 ×100`，1 位；海运正数，不会除零。
- 时效差 = `sea_days − air_days`；可为负。
- 每天买时间成本 = `差额 ÷ 时效差`，2 位；**仅时效差 > 0** 时有值，否则 null。
- 在途资金（给出 unit-cost 时）：
  - 货值 = `units × unit_cost`。
  - 海运资金成本 = 货值 × `sea_days ÷ 365` × `carrying_rate ÷100`。
  - 空运同理；差额 = 海运 − 空运。
  - 只计在途时间差，不含仓储、滞销、保险。
- ETA = `today + 对应天数`。
- 建议分支：
  - 时效差 ≤ 0 → 「空运无时效优势」文案，即便空运溢价很高或为负。
  - 否则溢价 ≤ 25% → 空运优先。
  - 否则溢价 ≤ 80% → 空运/海运组合。
  - 否则 > 80% → 海运为主，空运只补急。
  - 负溢价（空运更便宜）落入「≤25%」分支，文案仍称「溢价可接受」。
- `notes`：CBM 费率且总 CBM <1 → LCL 最低收费提示；体积重 > 实重 → 体积重提示；给了 unit-cost → 资金口径提示；最后固定追加判断口径提示。

### 5.3 取整与边界

- 所有金额、比率用 Python `round()`（银行家舍入）；本脚本的输出精度见 §4。
- `days_of_cover` 向下取整用于断货日，但输出保留 1 位，因此「可售 15.5 天」的断货日仍按 15 天。
- `ceil` 用于建议量，缺口为 0 时不取整直接 0。
- `daily=0` 时所有除法路径短路为 null，不产生除零异常。
- 负值：除 `daily_sales` 允许 0 外，所有关键量必须为正/非负，校验在计算前完成。
- `sea_days == air_days` 合法（时效差 0），但 `cost_per_day_saved=null`。
- `air_days > sea_days` 合法，时效差为负，`cost_per_day_saved=null`。

## 6. 已知行为与坑（现状）

| 现象 | 触发条件 | 现状行为（含实测退出码/输出） | 建议保留/修正 |
|---|---|---|---|
| 缺海运费率 | 既不给 `--sea-rate-per-kg` 也不给 `--sea-rate-per-cbm` | 退出 2；`missing=["sea_rate_per_kg|sea_rate_per_cbm"]`；信息「海运报价至少给一个」 | 保留；`missing` 用竖线拼接不便于程序消费，建议拆分 |
| CBM 优先 | 同时给 kg 与 CBM 费率 | 静默用 CBM 计费；`sea.charge_basis` 为 CBM；`inputs.sea_rate_per_kg` 仍回显（实跑） | 保留优先级；应输出「已忽略 kg 费率」提示 |
| CBM 费率的替代路径 | 只给 `--sea-rate-per-cbm` | 合法；海运 = max(CBM,1) × 费率；kg 价不参与（实跑 100 件 0.178 CBM → 60.00） | 保留；建议补 `sea_rate_per_cbm` 到 `inputs` |
| 最低 1 CBM | 总 CBM <1（含 0） | 海运按 1 CBM 计；0 CBM 时密度 null但运费仍为 1×费率；notes 有 LCL 提示（实跑 60.00） | 保留 LCL 模型；0 CBM 场景应提示体积数据缺失 |
| 输入未回显 CBM 费率 | 使用 `--sea-rate-per-cbm` | `inputs` 无该键，只有 `sea.charge_basis` 能间接看出（实跑确认） | 修正：补回显，保证可复算 |
| 输入未回显资金费率 | 使用 `--carrying-rate-pct` | `inputs` 无该键，只在 `capital.carrying_rate_pct` 出现 | 修正：统一放到 `inputs` |
| 零日均销量 | `--daily-sales 0` | 退出 0；`days_of_cover=null`、断货日/截止日 null、`risk_level=N/A`、建议 0；stock=0 时 note 两条（实跑） | 保留；下游需处理 null |
| 库存为 0 但日均 >0 | `--stock 0` | 退出 0；可售 0、断货日=今天、截止日=今天−lead、HIGH | 保留 |
| 负值 | stock=-5、moq=0、carrying=-1 等 | 均退出 2，`missing` 为对应参数（实跑） | 保留；信息已含收到值 |
| 单件成本为 0 | `--unit-cost 0` | 退出 2；未给与给 0 语义不同 | 保留；文档需强调 |
| 日期默认 today | 不传 `--today` | 取本机当天（实测 2026-10-30），所有日期随之平移 | 保留；差分测试必须显式传日期 |
| 非零填充日期 | `--today 2026-1-1` | 退出 2；`missing=["today"]` | 保留严格 ISO |
| 截止日等号 | 可售天数恰好等于 lead | `order_deadline`=今天，`order_deadline_passed=false`、`days_until_deadline=0`；风险 MEDIUM（实跑 900 件） | 保持基线行为；文字不追加后缀（本版本不改） |
| 资金费率上限 | `--carrying-rate-pct 200` | 基线退出 0 并算出 2 倍资金成本；当前实现按 #10 退出 2 | 有意差异 #10 |
| 风险严格边界 | 可售天数 = lead + safety | `risk_level=LOW`；只有严格小于才升档 | 保留；文档写明 |
| 建议量为 0 | 库存 ≥ 目标水位 | 建议 0，覆盖天数仍按现有库存输出，资金 0.0（有 unit-cost） | 保留；不做库存上限截断 |
| 资金口径 | 给 unit-cost | 只算「建议量 × 单件成本」，不含运费、关税、头程；在途资金另算 | 保留；需与 02 落地成本区分 |
| compare 空运更慢 | air_days > sea_days | 退出 0；`days_saved` 为负、`cost_per_day_saved=null`；建议「无时效优势」，即使溢价 150%（实跑） | 保留；建议文案提示时效数据可能填反 |
| compare 负溢价 | 空运总价低于海运 | 退出 0；`premium_pct` 为负；建议落入「≤25%」分支，仍称「溢价可接受」（实跑 -96.7%） | 修正文案：负溢价应称「空运更便宜」 |
| compare 计费口径 | 体积重 > 实重 | 空运按体积重计；notes 有提示；CBM=0 时体积重为 0 | 保留；空运 167 kg/CBM 需与货代确认 |
| 示例文档数字失真 | 基线 `examples/portable_blender_replenishment.md` | 命令传 `--unit-cost 7.99`，但文档写货值 4335、海运 49.88、空运 11.40、差额 38.48；实跑为 3995、45.97、10.51、35.46（按 8.67 才算 4335） | 已按 #11 以实跑值为准（本文 §5.2、§7.2）；不复制基线示例原文 |
| 无子命令 | 只运行脚本 | 退出 2；帮助在 stdout；stderr 「缺少子命令」 | 保留 |
| 子命令前写 `--json` | `... --json calc ...` | 顶层不识别，退出 2；仍输出 JSON 错误体 | 保留；文档需写明位置 |
| 成功恒 0 | HIGH、错过窗口、负时效差 | 退出 0（实跑） | 保留；下游按 risk_level/字段判断 |

## 7. 差分测试基准（必须可复现）

工作目录：`Agents/08_Fulfillment_Agent`。

### 7.1 calc

```bash
python scripts/inventory_plan.py calc --daily-sales 20 --lead-time-days 45 ^
  --safety-days 21 --stock 300 --moq 500 --inbound-interval-days 30 ^
  --unit-cost 7.99 --today 2026-10-30 --json
```

期望（退出 0）：

- `reorder_point=1320.0`、`days_of_cover=15.0`、`expected_stockout_date=2026-11-14`。
- `order_deadline=2026-09-30`、`order_deadline_passed=true`、`days_until_deadline=-30`。
- `target_stock=1920.0`、`suggested_order_qty=2000`、`coverage_after_order_days=115.0`。
- `capital_required=15980.0`、`risk_level=HIGH`。
- `notes` 两条：可售 15.0 天 < 交期 45 天；下单截止日已过 30 天。

### 7.2 compare（kg 费率）

```bash
python scripts/inventory_plan.py compare --units 500 --weight-kg 0.62 ^
  --cbm-per-unit 0.00178 --sea-rate-per-kg 3.2 --air-rate-per-kg 8.0 ^
  --sea-days 35 --air-days 8 --unit-cost 7.99 --today 2026-10-30 --json
```

期望（退出 0）：

- `cargo.total_weight_kg=310.0`、`total_cbm=0.89`、`density_kg_per_cbm=348.3`、`air_volumetric_kg=148.6`、`air_chargeable_kg=310.0`。
- `sea.total=992.0`、`sea.per_unit=1.984`、`eta=2026-12-04`、`charge_basis=按重量（kg）`。
- `air.total=2480.0`、`air.per_unit=4.96`、`eta=2026-11-07`。
- `diff.total=1488.0`、`per_unit=2.976`、`premium_pct=150.0`、`days_saved=27`、`cost_per_day_saved=55.11`。
- `capital.inventory_value=3995.0`、`sea_capital_cost=45.97`、`air_capital_cost=10.51`、`capital_diff=35.46`。
- `recommendation` 为「海运为主，空运只用于断货补急」。

### 7.3 compare（CBM 费率 + 最低收费）

```bash
python scripts/inventory_plan.py compare --units 100 --weight-kg 0.62 ^
  --cbm-per-unit 0.00178 --sea-rate-per-cbm 60 --air-rate-per-kg 8 ^
  --sea-days 35 --air-days 8 --json
```

期望（退出 0）：

- `total_cbm=0.178`、`density_kg_per_cbm=348.3`（总重 62.0）。
- 海运按 1 CBM：`sea.total=60.0`、`per_unit=0.6`、`charge_basis=按体积重（CBM，LCL 最低 1 CBM 起算）`。
- `air.total=496.0`、`diff.total=436.0`、`premium_pct=726.7`、`days_saved=27`、`cost_per_day_saved=16.15`。
- `notes` 含 LCL 最低收费提示；`capital=null`（未给 unit-cost）。

### 7.4 边界与失败差分测试

| 命令要点 | 期望 |
|---|---|
| calc `--daily-sales 0` | 退出 0；断货日/截止日/覆盖 null、`risk_level=N/A`、建议 0 |
| calc `--daily-sales 0 --stock 300 --unit-cost 7.99` | 退出 0；`capital_required=0.0` |
| calc `--stock 900`（45 天） | 退出 0；`risk_level=MEDIUM`、截止日=今天、`days_until_deadline=0` |
| calc `--stock 2000`（100 天） | 退出 0；`risk_level=LOW`、建议 0 |
| calc `--lead-time-days 0` | 退出 2；`missing=["lead_time_days"]` |
| calc `--stock -5` | 退出 2；`missing=["stock"]` |
| calc `--moq 0` | 退出 2；`missing=["moq"]` |
| calc `--unit-cost 0` | 退出 2；`missing=["unit_cost"]` |
| calc `--today 2026-13-01` / `2026-1-1` | 退出 2；`missing=["today"]` |
| compare 不给任何海运费率 | 退出 2；`missing=["sea_rate_per_kg|sea_rate_per_cbm"]` |
| compare 空运更慢（sea 8 / air 10 或 sea 8 / air 35） | 退出 0；`days_saved` 为负、`cost_per_day_saved=null`；建议「无时效优势」 |
| compare 空运更便宜（1 件、0 CBM、海运 60、空运 4×0.5=2） | 退出 0；`premium_pct` 为负；建议仍称「溢价可接受」 |
| compare `--units 1.5` | argparse 退出 2；`missing=[]` |
| compare `--carrying-rate-pct -1` | 退出 2；`missing=["carrying_rate_pct"]` |
| compare `--carrying-rate-pct 200` | 退出 2；`missing=["carrying_rate_pct"]`（#10，基线退出 0） |
| 只运行脚本 | 退出 2；帮助 stdout + stderr「缺少子命令」 |

### 7.5 运输建议分支差分测试

| 场景 | 参数要点 | 实测关键值 | 建议 |
|---|---|---|---|
| 空运溢价 9.4% | 500 件、单件 0.62 kg、海 3.2、空 3.5、35/8 天 | 海 992、空 1085、差 93、`premium_pct=9.4`、`cost_per_day_saved=3.44` | 空运溢价可接受：优先空运 |
| 空运溢价 56.2% | 500 件、单件 0.5 kg、海 3.2、空 5.0、35/8 天 | 海 800、空 1250、差 450、`premium_pct=56.2`、`cost_per_day_saved=16.67` | 海空组合：首批/紧急空运，常规海运 |
| 空运溢价 150% | 500 件、单件 0.62 kg、海 3.2、空 8.0、35/8 天 | 差 1488、`premium_pct=150.0`、`cost_per_day_saved=55.11` | 海运为主，空运只补急 |
| 空运更慢 | sea_days=8、air_days=35，其余同上 | 差 1488、`premium_pct=150.0`、`days_saved=-27`、成本 null | 空运无时效优势 |
| 空运更便宜 | 1 件、0 CBM、CBM 海运费率 60、空运 4 | 海 60、空 2、差 -58、`premium_pct=-96.7`、成本 -2.15 | 仍输出「空运溢价可接受」 |

## 8. 未完整刻画/待确认

- ~~示例文档 compare 资金数字与命令不一致~~ 已由 #11 落定：以实跑值 3995 / 45.97 / 10.51 / 35.46 为准（见 §7.2）。
- 空运体积重系数 167 kg/CBM 为常量，是否需要按货代/航线可配置未确认。
- LCL 最低 1 CBM 是否对所有海运渠道成立未确认。
- `days_of_cover` 输出 1 位但断货日向下取整的展示口径是否会让用户误读未确认。
- 截止日 `days=0` 不算已过、风险严格边界（等于 lead 记 MEDIUM）是否符合业务习惯未确认。
- ~~`--carrying-rate-pct` 无上限~~ 已由 #10 落定为 0–100（上限 100，0 仍合法）。
- `--currency` 不校验 ISO 代码，是否应限制枚举未确认。
- `status="ERROR"` 无触发路径；是否保留未确认。
- 未测试超大批量/极端小数带来的浮点误差（如 0.1 CBM 与 167 的乘积）。
