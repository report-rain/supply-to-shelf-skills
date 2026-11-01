# product_brief 填写模板

> 这是一份**给人填写**的事实清单，不是程序读取的配置格式。仓库里的脚本只消费命令行参数（或 CSV / JSON 输入文件），不会读取本文件。
>
> 用法：复制本文件改名（如 `product_brief_<产品名>.md`），逐项填写。缺字段时脚本按「不猜」原则报 `[INPUT_MISSING]` 并退出 2 / 3；空值请写 `未确认`，不要留空或填 0 掩盖。

## 1. 产品基础信息

| 字段 | 单位 / 取值 | 示例 | 必填 | 用途 / 对应 CLI |
|---|---|---|---|---|
| `product_name` | 文本 | `NordPulse Portable Blender 16 oz` | 是 | 04 `title` / `item_name`；报告标题 |
| `brand` | 文本 | `NordPulse` | 是 | 04 Amazon `brand` 前置检查 |
| `model` | 文本 | `NP-BL16` | 可选 | 报告与证书型号核对 |
| `marketplace` | `amazon_us` / `tiktok_us` / `both` | `amazon_us` | 是 | 03 `--marketplace`；04 / 05 `--platform` |
| `launch_date` | `YYYY-MM-DD` | `2026-11-15` | 可选 | 认证周期倒排、旺季判断参考 |
| `supplier` | 文本 | `宁波某某电器` | 可选 | 证书主体与工厂一致性核对 |

## 2. 类目

| 字段 | 单位 / 取值 | 示例 | 必填 | 用途 / 对应 CLI |
|---|---|---|---|---|
| `category_key` | `config/category_map.json` 的键 | `small_appliances` | 是（推荐） | 02 `--category-key`；03 `--category` |
| `platform_category_path` | 后台类目完整路径 | `Home & Kitchen > Kitchen & Dining > Small Appliances` | 条件必填（无 `category_key` 时） | 02 `--category`；03 `--category` |
| `compliance_key` | 由 `category_key` 映射得到，不要手填 | `small_appliances` | 否 | 03 内部使用，输出 `generated_for.category` |

要点：

- `category_key` 与平台路径二选一即可；两者都给且不一致时，02 直接 exit 2。
- 映射键与合规类目不一定同名：`clothing → textile`、`electronics_accessories → electronics`、`home_kitchen → kitchenware`；`default` 无合规类目，调用即报错。
- 平台路径按最长前缀解析，会打 `[WARN]`；能写 `category_key` 就不要写路径。
- 查可用键：`python Agents\03_Compliance_Agent\scripts\compliance_gate.py --list-categories`。

## 3. 属性标签（13 个，逐个勾选）

属性**不会自动推断**，必须按产品实际结构逐项确认「是 / 否」。少填不会报错，只会少算义务；结果可能仍然是 `CONDITIONAL`，但上架后会缺文件。

| 属性键 | 本产品是否适用 | 说明 / 主要义务 | 漏填后果 |
|---|---|---|---|
| `lithium_battery` | 是 / 否 | 锂电池：UN38.3、SDS、UN3481 运输标签、UL 2054 / IEC 62133 | 少 4 项；UN38.3 直接不出现，样例必需项从 12 降到 8 |
| `alkaline_battery` | 是 / 否 | 碱性电池：SDS、无汞声明 | 少 2 项运输与成分文件 |
| `food_contact` | 是 / 否 | 食品接触：FDA 符合性、Prop 65、迁移测试 | 少 3 项；杯体 / 刀头 / 密封圈可能无文件 |
| `children_under_12` | 是 / 否 | 12 岁以下：CPC、ASTM F963、追踪标签、邻苯、铅、小零件 | 少 6 项；儿童产品证书与第三方测试缺失 |
| `skin_contact` | 是 / 否 | 皮肤接触：Prop 65、MoCRA、化妆品标签 | 少 3 项个护 / 化妆品合规 |
| `radio_frequency` | 是 / 否 | 无线射频：FCC Part 15B、FCC ID、RF 暴露 | 少 3 项；蓝牙 / Wi-Fi 产品无法举证 |
| `laser` | 是 / 否 | 激光：CDRH、激光标签 | 少 2 项；激光等级与标签缺失 |
| `mains_power` | 是 / 否 | 市电：UL / ETL 整机、插头电源线、DOE 能效 | 少 3 项；整机 NRTL 与适配器能效缺失 |
| `magnet` | 是 / 否 | 磁铁：16 CFR 1262、磁通指数 | 少 2 项磁铁安全要求 |
| `aerosol` | 是 / 否 | 气雾剂：DOT 气雾剂、SDS、CARB VOC | 少 3 项运输与 VOC 要求 |
| `medical_claim` | 是 / 否 | 医疗 / 功效声明：FDA 器械清关、FTC 健康声称（**两项均为阻断级**） | 缺失即 `BLOCKED`，exit 2 |
| `textile` | 是 / 否 | 纺织：16 CFR 1610、纤维标签、Prop 65 | 少 3 项阻燃与标签要求 |
| `furniture` | 是 / 否 | 家具：TB 117、16 CFR 1640、TSCA Title VI、Prop 65 | 少 4 项阻燃与甲醛要求 |

