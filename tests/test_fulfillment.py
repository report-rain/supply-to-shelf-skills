"""08 补货与海空运（inventory_plan.py）回归测试。

基线数值取自 docs/spec/08_fulfillment.md §7，并已与旧侧黑盒对拍一致：
calc 补货点 1320 / 可售 15 天 / 建议 2000 / 风险 HIGH；
compare kg 海运 992、空运 2480、资金占用 3995/45.97/10.51/35.46。

覆盖本批有意差异：#10 --carrying-rate-pct 上限 100（旧侧无上限）。

    python -m unittest discover -s tests -v
"""

import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "Agents" / "08_Fulfillment_Agent" / "scripts" / "inventory_plan.py"

ENV = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUTF8="1")

CALC_BASE = [
    "--daily-sales", "20",
    "--lead-time-days", "45",
    "--safety-days", "21",
    "--stock", "300",
    "--moq", "500",
    "--inbound-interval-days", "30",
    "--unit-cost", "7.99",
    "--today", "2026-10-30",
]


def run(args):
    return subprocess.run(
        [sys.executable, str(SCRIPT)] + args,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=ENV,
    )


def calc(extra=None, as_json=True):
    extra = CALC_BASE if extra is None else extra
    args = ["calc"] + list(extra)
    if as_json:
        args.append("--json")
    return run(args)


def compare(extra, as_json=True):
    args = ["compare"] + list(extra)
    if as_json:
        args.append("--json")
    return run(args)


def payload(result):
    return json.loads(result.stdout)


