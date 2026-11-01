# 02 Cost & Pricing Agent — 规格冻结（clean-room 重写基线）

> 只描述可观察行为，不复制实现。数值来自 2026-10-30 在 Windows / Python 3.12.0 的实跑或代码明确常量。
> 覆盖：`Agents/02_Cost_Pricing_Agent/scripts/landed_cost.py`（实际 1152 行）、`scripts/us_fees.json`、`scripts/hts_tariff.json`、`config/category_map.json`、根目录 `cli_common.py`。

## 1. 范围与脚本

| 入口 | 一句话职责 |
|---|---|
| `landed_cost.py calc` | 单 SKU：FOB→到岸成本→referral/FBA/广告/退货→净利、盈亏价、目标价、MOQ 占款 |
| `landed_cost.py matrix` | 多 SKU CSV：逐行复用 calc，整表继续、失败行汇总，附达标判断 |
| `landed_cost.py --list-platforms` | 从 `us_fees.json` 打印平台 referral 分段速查（Markdown） |
| `landed_cost.py --list-fba-tiers` | 从 `us_fees.json` 打印 2026 FBA 档位费率速查（Markdown） |

依赖：
- `scripts/us_fees.json`：平台佣金（`platforms`）、FBA 档位（`fba.tiers`）、旺季/燃油窗口与附加费率。
- `scripts/hts_tariff.json`：HTS→MFN + Section 301、`verified` 标记、备注。
- `config/category_map.json`：`category_key` 唯一口径、平台路径前缀、旧键别名、`us_fees_key`。
- `cli_common.py`（仓库根）：`JsonArgumentParser`、`fail/emit_fail`、`set_json_mode/set_raise_mode`。
- 全部纯标准库；CSV/JSON 读取均 `utf-8-sig`（容忍 BOM）。

关键常量：`DEFAULT_PLATFORM=amazon_us`、`DEFAULT_ADS_PCT=10.0`、`DEFAULT_RETURNS_PCT=3.0`、`DEFAULT_TARGET_MARGIN=25.0`、`DEFAULT_MOQ=500`、`DEFAULT_CUSTOMS_FEE=0.18`、`OZ_PER_LB=16.0`。旺季窗口 `2026-10-15..2027-01-14`，非旺季 `2026-01-15..2026-10-14`；燃油附加费率 `3.5%`，生效日 `2026-04-17`。

## 2. CLI 契约

顶层只有两个 flag，无位置子命令参数；子命令为 `calc`、`matrix`。

### 2.1 顶层

| 参数名 | 类型 | 必填 | 默认值 | 取值范围/枚举 | 说明 |
|---|---|---|---|---|---|
| `--list-platforms` | flag | 否 | false | — | 打印平台费率后退出 0；优先于任何子命令 |
| `--list-fba-tiers` | flag | 否 | false | — | 打印 FBA 档位后退出 0；与 `--list-platforms` 同时给时先执行 platforms |

两个 flag 都为真时按代码顺序先 platforms、后直接 `return`，不再执行 fba 列表。

### 2.2 `calc`

| 参数名 | 类型 | 必填 | 默认值 | 取值范围/枚举 | 说明 |
|---|---|---|---|---|---|
| `--factory-rmb` | float | 是 | `None` | ≥0（负值报错） | 人民币出厂价/件 |
| `--fx` | float | 是 | `None` | >0 | 1 CNY = ? USD |
| `--freight-per-unit` | float | 是 | `None` | 任意 float（不校验负值） | 头程单件分摊 USD |
| `--duty-pct` | float | 条件 | `None` | 任意 float（不校验负值） | 显式关税百分比；提供时覆盖 `--hts` |
| `--hts` | str | 条件 | `None` | 见 `hts_tariff.json`，前缀匹配 | HTS 编码，如 `8509.40` |
| `--category` | str | 条件 | `None` | category_key / 别名 / 平台类目路径 | 会映射为 `category_key` |
| `--category-key` | str | 条件 | `None` | `config/category_map.json` 的 `categories` 键 | 推荐口径；与 `--category` 必须一致 |
| `--assume-default-referral` | flag | 否 | false | — | 缺类目时显式按 `default` 15% 估算并写 `assumptions` |
| `--platform` | str | 否 | `None`→`amazon_us` | `amazon_us` / `tiktok_us` | 平台；缺省时 notes 提示 |
| `--referral` | float | 否 | `None` | 任意 float（不校验负值/上限） | 显式佣金百分比，覆盖平台/类目路径 |
| `--fba-fee` | float | 条件 | `None` | 任意 float | 显式 FBA 费 USD/件，优先于重量推导 |
| `--weight-g` | float | 条件 | `None` | 任意 float | 发货重量（克），自动选标准档 |
| `--weight-oz` | float | 条件 | `None` | 任意 float | 发货重量（盎司）；与 `--weight-g` 同时给时**以 oz 为准** |
| `--tier` | str | 否 | `None` | `small_standard` / `large_standard` / `small_bulky` / `large_bulky` | 显式 FBA 档；缺省按重量选 standard |
| `--season` | str | 否 | `None`→`auto` | `auto` / `nonpeak` / `peak` | FBA 季节档；显式值优先于 ship-date |
| `--ship-date` | str | 否 | `None`→运行日 | `YYYY-MM-DD` | 判旺季与燃油附加费 |
| `--no-fuel-surcharge` | flag | 否 | false | — | 不计 3.5% 燃油附加费 |
| `--ads-pct` | float | 否 | `None`→`10.0` | 任意 float | 广告占售价百分比 |
| `--returns-pct` | float | 否 | `None`→`3.0` | 任意 float | 退货占售价百分比 |
| `--price` | float | 是 | `None` | >0 | 当前零售价 USD |
| `--target-margin` | float | 否 | `None`→`25.0` | 任意 float | 目标净利率百分比 |
| `--moq` | int | 否 | `None`→`500` | 任意 int（不校验 ≤0） | MOQ 件数 |
| `--customs-fee-per-unit` | float | 否 | `None`→`0.18` | 任意 float | 报关杂费 USD/件 |
| `--json` | flag | 否 | false | — | 成功输出 JSON；错误也输出统一 JSON |

「条件必填」：`--duty-pct` 与 `--hts` 至少一个；`--fba-fee` 与 `--weight-g`/`--weight-oz` 至少一个；类目在无 `--referral`、无 `--assume-default-referral` 时必填。

### 2.3 `matrix`

| 参数名 | 类型 | 必填 | 默认值 | 取值范围/枚举 | 说明 |
|---|---|---|---|---|---|
| `--file` | str | 是 | `None` | 存在的 CSV | SKU 文件 |
| `--fx` | float | 是 | `None` | >0（逐行计算时校验） | 全表统一汇率 |
| `--assume-default-referral` | flag | 否 | false | — | 缺类目行按 default 15% 估算；否则该行失败 |
| `--json` | flag | 否 | false | — | 成功输出矩阵 JSON；有失败行时输出错误 JSON（含成功行） |

### 2.4 参数冲突与互斥规则

