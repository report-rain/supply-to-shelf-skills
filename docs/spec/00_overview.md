# 00 · 规格总览（第一阶段）

> 本目录只描述「行为」，不含实现。读者仅凭本目录即可独立实现行为等价的 8 个模块 / 11 个脚本。
> 状态：规格冻结（2026-10-30）。所有数值均来自实跑或规则库常量；无法从代码确认的条目在各分册 §8 标为「未确认」。

## 1. 模块与脚本地图

| 模块 | 目录 | 脚本 | 分册 |
|---|---|---|---|
| 01 选品 | `Agents/01_Selection_Agent` | `market_metrics.py`、`normalize_export.py`、`opportunity_score.py` | `01_selection.md` |
| 02 成本定价 | `Agents/02_Cost_Pricing_Agent` | `landed_cost.py` | `02_cost_pricing.md` |
| 03 合规 | `Agents/03_Compliance_Agent` | `compliance_gate.py`（规则库 `compliance_rules.json`） | `03_compliance.md` |
| 04 Listing | `Agents/04_Listing_Agent` | `claim_scan.py`、`listing_lint.py` | `04_listing.md` |
| 05 素材 | `Agents/05_Creative_Agent` | `asset_check.py` | `05_creative.md` |
| 06 广告 | `Agents/06_Ads_Agent` | `ads_metrics.py` | `06_ads.md` |
| 07 评论运营 | `Agents/07_Review_Ops_Agent` | `review_ops.py` | `07_review_ops.md` |
| 08 履约 | `Agents/08_Fulfillment_Agent` | `inventory_plan.py` | `08_fulfillment.md` |

数据流（单向）：`01 → 02 → 03 → 04 → 05 → 06 → 07 → 08`。脚本之间不互相调用，只共享配置文件：
- 费率唯一事实来源：`Agents/02_Cost_Pricing_Agent/scripts/us_fees.json`（06 只读引用）。
- 类目唯一事实来源：仓库根 `config/category_map.json`（02/03 共用）。
- 关税示例表：`Agents/02_Cost_Pricing_Agent/scripts/hts_tariff.json`（未核校项必须显式覆盖）。
- 合规规则库：`Agents/03_Compliance_Agent/scripts/compliance_rules.json`。

## 2. 跨模块共享契约

### 2.1 错误契约（所有已接入脚本）
- `--json` 时，stdout 必须是且仅是一个合法 JSON 对象：
  `{"status": "INPUT_MISSING"|"ERROR", "missing": [字段名...], "message": "..."}`
- 人类可读信息写 stderr（带 `[INPUT_MISSING]` 前缀），不得混入 stdout。
- 成功路径的字段名、输出格式、退出码不因错误契约改造而变化；只允许新增字段。
- 02/06/07/08：输入错误 = 2。03：输入/参数/配置错误 = 3（不得与 BLOCKED=2 混淆）。
- argparse 参数错误同样遵循上述契约（`--json` 从 argv 检测）。
- 特例（现状、未统一）：01 全部脚本、04 `claim_scan.py` 的部分错误路径、05 的退出码仍各自为政，详见分册 §6。

### 2.2 退出码语义总表

| 脚本 | 0 | 1 | 2 | 3 |
|---|---|---|---|---|
| 01 market_metrics | 成功 | — | 输入错误（`fail` 固定 2） | — |
| 01 normalize_export | 成功 | — | 输入错误（`fail` 固定 2） | — |
| 01 opportunity_score | 成功 | — | 输入 / 参数校验错误（`fail` 固定 2） | — |
| 02 landed_cost | 成功 | 非法日期 + 显式 season 的未捕获 `ValueError` | 输入错误（含 matrix 部分行失败） | 配置缺 `fba.tiers` |
| 03 compliance_gate | PASS | CONDITIONAL | BLOCKED | 输入/参数/配置错误 |
| 04 claim_scan | 无 HIGH | 有 HIGH | 输入/参数错误 | — |
| 04 listing_lint | 无 FAIL | 有 FAIL | 输入错误 | — |
| 05 asset_check | 通过/仅 WARN | 有 FAIL（含缺图） | 参数/spec 错误或输入文件缺失 | — |
| 06 ads_metrics | 成功（含业务告警） | — | 输入错误 | — |
| 07 review_ops | 成功（含业务告警） | `CRITICAL` 且 `--fail-on-critical` | 输入错误 | — |
| 08 inventory_plan | 成功 | — | 输入/参数错误 | — |