class CalcTests(unittest.TestCase):
    def test_full_numbers(self):
        result = calc()
        self.assertEqual(result.returncode, 0, result.stderr)
        data = payload(result)
        self.assertEqual(data["reorder_point"], 1320.0)
        self.assertEqual(data["days_of_cover"], 15.0)
        self.assertEqual(data["expected_stockout_date"], "2026-11-14")
        self.assertEqual(data["order_deadline"], "2026-09-30")
        self.assertTrue(data["order_deadline_passed"])
        self.assertEqual(data["days_until_deadline"], -30)
        self.assertEqual(data["target_stock"], 1920.0)
        self.assertEqual(data["suggested_order_qty"], 2000)
        self.assertEqual(data["coverage_after_order_days"], 115.0)
        self.assertEqual(data["capital_required"], 15980.0)
        self.assertEqual(data["risk_level"], "HIGH")

    def test_medium_risk_at_lead_boundary(self):
        extra = [a for a in CALC_BASE]
        extra[extra.index("300")] = "900"
        result = calc(extra)
        self.assertEqual(result.returncode, 0, result.stderr)
        data = payload(result)
        self.assertEqual(data["risk_level"], "MEDIUM")
        self.assertEqual(data["days_until_deadline"], 0)
        self.assertFalse(data["order_deadline_passed"])
        self.assertEqual(data["suggested_order_qty"], 1500)
        self.assertIn("低于补货点 1320 件", data["notes"][0])

    def test_low_risk_and_zero_order(self):
        extra = [a for a in CALC_BASE]
        extra[extra.index("300")] = "2000"
        result = calc(extra)
        self.assertEqual(result.returncode, 0, result.stderr)
        data = payload(result)
        self.assertEqual(data["risk_level"], "LOW")
        self.assertEqual(data["suggested_order_qty"], 0)
        self.assertEqual(data["capital_required"], 0.0)
        self.assertEqual(len(data["notes"]), 2)

    def test_zero_daily_sales_is_na(self):
        result = calc(["--daily-sales", "0", "--lead-time-days", "45", "--stock", "0",
                       "--moq", "500", "--today", "2026-10-30"])
        self.assertEqual(result.returncode, 0, result.stderr)
        data = payload(result)
        self.assertEqual(data["risk_level"], "N/A")
        self.assertIsNone(data["days_of_cover"])
        self.assertIsNone(data["expected_stockout_date"])
        self.assertIsNone(data["order_deadline"])
        self.assertEqual(data["suggested_order_qty"], 0)
        self.assertEqual(len(data["notes"]), 2)

    def test_zero_sales_with_unit_cost_zero_capital(self):
        result = calc(["--daily-sales", "0", "--lead-time-days", "45", "--stock", "300",
                       "--moq", "500", "--unit-cost", "7.99", "--today", "2026-10-30"])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(payload(result)["capital_required"], 0.0)

    def test_human_output_deadline_suffix(self):
        result = calc(as_json=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("下单截止日：2026-09-30（已过 30 天，需立即下单）", result.stdout)
        self.assertIn("断货风险等级：HIGH", result.stdout)

    def test_lead_time_zero_fails(self):
        result = calc(["--daily-sales", "20", "--lead-time-days", "0", "--moq", "500"])
        self.assertEqual(result.returncode, 2)
        self.assertEqual(payload(result)["missing"], ["lead_time_days"])

    def test_negative_stock_fails(self):
        result = calc(["--daily-sales", "20", "--lead-time-days", "45", "--stock", "-5",
                       "--moq", "500"])
        self.assertEqual(result.returncode, 2)
        self.assertEqual(payload(result)["missing"], ["stock"])

    def test_moq_zero_fails(self):
        result = calc(["--daily-sales", "20", "--lead-time-days", "45", "--moq", "0"])
        self.assertEqual(result.returncode, 2)
        self.assertEqual(payload(result)["missing"], ["moq"])

    def test_unit_cost_zero_fails(self):
        result = calc(["--daily-sales", "20", "--lead-time-days", "45", "--moq", "500",
                       "--unit-cost", "0"])
        self.assertEqual(result.returncode, 2)
        self.assertEqual(payload(result)["missing"], ["unit_cost"])

    def test_bad_month_fails(self):
        result = calc(["--daily-sales", "20", "--lead-time-days", "45", "--moq", "500",
                       "--today", "2026-13-01"])
        self.assertEqual(result.returncode, 2)
        self.assertEqual(payload(result)["missing"], ["today"])

    def test_non_padded_date_fails(self):
        result = calc(["--daily-sales", "20", "--lead-time-days", "45", "--moq", "500",
                       "--today", "2026-1-1"])
        self.assertEqual(result.returncode, 2)
        self.assertIn("2026-1-1", payload(result)["message"])

    def test_no_subcommand(self):
        result = run([])
        self.assertEqual(result.returncode, 2)
        self.assertIn("缺少子命令", result.stderr)
        self.assertIn("inventory_plan.py", result.stdout)


class CompareTests(unittest.TestCase):
    KG = ["--units", "500", "--weight-kg", "0.62", "--cbm-per-unit", "0.00178",
          "--sea-rate-per-kg", "3.2", "--air-rate-per-kg", "8.0",
          "--sea-days", "35", "--air-days", "8", "--unit-cost", "7.99",
          "--today", "2026-10-30"]

    def test_kg_rate_numbers(self):
        result = compare(self.KG)
        self.assertEqual(result.returncode, 0, result.stderr)
        data = payload(result)
        self.assertEqual(data["cargo"]["total_weight_kg"], 310.0)
        self.assertEqual(data["cargo"]["total_cbm"], 0.89)
        self.assertEqual(data["cargo"]["density_kg_per_cbm"], 348.3)
        self.assertEqual(data["cargo"]["air_volumetric_kg"], 148.6)
        self.assertEqual(data["cargo"]["air_chargeable_kg"], 310.0)
        self.assertEqual(data["sea"]["total"], 992.0)
        self.assertEqual(data["sea"]["per_unit"], 1.984)
        self.assertEqual(data["sea"]["eta"], "2026-12-04")
        self.assertEqual(data["sea"]["charge_basis"], "按重量（kg）")
        self.assertEqual(data["air"]["total"], 2480.0)
        self.assertEqual(data["air"]["per_unit"], 4.96)
        self.assertEqual(data["diff"]["total"], 1488.0)
        self.assertEqual(data["diff"]["per_unit"], 2.976)
        self.assertEqual(data["diff"]["premium_pct"], 150.0)
        self.assertEqual(data["diff"]["days_saved"], 27)
        self.assertEqual(data["diff"]["cost_per_day_saved"], 55.11)
        self.assertEqual(data["capital"]["inventory_value"], 3995.0)
        self.assertEqual(data["capital"]["sea_capital_cost"], 45.97)
        self.assertEqual(data["capital"]["air_capital_cost"], 10.51)
        self.assertEqual(data["capital"]["capital_diff"], 35.46)
        self.assertIn("海运为主", data["recommendation"])

    def test_cbm_rate_hits_lcl_minimum(self):
        result = compare(["--units", "100", "--weight-kg", "0.62", "--cbm-per-unit", "0.00178",
                          "--sea-rate-per-cbm", "60", "--air-rate-per-kg", "8",
                          "--sea-days", "35", "--air-days", "8"])
        self.assertEqual(result.returncode, 0, result.stderr)
        data = payload(result)
        self.assertEqual(data["cargo"]["total_cbm"], 0.178)
        self.assertEqual(data["sea"]["total"], 60.0)
        self.assertEqual(data["sea"]["per_unit"], 0.6)
        self.assertEqual(data["sea"]["charge_basis"], "按体积重（CBM，LCL 最低 1 CBM 起算）")
        self.assertEqual(data["air"]["total"], 496.0)
        self.assertEqual(data["diff"]["total"], 436.0)
        self.assertEqual(data["diff"]["premium_pct"], 726.7)
        self.assertEqual(data["diff"]["cost_per_day_saved"], 16.15)
        self.assertIsNone(data["capital"])
        self.assertTrue(any("LCL" in note for note in data["notes"]))

    def test_air_slower_has_no_time_advantage(self):
        result = compare(["--units", "500", "--weight-kg", "0.62", "--cbm-per-unit", "0.00178",
                          "--sea-rate-per-kg", "3.2", "--air-rate-per-kg", "8",
                          "--sea-days", "8", "--air-days", "35"])
        self.assertEqual(result.returncode, 0, result.stderr)
        data = payload(result)
        self.assertEqual(data["diff"]["days_saved"], -27)
        self.assertIsNone(data["diff"]["cost_per_day_saved"])
        self.assertIn("无时效优势", data["recommendation"])

    def test_negative_premium_still_uses_accept_branch(self):
        result = compare(["--units", "1", "--weight-kg", "0.5", "--cbm-per-unit", "0",
                          "--sea-rate-per-cbm", "60", "--air-rate-per-kg", "4",
                          "--sea-days", "35", "--air-days", "8"])
        self.assertEqual(result.returncode, 0, result.stderr)
        data = payload(result)
        self.assertEqual(data["sea"]["total"], 60.0)
        self.assertEqual(data["air"]["total"], 2.0)
        self.assertEqual(data["diff"]["total"], -58.0)
        self.assertEqual(data["diff"]["premium_pct"], -96.7)
        self.assertIn("溢价可接受", data["recommendation"])

    def test_missing_sea_rate_fails(self):
        result = compare(["--units", "100", "--weight-kg", "1", "--air-rate-per-kg", "8",
                          "--sea-days", "35", "--air-days", "8"])
        self.assertEqual(result.returncode, 2)
        self.assertEqual(payload(result)["missing"], ["sea_rate_per_kg|sea_rate_per_cbm"])

    def test_units_fraction_is_argparse_error(self):
        result = compare(["--units", "1.5", "--weight-kg", "1", "--air-rate-per-kg", "8",
                          "--sea-rate-per-kg", "3", "--sea-days", "35", "--air-days", "8"])
        self.assertEqual(result.returncode, 2)
        self.assertEqual(payload(result)["missing"], [])

    def test_carrying_rate_negative_fails(self):
        result = compare(["--units", "100", "--weight-kg", "1", "--sea-rate-per-kg", "3",
                          "--air-rate-per-kg", "8", "--sea-days", "35", "--air-days", "8",
                          "--carrying-rate-pct", "-1"])
        self.assertEqual(result.returncode, 2)
        self.assertEqual(payload(result)["missing"], ["carrying_rate_pct"])

    def test_carrying_rate_above_hundred_fails(self):
        result = compare(["--units", "100", "--weight-kg", "1", "--sea-rate-per-kg", "3",
                          "--air-rate-per-kg", "8", "--sea-days", "35", "--air-days", "8",
                          "--carrying-rate-pct", "200"])
        self.assertEqual(result.returncode, 2)
        self.assertEqual(payload(result)["status"], "INPUT_MISSING")
        self.assertEqual(payload(result)["missing"], ["carrying_rate_pct"])

    def test_carrying_rate_zero_is_allowed(self):
        result = compare(["--units", "100", "--weight-kg", "1", "--sea-rate-per-kg", "3",
                          "--air-rate-per-kg", "8", "--sea-days", "35", "--air-days", "8",
                          "--unit-cost", "7.99", "--carrying-rate-pct", "0"])
        self.assertEqual(result.returncode, 0, result.stderr)
        capital = payload(result)["capital"]
        self.assertEqual(capital["sea_capital_cost"], 0.0)
        self.assertEqual(capital["air_capital_cost"], 0.0)

    def test_human_output_contains_key_numbers(self):
        result = compare(self.KG, as_json=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("USD 992.00", result.stdout)
        self.assertIn("USD 2480.00", result.stdout)
        self.assertIn("150.0%", result.stdout)


if __name__ == "__main__":
    unittest.main()