| 组合 | 规则 |
|---|---|
| `--duty-pct` + `--hts` | 不报错；`--duty-pct` 覆盖 HTS，notes 追加「按显式 --duty-pct 覆盖 HTS 推导值」 |
| `--category` + `--category-key` 值不同 | 退出 2，`missing=["category_key"]` |
| `--referral` + `--platform`/`--category` | 不报错；显式 referral 生效，notes 提示被覆盖 |
| `--fba-fee` + `--weight-g/--weight-oz` | 不报错；显式 FBA 费生效，不按重量选档；`weight_oz` 仍记录（有值时） |
| `--weight-g` + `--weight-oz` | 不报错；`weight_oz` 优先，克数被忽略 |
| `--season` + `--ship-date` | season 显式优先；ship-date 仍用于燃油附加费判定 |
| `--platform tiktok_us` + `--category` | 不报错；TikTok 分支在读类目前返回，类目仅原样回显、不解析/不校验 |
| `--referral` 且无类目 | 不报错；`category/category_key` 为 `null` |
| `--assume-default-referral` 且给了类目 | 忽略兜底；类目正常解析 |
| `--list-platforms` + 子命令 | 列表优先，子命令不执行 |
| 顶层 `--json`（子命令之前） | argparse 报 `unrecognized arguments`，退出 2 |
| `--no-fuel-surcharge` + `--season` | 附加费为 0；季节仍按显式值 |

### 2.5 典型调用示例

```powershell
# 1) 全自动：HTS + 类目 + 重量 + 旺季日期
python Agents/02_Cost_Pricing_Agent/scripts/landed_cost.py calc --factory-rmb 38 --fx 0.14 --freight-per-unit 1.60 --hts 8509.40 --category-key small_appliances --weight-g 620 --price 29.99 --ship-date 2026-10-30 --json

# 2) 全显式：不依赖配置档位
python Agents/02_Cost_Pricing_Agent/scripts/landed_cost.py calc --factory-rmb 38 --fx 0.14 --freight-per-unit 1.6 --duty-pct 16.7 --fba-fee 5.93 --category-key home_kitchen --price 29.99 --json

# 3) 类目缺失时的显式兜底
python Agents/02_Cost_Pricing_Agent/scripts/landed_cost.py calc --factory-rmb 38 --fx 0.14 --freight-per-unit 1.6 --hts 8509.40 --weight-g 620 --price 29.99 --assume-default-referral --json

# 4) 批量
python Agents/02_Cost_Pricing_Agent/scripts/landed_cost.py matrix --file Agents/02_Cost_Pricing_Agent/examples/sample-skus.csv --fx 0.14 --json

# 5) 速查
python Agents/02_Cost_Pricing_Agent/scripts/landed_cost.py --list-platforms
python Agents/02_Cost_Pricing_Agent/scripts/landed_cost.py --list-fba-tiers
```

示例 1 走完整配置链路（`us_fees.json` + `hts_tariff.json` + `category_map.json`）；示例 2 只依赖 `category_map.json`（显式 referral 时甚至可不传类目）；示例 3 只依赖 referral 兜底常量。

## 3. 输入契约

### 3.1 `calc` 输入

无文件输入；全部通过 CLI。校验顺序：先参数齐全性（一次列全缺失项）→ `load us_fees.json` → `build_params` 默认值/一致性 → `compute_core` 数值校验（`factory_rmb ≥0`、`fx >0`、`price >0`）→ 关税口径 → referral → FBA。

### 3.2 `matrix` 输入 CSV

编码 `utf-8-sig`；表头与单元格 `strip()`。物理空白行由 `csv` 模块跳过；仅由逗号组成的全空字段行**不跳过**，会因 `sku` 为空而记为该行失败。列名**精确匹配**，无别名。缺列前置校验，未通过不读取行计算。

必需列：

| 列 | 语义 | 单位/类型 | 缺失/替代 |
|---|---|---|---|
| `sku` | SKU 标识 | str | 不可缺；行内为空 → 该行失败 |
| `factory_rmb` | 人民币出厂价 | CNY/件，float | 不可缺 |
| `freight_per_unit` | 头程单件 | USD，float | 不可缺 |
| `price` | 售价 | USD，float | 不可缺 |

条件列：

| 列 | 语义 | 缺失/替代 |
|---|---|---|
| `duty_pct` | 显式关税率（%） | 与 `hts` 至少一个；两者都空该行失败 |
| `hts` | HTS 编码 | 同上；`duty_pct` 有值时优先 |
| `fba_fee` | 显式 FBA 费 USD | 与 `weight_g`/`weight_oz` 至少一个；都空该行失败 |
| `weight_g` | 发货重量（克） | 同上；与 `weight_oz` 同时给时 oz 优先 |
| `weight_oz` | 发货重量（盎司） | 同上 |

可选列（空单元格 = 用默认）：

| 列 | 单位/范围 | 默认 | 说明 |
|---|---|---|---|
| `platform` | `amazon_us`/`tiktok_us` | `amazon_us` | 非法值 → 该行失败 |
| `category_key` | category_key | 无 | 优先于 `category` |
| `category` | 键/别名/平台路径 | 无 | `category_key` 为空时使用 |
| `referral` | % | 无 | 显式覆盖 |
| `ads_pct` | % | 10.0 | |
| `returns_pct` | % | 3.0 | |
| `target_margin` | % | 25.0 | |
| `moq` | 件，int | 500 | 按 float 解析后 `int()` 截断 |
| `customs_fee_per_unit` | USD | 0.18 | |
| `fba_tier` | 4 档枚举 | 自动 | 未知档 → 该行失败 |
| `season` | `auto`/`nonpeak`/`peak`（代码不校验枚举） | 自动 | 非法值走 auto 分支（与 CLI `--season` 不同，见 §6.1） |
| `ship_date` | `YYYY-MM-DD` | 运行日 | 非法值见 §6 |
| `no_fuel_surcharge` | 任意非空字符串 | 空=计附加费 | **非空即视为 true**，`"false"`/`"0"` 也会关闭附加费 |

数值清洗：去 `,`、`$`、`strip`；空串视为缺省。`parse_float` 失败 → 该行失败。`cell()` 对空白列返回 `None`。

### 3.3 `us_fees.json` 关键结构

- `_meta`：`updated`、`currency`、`disclaimer`、`notes`；仅用于列表页展示。
- `platforms.<key>`：`name`、`default_referral_pct`、`min_referral_fee_usd`、`categories{...}`、可选 `note`。
  - `amazon_us.categories.<key>`：`label`、`tiers`（`[{max_price_usd:num|null, pct:num}]`）、可选 `min_fee_usd`（覆盖平台最低佣金）、`note`；个别兼容旧结构 `referral_pct` + `tier_threshold_usd` + `above_threshold_pct`。
  - `tiktok_us`：`default_referral_pct=6.0`、`new_seller_promo_pct=3.0`、`new_seller_window_days=60`、`new_seller_gmv_cap_usd=500000`、`min_referral_fee_usd=0.0`；无 `categories`。
