---
name: supply-to-shelf
description: 跨境电商供应链与上架全链路离线工具集（选品、到岸成本/定价、合规初筛、Listing 自检、素材规格、广告指标、评论/退货运营、补货与海空运对比）。当用户需要算到岸成本/盈亏线、做合规预判、检查 Listing 文案、扫描高风险声明、核对图片视频规格、诊断广告 ACOS/TACOS、分析评论退货、算补货点或海运/空运取舍时使用。纯本地 CLI，不联网、不调用平台 API。
---

# supply-to-shelf（选品到上架）

8 个独立 CLI，统一输入 CSV/JSON/文本，输出 JSON 或人类可读报告。全部离线，仅用 Python 标准库（05 的像素级检查可选依赖 Pillow）。

## 使用方式

在仓库根目录用**绝对路径**调用脚本，不要 `cd` 进子目录（脚本依赖仓库根的 `shared/` 与 `config/`，启动时会自行 bootstrap 路径）。

```powershell
python <仓库根>\Agents\<模块>\scripts\<脚本>.py <参数> --json
```

所有脚本支持 `--json`。错误时输出统一错误对象（`status` / `missing` / `message`），人类信息走 stderr。

## 路由

| 用户意图 | 脚本 | 典型参数 |
|---|---|---|
| 类目导出清洗、价格带、机会分 | `Agents/01_Selection_Agent/scripts/{normalize_export,market_metrics,opportunity_score}.py` | `normalize_export.py <csv> --json` |
| 到岸成本、佣金、盈亏线、目标价、占款、SKU 矩阵 | `Agents/02_Cost_Pricing_Agent/scripts/landed_cost.py` | `calc` / `matrix`；`--factory-rmb --fx --freight-per-unit --hts/--duty-pct --price` |
| 合规前置判断与 IP 初筛 | `Agents/03_Compliance_Agent/scripts/compliance_gate.py` | `--category --attr --marketplace --have --trademark` |
| Listing 字段自检 | `Agents/04_Listing_Agent/scripts/listing_lint.py` | `--file listing.json --platform amazon_us/tiktok_us` |
| 高风险声明扫描（FTC/FDA） | `Agents/04_Listing_Agent/scripts/claim_scan.py` | `--file <txt>` 或 `--text "..."` |
| 图片/视频规格校验、修正图 | `Agents/05_Creative_Agent/scripts/asset_check.py` | `<image>` 或 `--spec video.json`；`--platform`；`--fix` |
| 广告盈亏线、ACOS/ROAS/TACOS、报表诊断 | `Agents/06_Ads_Agent/scripts/ads_metrics.py` | `calc` / `diagnose --file campaign.csv` |
| 评论、退货、账号健康 | `Agents/07_Review_Ops_Agent/scripts/review_ops.py` | `reviews` / `returns` / `health` |
| 补货点、断货日、下单量、海运 vs 空运 | `Agents/08_Fulfillment_Agent/scripts/inventory_plan.py` | `calc` / `compare` |

## 契约与示例

- 总纲：`docs/spec/00_overview.md`
- 分册：`docs/spec/01_selection.md` … `08_fulfillment.md`（每个脚本的参数、JSON 字段、退出码、示例均在分册 §2–§7）
- 有意差异与缺口结论：`docs/spec/99_gap_and_decisions.md`
- 快速命令：`README.md`「快速开始」

## 主基准（可自查）

```powershell
python Agents\02_Cost_Pricing_Agent\scripts\landed_cost.py calc --factory-rmb 38 --fx 0.14 --freight-per-unit 1.60 --hts 8509.40 --category-key small_appliances --weight-g 620 --price 29.99 --ship-date 2026-10-30 --ads-pct 10 --returns-pct 3 --target-margin 25 --moq 500 --json
```

期望：到岸 `7.99`、净利 `7.67`、净利率 `25.58`、盈亏价 `19.33`、目标价 `29.62`、占款 `3995.0`。

## 边界

- 03 是合规初筛，不是法律意见；税率/平台费率均为时点口径，发布前复核。
- 06/07/08 业务告警默认退出 0（仅 07 有可选 `--fail-on-critical`）。
- 严格 `utf-8-sig` 读取，不做 GBK 回退；解码失败 exit 2。
- 05 未安装 Pillow 时降级为文件级检查，输出 `[WARN] PILLOW_MISSING`。
