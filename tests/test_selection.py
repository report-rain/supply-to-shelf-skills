"""01 Selection Agent 行为测试（normalize / market_metrics / opportunity_score）。

覆盖本批有意差异：#1 输入错误 exit 2、#4 单行脏数据报行号列名、#5 NaN/Inf 校验；
同时锁定基线：28 个 ASIN、月销 38,680、月销售额 1,527,531、Go 10 / Watch 15 / No-Go 3。

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
SCRIPTS = ROOT / "Agents" / "01_Selection_Agent" / "scripts"
NORMALIZE = SCRIPTS / "normalize_export.py"
MARKET = SCRIPTS / "market_metrics.py"
OPPORTUNITY = SCRIPTS / "opportunity_score.py"
SAMPLE = ROOT / "Agents" / "01_Selection_Agent" / "examples" / "sample_category_export.csv"

ENV = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUTF8="1")

HEADER = (
    "asin,title,brand,seller,price,monthly_sales,monthly_revenue,"
    "reviews,rating,bsr,fulfillment"
)
GOOD_ROW = "B0X,T,B,S,29.99,100,2999.00,10,4.0,100,FBA"


def run(script, args):
    return subprocess.run(
        [sys.executable, str(script)] + args,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=ENV,
    )


class SelectionTestBase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def write(self, name, text, encoding="utf-8"):
        path = self.tmp / name
        path.write_text(text, encoding=encoding)
        return path


class NormalizeExportTests(SelectionTestBase):
    def test_empty_csv_exit_2(self):
        """#1：空 CSV 是输入错误，退出码由 1 改为 2。"""
        path = self.write("empty.csv", "")
        result = run(NORMALIZE, [str(path)])
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout, "")
        self.assertIn("[INPUT_MISSING] CSV 没有表头", result.stderr)

    def test_missing_columns_exit_2(self):
        """#1：缺列是输入错误，退出码 2，并列出缺失与现存表头。"""
        path = self.write("missing.csv", "asin,title,price\nB0X,T,1.00\n")
        result = run(NORMALIZE, [str(path)])
        self.assertEqual(result.returncode, 2)
        self.assertIn("[INPUT_MISSING] CSV 缺少列", result.stderr)
        self.assertIn("brand", result.stderr)
        self.assertIn("现有表头", result.stderr)
        self.assertFalse((self.tmp / "missing.normalized.json").exists())

    def test_header_only_exit_2(self):
        path = self.write("header.csv", HEADER + "\n")
        result = run(NORMALIZE, [str(path)])
        self.assertEqual(result.returncode, 2)
        self.assertIn("CSV 没有数据行", result.stderr)

    def test_dirty_row_reports_row_and_column_exit_2(self):
        """#4：单行脏数据必须报行号 + 列名，退出码 2，不静默产出数值。"""
        path = self.write("dirty.csv", HEADER + "\n" + "B0X,T,B,S,abc,100,2999.00,10,4.0,100,FBA\n")
        result = run(NORMALIZE, [str(path)])
        self.assertEqual(result.returncode, 2)
        self.assertIn("[INPUT_MISSING] 第 2 行 price='abc' 不是数字", result.stderr)
        self.assertFalse((self.tmp / "dirty.normalized.json").exists())

    def test_nan_rejected(self):
        """#5：NaN 不进入计算；nan 视作缺值并报行号。"""
        path = self.write("nan.csv", HEADER + "\n" + "B0X,T,B,S,nan,100,2999.00,10,4.0,100,FBA\n")
        result = run(NORMALIZE, [str(path)])
        self.assertEqual(result.returncode, 2)
        self.assertIn("第 2 行缺少 price", result.stderr)
        self.assertFalse((self.tmp / "nan.normalized.json").exists())

    def test_inf_rejected(self):
        """#5：Inf 显式校验，不再写出 Infinity。"""
        path = self.write("inf.csv", HEADER + "\n" + "B0X,T,B,S,inf,100,2999.00,10,4.0,100,FBA\n")
        result = run(NORMALIZE, [str(path)])
        self.assertEqual(result.returncode, 2)
        self.assertIn("第 2 行 price='inf' 不是有限数值（NaN/Inf）", result.stderr)
        self.assertFalse((self.tmp / "inf.normalized.json").exists())

    def test_negative_price_kept(self):
        """负价不做业务拦截（既有行为）：照常写出，由下游判断。"""
        path = self.write("neg.csv", HEADER + "\n" + "B0X,T,B,S,-29.99,100,-2999.00,10,4.0,100,FBA\n")
        result = run(NORMALIZE, [str(path)])
        self.assertEqual(result.returncode, 0)
        payload = json.loads((self.tmp / "neg.normalized.json").read_text(encoding="utf-8"))
        self.assertEqual(payload["meta"]["item_count"], 1)
        self.assertEqual(payload["items"][0]["price"], -29.99)

    def test_bom_and_crlf(self):
        """BOM + CRLF 必须可读；纯空行跳过（既有行为），不报 asin 为空。"""
        path = self.tmp / "bom.csv"
        with open(path, "w", encoding="utf-8-sig", newline="") as handle:
            handle.write(HEADER + "\r\n" + GOOD_ROW + "\r\n\r\n")
        result = run(NORMALIZE, [str(path)])
        self.assertEqual(result.returncode, 0)
        payload = json.loads((self.tmp / "bom.normalized.json").read_text(encoding="utf-8"))
        self.assertEqual(payload["meta"]["item_count"], 1)
        self.assertEqual(payload["items"][0]["asin"], "B0X")
        self.assertEqual(payload["items"][0]["price"], 29.99)