> 以实际行为为准（本表按 2026-11-01 代码核实）。

### 2.3 数值与文本约定
- 金额：USD，输出保留 2 位小数；中间量先算后 `round(x, 2)`，不使用银行家舍入（Python `round` 行为，遇 .5 依赖二进制表示）。
- 百分比：字段名带 `_pct`，数值为百分数本身（如 25.58 表示 25.58%），不是小数。
- 编码：输入一律按 `utf-8-sig` 读取（容忍 BOM）；CSV 用 `csv.DictReader`，列名去空格后再匹配别名，匹配不区分大小写。
- 空值识别：`""`、`-`、`—`、`N/A`、`nan` 视为缺失；缺失不得按 0 参与计算。
- 时间口径：日期一律 `YYYY-MM-DD`；02 旺季边界、08 默认 today 以本地日期为准。

## 3. 差分测试总表（验收必须逐项通过）

### 3.1 端到端主基准（02 → 03 → 06 → 07 → 08）
02 参考算例（必须逐字段一致）：
```
landed_cost.py calc --factory-rmb 38 --fx 0.14 --freight-per-unit 1.60 \
  --hts 8509.40 --category-key small_appliances --weight-g 620 \
  --price 29.99 --ship-date 2026-10-30 --ads-pct 10 --returns-pct 3 \
  --target-margin 25 --moq 500 --json
```
期望：`landed_cost_usd=7.99`、`net_profit_usd=7.67`、`net_margin_pct=25.58`、`break_even_price_usd=19.33`、`target_price_usd=29.62`、`cash_required_usd=3995.00`。

### 3.2 各模块最低差分测试项
| 模块 | 最低验收 |
|---|---|
| 01 | normalize → metrics → score 三连跑，正常退出 0；坏输入退出码与分册一致 |
| 02 | 上例 + `matrix examples/sample-skus.csv` 5 行成功；两行 CSV 中一行缺类目 → 该行失败、另一行成功、退出 2 |
| 03 | `small_appliances + lithium_battery` → CONDITIONAL/1；`baby` 等 7 新类目无 `[INPUT_MISSING]`；未知类目 → JSON 错误 + 3 |
| 04 | `claim_scan` 有 HIGH → 1；`listing_lint` 有 FAIL → 1；缺文件 → 2 且 JSON 合法 |
| 05 | 仓库示例 spec 与平台组合，记录 PASS/WARN/FAIL 与退出码 |
| 06 | `diagnose examples/sample-campaign.csv` 成功；`break_even_acos_pct=38.58` 算例见分册 |
| 07 | reviews/returns/health 三子命令示例成功，记录评分与阈值判定 |
| 08 | `calc` 示例 `reorder_point=360.0`、`days_of_cover=15.0`；`compare` 计费重与差额 |

> 完整命令与输入字段见各分册 §7。任何与前表数字不一致的结果都视为回归。

## 4. 建议实现顺序
1. 先落共享层：错误契约、金额/百分比/BOM-CSV/日期工具、`config/category_map.json` 解析。
2. 02（计算最重、下游 06/08 复用费率）→ 03（规则数据驱动）→ 06/08（消费 02 费率）。
3. 01 → 04 → 05 → 07（文本/规则密集型，独立性强）。
4. 每完成一个模块，直接跑分册 §7 的差分测试基准，通过后再进入下一个。

## 5. 阅读指引
- 只关心某个脚本：直接跳对应分册 §2–§5。
- 关心「哪些现状会被新实现修正」：看各分册 §6 表格最后一列。
- 关心需要用户拍板的分歧：看 `99_gap_and_decisions.md`。