- `fba.fuel_surcharge_pct`、`fuel_surcharge_effective`、`windows.{nonpeak,peak}`。
- `fba.tiers.<key>`：`label`、`rates.{nonpeak,peak}[]`（`max_oz`、`fees{lt10,10_50,gt50}` 或 `over_3lb{base{...},per_4oz_usd}`）或 `base.{nonpeak,peak}{...}` + `per_lb_over_first_usd`（bulky 档）。
- 价格档键固定：`lt10`（<$10）、`10_50`（$10–$50，含 10 与 50）、`gt50`（>$50）。

### 3.4 `hts_tariff.json` 关键结构

`codes.<code>`：`mfn_pct`、`section301_pct`、`verified`（bool）、`note`、`additional_provision`、`all_in_pct`、`description(_cn)`。`duty_pct = mfn_pct + section301_pct`。当前仅 6 个键：`8509.40`、`8509.90`、`8516`、`3924`、`6307`、`8479`；前两个 `verified=true`，其余 `false`（会触发未核校提醒）。

### 3.5 `category_map.json` 关键结构

`categories.<category_key>`：`label`、`us_fees_key`（缺省回落到 key 本身）、`compliance_key`、`platform_paths[]`（类目路径前缀）。`aliases.<旧键>` → `category_key`（当前 5 个：`small_appliance`、`kitchenware`、`textile`、`apparel`、`home-and-kitchen`）。
解析顺序：精确 `category_key` → `aliases` → 平台路径最长前缀（大小写不敏感，`>`/`|` 规范为 ` > `）。路径命中方式：完全相等，或 `path.startswith(prefix + " >")`。同长度多主体会报歧义并退出 2。

### 3.6 配置读取与缺省回退

| 配置项 | 缺失/异常时 | 退出码 |
|---|---|---|
| `us_fees.json` 文件不存在/JSON 损坏 | `missing=["<us_fees.json 绝对路径>"]`，无法计算 | 2 |
| `us_fees.json:fba.tiers` | `missing=["us_fees.json:fba.tiers"]`（唯一走 3 的分支） | 3 |
| `fba.tiers` 中显式指定的档不存在 | `missing=["fba_tier"]`，列出可选档 | 2 |
| `us_fees.json:platforms.<平台>` | `missing=["platform"]`，列出可选平台 | 2 |
| `platforms.amazon_us.min_referral_fee_usd` | `get(..., 0.0)` → 视为无最低佣金（不报错） | — |
| 类目对象无 `tiers` | 走旧结构 `referral_pct`/`above_threshold_pct` | — |
| 旧结构无 `above_threshold_pct` | 全程单一 `referral_pct` | — |
| `config/category_map.json` 文件缺失/解析失败 | `missing=["config/category_map.json"]` | 2 |
| `hts_tariff.json` 文件缺失/解析失败 | `missing=["<hts_tariff.json 绝对路径>"]`（仅使用 `--hts` 时加载） | 2 |
| HTS 条目缺 `mfn_pct`/`section301_pct` | `entry.get(..., 0.0)` → 按 0 计，不报错 | 0 |

配置中的 `windows`、`_meta.updated`、`disclaimer` 只影响展示，不影响计算；计算使用代码内硬编码的 2026 窗口常量。

## 4. 输出契约

### 4.1 `calc` 成功 JSON

```
{
 "inputs": {factory_rmb:num2, fx_cny_usd:float, freight_per_unit_usd:num2,
            customs_fee_per_unit_usd:num2, customs_fee_placeholder:bool,
            duty_pct:num2, duty_source:"hts"|"explicit",
            hts:str|null, mfn_pct:num|null, section301_pct:num|null,
            platform:str, category:str|null, category_key:str|null,
            category_source:"explicit"|"alias"|"platform_path"|"assumed_default",
            referral_pct:num2, referral_source:"platform_category"|"platform_default"|"explicit",
            fba_fee_usd:num2, fba_tier:str, fba_tier_label:str,
            fba_season:"peak"|"nonpeak"|"-", fba_price_band:"lt10"|"10_50"|"gt50"|"-",
            fba_base_fee_usd:num2, fba_surcharge_pct:float, weight_oz:num2|null,
            ads_pct:num2, returns_pct:num2, price_usd:num2,
            target_margin_pct:num2, moq:int},
 "costs": {fob_usd:num2, freight_usd:num2, duty_usd:num2,
           customs_fee_usd:num2, landed_cost_usd:num2},
 "fees": {referral_usd:num2, referral_pct_effective:num2, fba_fee_usd:num2,
          ads_usd:num2, returns_usd:num2},
 "profit": {net_profit_usd:num2, net_margin_pct:num2, contribution_per_unit_usd:num2},
 "pricing": {break_even_price_usd:num2, target_price_usd:num2,
             price_gap_usd:num2, target_price_reached:bool},
 "cash": {moq:int, cash_required_usd:num2},
 "summary": {net_margin_pct, break_even_price, target_price,
             cash_required, contribution_per_unit},
 "assumptions": [str], "notes": [str]
}
```

`num2` = JSON 数值、最多 2 位小数（Python `round` 结果，不补零）。`summary` 与对应字段同值。
人类可读（Markdown）结构：`# 到岸成本与定价测算` → `## 1. 输入与口径`（工厂价/汇率/MOQ、售价/广告/退货、关税来源与拆分、平台/类目/来源/有效 referral、FBA 档/季节/价格档/基准+燃油、目标净利率与报关杂费、逐条 notes）→ `## 2. 到岸成本拆解`（FOB/头程/关税/杂费/到岸成本）→ `## 3. 定价与利润`（售价、到岸、佣金、FBA、广告、退货、净利、贡献毛利及占售价）→ `## 4. 底线价与现金流`（盈亏价、目标价与差额方向、MOQ 占款）→ 公式与时点口径脚注。金额格式 `$1,234.56`，百分比 2 位。

### 4.2 `matrix` 成功 JSON

```
{"meta": {generated_by:"landed_cost.py matrix", fx_cny_usd:float,
          defaults:str, rows:int},
 "rows": [<calc 结果>, {..., "sku":str, "judgement":"达标"|"低于目标净利"|"亏损"}]}
```

`rows` 保持 CSV 有效行顺序；`meta.rows` 只计成功行。人类可读：标题 `# SKU 到岸成本与定价矩阵`；头部汇率与默认值说明；表列 `SKU | 到岸成本 | 售价 | 净利/件 | 净利率 | 盈亏价 | 目标价 | MOQ占款 | 判断`；表下合计 MOQ 占款、净利率最高/最低 SKU；有失败行时追加 `## 无法计算的行（已跳过，整表继续）` 列表；脚注给判断口径、未核校 HTS 提醒（按 SKU 排序）、费率时点提醒。金额 `$` 千分位，净利率 2 位。

### 4.3 列表命令

