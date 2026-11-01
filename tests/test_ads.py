"""06 广告投放指标（ads_metrics.py）回归测试。

基线数值取自 docs/spec/06_ads.md §7，并已与基线期望值一致：
calc 盈亏线 35.58% / 目标 ROAS 4.0 / TACOS 34.61%；
diagnose 总计 96940 曝光、799.27 花费、2309.23 销售额、净贡献 22.32。

    python -m unittest discover -s tests -v
"""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
AGENT = ROOT / "Agents" / "06_Ads_Agent"
SCRIPT = AGENT / "scripts" / "ads_metrics.py"
SAMPLE = AGENT / "examples" / "sample-campaign.csv"

ENV = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUTF8="1")

BASE = [
    "--price", "29.99",
    "--product-cost", "7.99",
    "--referral", "15",
    "--fba-fee", "5.93",
    "--ads-pct", "10",
    "--returns-pct", "3",
    "--target-acos", "25",
]


def run(args):
    return subprocess.run(
        [sys.executable, str(SCRIPT)] + args,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=ENV,
    )


def calc(extra=None, as_json=True, platform="amazon_us"):
    args = ["calc", "--platform", platform] + BASE + list(extra or [])
    if as_json:
        args.append("--json")
    return run(args)


def diagnose(path, extra=None, as_json=True, platform="amazon_us"):
    args = ["diagnose", "--file", str(path), "--platform", platform] + BASE + list(extra or [])
    if as_json:
        args.append("--json")
    return run(args)


def payload(result):
    return json.loads(result.stdout)


class CalcTests(unittest.TestCase):
    def test_full_input_matches_baseline(self):
        result = calc(["--cvr", "8", "--ad-spend", "799.27", "--total-sales", "2309.23"])
        self.assertEqual(result.returncode, 0, result.stderr)
        data = payload(result)["metrics"]
        self.assertEqual(data["referral_fee"], 4.5)
        self.assertEqual(data["returns_provision"], 0.9)
        self.assertEqual(data["planned_ad_provision"], 3.0)
        self.assertEqual(data["pre_ad_contribution"], 10.67)
        self.assertEqual(data["pre_ad_margin_pct"], 35.58)
        self.assertEqual(data["contribution_after_planned_ads"], 7.67)
        self.assertEqual(data["break_even_acos"], 0.3558)
        self.assertEqual(data["break_even_acos_pct"], 35.58)
        self.assertEqual(data["break_even_roas"], 2.81)
        self.assertEqual(data["target_roas"], 4.0)
        self.assertEqual(data["affordable_cpc"], 0.6)
        self.assertEqual(data["tacos"], 0.3461)
        self.assertEqual(data["tacos_pct"], 34.61)
        self.assertIsNone(data["model_warning"])
        self.assertEqual(payload(result)["missing"], [])

    def test_minimal_input_leaves_optional_metrics_null(self):
        result = calc()
        self.assertEqual(result.returncode, 0, result.stderr)
        data = payload(result)
        self.assertIsNone(data["metrics"]["affordable_cpc"])
        self.assertIsNone(data["metrics"]["tacos"])
        self.assertIsNone(data["metrics"]["tacos_pct"])
        self.assertEqual(len(data["missing"]), 2)

    def test_only_one_tacos_input_keeps_tacos_null(self):
        result = calc(["--ad-spend", "100"])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIsNone(payload(result)["metrics"]["tacos"])
        self.assertIn("TACOS", payload(result)["missing"][-1])

    def test_negative_contribution_keeps_full_model(self):
        result = calc(["--product-cost", "20"])
        self.assertEqual(result.returncode, 0, result.stderr)
        data = payload(result)["metrics"]
        self.assertEqual(data["pre_ad_contribution"], -1.34)
        self.assertEqual(data["pre_ad_margin_pct"], -4.46)
        self.assertEqual(data["break_even_acos_pct"], -4.46)
        self.assertIsNone(data["break_even_roas"])
        self.assertIn("广告前贡献", data["model_warning"])

    def test_tiktok_platform_uses_same_formula(self):
        result = calc(["--product-cost", "7.99", "--referral", "6", "--fba-fee", "0"],
                      platform="tiktok_us")
        self.assertEqual(result.returncode, 0, result.stderr)
        data = payload(result)["metrics"]
        self.assertEqual(data["referral_fee"], 1.8)
        self.assertEqual(data["pre_ad_contribution"], 19.3)
        self.assertEqual(data["pre_ad_margin_pct"], 64.36)
        self.assertEqual(data["break_even_acos_pct"], 64.36)
        self.assertEqual(payload(result)["platform_label"], "TikTok Shop US")

    def test_human_output_contains_key_numbers(self):
        result = calc(as_json=False, extra=["--cvr", "8", "--ad-spend", "799.27",
                                            "--total-sales", "2309.23"])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("盈亏线 ACOS 35.58%", result.stdout)
        self.assertIn("目标 ROAS 4.00", result.stdout)
        self.assertIn("TACOS 34.61%", result.stdout)

    def test_price_zero_fails(self):
        result = calc(["--price", "0"])
        self.assertEqual(result.returncode, 2)
        self.assertEqual(payload(result)["status"], "INPUT_MISSING")
        self.assertEqual(payload(result)["missing"], [])

    def test_referral_zero_fails(self):
        result = calc(["--referral", "0"])
        self.assertEqual(result.returncode, 2)
        self.assertIn("0–100", result.stderr)

    def test_target_acos_ninety_nine_allowed(self):
        result = calc(["--target-acos", "99"])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(payload(result)["metrics"]["target_acos_pct"], 99.0)

    def test_target_acos_hundred_fails(self):
        result = calc(["--target-acos", "100"])
        self.assertEqual(result.returncode, 2)
        self.assertIn("0–100", result.stderr)

    def test_total_sales_zero_fails_when_paired(self):
        result = calc(["--ad-spend", "100", "--total-sales", "0"])
        self.assertEqual(result.returncode, 2)
        self.assertIn("total-sales", result.stderr)

    def test_missing_subcommand_is_argparse_error(self):
        result = run([])
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout, "")
        self.assertIn("required", result.stderr)

    def test_json_before_subcommand_is_treated_as_error(self):
        result = run(["--json", "calc"])
        self.assertEqual(result.returncode, 2)
        self.assertEqual(payload(result)["status"], "INPUT_MISSING")


class DiagnoseTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.work = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, name, text):
        path = self.work / name
        path.write_text(text, encoding="utf-8")
        return path

    def test_sample_report_totals(self):
        result = diagnose(SAMPLE)
        self.assertEqual(result.returncode, 0, result.stderr)
        data = payload(result)
        self.assertEqual(data["mode"], "diagnose")
        self.assertEqual(data["total"]["campaigns"], 9)
        self.assertEqual(data["total"]["impressions"], 96940)
        self.assertEqual(data["total"]["clicks"], 2485)
        self.assertEqual(data["total"]["spend"], 799.27)
        self.assertEqual(data["total"]["orders"], 77)
        self.assertEqual(data["total"]["sales"], 2309.23)
        self.assertEqual(data["total"]["roas"], 2.89)
        self.assertEqual(data["total"]["tacos_pct"], 34.61)
        self.assertEqual(data["total"]["net_contribution"], 22.32)
        self.assertEqual(data["priority_counts"], {"P0": 2, "P1": 4, "P2": 2, "INFO": 1})

    def test_sample_report_key_rows(self):
        result = diagnose(SAMPLE)
        rows = {row["campaign"]: row for row in payload(result)["campaigns"]}
        self.assertEqual(rows["PB-Longtail-Phrase"]["clicks"], 96)
        self.assertEqual(rows["PB-Longtail-Phrase"]["orders"], 0)
        self.assertEqual(rows["PB-Longtail-Phrase"]["grade"], "P0")
        self.assertEqual(rows["PB-Broad-Cheap"]["roas"], 1.25)
        self.assertEqual(rows["PB-Broad-Cheap"]["acos_pct"], 79.75)
        self.assertEqual(rows["PB-Core-Exact"]["roas"], 5.9)
        self.assertEqual(rows["PB-Core-Exact"]["acos_pct"], 16.95)
        self.assertEqual(rows["PB-Core-Exact"]["grade"], "P2")
        self.assertEqual(rows["PB-New-Video"]["grade"], "INFO")

    def test_sample_report_human_output(self):
        result = diagnose(SAMPLE, as_json=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("PB-Core-Exact", result.stdout)
        self.assertIn("盈亏线 ACOS 35.58%", result.stdout)

    def test_missing_file_fails(self):
        result = diagnose(self.work / "absent.csv")
        self.assertEqual(result.returncode, 2)
        self.assertEqual(payload(result)["missing"], ["file"])

    def test_header_only_fails(self):
        path = self.write("empty.csv", "campaign,impressions,clicks,spend,orders,sales\n")
        result = diagnose(path)
        self.assertEqual(result.returncode, 2)
        self.assertEqual(payload(result)["missing"], ["file"])

    def test_missing_column_fails(self):
        path = self.write("nocol.csv", "campaign,impressions,clicks,spend,orders\nPB,1000,10,5,1\n")
        result = diagnose(path)
        self.assertEqual(result.returncode, 2)
        self.assertEqual(payload(result)["missing"], ["sales"])

    def test_negative_spend_fails_with_row_number(self):
        path = self.write("neg.csv", "campaign,impressions,clicks,spend,orders,sales\nPB,1000,10,-1,1,20\n")
        result = diagnose(path)
        self.assertEqual(result.returncode, 2)
        self.assertEqual(payload(result)["missing"], [])
        self.assertIn("第 2 行", result.stderr)

    def test_missing_returns_pct_notice(self):
        args = ["--price", "29.99", "--product-cost", "7.99", "--referral", "15",
                "--fba-fee", "5.93", "--target-acos", "25"]
        result = run(["diagnose", "--file", str(SAMPLE), "--platform", "amazon_us"]
                     + args + ["--json"])
        self.assertEqual(result.returncode, 0, result.stderr)
        data = payload(result)
        self.assertEqual(len(data["missing"]), 1)
        self.assertEqual(data["cost_model"]["break_even_acos_pct"], 38.58)
        self.assertEqual(data["cost_model"]["break_even_roas"], 2.59)

    def test_zero_spend_row_is_info(self):
        path = self.write("zero.csv", "campaign,impressions,clicks,spend,orders,sales\nPB,2000,50,0,0,0\n")
        result = diagnose(path)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(payload(result)["campaigns"][0]["grade"], "INFO")

    def test_negative_contribution_grades_all_p0(self):
        path = self.write("bad.csv", "campaign,impressions,clicks,spend,orders,sales\nBad,5000,100,50,0,0\n")
        result = run(["diagnose", "--file", str(path), "--platform", "amazon_us",
                      "--price", "29.99", "--product-cost", "20", "--referral", "15",
                      "--fba-fee", "5.93", "--returns-pct", "3", "--target-acos", "25", "--json"])
        self.assertEqual(result.returncode, 0, result.stderr)
        data = payload(result)
        self.assertIsNone(data["cost_model"]["break_even_roas"])
        self.assertEqual(data["campaigns"][0]["grade"], "P0")


if __name__ == "__main__":
    unittest.main()
