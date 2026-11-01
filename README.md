# supply-to-shelf（v2）

跨境电商「选品 → 定价 → 合规 → 上架 → 素材 → 广告 → 运营 → 补货」全链路黑盒工具集：8 个独立 CLI，输入 CSV/JSON/文本，输出 JSON 或人类可读报告。

本仓库是 **clean-room 重写**：代码从零编写，行为对齐早期项目（下称「旧侧」），不复用旧仓库源码。所有可观测输出（退出码、stdout/stderr、JSON 语义、文本）都以 `tests/compare_oracle.py` 对旧侧做黑盒对拍；差异只有在 `docs/spec/99_gap_and_decisions.md` 里登记过才算「有意差异」。

## 能力一览

| 模块 | 脚本 | 作用 |
|---|---|---|
| 01 选品 | `Agents/01_Selection_Agent/scripts/normalize_export.py`、`market_metrics.py`、`opportunity_score.py` | 类目导出清洗、价格带/销量分布、机会分 |
| 02 成本定价 | `Agents/02_Cost_Pricing_Agent/scripts/landed_cost.py` | 到岸成本、平台佣金、盈亏线、目标价、占款；支持 CSV 批量矩阵 |
| 03 合规 | `Agents/03_Compliance_Agent/scripts/compliance_gate.py` | 类目/属性/站点前置合规与 IP 初筛 |
| 04 上架 | `Agents/04_Listing_Agent/scripts/listing_lint.py`、`claim_scan.py` | Listing 字段自检、FTC/FDA 高风险声明扫描 |
| 05 素材 | `Agents/05_Creative_Agent/scripts/asset_check.py` | 图片/视频规格校验，`--fix` 生成修正图 |
| 06 广告 | `Agents/06_Ads_Agent/scripts/ads_metrics.py` | 广告盈亏线、ACOS/ROAS/TACOS、报表诊断 |
| 07 运营 | `Agents/07_Review_Ops_Agent/scripts/review_ops.py` | 评论、退货、账号健康分析 |
| 08 补货 | `Agents/08_Fulfillment_Agent/scripts/inventory_plan.py` | 补货点/断货日/建议下单量、海运 vs 空运 |

详细契约见 [`docs/spec/`](docs/spec)：`00_overview.md` 是总纲，01–08 各自成册，`99_gap_and_decisions.md` 记录有意差异与缺口结论。

## 环境

- Python **3.10+**（CI 覆盖 3.10 / 3.12），仅用标准库。
- 可选：`Pillow>=9.0`，仅 05 的像素级检查与 `--fix` 需要；未安装时输出 `[WARN] PILLOW_MISSING` 并降级为文件级检查，不会崩溃。
- Windows / macOS / Linux 均可；PowerShell 5 不支持 `&&`，下文命令均用 `;` 连接。

```powershell
python --version
pip install "Pillow>=9.0"   # 可选
```

## 快速开始（PowerShell 可直接复制）

在仓库根目录执行。

**02 定价（端到端主基准）**

```powershell
python Agents\02_Cost_Pricing_Agent\scripts\landed_cost.py calc --factory-rmb 38 --fx 0.14 --freight-per-unit 1.60 --hts 8509.40 --category-key small_appliances --weight-g 620 --price 29.99 --ship-date 2026-10-30 --ads-pct 10 --returns-pct 3 --target-margin 25 --moq 500 --json
```

期望：到岸 `7.99`、净利 `7.67`、净利率 `25.58`、盈亏价 `19.33`、目标价 `29.62`、占款 `3995.0`。

**01 清洗**

```powershell
python Agents\01_Selection_Agent\scripts\normalize_export.py Agents\01_Selection_Agent\examples\sample_category_export.csv --json
```

**03 合规**

```powershell
python Agents\03_Compliance_Agent\scripts\compliance_gate.py --category small_appliances --attr lithium_battery,food_contact,mains_power --marketplace amazon_us --json
```

**04 上架自检 + 声明扫描**

```powershell
python Agents\04_Listing_Agent\scripts\listing_lint.py --file Agents\04_Listing_Agent\examples\listing_input.json --platform amazon_us --json
python Agents\04_Listing_Agent\scripts\claim_scan.py --file Agents\04_Listing_Agent\examples\copy.txt --json
```

**05 素材**

```powershell
python Agents\05_Creative_Agent\scripts\asset_check.py <图片路径> --platform amazon_us --json
python Agents\05_Creative_Agent\scripts\asset_check.py --spec Agents\05_Creative_Agent\examples\video_spec.json --platform tiktok_us --json
```

**06 广告**

```powershell
python Agents\06_Ads_Agent\scripts\ads_metrics.py calc --platform amazon_us --price 29.99 --product-cost 7.99 --referral 15 --fba-fee 5.93 --ads-pct 10 --returns-pct 3 --target-acos 25 --json
```

**07 运营**

