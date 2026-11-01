# supply-to-shelf

[![CI](https://github.com/report-rain/supply-to-shelf-skills/actions/workflows/ci.yml/badge.svg?branch=v2)](https://github.com/report-rain/supply-to-shelf-skills/actions/workflows/ci.yml?query=branch%3Av2)

把跨境电商「选品数据清洗 → 到岸成本 → 合规前置 → Listing 自检 → 素材规格 → 广告指标 → 评论运营 → 补货」变成一组**可复算的离线 CLI**：输入 CSV / JSON / 文本，输出 JSON 或人类可读报告，金额、税率、字符上限、评分阈值全部由脚本计算。

本仓库**不是 SaaS**，没有服务端、账号或多租户；**不是选品软件**，不会替你找品、预测爆款或抓取平台数据。它只处理你导出的数据和你提供的事实，并把结论算成可复核的数字。

## 八模块一览

数据流是单向的：`01 → 02 → 03 → 04 → 05 → 06 → 07 → 08`。脚本之间不互相调用，只共享 `shared/` 与 `config/`。

| 模块 | 对应脚本 | 主要产出 | 进入条件 | 否决 / 阻断条件 |
|---|---|---|---|---|
| 01 选品 | `Agents/01_Selection_Agent/scripts/normalize_export.py`、`market_metrics.py`、`opportunity_score.py` | 清洗后的商品 JSON、价格带与销量分布、五维机会分 | 有类目导出 CSV 或已清洗 JSON | 缺列 / 非法数值 → exit 2；同价且总销量 0 → `meta.status=WARNING`、价带置空，exit 0 |
| 02 成本定价 | `Agents/02_Cost_Pricing_Agent/scripts/landed_cost.py` | landed cost、平台佣金、FBA、净利、盈亏线、目标价、MOQ 占款；`matrix` 批量 SKU | 有出厂价、汇率、头程、HTS 或关税率、类目、重量或 FBA 费、售价 | 缺必填 / 类目不可识别 / 参数冲突 → exit 2；`matrix` 部分行失败 → 保留成功行并 exit 2 |
| 03 合规 | `Agents/03_Compliance_Agent/scripts/compliance_gate.py` | 必需文件清单、缺失项、`PASS` / `CONDITIONAL` / `BLOCKED`、IP 初筛 | 有 `category_key`（或平台路径）、属性标签、站点 | `BLOCKED` → exit 2，**不得进入 04/05**；`CONDITIONAL` → exit 1；输入 / 参数 / 配置错误 → exit 3 |
| 04 上架 | `Agents/04_Listing_Agent/scripts/listing_lint.py`、`claim_scan.py` | 字段级 PASS / WARN / FAIL、标题 / bullet / 后台词长度检查、FTC / FDA 高风险声明命中 | 03 已放行（非 BLOCKED）；02 已给出售价与成本口径；有 Listing JSON / 文案 | 任一 FAIL 或 HIGH 声明 → exit 1，不应发布 |
| 05 素材 | `Agents/05_Creative_Agent/scripts/asset_check.py` | 图片 / 视频规格 findings、人工复核清单；`--fix` 可生成白底补方图 | 04 已定稿主图与文案；有图片或视频 spec JSON | 任一 FAIL → exit 1；输入文件不可读 → exit 2 |
| 06 广告 | `Agents/06_Ads_Agent/scripts/ads_metrics.py` | 盈亏线 ACOS、ROAS、TACOS、按计划的净贡献；报表诊断 | 02 的成本口径；`calc` 只需参数，`diagnose` 另需广告报表 CSV | 业务告警（负贡献 / 高 ACOS 等）默认 exit 0，看 JSON 与 notes |
| 07 运营 | `Agents/07_Review_Ops_Agent/scripts/review_ops.py` | 评论情感与问题分类、退货原因、账号健康分级 | 有评论 / 退货 / 账号健康导出 | `CRITICAL` 默认 exit 0；仅 `--fail-on-critical` 时 exit 1 |
| 08 补货 | `Agents/08_Fulfillment_Agent/scripts/inventory_plan.py` | 补货点、可售天数、建议下单量与截止日、海运 vs 空运对比 | 有日销、交期、库存、MOQ；对比需重量 / 体积 / 费率 | 非法参数 → exit 2；错过下单日只是提示，不改退出码 |

两条顺序约束最容易踩：

- **03 先于 04 / 05**：`BLOCKED` 表示必需文件缺失，继续写 Listing 或做图是无效工作。
- **02 先于 04**：Listing 的定价、促销与盈亏表述必须建立在同一套 landed cost 与目标价上。

## 快速开始

要求 Python **3.10+**（CI 覆盖 3.10 / 3.12），运行期只用标准库。以下命令都在**仓库根目录**执行；PowerShell 5 不支持 `&&`，多命令用 `;`。

```powershell
python --version
pip install "Pillow>=9.0"   # 可选，仅 05 的像素检查与 --fix 需要
```

### 02 定价（端到端主基准）

```powershell
python Agents\02_Cost_Pricing_Agent\scripts\landed_cost.py calc --factory-rmb 38 --fx 0.14 --freight-per-unit 1.60 --hts 8509.40 --category-key small_appliances --weight-g 620 --price 29.99 --ship-date 2026-10-30 --ads-pct 10 --returns-pct 3 --target-margin 25 --moq 500 --json
```

期望：exit 0；`landed_cost_usd=7.99`、`net_profit_usd=7.67`、`net_margin_pct=25.58`、`break_even_price_usd=19.33`、`target_price_usd=29.62`、`cash_required_usd=3995.0`。

批量 SKU（示例文件 5 行）：

```powershell
python Agents\02_Cost_Pricing_Agent\scripts\landed_cost.py matrix --file Agents\02_Cost_Pricing_Agent\examples\sample-skus.csv --fx 0.14 --json
```

### 03 合规门禁

```powershell
python Agents\03_Compliance_Agent\scripts\compliance_gate.py --category small_appliances --attr lithium_battery,food_contact,mains_power --marketplace amazon_us --json
```

期望：exit **1**（`CONDITIONAL`，不是报错）；`counts.required=12`、`missing=12`、`blocking_missing=0`。

换成阻断级声明可看到 `BLOCKED` / exit 2：

```powershell
python Agents\03_Compliance_Agent\scripts\compliance_gate.py --category small_appliances --attr medical_claim --marketplace amazon_us --json
```

### 其余模块（均已实跑）

```powershell
# 01：清洗 → 指标 → 机会分
python Agents\01_Selection_Agent\scripts\normalize_export.py Agents\01_Selection_Agent\examples\sample_category_export.csv --output $env:TEMP\normalized.json --json
python Agents\01_Selection_Agent\scripts\market_metrics.py $env:TEMP\normalized.json --json
python Agents\01_Selection_Agent\scripts\opportunity_score.py --file Agents\01_Selection_Agent\examples\sample_category_export.csv --factory-cost-usd 5.32 --target-price 29.99 --json

# 04：字段自检 + 声明扫描
python Agents\04_Listing_Agent\scripts\listing_lint.py --file Agents\04_Listing_Agent\examples\listing_input.json --platform amazon_us --json
python Agents\04_Listing_Agent\scripts\claim_scan.py --file Agents\04_Listing_Agent\examples\copy.txt --json

# 05：视频规格（图片模式传图片路径即可）
python Agents\05_Creative_Agent\scripts\asset_check.py --spec Agents\05_Creative_Agent\examples\video_spec.json --platform tiktok_us --json

# 06：广告盈亏线 + 报表诊断
python Agents\06_Ads_Agent\scripts\ads_metrics.py calc --platform amazon_us --price 29.99 --product-cost 7.99 --referral 15 --fba-fee 5.93 --ads-pct 10 --returns-pct 3 --target-acos 25 --json
python Agents\06_Ads_Agent\scripts\ads_metrics.py diagnose --file Agents\06_Ads_Agent\examples\sample-campaign.csv --platform amazon_us --price 29.99 --product-cost 7.99 --referral 15 --fba-fee 5.93 --target-acos 25 --json

# 07：评论 / 退货 / 账号健康
python Agents\07_Review_Ops_Agent\scripts\review_ops.py reviews --file Agents\07_Review_Ops_Agent\examples\sample-reviews.csv --json
python Agents\07_Review_Ops_Agent\scripts\review_ops.py returns --file Agents\07_Review_Ops_Agent\examples\sample-returns.csv --json
python Agents\07_Review_Ops_Agent\scripts\review_ops.py health --file Agents\07_Review_Ops_Agent\examples\sample-health.json --json

# 08：补货计算 + 海运/空运对比
python Agents\08_Fulfillment_Agent\scripts\inventory_plan.py calc --daily-sales 20 --lead-time-days 45 --safety-days 21 --stock 300 --moq 500 --inbound-interval-days 30 --unit-cost 7.99 --today 2026-10-30 --json
python Agents\08_Fulfillment_Agent\scripts\inventory_plan.py compare --units 1000 --weight-kg 500 --cbm-per-unit 0.02 --sea-rate-per-kg 1.2 --air-rate-per-kg 5.5 --sea-days 35 --air-days 7 --unit-cost 7.99 --carrying-rate-pct 20 --json
```

所有脚本都支持 `--json`；错误时 JSON 走 stdout，人类提示走 stderr（`claim_scan.py` 的错误信息也走 stdout，见 04 分册），退出码见上表与各分册。

## 输入契约

### 通用约定

- 编码统一按 `utf-8-sig` 读取（容忍 BOM），不做 GBK 静默回退；解码失败明确报错。
- 空值 `""`、`-`、`—`、`N/A`、`nan` 视为缺失，**不按 0 参与计算**。
- 金额单位为 USD，输出保留 2 位小数；百分比字段带 `_pct`，数值是百分数本身（`25.58` 表示 25.58%）。
- 日期一律 `YYYY-MM-DD`；02 的旺季 / 燃油与 08 的默认 today 以本地日期或显式 `--ship-date` / `--today` 为准。

### `product_brief` 关键字段

本仓库**不附带也不解析** `product_brief` 文件；它指你维护的上游事实清单（Markdown、JSON 或表格均可）。脚本只消费命令行参数。建议至少准备以下字段，再按表映射：

| brief 字段 | 含义 | 对应 CLI |
|---|---|---|
| `product_name` | 产品名 / 型号 | 04 的 `title`、`item_name` |
| `category_key` | 唯一类目键（推荐） | 02 `--category-key`；03 `--category` |
| `platform_category_path` | 后台类目路径，如 `Home & Kitchen > Small Appliances` | 02 `--category`；03 `--category` |
| `marketplace` | `amazon_us` / `tiktok_us` | 03 `--marketplace`；04/05 `--platform` |
| `factory_price_rmb` | 含税出厂价（元/件） | 02 `--factory-rmb` |
| `fx_cny_usd` | 1 CNY 换多少 USD | 02 `--fx` |
| `freight_per_unit_usd` | 头程单件分摊 | 02 `--freight-per-unit` |
| `hts_code` / `duty_rate_pct` | HTS 编码或显式关税率，至少一个 | 02 `--hts` / `--duty-pct` |
| `weight_g` / `fba_fee_usd` | 发货重量或已知 FBA 费，至少一个 | 02 `--weight-g` / `--fba-fee` |
| `price_usd` | 当前或目标零售价 | 02 `--price`；06 `--price` |
| `ads_pct` / `returns_pct` | 广告、退货占售价比例 | 02 / 06 同名参数 |
| `target_margin_pct` / `moq` | 目标净利率、起订量 | 02 `--target-margin` / `--moq` |
| `ship_date` | 计划发货 / 上架日 | 02 `--ship-date` |
| `attributes[]` | 13 个属性标签 | 03 `--attr` |
| `certifications_on_hand[]` | 已持有报告 / 证书名 | 03 `--have` |
| `trademark_status` / `patent_search_done` | IP 状态与是否检索 | 03 `--trademark` / `--patent-search-done` |

### 13 个属性标签

属性**不会被自动推断**：脚本不会从标题、类目或图片猜测，必须显式传入。少填一项不会报错，只会少算义务。

| 属性键 | 中文 | 主要新增文件（数量） | 漏填后果 |
|---|---|---|---|
| `lithium_battery` | 锂电池 | UN38.3、SDS、运输标签、UL 2054 / IEC 62133（4） | 小家电样例的必需项会从 12 掉到 8，UN38.3 直接消失，结果**仍可能是 CONDITIONAL** |
| `alkaline_battery` | 碱性电池 | 碱性电池 SDS、无汞声明（2） | 漏掉电池运输与成分文件 |
| `food_contact` | 食品接触 | FDA 食品接触符合性、Prop 65、迁移测试（3） | 漏掉杯体 / 刀头 / 密封圈的材料合规 |
| `children_under_12` | 12 岁以下儿童产品 | CPC、ASTM F963、追踪标签、邻苯、铅、小零件（6） | 漏掉第三方测试与儿童产品证书 |
| `skin_contact` | 皮肤接触 | Prop 65、MoCRA、化妆品标签（3） | 漏掉化妆品 / 个护类合规 |
| `radio_frequency` | 无线射频 | FCC Part 15B、FCC ID、RF 暴露（3） | 漏掉射频与 FCC ID |
| `laser` | 激光 | CDRH、激光标签（2） | 漏掉激光产品报告与标签 |
| `mains_power` | 市电供电 | UL / ETL、插头与电源线、DOE 能效（3） | 漏掉整机 NRTL 与适配器能效 |
| `magnet` | 磁铁 | 16 CFR 1262、磁通指数（2） | 漏掉磁铁安全标准 |
| `aerosol` | 气雾剂 | DOT 气雾剂、SDS、CARB VOC（3） | 漏掉运输与挥发性有机物要求 |
| `medical_claim` | 医疗 / 功效声明 | FDA 器械清关、FTC 健康声称（2，均为阻断级） | 缺失即 `BLOCKED` |
| `textile` | 纺织 | 16 CFR 1610、纤维标签、Prop 65（3） | 漏掉阻燃与纤维标签 |
| `furniture` | 家具 | TB 117、16 CFR 1640、TSCA Title VI、Prop 65（4） | 漏掉阻燃与甲醛要求 |

### `category_key` 与平台路径

`config/category_map.json` 是 02 / 03 共用的唯一类目口径：18 个映射项（含 `default`），对应 16 个合规类目，并记录平台路径前缀与 5 个旧键别名（`small_appliance→small_appliances`、`kitchenware→home_kitchen`、`textile→clothing`、`apparel→clothing`、`home-and-kitchen→home_kitchen`）。

解析顺序（不猜测）：

1. 精确 `category_key`；
2. 旧键别名；
3. 平台路径**最长前缀**（大小写不敏感，`>` / `|` 归一为 ` > `）；
4. 规则库类目直通（当前配置下不可达）；
5. 仍失败 → 02 exit 2、03 exit 3。

注意映射键与合规类目不一定同名：`clothing` 的合规类目是 `textile`，`electronics_accessories` 指向 `electronics`，`home_kitchen` 指向 `kitchenware`，`default` 没有合规类目（调用即报错）。平台路径可以传，但会打 `[WARN]` 并建议直接写 `category_key`。

```powershell
python Agents\02_Cost_Pricing_Agent\scripts\landed_cost.py --list-platforms
python Agents\02_Cost_Pricing_Agent\scripts\landed_cost.py --list-fba-tiers
python Agents\03_Compliance_Agent\scripts\compliance_gate.py --list-categories
python Agents\03_Compliance_Agent\scripts\compliance_gate.py --list-attributes
```

## 安装为 Trae skill

一个 Trae skill 是「一个目录 + 根目录 `SKILL.md`」。本仓库 `SKILL.md` 在根目录，8 个 Agent 共用 `shared/`、`config/` 与根路径推导。

**必须整仓复制，不能只拷 `Agents/` 或某个 Agent 子目录**：脚本启动时会从自身位置回溯到仓库根加载 `shared/` 与 `config/category_map.json`；只复制子目录会直接 `ImportError` 或类目解析失败。`docs/spec/` 与 `tests/` 不是运行必需，但建议保留，便于查契约与自测。

```text
supply-to-shelf-skills/
├── SKILL.md                 # Trae skill 入口（name / description / 路由）
├── README.md
├── CHANGELOG.md
├── LICENSE
├── requirements.txt
├── .github/workflows/ci.yml
├── config/category_map.json # 02 / 03 共用类目映射
├── shared/                  # 共用层：errors / args / numbers / config / category
├── Agents/
│   ├── 01_Selection_Agent/{scripts,examples}
│   ├── 02_Cost_Pricing_Agent/{scripts,examples}   # scripts 内含 hts_tariff.json / us_fees.json
│   ├── 03_Compliance_Agent/scripts                # 含 compliance_rules.json
│   ├── 04_Listing_Agent/{scripts,examples}
│   ├── 05_Creative_Agent/{scripts,examples}
│   ├── 06_Ads_Agent/{scripts,examples}
│   ├── 07_Review_Ops_Agent/{scripts,examples}
│   └── 08_Fulfillment_Agent/scripts
├── docs/{PROGRESS.md,spec/}
└── tests/                   # unittest + 对拍 harness
```

安装（Windows，用户级 skills 目录）：

```powershell
$src = "E:\SKILLS\supply-to-shelf-core"
$dst = Join-Path $env:USERPROFILE ".trae-cn\skills\supply-to-shelf-skills"
New-Item -ItemType Directory -Force -Path $dst | Out-Null
robocopy $src $dst /E /XD .git __pycache__
```

复制后重载 / 重启 Trae，让 skills 索引刷新。验证方式：

1. 确认 `$dst\SKILL.md` 存在，且 frontmatter 的 `name` 为 `supply-to-shelf`；
2. 在对话里说「用 02 算到岸成本：出厂价 38 元、汇率 0.14、头程 1.6 美元、HTS 8509.40、小家电、620 克、售价 29.99」，应路由到 `landed_cost.py`；
3. 或直接跑 `python "$dst\Agents\02_Cost_Pricing_Agent\scripts\landed_cost.py" calc ... --json`，确认输出与上文主基准一致。

调用脚本时用**绝对路径**，不要 `cd` 进 Agent 子目录再跑。

## 确定性与边界

- **脚本算数，模型解释**。金额、税率、佣金、ACOS、补货点、字符上限（Amazon 标题 200 / TikTok 255、后台词 250 UTF-8 字节、Amazon 单条 bullet 220）与像素阈值都由脚本计算；调用方只负责提供事实与解释结果。
- **不接平台 API**。不抓评论、广告报表、竞品数据，也不代办认证、备案或商标申请；输入必须自己导出。
- **不渲染图片**。05 只校验与生成白底补方修正图，不做产品图生成、合成或美化。
- **只做美国站**。平台仅 `amazon_us` / `tiktok_us`；不做欧洲、日本站，也不含 VAT / EPR / 欧代等规则。
- **费率是时点口径**。HTS、Section 301、平台佣金、FBA 档位、燃油附加费与合规规则均按 **2026-10-30** 的公开口径整理，发布前必须按卖家中心 / 报关行 / 法规原文复核。
- **不是法律意见**。03 是前置初筛，不替代合规服务商或律师；`PASS` 也不代表平台审核一定通过。
- **业务告警默认不失败**。06 / 07 / 08 是计算器而非门禁；只有 07 提供可选 `--fail-on-critical`。
- **严格 UTF-8**。不做 GBK 自动回退；遇到非 UTF-8 输入会明确失败，避免把脏数据算进结果。

## 质量现状

- unittest：**157 条全部通过**（`Ran 157 tests ... OK`）。
- 八模块对拍：**SAME 121 / INTENDED_DIFF 24 / REGRESSION 0**。每个差异都能归到 `docs/spec/99_gap_and_decisions.md` 的编号（#1–#14）。
- CI：GitHub Actions 六矩阵（ubuntu / windows / macos × Python 3.10 / 3.12）全绿，见上方徽章。

```powershell
python -m unittest discover -s tests -p "test_*.py"
python tests\compare_oracle.py --old-repo ..\supply-to-shelf-skills
python tests\compare_oracle.py --old-repo ..\supply-to-shelf-skills --agent 02
```

对拍 harness 只把旧实现当黑盒 oracle：跑命令、比较退出码与 stdout / stderr / JSON，不导入旧代码。`SAME` 为一致；`INTENDED_DIFF` 为登记过的有意差异；`REGRESSION` 必须为 0。02 / 03 目前由对拍覆盖，没有单列 unittest 文件。

## 已知限制

- **07 情感是关键词词典**：子串匹配、无否定词与词边界处理，`clean design` 可能被归入「清洁异味」；误判率未量化。
- **02 关税只含 MFN + Section 301**：不含反倾销 / 反补贴、州税、进口商杂项；未给报关杂费时按 `$0.18/件` 占位并输出 `[WARN]`。
- **05 主体判定需人工复核**：主体占比按像素 bbox 估算，构图、卖点与「主体是否该出现」仍需人看；`--fix` 只拉白与补方，不改变主体大小。
- **部分边界缺真实样本**：02 类目路径并列歧义、04 `BRAND_TOO_LATE` 80/81 位次、03 `rules_direct` 分支、06 `status=ERROR` 路径等未构造实测样本，结论按「保持旧样」记录在 99。
- **已知缺陷**：01 `market_metrics.py --help` 会因帮助文案中的 `%` 触发 argparse 格式化错误；直接执行计算不受影响，本轮文档整理未改代码。

## 项目来源与许可

本仓库是 **clean-room 重写**：源码从零编写，行为对齐早期实现（旧实现仅作为对拍基线，不作为代码来源，也不复制其文档原文）。可观测行为（退出码、stdout / stderr、JSON 语义、文本）由 `tests/compare_oracle.py` 对旧实现做黑盒对拍，未登记的差异视为回归。

MIT，见 [LICENSE](LICENSE)。`Copyright (c) 2026 report-rain contributors`。