**重点提示**

- `lithium_battery`：只要出货含锂电池（含内置充电电池）就必须勾选；UN38.3 报告要覆盖实际出货电芯型号，电芯报告不能替代电池组报告。
- `food_contact`：杯体、刀头、密封圈、内胆等**每个接触部件**都要有对应材料文件，缺一个部件就是缺一份文件。
- `mains_power`：随附电源适配器或美规插头时勾选；整机报告与适配器报告不可混用，USB 供电也要评估是否触发 FCC Part 15B。
- `medical_claim`：普通商品写「治疗 / 治愈 / FDA 批准」等表述会触发阻断级义务，先改文案再送审。

填写格式（对应 03 `--attr`）：

```text
attributes: lithium_battery, food_contact, mains_power
```

## 4. 价格与成本

| 字段 | 单位 | 示例 | 必填 | 用途 / 对应 CLI |
|---|---|---|---|---|
| `factory_price_rmb` | CNY / 件（含税出厂价） | `38` | 是 | 02 `--factory-rmb` |
| `fx_cny_usd` | 1 CNY 换 USD | `0.14` | 是 | 02 `--fx`；`matrix` 也需全表统一汇率 |
| `freight_per_unit_usd` | USD / 件 | `1.60` | 是 | 02 `--freight-per-unit`（头程单件分摊） |
| `hts_code` | HTS 编码 | `8509.40` | 条件必填（与关税率至少一个） | 02 `--hts` |
| `duty_rate_pct` | % | `16.7` | 条件必填 | 02 `--duty-pct`（显式值覆盖 HTS） |
| `customs_fee_per_unit_usd` | USD / 件 | `0.18` | 可选 | 02 `--customs-fee-per-unit`；缺省按 0.18 占位并告警 |
| `weight_g` | g（发货重量） | `620` | 条件必填（与 FBA 费至少一个） | 02 `--weight-g`，自动选 FBA 档 |
| `fba_fee_usd` | USD / 件 | `5.93` | 条件必填 | 02 `--fba-fee`，优先于重量推导 |
| `price_usd` | USD | `29.99` | 是 | 02 `--price`；06 `--price` |
| `target_margin_pct` | %（净利率） | `25` | 可选 | 02 `--target-margin`，默认 25 |
| `moq` | 件 | `500` | 可选 | 02 `--moq`，默认 500；算占款 |
| `ads_pct` | %（占售价） | `10` | 可选 | 02 `--ads-pct`；06 `--ads-pct`，默认 10 |
| `returns_pct` | %（占售价） | `3` | 可选 | 02 `--returns-pct`；06 `--returns-pct`，默认 3 |

口径提醒：

- 金额统一 USD 输出、保留 2 位小数；百分比字段写百分数本身（`25` 表示 25%），不是 0.25。
- 02 的关税基于已取整 FOB；关税模型只含 MFN + Section 301，不含反倾销 / 反补贴。
- 目标价、盈亏价是基于当前售价下有效 referral 费率的近似反算；分段费率建议用 `calc` 逐价复核。