- `--list-platforms`：`# 平台费率速查`；口径日期/币种/disclaimer；按平台 `## 名称（key）`、默认 referral 与最低佣金、类目表（key/类目/referral 分段/备注），分段用 `<br>` 连接。
- `--list-fba-tiers`：`# FBA 尺寸档速查（2026 年）`；口径日期、两窗口、燃油费率与生效日、`_meta.note`；按非旺季/旺季两张表 `档位 | 发货重量 | <$10 | $10–$50 | >$50`；`over_3lb` 行显示「3–20 lb」「基准 + $0.08/4oz」。

### 4.4 失败契约与退出码

统一由 `cli_common.fail`：`--json` 时 **stdout** 输出合法 JSON，人类信息写 **stderr**；非 JSON 时只写 stderr。退出码：`2`=输入错误（含 argparse 参数错误），`3`=参数/配置错误（当前仅 `us_fees.json` 缺 `fba.tiers` 用到），`0`=成功。

单条错误 JSON：
```
{"status":"INPUT_MISSING"|"ERROR", "missing":[str], "message":str}
```
`status` 默认 `INPUT_MISSING`；当前代码未主动传 `ERROR`，故实际只见 `INPUT_MISSING`。`message` 会剥离开头的 `[INPUT_MISSING]`/`[ERROR]` 标签。`calc` 缺参时 `message` 里的参数名按旧实现用 `", "`（逗号+空格）拼接，不使用中文顿号。

矩阵失败 JSON（有失败行时）：
```
{"status":"INPUT_MISSING","missing":[合并去重并排序的 missing],
 "message":"以下 SKU 行无法计算（整表其余行已继续）：...",
 "failed_rows":[{row:int, sku:str|null, message:str, missing:[str]}],
 "rows":[成功行]}
```
非 JSON 矩阵：先打印完整 Markdown（含失败行列表），再向 stderr 发一条汇总消息，退出 2；stdout **不含** `rows` JSON。

场景与退出码（实测/代码明确）：

| 场景 | 退出码 | 输出要点 |
|---|---|---|
| 无子命令、无列表 flag | 2 | 打印 help，JSON 错误 `缺少子命令：calc 或 matrix` |
| `calc` 缺必填参数 | 2 | 一次列全 `--fx`、`--freight-per-unit`、FBA、`--price`、关税项 |
| argparse 类型错误（如 `--factory-rmb abc`） | 2 | `参数错误：argument --factory-rmb: invalid float value: 'abc'`；`--json` 时仍是 JSON |
| `factory-rmb < 0` | 2 | `missing=["factory_rmb"]` |
| `fx ≤ 0` | 2 | `missing=["fx"]` |
| `price ≤ 0` | 2 | `missing=["price"]` |
| 缺关税口径 | 2 | `missing=["duty_pct|hts"]` |
| 缺 FBA 口径 | 2 | `missing=["fba_fee|weight_g|weight_oz"]` |
| 缺类目且未开兜底 | 2 | `missing=["category_key"]`，列出可选类目 |
| 无法识别类目/路径歧义 | 2 | `missing=["category_key"]` |
| `--category` 与 `--category-key` 不一致 | 2 | `missing=["category_key"]` |
| 不支持的 platform | 2 | `missing=["platform"]` |
| HTS 未收录 | 2 | `missing=["hts"]`，提示改用 `--duty-pct` |
| 重量超出所选档 | 2 | `missing=["weight_oz"]` |
| referral+广告+退货 ≥100% | 2 | `missing=["referral|ads_pct|returns_pct"]` |
| referral+广告+退货+目标净利率 ≥100% | 2 | `missing=["target_margin"]` |
| `--ship-date` 非法（无显式 `--season`/`--fba-fee`） | 2 | `missing=["ship_date"]` |
| `--ship-date` 非法 + 显式 `--fba-fee` | 0 | 日期根本未被解析，计算正常完成 |
| `--ship-date` 非法 + 显式 `--season` + 重量推导 | **1** | 未捕获 `ValueError` traceback |
| matrix 文件不存在 / 无表头 / 无数据行 | 2 | `missing=["file"]` |
| matrix 缺必需列 | 2 | `missing=[缺失列名...]`，并列出 `duty_pct|hts`、`fba_fee|weight_g|weight_oz` 的要求 |
| matrix 行失败 | 2 | 整表继续，失败行汇总（见上） |
| `us_fees.json` 缺 `fba.tiers` | 3 | `missing=["us_fees.json:fba.tiers"]` |
| 配置文件不存在/无法解析 | 2 | `missing=[配置路径]` |

### 4.5 矩阵行级失败的 `missing` 聚合（probe，2026-10-30）

`failed_rows[].missing` 只承载「缺哪个输入项才能修好这一行」的**字段名**；行内数值解析失败、必填为空、口径两空属于「值坏了/没值」，没有可直接补的字段名，故为 `[]`。顶层 `missing` = 各行 `missing` 的并集去重后排序。

| 失败类型 | 触发示例（第 N 行） | `failed_rows[].missing` | 是否进入顶层 `missing` |
|---|---|---|---|
| 数值不可解析 | `weight_g=abc` | `[]` | 否 |
| 必填数值为空 | `price` 为空 | `[]` | 否 |
| `sku` 为空 | 首列为空 | `[]` | 否 |
| 关税口径两空 | `duty_pct` 与 `hts` 均为空 | `[]` | 否 |
| FBA 口径三空 | `fba_fee`/`weight_g`/`weight_oz` 均空 | `[]` | 否 |
| 类目缺失（未开兜底） | 无 `category_key`/`category` | `["category_key"]` | 是 |
| 平台非法 | `platform=bogus` | `["platform"]` | 是 |
| FBA 档未知 | `fba_tier=bogus` | `["fba_tier"]` | 是 |
| 重量超出档上限 | 20000 g → 705.48 oz | `["weight_oz"]` | 是 |

判定依据：`missing` 由抛错调用点传入——matrix 的行内前置校验（sku/数字/必填/口径空）统一传 `missing=[]`；`compute_sku` 中的配置/枚举/边界错误沿用其单 SKU 形态的 `missing`（`category_key`/`platform`/`fba_tier`/`weight_oz` 等）。

探测（旧仓库，2026-10-30）：

```powershell
python Agents/02_Cost_Pricing_Agent/scripts/landed_cost.py matrix --file <9 行坏样本.csv> --fx 0.14 --json
```

观察：EXIT=2；9 行全部失败；逐行 `missing` 依次为 `[]`、`[category_key]`、`[platform]`、`[fba_tier]`、`[]`、`[]`、`[]`、`[weight_oz]`、`[]`；顶层 `missing=["category_key","fba_tier","platform","weight_oz"]`。

### 4.6 `inputs.customs_fee_placeholder`（字段存在性语义，probe，2026-10-30）

