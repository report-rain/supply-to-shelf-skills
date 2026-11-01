# supply-to-shelf

把跨境选品的「数据清洗、到岸成本、合规初筛、Listing 自检、素材规格、广告指标、评论运营、补货」拆成 8 个可复算的离线 CLI：你给数据和参数，它输出 JSON 或报告。

## 什么时候用它

- 有货源，想判断这个品值不值得做：清洗类目导出，算价格带、销量分布和机会分。
- 要报 landed cost：按工厂价、汇率、头程、HTS、FBA 和售价算出净利与盈亏价。
- 要过合规：按类目和属性列出必需文件，给出 PASS / CONDITIONAL / BLOCKED。
- 要写 Listing：检查标题、五点、后台词长度，扫描 FTC / FDA 高风险声明。
- 广告亏了或补货断了：算盈亏线 ACOS，按日销和交期算补货点与下单日。

## 接入方式

把 `<仓库路径>` 替换为你 clone 或复制后的实际目录。

**支持 skills 约定的客户端**：把整个仓库放进它的 skills 目录，由根 `SKILL.md` 自动识别。必须整仓复制：模块内用 `../../Templates`、`../../config` 这类相对路径，只复制某个模块子目录会断。

```powershell
git clone https://github.com/report-rain/supply-to-shelf-skills.git "<仓库路径>"
$src = "<仓库路径>"
$dst = "<skills目录>/supply-to-shelf-skills"
New-Item -ItemType Directory -Force -Path $dst | Out-Null
robocopy $src $dst /E /XD .git __pycache__
```

```bash
git clone https://github.com/report-rain/supply-to-shelf-skills.git "<仓库路径>"
cp -R "<仓库路径>" "<skills目录>/supply-to-shelf-skills"
```

**不支持 skills 的智能体**：把根 `SKILL.md` 和所需模块的 `SKILL.md` 作为上下文或系统提示，或直接交绝对路径并让它先读 `SKILL.md`：

```text
仓库路径：<仓库路径>
先读 <仓库路径>/SKILL.md，再按我指定的模块读 <模块>/SKILL.md 并调用脚本。
```

验证是否接入成功：问它「按 02 模块算这个品的到岸成本」，能给出数值即成功。

## 十分钟跑通

**1. 从模板开始**：复制 [Templates/product_brief_template.md](Templates/product_brief_template.md)，按产品填写类目、13 个属性、成本、物流与合规状态。

```powershell
Copy-Item "<仓库路径>/Templates/product_brief_template.md" "<你的工作目录>/product_brief_mine.md"
```

```bash
cp "<仓库路径>/Templates/product_brief_template.md" "<你的工作目录>/product_brief_mine.md"
```

你应该看到：一个 10 节的 Markdown 模板，`category_key`、成本、13 个属性都有对应栏位。

**2. 02 算成本**

```powershell
python "<仓库路径>/Agents/02_Cost_Pricing_Agent/scripts/landed_cost.py" calc --factory-rmb 38 --fx 0.14 --freight-per-unit 1.60 --hts 8509.40 --category-key small_appliances --weight-g 620 --price 29.99 --ship-date 2026-10-30 --ads-pct 10 --returns-pct 3 --target-margin 25 --moq 500 --json
```

你应该看到：`landed_cost_usd=7.99`、`net_profit_usd=7.67`、`net_margin_pct=25.58`、`break_even_price_usd=19.33`、`target_price_usd=29.62`。

**3. 03 过合规**

```powershell
python "<仓库路径>/Agents/03_Compliance_Agent/scripts/compliance_gate.py" --category small_appliances --attr lithium_battery,food_contact,mains_power --marketplace amazon_us --json
```

你应该看到：`status=CONDITIONAL`、`required=12`、`missing=12`；exit **1** 是 CONDITIONAL，不是报错。

**4. 04 写 Listing**

```powershell
python "<仓库路径>/Agents/04_Listing_Agent/scripts/listing_lint.py" --file "<仓库路径>/Agents/04_Listing_Agent/examples/listing_input.json" --platform amazon_us --json
```

你应该看到：`verdict=PASS`、`counts.PASS=30`、没有 FAIL，exit 0。

## 模块速查表

