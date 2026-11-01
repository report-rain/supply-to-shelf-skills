# 实现进度

> 记录每个阶段的范围、差分测试结果与提交。差分测试以独立基线目录为参照。
> 判定口径：SAME / INTENDED_DIFF（编号必须对应 `99_gap_and_decisions.md`）/ REGRESSION（必须为 0）。

## 阶段 1：骨架 + 共享层 + 02 + 03
- 范围：仓库骨架、`core/` 共享层、`calc_landed_cost.py`、`compliance_gate.py`。
- 状态：完成（`d8c60db`、`64ff332`、`8afc942`）。

## 阶段 2：01 Selection + 05 Creative
- 范围：`normalize_export.py`、`market_metrics.py`、`opportunity_score.py`、`asset_check.py`。
- 有意差异：#1–#5。
- 测试：44 条通过。
- 差分测试：SAME 21 / INTENDED_DIFF 8 / REGRESSION 0。
- 状态：完成（`fd89a0b`、`ecdb536`）。

## 阶段 2.5：三处崩溃修复
- 范围：05 视频输入异常统一 INPUT_ERROR（#12）；01 market 同价零销量转 WARNING（#13）；05 `--fix` 拒绝覆盖原图（#14）。
- 测试：49 条通过。
- 差分测试：SAME 21 / INTENDED_DIFF 13 / REGRESSION 0。
- 状态：完成。

## 阶段 3：04 Listing + 07 Review Ops
- 范围：`listing_lint.py`、`claim_scan.py`、`review_ops.py`；有意差异 #6、#7、#9。
- 测试：111 条通过。
- 差分测试：SAME 54 / INTENDED_DIFF 17 / REGRESSION 0（04：SAME 16 / INTENDED 3；07：SAME 16 / INTENDED 1）。
- 状态：完成（`613dcca`）。

## 阶段 4：06 Ads + 08 Fulfillment
- 范围：`ads_metrics.py`、`inventory_plan.py`；有意差异 #10、#11。
- 测试：157 条通过（新增 `test_ads.py` 23 条、`test_fulfillment.py` 23 条）。
- 差分测试：SAME 48 / INTENDED_DIFF 1 / REGRESSION 0（06：SAME 22；08：SAME 26 + #10）。
- 修正：06 中间量改为全精度计算、输出取整（TikTok 64.36%）；08 错误文案/help/截止日后缀与基线对齐。
- 状态：完成（`d84957f`）。

## 阶段 5：整合与交付
- 范围：八模块全量差分测试、端到端复算、`99_gap_and_decisions.md` 回填、README/SKILL/CHANGELOG/LICENSE、CI。
- 用例补齐：新增 02（13 条）与 03（12 条）用例，覆盖 calc/matrix/list/错误分支与 03 的 PASS/CONDITIONAL/BLOCKED/未知类目。
- 差分测试修正：
  - 02 `calc` 缺参 `message` 的参数分隔符改回基线 `", "`。
  - harness 将 `generated_at` 归一为 `<TIME>`，消除 03 跨秒抖动（`03 BLOCKED medical` 曾偶发 REGRESSION）。
  - 02 六条用例登记 `#8`（`customs_fee_placeholder` + `[WARN]` note）。
- 全量差分测试：**SAME 121 / INTENDED_DIFF 24 / REGRESSION 0**。
  - 01 `6/6/0`、02 `7/6/0`、03 `12/0/0`、04 `16/3/0`、05 `15/7/0`、06 `22/0/0`、07 `17/1/0`、08 `26/1/0`。
- 端到端复算（02 主基准）：到岸 7.99、净利 7.67、净利率 25.58、盈亏价 19.33、目标价 29.62、占款 3995.0，与基线的期望值一致。
- 文档：`99` 的 D1–D16 全部给出决定，附列 14 项回填（含 02 列表 JSON、04 `100 %`、03 BOM 实测）。
- 交付物：`README.md`、`SKILL.md`（skill 入口）、`CHANGELOG.md`、`LICENSE`（MIT）、`.github/workflows/ci.yml`（3 平台 × 3.10/3.12）。
- 测试：157 条通过。
- 状态：完成（`3c83613`）。