- **恒存在**：`calc` 成功 JSON 的 `inputs`、`matrix` 成功行的 `inputs` 均包含该布尔字段。
- 未显式传入（`calc` 无 `--customs-fee-per-unit`；CSV `customs_fee_per_unit` 单元格为空）→ `true`，且 `notes` 追加 `[WARN] 未提供 --customs-fee-per-unit，报关杂费按默认 $0.18/件计算`。
- 显式传入（含显式传 `0.18` 本身）→ `false`，不追加该 `[WARN]`。
- `[WARN]` note 的位置：`calc` 中位于默认值类 note 第 5 条（`index 4`，即 ads/returns/target/moq 之后、platform 之前）；`matrix` 行里 ads/returns/target/moq 默认 note 被抑制，该条成为 `notes[0]`（队首），其后才是 platform/旺季/燃油/分段近似。
- 该字段与 `[WARN]` 前缀是重写新增，旧实现既无该键也无该前缀、只有无前缀的默认 note（`notes[4]`）；对应 `99_gap_and_decisions.md` 有意差异 #8，既有字段语义不变。

探测（2026-10-30）：

| 命令 | 旧结果 | 新结果 |
|---|---|---|
| `calc ...`（不传 customs） | `notes[4]="未提供 --customs-fee-per-unit，报关杂费按默认 $0.18/件计算"`；`inputs` 无 `customs_fee_placeholder` | `inputs.customs_fee_placeholder=true`；`notes[4]` 带 `[WARN] ` 前缀 |
| `calc ... --customs-fee-per-unit 0.5` | 无该 note；无该键 | `=false`；无 `[WARN]` |
| `matrix`（行 customs 空） | 行 `notes[0]="未提供 --platform，按 amazon_us 计算"`；无该键 | `=true`；`notes[0]` 为 `[WARN] …报关杂费…` |
| `matrix`（行 customs=0.5） | 同上；无该键 | `=false`；`notes[0]` 恢复为 platform note |

## 5. 计算规则

所有金额 `round2(x)=round(x+0.0, 2)`，即 Python 内置 `round` 的银行家舍入 + 二进制浮点实际结果；不额外加 0.005。

### 5.1 到岸成本

- `FOB = round2(factory_rmb × fx)`
- `freight = round2(freight_per_unit)`
- `duty_usd = round2(FOB × duty_pct / 100)`
- `customs = round2(customs_fee_per_unit)`，默认 0.18
- `landed = round2(FOB + freight + duty_usd + customs)`，**四个分量先各自取整再求和**

关税口径：
- 显式 `--duty-pct`：`duty_pct` 原值；`hts/mfn/section301 = null`；`duty_source=explicit`。
- HTS：`duty_pct = mfn_pct + section301_pct`；`hts` 为命中的键；`duty_source=hts`。`verified=false` 时 notes 追加「为未核校示例…必须用 --duty-pct 覆盖」。
- HTS 匹配：去空格、去尾部 `.` 后，若 `cleaned == key`、`cleaned` 以 key 开头、或 key 以 `cleaned` 开头均算候选；取「最长 key，其次字典序最大」。**前缀输入会静默选中字典序最大的子目**（如 `--hts 8509` → `8509.90`，税率 41.7%，而非 8509.40 的 16.7%）。

### 5.2 Referral

优先级：显式 `--referral` > `tiktok_us` 平台默认 > `amazon_us` 类目分段/旧结构 > 缺省兜底。

- 显式：`referral_usd = round2(price × referral / 100)`；`referral_pct_effective = referral`；`label="显式 referral"`；`tiered=false`；不受最低佣金约束。
- `tiktok_us`：`rate = default_referral_pct`（6.0）；`referral_usd = round2(price × rate/100)`；`source=platform_default`；`min` 不生效；notes 追加 6% 与新手优惠说明 + 「达人佣金另计」。
- `amazon_us`：
  - 类目缺失且 `--assume-default-referral`：用 `default` 类目（15%），`category_source=assumed_default`，`assumption` 写入输出 `assumptions`，notes 加 `[WARN]`。
  - 类目解析：精确 key → 别名 → 平台路径最长前缀；命中路径/别名时 notes 提示，路径映射带 `[WARN]`。
  - 分段：`tiered_amount(price, tiers)` 从 0 开始逐段累加：每段 `portion = min(price, upper) − lower`（`upper=null` 视为 ∞）；`portion>0` 时计入 `portion × pct/100` 并推进 `lower`；`price ≤ upper` 时停止。`amount_raw` 求和后 `round2`。
  - 有效费率：`referral_pct_effective = round2(amount_raw / price × 100)`（`price=0` 时为 0，但入口已拒绝 ≤0）。
  - 旧结构（无 `tiers`）：`base=referral_pct(默认15)`；若 `threshold` 与 `above` 均存在且 `price > threshold`，`amount = round2(base×threshold/100 + above×(price−threshold)/100)`；否则 `round2(price×base/100)`。
  - 最低佣金：`effective_min = 类目 min_fee_usd`（若存在，可为 0）否则平台 `min_referral_fee_usd`（Amazon 0.30）；若 `effective_min > 0` 且 `amount < effective_min`，`amount = round2(effective_min)`，重算有效费率，`min_applied=true`，notes 提示。
  - 输出字段：`category=us_fees_key`、`category_key=canonical`、`source=platform_category`、`tiered`（分段或旧结构为 true）、`detail`（逐段文本）。

### 5.3 FBA

- 显式 `--fba-fee`：`fee = round2(fba_fee)`；`base_fee = fee`；`surcharge=0`；`tier="explicit"`、`tier_label="显式 --fba-fee"`、`season/price_band="-"`；不判季节、不判日期、不加燃油费；`weight_oz` 有值时记录。
- 重量换算：`weight_oz = round2(weight_g / 28.3495)`；若直接给 oz 则用原值（不取整）。
- 档位：无 `--tier` 时 `weight_oz ≤ 16` → `small_standard`，否则 `large_standard`；显式档必须在 `fba.tiers` 中。
- 季节：`--season` 为 `peak`/`nonpeak` 时直接用并写 note；否则取 `--ship-date`，缺省 `date.today()`；落在旺季窗口→`peak`；落在非旺季窗口→`nonpeak`；两窗口外→`nonpeak` + 「超出 2026 已公布窗口…需复核」。
- 价格档：`price < 10` → `lt10`；`10 ≤ price ≤ 50` → `10_50`；`price > 50` → `gt50`。
- 有 `rates` 的档（standard）：
  - 顺序扫描该季节的 `rates`，取第一个 `weight_oz ≤ max_oz` 的行。
  - 行含 `fees`：`base_fee = fees[band]`。
  - 行含 `over_3lb`（large_standard 的 48–320 oz 段）：`steps = max(0, ceil((weight_oz − 48)/4))`；`base_fee = base[band] + steps × per_4oz_usd`（当前 0.08）。重量 ≤48 时 steps=0。
  - 无匹配行（超过该档最大 oz）→ 输入错误 2，提示换档或显式 FBA 费。
- 无 `rates` 的 bulky 档：`extra_lb = max(0, ceil(weight_oz/16) − 1)`；`base_fee = base[season][band] + extra_lb × per_lb_over_first_usd`（当前 0.38）。
- 燃油附加费：未加 `--no-fuel-surcharge` 时，参考日 = `--ship-date` 或 `date.today()`；参考日 ≥ `2026-04-17` → `surcharge_pct = 3.5`，note 提示；否则 0。
- `fee = round2(base_fee × (1 + surcharge_pct/100))`；`base_fee_usd = round2(base_fee)`。

