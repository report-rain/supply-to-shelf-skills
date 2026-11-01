"""07 Review Ops Agent 行为测试（review_ops.py：reviews / returns / health）。

覆盖本版本有意差异：#9 health 新增 --fail-on-critical（默认关）。
基线数值取自 docs/spec/07_review_ops.md §7，并已与基线期望值一致。

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
AGENT = ROOT / "Agents" / "07_Review_Ops_Agent"
SCRIPT = AGENT / "scripts" / "review_ops.py"
EXAMPLES = AGENT / "examples"

ENV = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUTF8="1")


def run(args):
    return subprocess.run(
        [sys.executable, str(SCRIPT)] + args,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=ENV,
    )


def reviews(path, as_json=True):
    args = ["reviews", "--file", str(path)]
    if as_json:
        args.append("--json")
    return run(args)


def returns(path, orders=None, as_json=True):
    args = ["returns", "--file", str(path)]
    if orders is not None:
        args += ["--orders", str(orders)]
    if as_json:
        args.append("--json")
    return run(args)


def health(path, fail_on_critical=False, as_json=True):
    args = ["health", "--file", str(path)]
    if fail_on_critical:
        args.append("--fail-on-critical")
    if as_json:
        args.append("--json")
    return run(args)


class TempFiles(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def csv(self, name, content):
        path = self.tmp / name
        path.write_text(content, encoding="utf-8")
        return path

    def json_file(self, name, payload):
        path = self.tmp / name
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        return path


class ReviewsTests(TempFiles):
    def test_baseline_json(self):
        result = reviews(EXAMPLES / "sample-reviews.csv")
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stderr, "")
        payload = json.loads(result.stdout)
        self.assertEqual(payload["mode"], "reviews")
        self.assertEqual(payload["total_reviews"], 24)
        self.assertEqual(payload["average_rating"], 3.21)
        self.assertEqual(payload["rating_distribution"],
                         {"1": 4, "2": 6, "3": 3, "4": 3, "5": 8})
        self.assertEqual(payload["one_two_star_count"], 10)
        self.assertEqual(payload["one_two_star_pct"], 41.67)
        self.assertEqual(payload["three_star_pct"], 12.5)
        self.assertEqual(payload["positive_pct"], 45.83)
        self.assertEqual(payload["unclassified_count"], 0)
        self.assertEqual(payload["fixable_count"], 5)
        self.assertEqual(payload["fixable_rate_pct"], 50.0)
        self.assertEqual([item["count"] for item in payload["categories"]],
                         [2, 1, 2, 1, 1, 1, 1, 1])
        self.assertEqual([item["name"] for item in payload["top_issues"]],
                         ["质量做工", "功能故障", "尺寸容量"])
        self.assertEqual(payload["rules"]["fixable"],
                         ["使用门槛", "描述不符", "清洁异味", "质量做工"])

    def test_baseline_text(self):
        result = reviews(EXAMPLES / "sample-reviews.csv", as_json=False)
        self.assertEqual(result.returncode, 0)
        lines = result.stdout.splitlines()
        self.assertEqual(lines[0], "评论归因 · 24 条评论 ｜ 平均分 3.21")
        self.assertIn("可修复率 5/10 = 50.00%（质量做工/描述不符/清洁异味/使用门槛）",
                      result.stdout)
        self.assertIn("Top3 问题与修补建议：", result.stdout)
        self.assertIn("提醒：归因是修补线索，不是甩锅", result.stdout)

    def test_half_star_counts_as_negative_and_bucket_two(self):
        """2.5 星：计入 <3 星的负面计数、分桶归 2，但不参与归因（基线口径）。"""
        result = reviews(self.csv("half.csv", "rating,title,body\n2.5,Broke fast,The seal failed after a week.\n"))
        self.assertEqual(result.returncode, 0)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["total_reviews"], 1)
        self.assertEqual(payload["average_rating"], 2.5)
        self.assertEqual(payload["rating_distribution"]["2"], 1)
        self.assertEqual(payload["one_two_star_count"], 1)
        self.assertEqual(payload["negative_count"], 1)
        self.assertEqual(payload["one_two_star_pct"], 100.0)
        self.assertEqual(payload["attribution"]["质量做工"], 0)
        self.assertEqual(payload["negative_reviews"], [])
        self.assertEqual(payload["unclassified_count"], 0)
        self.assertEqual(payload["fixable_count"], 0)

    def test_empty_body_reports_line_number(self):
        result = reviews(self.csv("empty.csv", "rating,title,body\n5,Great,Love it\n4,Good,\n"))
        self.assertEqual(result.returncode, 2)
        self.assertEqual(json.loads(result.stdout)["message"], "第 3 行评论内容为空。")
        self.assertIn("[INPUT_MISSING] 第 3 行评论内容为空。", result.stderr)

    def test_rating_out_of_range(self):
        for rating in ("0", "6", "abc", ""):
            result = reviews(self.csv("bad.csv", "rating,title,body\n5,Great,Love it\n{},Good,Nice\n".format(rating)))
            self.assertEqual(result.returncode, 2)
            payload = json.loads(result.stdout)
            self.assertEqual(payload["status"], "INPUT_MISSING")
            self.assertIn("第 3 行评分缺失或不在 1–5 星", payload["message"])

    def test_missing_column(self):
        result = reviews(self.csv("nocol.csv", "stars,title\n5,Great\n"))
        self.assertEqual(result.returncode, 2)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["missing"], ["body"])
        self.assertIn("找不到必要列：评论内容。可用列：stars, title", payload["message"])

    def test_missing_file(self):
        result = reviews(self.tmp / "nope.csv")
        self.assertEqual(result.returncode, 2)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["missing"], ["file"])
        self.assertIn("找不到输入文件", payload["message"])

    def test_header_only_file(self):
        result = reviews(self.csv("header.csv", "rating,title,body\n"))
        self.assertEqual(result.returncode, 2)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["missing"], ["file"])
        self.assertIn("文件没有数据行", payload["message"])

    def test_snippet_truncated_at_180_without_ellipsis(self):
        body = "leak " * 60
        payload = json.loads(reviews(self.csv(
            "long.csv", "rating,title,body\n1,Leaks,{}\n".format(body))).stdout)
        snippet = payload["negative_reviews"][0]["snippet"]
        self.assertEqual(len(snippet), 180)
        self.assertNotIn("...", snippet)
        self.assertNotIn("…", snippet)

    def test_unclassified_negative(self):
        payload = json.loads(reviews(self.csv(
            "none.csv", "rating,title,body\n2,Meh,It was just okay for the price.\n")).stdout)
        self.assertEqual(payload["unclassified_count"], 1)
        self.assertEqual(payload["negative_reviews"][0]["category"], "未归类")
        self.assertEqual(payload["negative_reviews"][0]["matched_keywords"], [])


class ReturnsTests(TempFiles):
    def test_baseline_json(self):
        result = returns(EXAMPLES / "sample-returns.csv", orders=320)
        self.assertEqual(result.returncode, 0)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["returned_units"], 37)
        self.assertEqual(payload["return_rate_pct"], 11.56)
        self.assertEqual(payload["total_refund"], 1109.63)
        self.assertEqual(payload["unmapped_codes"], [])
        self.assertEqual(payload["missing"], [])
        self.assertEqual(payload["preventable"]["units"], 24)
        self.assertEqual(payload["preventable"]["share_pct"], 64.86)
        self.assertEqual(payload["preventable"]["refund_amount"], 719.76)
        self.assertEqual(payload["reasons"][0]["code"], "QUALITY_UNACCEPTABLE")
        self.assertEqual(payload["reasons"][0]["qty"], 7)

    def test_baseline_text(self):
        result = returns(EXAMPLES / "sample-returns.csv", orders=320, as_json=False)
        self.assertEqual(result.returncode, 0)
        lines = result.stdout.splitlines()
        self.assertEqual(lines[0], "退货归因 · 37 件 ｜ 退款 1109.63 USD")
        self.assertIn("退货率 11.56%（37 ÷ 320 订单）", result.stdout)
        self.assertIn("可预防退货 24/37 = 64.86%（退款 719.76 USD）", result.stdout)

    def test_missing_orders_is_reported_not_fatal(self):
        result = returns(EXAMPLES / "sample-returns.csv")
        self.assertEqual(result.returncode, 0)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["return_rate_pct"], None)
        self.assertEqual(payload["missing"],
                         ["[INPUT_MISSING] 退货率：需 --orders（同期订单数）。"])
        text = returns(EXAMPLES / "sample-returns.csv", as_json=False).stdout
        self.assertIn("退货率 [INPUT_MISSING]：需 --orders（同期订单数）", text)

    def test_orders_must_be_positive(self):
        result = returns(EXAMPLES / "sample-returns.csv", orders=0)
        self.assertEqual(result.returncode, 2)
        payload = json.loads(result.stdout)
        self.assertIn("--orders 必须大于 0", payload["message"])

    def test_bad_qty_and_refund(self):
        header = "reason_code,qty,refund_amount\n"
        result = returns(self.csv("qty.csv", header + "DAMAGED,0,10.00\n"), orders=10)
        self.assertEqual(result.returncode, 2)
        self.assertIn("第 2 行退货件数缺失或不是正整数", json.loads(result.stdout)["message"])

        result = returns(self.csv("refund.csv", header + "DAMAGED,1,-1.00\n"), orders=10)
        self.assertEqual(result.returncode, 2)
        self.assertIn("第 2 行退款金额缺失或为负数", json.loads(result.stdout)["message"])

    def test_unmapped_code_goes_to_other_with_warning(self):
        result = returns(self.csv(
            "other.csv", "reason_code,qty,refund_amount\nDAMAGED,2,20.00\nCUSTOM_REASON,1,9.00\n"),
            orders=10)
        self.assertEqual(result.returncode, 0)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["unmapped_codes"], ["CUSTOM_REASON"])
        others = [item for item in payload["reasons"] if item["code"] == "OTHER"]
        self.assertTrue(others)
        self.assertEqual(others[0]["qty"], 1)
        self.assertEqual(payload["missing"],
                         ["未映射原因码：CUSTOM_REASON；已归入 OTHER。"])

    def test_chinese_alias_and_empty_code(self):
        result = returns(self.csv(
            "alias.csv", "退货原因码,退货件数,退款金额\n运输损坏,2,20.00\n,1,5.00\n"), orders=10)
        self.assertEqual(result.returncode, 0)
        payload = json.loads(result.stdout)
        self.assertIn("DAMAGED", [item["code"] for item in payload["reasons"]])
        self.assertEqual(payload["unmapped_codes"], ["（空）"])

    def test_missing_column(self):
        result = returns(self.csv("nocol.csv", "reason_code,qty\nDAMAGED,1\n"), orders=10)
        self.assertEqual(result.returncode, 2)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["missing"], ["refund_amount"])
        self.assertIn("找不到必要列：退款金额", payload["message"])


class HealthTests(TempFiles):
    def test_baseline_json(self):
        result = health(EXAMPLES / "sample-health.json")
        self.assertEqual(result.returncode, 0)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["grade"], "CRITICAL")
        self.assertEqual(payload["critical_count"], 1)
        self.assertEqual(payload["warn_count"], 2)
        metrics = {item["key"]: item for item in payload["metrics"]}
        self.assertEqual(metrics["odr_pct"]["status"], "CRITICAL")
        self.assertEqual(metrics["odr_pct"]["distance_to_threshold_pct"], -0.35)
        self.assertEqual(metrics["late_shipment_pct"]["status"], "WARN")
        self.assertEqual(metrics["pre_fulfillment_cancel_pct"]["status"], "OK")

    def test_baseline_text(self):
        result = health(EXAMPLES / "sample-health.json", as_json=False)
        self.assertEqual(result.returncode, 0)
        lines = result.stdout.splitlines()
        self.assertEqual(lines[0], "账号健康 · 生存线告警（CRITICAL）")
        self.assertIn("- 订单缺陷率 ODR：1.35%（阈值 < 1%） → CRITICAL，距阈值 -0.35 个百分点",
                      result.stdout)

    def test_fail_on_critical_flag(self):
        """#9：默认不阻断；显式加 --fail-on-critical 时 CRITICAL 以 exit 1 结束。"""
        default = health(EXAMPLES / "sample-health.json")
        self.assertEqual(default.returncode, 0)

        flagged = health(EXAMPLES / "sample-health.json", fail_on_critical=True)
        self.assertEqual(flagged.returncode, 1)
        self.assertEqual(json.loads(flagged.stdout)["grade"], "CRITICAL")

    def test_fail_on_critical_ignores_warn_grade(self):
        payload = {
            "odr_pct": 0.9, "late_shipment_pct": 3.3, "pre_fulfillment_cancel_pct": 2.1,
            "negative_feedback_pct": 0.4, "a_to_z_claims": 0, "policy_violations": 0,
        }
        result = health(self.json_file("warn.json", payload), fail_on_critical=True)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(json.loads(result.stdout)["grade"], "WARN")

    def test_policies_and_claims_escalate(self):
        payload = {
            "odr_pct": 0.2, "late_shipment_pct": 1.0, "pre_fulfillment_cancel_pct": 0.5,
            "negative_feedback_pct": 0.1, "a_to_z_claims": 1, "policy_violations": 1,
        }
        result = health(self.json_file("policy.json", payload))
        self.assertEqual(result.returncode, 0)
        body = json.loads(result.stdout)
        self.assertEqual(body["grade"], "CRITICAL")
        self.assertEqual(body["warn_count"], 1)
        self.assertEqual(body["critical_count"], 1)

    def test_missing_fields_listed_once(self):
        result = health(self.json_file("missing.json", {"odr_pct": 0.5}))
        self.assertEqual(result.returncode, 2)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["missing"], [
            "late_shipment_pct", "pre_fulfillment_cancel_pct",
            "negative_feedback_pct", "a_to_z_claims", "policy_violations",
        ])

    def test_type_and_negative_validation(self):
        base = {
            "odr_pct": 0.5, "late_shipment_pct": 1.0, "pre_fulfillment_cancel_pct": 0.5,
            "negative_feedback_pct": 0.1, "a_to_z_claims": 0, "policy_violations": 0,
        }
        cases = [
            (dict(base, odr_pct="0.5"), "字段 odr_pct 必须是数字。"),
            (dict(base, a_to_z_claims=0.5), "字段 a_to_z_claims 必须是整数。"),
            (dict(base, late_shipment_pct=-1), "字段 late_shipment_pct 不能为负数。"),
        ]
        for payload, message in cases:
            result = health(self.json_file("bad.json", payload))
            self.assertEqual(result.returncode, 2)
            self.assertEqual(json.loads(result.stdout)["message"], message)

    def test_top_level_must_be_object(self):
        result = health(self.json_file("array.json", []))
        self.assertEqual(result.returncode, 2)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["message"], "账号健康 JSON 顶层必须是对象。")
        self.assertEqual(payload["missing"], ["file"])

    def test_broken_json(self):
        path = self.tmp / "broken.json"
        path.write_text("{bad json", encoding="utf-8")
        result = health(path)
        self.assertEqual(result.returncode, 2)
        payload = json.loads(result.stdout)
        self.assertIn("不是合法 JSON", payload["message"])
        self.assertEqual(payload["missing"], ["file"])

    def test_ok_grade_uses_maintenance_summary(self):
        payload = {
            "odr_pct": 0.1, "late_shipment_pct": 0.5, "pre_fulfillment_cancel_pct": 0.2,
            "negative_feedback_pct": 0.1, "a_to_z_claims": 0, "policy_violations": 0,
        }
        body = json.loads(health(self.json_file("ok.json", payload)).stdout)
        self.assertEqual(body["grade"], "OK")
        self.assertEqual(body["critical_count"], 0)
        self.assertEqual(body["warn_count"], 0)
        self.assertEqual(body["actions"],
                         ["维持周检：ODR、迟发、取消率连续 4 周在阈值内再谈放量。"])


if __name__ == "__main__":
    unittest.main()