```powershell
python Agents\07_Review_Ops_Agent\scripts\review_ops.py health --file Agents\07_Review_Ops_Agent\examples\sample-health.json --json
```

**08 补货**

```powershell
python Agents\08_Fulfillment_Agent\scripts\inventory_plan.py calc --daily-sales 20 --lead-time-days 45 --safety-days 21 --stock 300 --moq 500 --inbound-interval-days 30 --unit-cost 7.99 --today 2026-10-30 --json
```

所有脚本都支持 `--json`；错误时 `--json` 输出统一错误对象（`status` / `missing` / `message`），人类信息走 stderr，退出码见各分册 §4。

## 装成 Trae skill

一个 Trae skill 是「一个目录 + 根目录 `SKILL.md`」。本仓库的 8 个 Agent 共用 `shared/` 与 `config/`，**必须整仓复制，不能只拷 `Agents/` 子目录**，否则 import 与配置相对路径会断。

完整目录结构（安装后保持原样）：

```text
supply-to-shelf-skills/
├── SKILL.md                      # Trae skill 入口（元数据 + 路由说明）
├── README.md
├── CHANGELOG.md
├── LICENSE
├── requirements.txt
├── config/
│   └── category_map.json         # 02/03 共用的类目别名与路径
├── shared/                       # 01–08 共用：errors / args / numbers / config / category
│   ├── __init__.py
│   ├── args.py
│   ├── category.py
│   ├── config.py
│   ├── errors.py
│   └── numbers.py
├── Agents/
│   ├── 01_Selection_Agent/{examples,scripts}
│   ├── 02_Cost_Pricing_Agent/{examples,scripts}   # hts_tariff.json / us_fees.json 在 scripts 下
│   ├── 03_Compliance_Agent/scripts
│   ├── 04_Listing_Agent/{examples,scripts}
│   ├── 05_Creative_Agent/{examples,scripts}
│   ├── 06_Ads_Agent/{examples,scripts}
│   ├── 07_Review_Ops_Agent/{examples,scripts}
│   └── 08_Fulfillment_Agent/scripts
├── docs/
│   ├── PROGRESS.md
│   └── spec/00–08、99
└── tests/                        # 单测 + 对拍 harness（不装 skill 也可保留）
```

安装（整仓复制到用户级 skills 目录）：

```powershell
$src = "E:\SKILLS\supply-to-shelf-core"
$dst = Join-Path $env:USERPROFILE ".trae-cn\skills\supply-to-shelf-skills"
New-Item -ItemType Directory -Force -Path $dst | Out-Null
robocopy $src $dst /E /XD .git __pycache__
```

复制完成后在 Trae 里重载/重启，使 skills 索引刷新。`SKILL.md` 的 `description` 决定何时自动触发；脚本调用一律使用**绝对路径**，不要 `cd` 到子目录再跑，以免 `shared/` 与 `config/` 解析失败。

## 测试与对拍

```powershell
# 单测（157 条）
python -m unittest discover -s tests -p "test_*.py"

# 八模块全量对拍（需要旧侧仓库作黑盒 oracle，仅读不写）
python tests\compare_oracle.py --old-repo ..\supply-to-shelf-skills

# 单模块
python tests\compare_oracle.py --old-repo ..\supply-to-shelf-skills --agent 02
```

判定口径：

- `SAME`：退出码 + JSON 语义 / 文本逐行一致（绝对路径、`generated_at` 已归一）。
- `INTENDED_DIFF`：差异能对应 `99_gap_and_decisions.md` 的编号（#1–#14）。
- `REGRESSION`：未登记的差异，harness 以退出码 1 失败，必须修到 0。

当前基线：**SAME 121 / INTENDED_DIFF 24 / REGRESSION 0**（八模块合计）。分模块：01 `6/6/0`、02 `7/6/0`、03 `12/0/0`、04 `16/3/0`、05 `15/7/0`、06 `22/0/0`、07 `17/1/0`、08 `26/1/0`。

对拍 harness 只跑旧侧命令、比较 stdout/stderr/退出码/落盘产物，不导入旧代码。

## 能力边界

- **不是法律意见**：03 只做前置初筛，最终合规与 IP 结论由合规服务商/律师复核。
- **费率为时点口径**：HTS、Section 301、平台佣金、FBA 档位、燃油附加费均需发布前按卖家中心/报关行复核；配置里的未核校 HTS 会显式告警但仍参与计算。
- **不做联网抓取**：全部脚本离线运行，不调用平台 API，不抓评论/广告报表；输入需自行导出。
- **图片能力依赖 Pillow**：未安装时只做文件级检查；`--fix` 需要 Pillow。
- **业务告警默认退出 0**：06/07/08 是计算器而非门禁；仅 07 提供可选 `--fail-on-critical`。
- **严格 UTF-8**：输入按 `utf-8-sig` 读取，不做 GBK 静默回退；解码失败明确报错 exit 2。

## 许可

MIT，见 [LICENSE](LICENSE)。`Copyright (c) 2026 report-rain contributors`。
