# Changelog

## 2.0.0 — 2026-11-01

clean-room 重写首版：8 个模块、共享层、规格、单测与黑盒对拍。

### 新增

- 共享层 `shared/`：`errors`（统一 `fail` / `emit_json` / `run_main`）、`args`（argparse 错误走统一 JSON）、`numbers`（`round2`）、`config`、`category`。
- 01 选品：`normalize_export.py`、`market_metrics.py`、`opportunity_score.py`。
- 02 成本定价：`landed_cost.py`（`calc` / `matrix` / `--list-platforms` / `--list-fba-tiers`）。
- 03 合规：`compliance_gate.py` + `compliance_rules.json`。
- 04 上架：`listing_lint.py`、`claim_scan.py`。
- 05 素材：`asset_check.py`（图片/视频、`--fix`）。
- 06 广告：`ads_metrics.py`（`calc` / `diagnose`）。
- 07 运营：`review_ops.py`（`reviews` / `returns` / `health`）。
- 08 补货：`inventory_plan.py`（`calc` / `compare`）。
- `docs/spec/00–08` 规格、`docs/spec/99_gap_and_decisions.md`、`docs/PROGRESS.md`。
- `tests/compare_oracle.py` 黑盒对拍 harness + 157 条单测。
- Trae skill 入口 `SKILL.md`，MIT `LICENSE`，GitHub Actions CI。

### 变更（有意差异 #1–#14）

- #1 01 输入错误退出码 1 → 2。
- #2 05 输入文件缺失/不可读退出码 1 → 2。
- #3 05 损坏图 / 0 尺寸 / 不可解码 → 明确状态码 + exit 2，无 traceback。
- #4 01 单行脏数据报行号与列名，exit 2。
- #5 01 NaN/Inf 显式拒绝。
- #6 04 解码失败明确报错 exit 2。
- #7 04 补 A+ 模块顺序校验。
- #8 02 `inputs.customs_fee_placeholder` + `[WARN]` note。
- #9 07 新增可选 `--fail-on-critical`（默认关）。
- #10 08 `--carrying-rate-pct` 限制 0–100。
- #11 08 示例资金数字按实跑值固化（3995 / 45.97 / 10.51 / 35.46）。
- #12 05 视频输入异常统一 `INPUT_ERROR` + exit 2。
- #13 01 `market_metrics` 同价且 Σ销量=0 转 WARNING，价带置空。
- #14 05 `--fix` 指向原图时拒绝覆盖，exit 2。

### 修复

- 02 `calc` 缺参 `message` 的参数分隔符与旧侧一致（`", "`）。
- 06 中间量改为全精度计算、输出取整（TikTok 64.36%、负贡献 -4.46% 与旧侧一致）。
- 08 错误文案、help、无子命令 `missing=["command"]`、截止日后缀条件逐项对齐旧侧。

### 测试与对拍基线

- 单测：157 条通过。
- 八模块全量对拍：`SAME 121 / INTENDED_DIFF 24 / REGRESSION 0`。
- 端到端主基准复算：到岸 7.99、净利 7.67、净利率 25.58%、盈亏价 19.33、目标价 29.62、占款 3995.0，与旧侧逐位一致。

### 已知限制

- 03 为合规初筛，不构成法律意见；税率与平台费率为时点口径。
- 不做联网抓取，不调用平台 API。
- 05 像素级检查与 `--fix` 依赖 Pillow；缺失时降级并告警。
- 06/07/08 业务告警默认退出 0；仅 07 提供可选严格开关。
- 严格 `utf-8-sig`，不做 GBK 回退。