### 5.4 利润、价格线与现金

- `ads = round2(price × ads_pct/100)`；`returns = round2(price × returns_pct/100)`。
- `net = round2(price − landed − referral_usd − fba − ads − returns)`
- `margin = round2(net / price × 100)`（入口保证 price>0）
- `contribution = round2(price − landed − referral_usd − fba)`（广告/退货前）
- `variable_pct = referral_pct_effective + ads_pct + returns_pct`
- `denom_be = 1 − variable_pct/100`；`denom_be ≤ 0` → 输入错误 2。
- `break_even = round2((landed + fba) / denom_be)`
- `denom_target = 1 − (variable_pct + target_margin)/100`；`≤0` → 输入错误 2。
- `target_price = round2((landed + fba) / denom_target)`
- `price_gap = round2(price − target_price)`；`target_price_reached = price ≥ target_price`
- `cash = round2(landed × moq)`（moq 不校验，≤0 可产生 0/负占款）
- 分段 referral 时 notes 追加「盈亏价/目标价用当前售价下有效费率近似反算」。

### 5.5 矩阵判断

- `price ≥ target_price` → `达标`；否则 `price ≥ break_even` → `低于目标净利`；否则 `亏损`。
- 合计占款 = `round2(Σ cash_required_usd)`；最好/最差按 `net_margin_pct` 取 max/min（同值取先出现者）。
- 未核校提醒：收集所有 notes 含「未核校」的成功行 SKU，排序去重后输出。

### 5.6 主基准逐项算例（新实现必须逐项一致）

以 §7.1 命令为例，按代码执行顺序：

1. `FOB = round(38×0.14, 2) = round(5.32, 2) = 5.32`。
2. 关税：`8509.40` → `mfn=4.2`、`section301=12.5` → `duty_pct=16.7`；`duty = round(5.32×0.167, 2) = round(0.88844, 2) = 0.89`。
3. `freight=1.60`、`customs=0.18`；`landed = round(5.32+1.60+0.89+0.18, 2) = 7.99`。注意关税以**已取整的 FOB** 为基数。
4. `weight_oz = round(620/28.3495, 2) = round(21.8724…, 2) = 21.87`；`21.87 ≤ 24` 行、`price=29.99` 落 `10_50` → 基准 `5.73`。
5. 燃油：`2026-10-30 ≥ 2026-04-17` → 3.5%；`fba = round(5.73×1.035, 2) = round(5.93055, 2) = 5.93`。附加费以**未取整的档位费**乘算后再舍入。
6. referral：`29.99×15% = 4.4985 → 4.5`；`effective = round(4.4985/29.99×100, 2) = 15.0`。
7. 广告 `29.99×10% = 2.999 → 3.0`；退货 `29.99×3% = 0.8997 → 0.9`。
8. `net = round(29.99−7.99−4.5−5.93−3.0−0.9, 2) = 7.67`；`margin = round(7.67/29.99×100, 2) = round(25.5751…, 2) = 25.58`。
9. 贡献毛利 `= round(29.99−7.99−4.5−5.93, 2) = 11.57`。
10. `variable = 15.0+10+3 = 28.0`；盈亏价 `= round((7.99+5.93)/(1−0.28), 2) = round(13.92/0.72, 2) = round(19.3333…, 2) = 19.33`。
11. 目标价分母 `= 1−(28.0+25)/100 = 0.47`；`= round(13.92/0.47, 2) = round(29.6170…, 2) = 29.62`。
12. `price_gap = round(29.99−29.62, 2) = 0.37`；`target_price_reached = true`（29.99 ≥ 29.62）。
13. `cash = round(7.99×500, 2) = 3995.0`。

对照矩阵：若某行 `price ≥ target_price` → 达标；若 `break_even ≤ price < target` → 低于目标净利；若 `price < break_even` → 亏损。矩阵合计占款是各行 `cash_required_usd`（已 2 位）之和再 `round2`，因此与「合计到岸×MOQ」可能有分币差异。

## 6. 已知行为与坑（现状）

| # | 现象 | 触发条件 | 现状行为（实测退出码/输出） | 建议 |
|---|---|---|---|---|
| 1 | 缺类目不再静默 | calc/matrix 未给类目且无 `--referral` | 报错退出 2，提示 `--assume-default-referral`；列出全部可选 key | 保留强制显式 |
| 2 | 兜底与不兜底差异 | 同上 + `--assume-default-referral` | 成功；`category=default`、`category_source=assumed_default`、`assumptions` 有文案；实测净利率 29.86%（12.99 售价样例） | 保留并把 assumption 显示在报告显著位置 |
| 3 | 矩阵单行失败不再整表中断 | matrix 某行缺 duty/坏数字/非法平台 | 逐行报错、其余行继续；JSON 输出 `failed_rows` + 成功 `rows`；EXIT=2；非 JSON 先打印表格再 stderr 汇总 | 保留；建议非 JSON 的失败摘要也进 JSON 错误对象 |
| 4 | 未核校 HTS 仅提醒不阻断 | `--hts` 命中 `8516`/`3924`/`6307`/`8479` | 正常计算；notes 提醒；矩阵末尾列出 SKU 强制复核 | 保留提醒；可考虑 `--strict` |
| 5 | 旺季/燃油按 ship-date | `--season auto`（缺省） | 2026-10-30 → peak；燃油按 `2026-04-17` 起 +3.5% | 保留；报告必须显示判定依据 |
| 6 | 显式 `--fba-fee` 完全跳过日期逻辑 | 给 `--fba-fee` | 非法 `--ship-date` 也被忽略，EXIT=0；`fba_season="-"`、附加费 0 | 新实现应仍校验日期格式 |
| 7 | 非法日期 + 显式 season → 崩溃 | `--season peak --ship-date 2026-13-01` 且用重量推导 | 未捕获 `ValueError: month must be in 1..12`，traceback，EXIT=**1** | 统一为输入错误 2 |
| 8 | argparse 错误也走 JSON | `--json` 在 argv 中且参数类型错误 | stdout 输出 `{"status":"INPUT_MISSING","missing":[],"message":"参数错误：..."}`，EXIT=2；usage 写 stderr | 保留；`missing` 建议填参数名 |
| 9 | 参数/配置错误退出码仍为 2 | `JsonArgumentParser.error_code=2`；仅 `fba.tiers` 缺失用 3 | 参数错误与配置错误多为 2，3 极少 | 统一码表或文档固定现状 |
| 10 | `no_fuel_surcharge` 字符串真值 | matrix 列值 `"false"`/`"0"` | `bool(non-empty)` → **True**，附加费被关闭（实测 NF-1/NF-2 附加费 0） | 解析为明确的布尔枚举 |
| 11 | `--hts` 前缀匹配选错子目 | 只给 4 位品目如 `8509` | 选中 `8509.90`（41.7%），不是整机 `8509.40`（16.7%） | 前缀匹配应拒绝或要求完整子目 |
| 12 | 负关税不校验 | `--duty-pct -5` | 正常计算，`duty_usd=-0.27`、到岸成本下降，EXIT=0 | 增加 0–100 范围校验 |
| 13 | `moq ≤ 0` 不校验 | `--moq 0` 或负数 | `cash_required=0` 或负值，EXIT=0 | 增加 ≥1 校验 |
| 14 | 同时给 `--category`/`--category-key` 相同值 | 两参数等值 | 通过，无提示 | 保留 |
| 15 | 平台路径映射只提示 | 传 `"Home & Kitchen > Small Appliances"` | 映射成功，`category_source=platform_path`，notes `[WARN] 建议 brief 直接写 category_key` | 保留 |
| 16 | 类目路径歧义 | 同长度前缀命中多个 key | 退出 2，`missing=["category_key"]`；当前配置下未实测到歧义样本 | 保留拒绝猜测 |
| 17 | TikTok 忽略类目 | `--platform tiktok_us` + `--category` | 不解析类目，仅回显；referral 6%，`source=platform_default` | 文档写明类目对 TikTok 无意义 |
| 18 | 显式 referral 免类目 | `--referral 15` 无类目 | 成功；`category=null`、`source=explicit`、不受 min 佣金约束 | 保留 |
| 19 | 矩阵 notes 每行重复 | 多行同平台/同季节 | 每行 notes 重复「未提供 --platform」「旺季窗口」「燃油附加」 | 可去重或在 meta 层汇总 |
| 20 | matrix 列默认与 calc 参数默认一致 | 空单元格 | ads 10 / returns 3 / target 25 / moq 500 / customs 0.18；`moq` 先 float 再 int 截断 | 保留 |
| 21 | `--list-platforms` 优先 | 列表 flag + 子命令 | 只打印列表，EXIT=0；子命令参数被忽略 | 保留或报互斥 |
| 22 | 顶层 `--json` 无效 | `landed_cost.py --json` | argparse `unrecognized arguments: --json`，EXIT=2（JSON 错误） | 新实现可考虑全局 `--json` |
| 23 | 输出舍入 | 任意金额 | Python `round` 银行家舍入 + 浮点误差；例如 4.4985→4.5、5.6097→5.61 | 明确舍入口径并加对拍断言 |
| 24 | 配置解析失败统一 2 | JSON 损坏/文件缺失 | `fail(..., missing=[路径])`，EXIT=2（不是 3） | 与码表统一 |