## 5. 物流与补货

| 字段 | 单位 | 示例 | 必填 | 用途 / 对应 CLI |
|---|---|---|---|---|
| `daily_sales` | 件 / 天 | `20` | 是（08） | 08 `calc --daily-sales` |
| `lead_time_days` | 天 | `45` | 是（08） | 08 `calc --lead-time-days`（必须 > 0） |
| `safety_days` | 天 | `21` | 可选 | 08 `calc --safety-days`，默认 0；建议显式填写 |
| `stock` | 件 | `300` | 可选（08） | 08 `calc --stock`，默认 0 |
| `moq` | 件 | `500` | 是（08 calc） | 08 `calc --moq`（必填，与 02 的 `--moq` 互补） |
| `inbound_interval_days` | 天 | `30` | 可选 | 08 `calc --inbound-interval-days`，默认 0 |
| `unit_cost_usd` | USD / 件 | `7.99` | 可选 | 08 `--unit-cost`，用于资金占用 |
| `units` | 件 | `1000` | 是（08 compare） | 08 `compare --units` |
| `weight_kg` | kg（整批） | `500` | 是（08 compare） | 08 `compare --weight-kg` |
| `cbm_per_unit` | m³ / 件 | `0.02` | 可选 | 08 `compare --cbm-per-unit`，LCL 计费 |
| `sea_rate_per_kg` | USD / kg | `1.2` | 条件必填 | 08 `compare --sea-rate-per-kg` |
| `sea_rate_per_cbm` | USD / m³ | `45` | 条件必填（LCL） | 08 `compare --sea-rate-per-cbm` |
| `air_rate_per_kg` | USD / kg | `5.5` | 是（08 compare） | 08 `compare --air-rate-per-kg` |
| `sea_days` / `air_days` | 天 | `35` / `7` | 是（08 compare） | 08 `compare --sea-days --air-days` |
| `carrying_rate_pct` | % | `20` | 可选 | 08 `compare --carrying-rate-pct`，默认 12，限 0–100 |
| `today` | `YYYY-MM-DD` | `2026-10-30` | 可选 | 08 `--today`，默认本地日期 |

## 6. 合规与 IP 状态

| 字段 | 取值 | 示例 | 必填 | 用途 / 对应 CLI |
|---|---|---|---|---|
| `certifications_on_hand` | 报告 / 证书名的列表，逗号或重复传参 | `UL 认证,UN38.3,Prop 65` | 可选 | 03 `--have`；匹配按 id / 名称 / 别名双向包含 |
| `trademark_status` | `none` / `pending` / `registered_us` / `conflict` | `pending` | 可选 | 03 `--trademark`；未提供按未检索处理 |
| `patent_search_done` | `true` / `false` | `false` | 可选 | 03 `--patent-search-done` |
| `target_cert_date` | `YYYY-MM-DD` | `2026-11-01` | 可选 | 倒排认证周期（人为规划，不参与计算） |
| `compliance_notes` | 文本 | `杯体为 Tritan，密封圈为硅胶` | 可选 | 材料与报告对应关系说明 |

提醒：

- `--have` 里的 `pending / 待出 / 审核中` 会被视为未具备，并写入 `input_warnings`。
- 03 只做前置初筛，不替代律师或合规服务商意见；`PASS` 也不等于平台审核通过。
- IP 状态缺失不会阻断计算，但会在 `ip_screening` 中标记 `unknown`。

## 7. 平台与费率假设

