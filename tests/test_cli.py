"""Behavior tests for the clean-room rewrite (02 landed_cost + 03 compliance_gate).

Each test asserts the observable CLI contract: exit code, JSON structure/values,
stderr channel and rounding. Run from the repository root:

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
COST = ROOT / "Agents" / "02_Cost_Pricing_Agent" / "scripts" / "landed_cost.py"
GATE = ROOT / "Agents" / "03_Compliance_Agent" / "scripts" / "compliance_gate.py"

ENV = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUTF8="1")


def run(script, args):
    return subprocess.run(
        [sys.executable, str(script)] + args,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=ENV,
    )


def run_json(script, args):
    result = run(script, args)
    payload = json.loads(result.stdout)
    return result, payload


BASE = [
    "calc",
    "--factory-rmb", "38",
    "--fx", "0.14",
    "--freight-per-unit", "1.60",
    "--hts", "8509.40",
    "--category-key", "small_appliances",
    "--weight-g", "620",
    "--price", "29.99",
    "--ship-date", "2026-10-30",
]


class LandedCostCalcTests(unittest.TestCase):
    def test_main_baseline_numbers(self):
        result, payload = run_json(COST, BASE + ["--json"])
        self.assertEqual(result.returncode, 0)
        self.assertEqual(payload["costs"]["landed_cost_usd"], 7.99)
        self.assertEqual(payload["profit"]["net_profit_usd"], 7.67)
        self.assertEqual(payload["profit"]["net_margin_pct"], 25.58)
        self.assertEqual(payload["pricing"]["break_even_price_usd"], 19.33)
        self.assertEqual(payload["pricing"]["target_price_usd"], 29.62)

    def test_missing_category_exit_2_and_valid_json(self):
        args = [
            "calc",
            "--factory-rmb", "38",
            "--fx", "0.14",
            "--freight-per-unit", "1.60",
            "--hts", "8509.40",
            "--weight-g", "620",
            "--price", "29.99",
            "--json",
        ]
        result, payload = run_json(COST, args)
        self.assertEqual(result.returncode, 2)
        self.assertEqual(payload["status"], "INPUT_MISSING")
        self.assertEqual(payload["missing"], ["category_key"])
        self.assertIn("缺少类目", payload["message"])
        self.assertIn("[INPUT_MISSING]", result.stderr)

    def test_assume_default_referral_assumptions(self):
        args = [
            "calc",
            "--factory-rmb", "38",
            "--fx", "0.14",
            "--freight-per-unit", "1.60",
            "--hts", "8509.40",
            "--weight-g", "620",
            "--price", "29.99",
            "--assume-default-referral",
            "--json",
        ]
        result, payload = run_json(COST, args)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(
            payload["assumptions"],
            ["referral 按 default 15% 估算（--assume-default-referral）"],
        )
        self.assertEqual(payload["inputs"]["referral_pct"], 15.0)
        self.assertTrue(
            any("[WARN]" in note and "assume-default-referral" in note
                for note in payload["notes"])
        )

    def test_customs_placeholder_marks_warn_and_field(self):
        result, payload = run_json(COST, BASE + ["--json"])
        self.assertEqual(result.returncode, 0)
        self.assertIs(payload["inputs"]["customs_fee_placeholder"], True)
        self.assertEqual(payload["inputs"]["customs_fee_per_unit_usd"], 0.18)
        self.assertTrue(
            any("[WARN]" in note and "customs-fee-per-unit" in note
                for note in payload["notes"])
        )

    def test_explicit_customs_is_not_placeholder(self):
        result, payload = run_json(
            COST, BASE + ["--customs-fee-per-unit", "0.18", "--json"]
        )
        self.assertEqual(result.returncode, 0)
        self.assertIs(payload["inputs"]["customs_fee_placeholder"], False)
        self.assertFalse(
            any("customs-fee-per-unit" in note for note in payload["notes"])
        )

    def test_invalid_ship_date_exit_2(self):
        args = BASE + ["--ship-date", "2026-13-01", "--json"]
        result, payload = run_json(COST, args)
        self.assertEqual(result.returncode, 2)
        self.assertEqual(payload["missing"], ["ship_date"])
        self.assertIn("YYYY-MM-DD", payload["message"])

    def test_negative_factory_exit_2(self):
        args = [
            "calc", "--factory-rmb", "-1", "--fx", "0.14",
            "--freight-per-unit", "1.60", "--hts", "8509.40",
            "--category-key", "small_appliances", "--weight-g", "620",
            "--price", "29.99", "--json",
        ]
        result, payload = run_json(COST, args)
        self.assertEqual(result.returncode, 2)
        self.assertEqual(payload["missing"], ["factory_rmb"])
        self.assertIn("不能为负", payload["message"])

    def test_weight_over_tier_exit_2(self):
        args = [
            "calc", "--factory-rmb", "38", "--fx", "0.14",
            "--freight-per-unit", "1.60", "--hts", "8509.40",
            "--category-key", "small_appliances", "--weight-g", "20000",
            "--price", "29.99", "--json",
        ]
        result, payload = run_json(COST, args)
        self.assertEqual(result.returncode, 2)
        self.assertIn("超出", payload["message"])

    def test_no_subcommand_help_on_stdout(self):
        result = run(COST, [])
        self.assertEqual(result.returncode, 2)
        self.assertTrue(result.stdout.startswith("usage: landed_cost.py"))


class LandedCostMatrixTests(unittest.TestCase):
    def write_csv(self, text):
        handle = tempfile.NamedTemporaryFile(
            "w", suffix=".csv", delete=False, encoding="utf-8-sig"
        )
        handle.write(text)
        handle.close()
        self.addCleanup(os.unlink, handle.name)
        return handle.name

    def test_single_row_failure_does_not_abort(self):
        path = self.write_csv(
            "sku,factory_rmb,freight_per_unit,duty_pct,hts,price,fba_fee,weight_g,category_key\n"
            "OK-1,38,1.6,,8509.40,29.99,,620,small_appliances\n"
            "BAD-NUM,38,1.6,,8509.40,29.99,,abc,small_appliances\n"
            "OK-2,20,1.2,10,,19.99,4.5,,home_kitchen\n"
        )
        result, payload = run_json(
            COST, ["matrix", "--file", path, "--fx", "0.14", "--json"]
        )
        self.assertEqual(result.returncode, 2)
        self.assertEqual(len(payload["rows"]), 2)
        self.assertEqual(len(payload["failed_rows"]), 1)
        self.assertEqual(
            payload["failed_rows"][0]["message"],
            "第 3 行 weight_g 不是数字：abc",
        )
        self.assertTrue(payload["message"].startswith("以下 SKU 行无法计算"))

    def test_matrix_sample_values(self):
        sample = ROOT / "Agents" / "02_Cost_Pricing_Agent" / "examples" / "sample-skus.csv"
        result, payload = run_json(
            COST, ["matrix", "--file", str(sample), "--fx", "0.14", "--json"]
        )
        self.assertEqual(result.returncode, 0)
        self.assertEqual(len(payload["rows"]), 5)
        self.assertEqual(payload["rows"][0]["costs"]["landed_cost_usd"], 7.99)
        self.assertEqual(payload["meta"]["rows"], 5)

    def test_empty_csv_has_no_header(self):
        path = self.write_csv("")
        result, payload = run_json(
            COST, ["matrix", "--file", path, "--fx", "0.14", "--json"]
        )
        self.assertEqual(result.returncode, 2)
        self.assertEqual(payload["message"], "CSV 没有表头")


class ComplianceGateTests(unittest.TestCase):
    def test_conditional_exit_1(self):
        result, payload = run_json(
            GATE,
            ["--category", "home_kitchen", "--attr", "food_contact",
             "--marketplace", "amazon_us", "--json"],
        )
        self.assertEqual(result.returncode, 1)
        self.assertEqual(payload["status"], "CONDITIONAL")
        self.assertEqual(payload["counts"]["required"], 5)
        self.assertEqual(payload["counts"]["missing"], 5)

    def test_blocked_exit_2(self):
        result, payload = run_json(
            GATE,
            ["--category", "baby", "--attr", "children_under_12",
             "--marketplace", "both", "--trademark", "conflict", "--json"],
        )
        self.assertEqual(result.returncode, 2)
        self.assertEqual(payload["status"], "BLOCKED")
        self.assertGreater(payload["counts"]["ip_blocked"], 0)

    def test_blocking_source_line_when_both_causes(self):
        result = run(
            GATE,
            ["--category", "office", "--attr", "medical_claim",
             "--marketplace", "amazon_us", "--trademark", "conflict"],
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("阻断级缺失 2", result.stdout)
        self.assertIn(
            "阻断来源：IP 初筛识别到 2 项冲突（详见下方 IP 初筛）", result.stdout
        )

    def test_unknown_category_exit_3_valid_json(self):
        result, payload = run_json(
            GATE,
            ["--category", "nonexistent", "--attr", "textile",
             "--marketplace", "amazon_us", "--json"],
        )
        self.assertEqual(result.returncode, 3)
        self.assertEqual(payload["status"], "INPUT_MISSING")
        self.assertIn("无法识别的类目", payload["message"])

    def test_default_category_exit_3(self):
        result, payload = run_json(
            GATE,
            ["--category", "default", "--attr", "textile",
             "--marketplace", "amazon_us", "--json"],
        )
        self.assertEqual(result.returncode, 3)
        self.assertIn("没有对应类目", payload["message"])

    def test_pass_exit_0(self):
        names = (
            "宠物用品材料安全与可啃咬部件评估,消费品安全合规自证（CPSA）,"
            "加州 Prop 65 警告标签或暴露评估,服装纺织品阻燃测试（16 CFR 1610）,"
            "纤维成分与护理标签（16 CFR 303）"
        )
        result, payload = run_json(
            GATE,
            ["--category", "pet", "--attr", "textile", "--marketplace",
             "amazon_us", "--have", names, "--json"],
        )
        self.assertEqual(result.returncode, 0)
        self.assertEqual(payload["status"], "PASS")
        self.assertEqual(payload["counts"]["missing"], 0)


if __name__ == "__main__":
    unittest.main()