### 6.1 现状行为补充（probe，2026-10-30）

**`--season` 非法值的两条路径**

| 路径 | 形态 | 行为 | 退出码 |
|---|---|---|---|
| CLI 参数 | `calc ... --season bogus` | argparse `choices=["auto","nonpeak","peak"]` 直接拒绝；`--json` 时 stdout 为 `{"status":"INPUT_MISSING","missing":[],"message":"参数错误：argument --season: invalid choice: 'bogus' (choose from 'auto', 'nonpeak', 'peak')"}`，usage 写 stderr | 2 |
| CSV `season` 列 | `matrix --file ...`，行值 `fubar` / `peak2` | **不校验枚举**：只有字面量 `peak`/`nonpeak` 被采用，其余一律置空 → 走 auto，按 `ship_date`（缺省运行日）判定季节；该行正常计算 | 0 |

CSV 为何是 auto：matrix 本身没有 `--season` 选项，行级解析只认两个合法字面量，其他值等同「未指定」，于是回落到日期判定。探测结果：`SEA-BOGUS → fba_season=peak、fba_fee_usd=5.93`，notes 含「按 2026-10-30 落在 2026-10-15 至 2027-01-14 旺季窗口计算」；`SEA-NONPEAK → nonpeak、5.61`，notes 含「显式指定 --season nonpeak」。

**非法日期 + 显式 season → 退出 1**（非 2）

```powershell
python Agents/02_Cost_Pricing_Agent/scripts/landed_cost.py calc --factory-rmb 38 --fx 0.14 --freight-per-unit 1.6 --hts 8509.40 --category-key small_appliances --weight-g 620 --price 29.99 --season peak --ship-date 2026-13-01 --json
```

观察：EXIT=**1**，stdout 为空，stderr 是未捕获 `ValueError: month must be in 1..12` 的 traceback（显式 season 时仍要解析 ship-date 判燃油附加费）。对照：不传显式 season 的同命令 EXIT=2、`missing=["ship_date"]`。

**无子命令 → help 写 stdout**

```powershell
python Agents/02_Cost_Pricing_Agent/scripts/landed_cost.py
```

观察：EXIT=2；usage/help 全部写 **stdout**（首行 `usage: landed_cost.py [-h] [--list-platforms] [--list-fba-tiers]`）；`缺少子命令：calc 或 matrix` 写 stderr。

## 7. 对拍基准（可复现）

工作目录：仓库根；Python 3.12.0；运行日 2026-10-30（未给 ship-date 时按此）。以下命令均实测。

### 7.1 calc 主基准（必须逐字复现）

```powershell
python Agents/02_Cost_Pricing_Agent/scripts/landed_cost.py calc --factory-rmb 38 --fx 0.14 --freight-per-unit 1.60 --hts 8509.40 --category-key small_appliances --weight-g 620 --price 29.99 --ship-date 2026-10-30 --ads-pct 10 --returns-pct 3 --target-margin 25 --moq 500 --json
```

- EXIT=0。
- 关键输入推导：`weight_oz=21.87` → `large_standard`；`price` 落 `10_50`；ship-date 落旺季 → 基准 `$5.73`；+3.5% → `fba_fee_usd=5.93`；HTS 8509.40 → MFN 4.2 + S301 12.5 = **16.7%**。
- 期望：
  - `costs.fob_usd=5.32`、`freight_usd=1.6`、`duty_usd=0.89`、`customs_fee_usd=0.18`、`landed_cost_usd=7.99`
  - `fees.referral_usd=4.5`、`referral_pct_effective=15.0`、`fba_fee_usd=5.93`、`ads_usd=3.0`、`returns_usd=0.9`
  - `profit.net_profit_usd=7.67`、`net_margin_pct=25.58`、`contribution_per_unit_usd=11.57`
  - `pricing.break_even_price_usd=19.33`、`target_price_usd=29.62`、`price_gap_usd=0.37`、`target_price_reached=true`
  - `cash.cash_required_usd=3995.0`
  - `inputs.fba_season="peak"`、`fba_price_band="10_50"`、`fba_surcharge_pct=3.5`
  - `notes` 含默认报关杂费、默认 platform、分段有效费率、旺季窗口、燃油附加、分段反算提醒。

### 7.2 季节与燃油对照

```powershell
# 非旺季
... calc --factory-rmb 38 --fx 0.14 --freight-per-unit 1.60 --hts 8509.40 --category-key small_appliances --weight-g 620 --price 29.99 --season nonpeak --json
# 非旺季 + 关闭燃油
... --season nonpeak --no-fuel-surcharge --json
```