| 我要做什么 | 用哪个模块 | 一条命令 | 我拿到什么 |
|---|---|---|---|
| 清洗类目导出并算机会分 | 01 选品 | `python "<仓库路径>/Agents/01_Selection_Agent/scripts/opportunity_score.py" --file "<仓库路径>/Agents/01_Selection_Agent/examples/sample_category_export.csv" --factory-cost-usd 5.32 --target-price 29.99 --json` | 五维机会分、排名与入选理由 |
| 算到岸成本、净利、盈亏价 | 02 成本定价 | `python "<仓库路径>/Agents/02_Cost_Pricing_Agent/scripts/landed_cost.py" calc --factory-rmb 38 --fx 0.14 --freight-per-unit 1.6 --hts 8509.40 --category-key small_appliances --weight-g 620 --price 29.99 --json` | landed cost、佣金、FBA、净利、盈亏价、目标价 |
| 判断能不能上架 | 03 合规 | `python "<仓库路径>/Agents/03_Compliance_Agent/scripts/compliance_gate.py" --category small_appliances --attr lithium_battery --marketplace amazon_us --json` | 必需文件清单、缺失项、PASS / CONDITIONAL / BLOCKED |
| 检查 Listing 字段与声明 | 04 上架 | `python "<仓库路径>/Agents/04_Listing_Agent/scripts/listing_lint.py" --file "<仓库路径>/Agents/04_Listing_Agent/examples/listing_input.json" --platform amazon_us --json` | 字段级 PASS / WARN / FAIL 与长度结论 |
| 校验图片 / 视频规格 | 05 素材 | `python "<仓库路径>/Agents/05_Creative_Agent/scripts/asset_check.py" --spec "<仓库路径>/Agents/05_Creative_Agent/examples/video_spec.json" --platform tiktok_us --json` | 规格 findings 与人工复核清单 |
| 算广告盈亏线与诊断报表 | 06 广告 | `python "<仓库路径>/Agents/06_Ads_Agent/scripts/ads_metrics.py" calc --platform amazon_us --price 29.99 --product-cost 7.99 --referral 15 --fba-fee 5.93 --ads-pct 10 --returns-pct 3 --target-acos 25 --json` | 盈亏线 ACOS、ROAS、TACOS、净贡献 |
| 分析评论、退货与账号健康 | 07 运营 | `python "<仓库路径>/Agents/07_Review_Ops_Agent/scripts/review_ops.py" reviews --file "<仓库路径>/Agents/07_Review_Ops_Agent/examples/sample-reviews.csv" --json` | 情感分布、问题分类与健康分级 |
| 算补货点与海运 / 空运对比 | 08 补货 | `python "<仓库路径>/Agents/08_Fulfillment_Agent/scripts/inventory_plan.py" calc --daily-sales 20 --lead-time-days 45 --safety-days 21 --stock 300 --moq 500 --inbound-interval-days 30 --unit-cost 7.99 --today 2026-10-30 --json` | 补货点、可售天数、建议下单量与截止日 |

所有脚本加 `--json` 输出机器可读结果，去掉则给人类可读报告。

## 怎么让它开始干活

说清三件事：模块 + 数据 + 期望产出。

- 「用 02 模块算这个品的到岸成本、净利率和盈亏价，参数是：工厂价 38 元、汇率 0.14、头程 1.60、HTS 8509.40、重量 620g、售价 29.99。」
- 「用 03 模块判断这个品能不能上 Amazon US，类目 small_appliances，属性 lithium_battery、food_contact、mains_power。」
- 「用 04 模块按这个 brief 写 3 版标题和五点，并用 listing_lint 自检。」

智能体不认识这个 skill 时，先让它读 `SKILL.md`，再按模块调用。

## 限制与不做的事

- 只做美国站（amazon_us / tiktok_us），不含欧洲、日本、VAT / EPR。
- 不接平台 API，不抓评论、广告和竞品数据，输入要自己导出。
- 不生成图片或视频，05 只校验规格、补白底方图。
- 费率按 2026-10-30 口径，发布前按卖家中心、报关行和法规原文复核。
- 03 是前置初筛，不是法律意见，PASS 也不保证平台审核通过。
- 06 / 07 / 08 是计算器：业务告警默认 exit 0，只有 07 的 `--fail-on-critical` 会 exit 1。
- 13 个属性不会自动推断，必须按模板逐项填写；漏填只会少算义务，不报错。

## 许可

MIT，见 [LICENSE](LICENSE)。clean-room 重写，旧实现仅用于对拍。