class BaselineTests(SelectionTestBase):
    """锁定 01 的基准数据，任何数值漂移都算回归。"""

    def normalize_sample(self):
        target = self.tmp / "sample_category_export.csv"
        target.write_text(SAMPLE.read_text(encoding="utf-8"), encoding="utf-8")
        result = run(NORMALIZE, [str(target)])
        self.assertEqual(result.returncode, 0)
        self.assertIn("28 个 ASIN", result.stdout)
        return self.tmp / "sample_category_export.normalized.json"

    def test_market_metrics_baseline(self):
        normalized = self.normalize_sample()
        result = run(MARKET, [str(normalized), "--bins", "10", "--top", "10", "--json"])
        self.assertEqual(result.returncode, 0)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["market"]["items"], 28)
        self.assertEqual(payload["market"]["total_monthly_sales"], 38680.0)
        self.assertEqual(payload["market"]["total_monthly_revenue"], 1527531.0)

    def test_market_metrics_missing_field_exit_2(self):
        """items 字段不全时停止计算，不猜数（既有行为，exit 2）。"""
        broken = self.tmp / "broken.json"
        broken.write_text(
            json.dumps(
                {
                    "meta": {"item_count": 1},
                    "items": [
                        {
                            "asin": "B0X",
                            "title": "T",
                            "brand": "B",
                            "seller": "S",
                            "price": 1.0,
                            "monthly_sales": 1.0,
                            "monthly_revenue": 1.0,
                            "reviews": 1,
                            "rating": 4.0,
                            "bsr": 1,
                            "attributes": ["a"],
                        }
                    ],
                    "warnings": [],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        result = run(MARKET, [str(broken), "--json"])
        self.assertEqual(result.returncode, 2)
        self.assertIn("以下商品字段不完整，已停止计算（不猜测）", result.stdout)
        self.assertIn("B0X 缺少/非法字段：fulfillment", result.stdout)

    def test_market_metrics_same_price_zero_sales_warns(self):
        """#13：同价且总销量 0 不再除零崩溃，转业务告警且价带置空。"""
        data = self.tmp / "zero.json"
        data.write_text(
            json.dumps(
                {
                    "meta": {"item_count": 2},
                    "items": [
                        {"asin": "B0A", "title": "T", "brand": "B", "seller": "S", "price": 10.0,
                         "monthly_sales": 0, "monthly_revenue": 0, "reviews": 0, "rating": 4.0,
                         "bsr": 1, "fulfillment": "FBA", "attributes": []},
                        {"asin": "B0B", "title": "U", "brand": "B", "seller": "S", "price": 10.0,
                         "monthly_sales": 0, "monthly_revenue": 0, "reviews": 0, "rating": 4.0,
                         "bsr": 2, "fulfillment": "FBA", "attributes": []},
                    ],
                    "warnings": [],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        result = run(MARKET, [str(data), "--json"])
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stderr, "")
        payload = json.loads(result.stdout)
        self.assertEqual(payload["meta"]["status"], "WARNING")
        self.assertEqual(payload["price_bands"], [])
        self.assertIn("同价样本且总月销量为 0", payload["meta"]["warnings"][0])

    def test_opportunity_score_baseline(self):
        target = self.tmp / "sample_category_export.csv"
        target.write_text(SAMPLE.read_text(encoding="utf-8"), encoding="utf-8")
        result = run(
            OPPORTUNITY,
            ["--file", str(target), "--factory-cost-usd", "6.5", "--target-price", "34.99", "--json"],
        )
        self.assertEqual(result.returncode, 0)
        payload = json.loads(result.stdout)
        summary = payload["summary"]
        self.assertEqual(summary["verdict_counts"], {"Go": 10, "Watch": 15, "No-Go": 3})
        self.assertEqual(summary["dimension_averages"], {"demand": 70.0, "competition": 51.0,
                                                         "profit": 100.0, "compliance": 60.0,
                                                         "supply": 60.0})
        self.assertEqual(summary["top3"][0]["asin"], "B0GREENTECH")
        self.assertEqual(summary["top3"][0]["score"], 80.5)
        self.assertEqual(summary["entry_price_band"]["low"], 23.24)
        self.assertEqual(summary["entry_price_band"]["high"], 27.74)
        self.assertEqual(summary["entry_price_band"]["basis"], "Go 候选价格 P25–P75")


if __name__ == "__main__":
    unittest.main()