| 字段 | 取值 | 示例 | 必填 | 用途 / 对应 CLI |
|---|---|---|---|---|
| `platform` | `amazon_us` / `tiktok_us` | `amazon_us` | 可选 | 02 `--platform`，缺省 amazon_us 并提示 |
| `referral_pct` | % | `15` | 可选 | 02 `--referral`；显式值覆盖类目费率 |
| `fba_tier` | `small_standard` / `large_standard` / `small_bulky` / `large_bulky` | `large_standard` | 可选 | 02 `--tier` |
| `fba_season` | `auto` / `nonpeak` / `peak` | `auto` | 可选 | 02 `--season` |
| `ship_date` | `YYYY-MM-DD` | `2026-10-30` | 可选 | 02 `--ship-date`，判旺季与燃油附加费 |
| `no_fuel_surcharge` | `true` / `false` | `false` | 可选 | 02 `--no-fuel-surcharge` |
| `assume_default_referral` | `true` / `false` | `false` | 可选 | 02 `--assume-default-referral`；缺类目时显式按 15% 估算 |
| `rate_as_of` | `YYYY-MM-DD` | `2026-10-30` | 是 | 记录费率口径；发布前按卖家中心 / 报关行复核 |

费率口径：

- Amazon US 默认 referral 15%，每件最低 $0.30；类目分段费率见 `landed_cost.py --list-platforms`。
- TikTok Shop US 默认 6%；新卖家前 60 天 3%（上限 $500k），类目 / 活动 / 达人佣金另计。
- FBA 档位、旺季窗口与 3.5% 燃油附加费均按 2026-10-30 口径；`--list-fba-tiers` 可查档位。

## 8. 上架与素材（04 / 05 输入）

| 字段 | 单位 / 取值 | 示例 | 必填 | 用途 / 对应 CLI |
|---|---|---|---|---|
| `title` | 字符；Amazon ≤200，TikTok ≤255 | `NordPulse Portable Blender ...` | 是 | 04 `listing_lint.py` 的 `title` |
| `item_name` / `item_highlights` | 字符；Amazon 拆分模式 ≤75 / ≤125 | `NordPulse Portable Blender 16 oz` | 可选 | 04 标题拆分校验 |
| `bullets` | 字符串数组，Amazon 恰好 5 条、每条 ≤220 | 5 条卖点 | Amazon 必填 | 04 `listing_lint.py` |
| `description` / `short_description` | 字符；TikTok `short_description` ≤500 | 使用说明 | 条件必填 | 04 `listing_lint.py` |
| `backend_search_terms` | UTF-8 字节；≤250（>230 WARN） | `portable smoothie cup ...` | Amazon 必填 | 04 `listing_lint.py` |
| `listing_copy` | 文本 / `.txt` 文件 | `FDA approved, cures ...` | 二选一 | 04 `claim_scan.py --text/--file` |
| `ip_rating` | 字符串 | `none` / `ipx7` | 可选 | 04 `claim_scan.py --ip-rating` |
| `image_path` | 本地路径 | `E:\assets\main.jpg` | 条件必填 | 05 `asset_check.py <image>` |
| `video_spec` | JSON 路径 | `Agents\05_Creative_Agent\examples\video_spec.json` | 条件必填 | 05 `asset_check.py --spec` |
| `fix_output_path` | 本地路径 | `E:\assets\main_fixed.jpg` | 可选 | 05 `--fix <输出路径>`（传路径而非开关）；不接受覆盖原图 |

04 的 Listing 字段建议直接保存为 JSON（参考 `Agents\04_Listing_Agent\examples\listing_input.json`），由 `listing_lint.py --file` 读取。

## 9. 待确认与变更

| 项 | 内容 | 负责人 | 截止日 |
|---|---|---|---|
| 未确认字段 | 例：HTS 待报关行确认 | — | — |
| 费率复核 | 例：2026-10-30 口径需在发布前复核 | — | — |
| 变更记录 | 日期 / 改了什么 / 谁改的 | — | — |

## 10. 提交前自检

- [ ] `category_key` 或平台路径已填，且与后台类目一致
- [ ] 13 个属性逐个确认「是 / 否」，没有留空
- [ ] 含锂电池 / 食品接触 / 市电的产品已勾选对应属性，并确认对应报告
- [ ] 成本字段单位正确（CNY 与 USD 没有混用），汇率有日期
- [ ] HTS / 关税率至少一个；重量或 FBA 费至少一个
- [ ] 已持有报告与 `--have` 名称一致；pending 状态没有当作已具备
- [ ] `rate_as_of` 已记录，发布前复核费率
