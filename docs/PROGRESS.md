# 重写进度

> 记录每个批次的范围、对拍结果与提交。对拍 harness：`tests/compare_oracle.py --old-repo ..\supply-to-shelf-skills`。
> 判定口径：SAME / INTENDED_DIFF（编号必须对应 `99_gap_and_decisions.md`）/ REGRESSION（必须为 0）。

## 批次 1：骨架 + 共享层 + 02 + 03
- 范围：仓库骨架、`core/` 共享层、`calc_landed_cost.py`、`compliance_gate.py`。
- 状态：完成（`d8c60db`、`64ff332`、`8afc942`）。

## 批次 2：01 Selection + 05 Creative
- 范围：`normalize_export.py`、`market_metrics.py`、`opportunity_score.py`、`asset_check.py`。
- 有意差异：#1–#5。
- 测试：44 条通过。
- 对拍：SAME 21 / INTENDED_DIFF 8 / REGRESSION 0。
- 状态：完成（`fd89a0b`、`ecdb536`）。

## 批次 2.5：三处崩溃修复
- 范围：05 视频输入异常统一 INPUT_ERROR（#12）；01 market 同价零销量转 WARNING（#13）；05 `--fix` 拒绝覆盖原图（#14）。
- 测试：49 条通过。
- 对拍：SAME 21 / INTENDED_DIFF 13 / REGRESSION 0。
- 状态：完成。

## 批次 3：04 Listing + 07 Review Ops
- 范围：`listing_lint.py`、`claim_scan.py`、`review_ops.py`；有意差异 #6、#7、#9。
- 测试：111 条通过。
- 对拍：SAME 54 / INTENDED_DIFF 17 / REGRESSION 0（04：SAME 16 / INTENDED 3；07：SAME 16 / INTENDED 1）。
- 状态：完成（`613dcca`）。

## 批次 4：06 Ads + 08 Fulfillment
- 范围：`ads_metrics.py`、`fulfillment_plan.py`；有意差异 #10、#11。
- 状态：待开始。

## 批次 5：整合与交付
- 范围：全量对拍、端到端复算、文档缺口回填、README/CHANGELOG/LICENSE、CI。
- 状态：待开始。