| 用例 | FBA 基准 | FBA 费 | 净利 | 净利率 | 盈亏价 | 目标价 | EXIT |
|---|---|---|---|---|---|---|---|
| 旺季（7.1） | 5.73 | 5.93 | 7.67 | 25.58 | 19.33 | 29.62 | 0 |
| 非旺季 | 5.42 | 5.61 | 7.99 | 26.64 | 18.89 | 28.94 | 0 |
| 非旺季 + 无燃油 | 5.42 | 5.42 | 8.18 | 27.28 | — | — | 0 |

### 7.3 矩阵基准

```powershell
python Agents/02_Cost_Pricing_Agent/scripts/landed_cost.py matrix --file Agents/02_Cost_Pricing_Agent/examples/sample-skus.csv --fx 0.14 --json
```

- 输入要点：5 行；列 `sku,factory_rmb,freight_per_unit,hts,category,weight_g,ads_pct,returns_pct,price,target_margin,moq`；未给 ship-date → 运行日旺季。
- EXIT=0；`meta.rows=5`。
- 期望每行关键值：

| SKU | 到岸成本 | 净利/件 | 净利率 | 盈亏价 | 目标价 | MOQ占款 | 判断 |
|---|---|---|---|---|---|---|---|
| PB-16OZ-01 | 7.99 | 7.67 | 25.58 | 19.33 | 29.62 | 3995.00 | 达标 |
| PB-CUP-02 | 2.64 | 3.36 | 25.87 | 8.51 | 14.18 | 2640.00 | 低于目标净利 |
| PB-BLADE-03 | 1.96 | 2.76 | 27.63 | 6.31 | 10.51 | 3920.00 | 低于目标净利 |
| PB-BUNDLE-04 | 10.88 | 10.05 | 25.13 | 26.03 | 39.87 | 3264.00 | 达标 |
| PB-BOTTLE-05 | 4.55 | 5.66 | 29.81 | 11.44 | 18.26 | 3640.00 | 达标 |

- 合计占款 `$17,459.00`；最高净利率 PB-BOTTLE-05（29.81%），最低 PB-BUNDLE-04（25.13%）。
- 未核校 HTS 提醒 SKU：PB-CUP-02、PB-BLADE-03、PB-BOTTLE-05（使用 3924/8479）。

### 7.4 失败用例（实测）

| 用例 | 期望 |
|---|---|
| `calc --factory-rmb 38 --json` | EXIT=2；JSON `missing=[--fx, --freight-per-unit, --fba-fee 或 --weight-g/--weight-oz, --price, --duty-pct 或 --hts]` |
| `calc --factory-rmb abc --json` | EXIT=2；JSON `message="参数错误：argument --factory-rmb: invalid float value: 'abc'"` |
| `calc ... --factory-rmb -1 ... --json` | EXIT=2；`missing=["factory_rmb"]` |
| `calc ... --fx 0 ... --json` | EXIT=2；`missing=["fx"]` |
| `calc ... --price 0 ... --json` | EXIT=2；`missing=["price"]` |
| `calc ... --ads-pct 90 --json` | EXIT=2；`missing=["referral|ads_pct|returns_pct"]` |
| `calc --hts 8509 ...` | EXIT=0；命中 8509.90，`mfn=4.2`、`section301=37.5`、`duty_pct=41.7`（已知坑） |
| `calc ... --ship-date 2026-13-01`（重量推导） | EXIT=2；`missing=["ship_date"]` |
| `calc ... --season peak --ship-date 2026-13-01` | EXIT=**1**；`ValueError` traceback（已知坑） |
| `calc ... --fba-fee 5.93 --ship-date 2026-13-01` | EXIT=0；日期被忽略 |
| `matrix --file <坏行 CSV> --fx 0.14 --json` | EXIT=2；`failed_rows` 两条（缺 duty、坏数字），`rows` 两条成功 |
| `matrix --file <无类目行> --fx 0.14 --json` | EXIT=2；`failed_rows` 含 `missing=["category_key"]`，`rows=[]` |
| 同上 + `--assume-default-referral` | EXIT=0；`category_source=assumed_default`，净利率 29.86% |
| `matrix --file <空文件/无表头>` | EXIT=2；`missing=["file"]` |
| `matrix --file <只有表头>` | EXIT=2；`missing=["file"]` |
| `matrix --file <缺 sku 列>` | EXIT=2；`missing=["sku"]` |
| `matrix --file <不存在>` | EXIT=2；`missing=["file"]` |
| `--list-platforms` / `--list-fba-tiers` | EXIT=0，Markdown 列表 |
| 无参数 | EXIT=2；help + `缺少子命令：calc 或 matrix` |

## 8. 未完整刻画/待确认

1. **舍入细节**：`round2` 用 Python `round`，银行家舍入与浮点误差的具体组合未穷举；规格需固定「先算后舍、2 位、银行家」还是十进制 HALF_UP。
2. **分段边界**：实测 price=300 时 referral=45.0（15%），说明 ≤300 段含边界；price 恰好 15/20/100/250/1500 等其它边界未逐一实测。
3. **HTS 前缀匹配的反向包含**：除 `8509` 外，短编码（如 `85`）、带点尾（如 `8509.`）、`8509.40.00.15` 的匹配结果未逐一实测；已知 `8509` 会选 8509.90。
4. **类目路径同长度歧义**：代码会报错，但当前配置未构造出实测样本，错误文案与 `missing` 已按代码记录。
5. **旧结构 referral 分支**：`referral_pct + tier_threshold_usd + above_threshold_pct` 的兼容逻辑当前配置不触发，未实测。
6. ~~**`season` 列的非法值**：matrix 不校验枚举，`"foo"` 会走 auto 分支并可能按 ship-date 判定；未实测。~~ 已实测（2026-10-30）：`fubar`/`peak2` 均回落 auto，见 §6.1。
7. **`no_fuel_surcharge` 的合法取值集合**：当前是「非空即真」，新实现需产品确认布尔表示（`true/false`、`1/0`、`Y/N`）。
8. **`--fba-fee` + 极小/负值**：不校验，可能产生负 FBA 费；未实测。
9. **`--weight-g`/`--weight-oz` 为负或 0**：可能落入最小档或异常；未实测。
10. **矩阵超过档位上限时的整表行为**：单行失败并继续已由 catch 覆盖，但错误消息中的重量格式未逐档验证。
11. **FBA `_meta`/`windows` 与代码常量不一致**：代码硬编码 2026 窗口常量，JSON 也有 `windows`；若两者被改成不同值，以代码常量为准（未实测配置漂移）。
12. **`status="ERROR"` 分支**：`fail` 支持但当前调用均未传 `ERROR`；新实现是否引入运行期错误分类待定。
13. **`--list-platforms` / `--list-fba-tiers` 与 `--json`**：列表命令忽略 `--json` 且顶层不接受 `--json`；未定义机器可读版本。
14. **文件行数**：任务描述约 1047 行，实际文件 1152 行；本文按实际文件行为撰写。
