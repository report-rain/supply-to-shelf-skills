"""04 Listing Agent 行为测试（claim_scan.py / listing_lint.py）。

覆盖本批有意差异：#6 非 UTF-8 输入明确报错 exit 2、#7 A+ 模块顺序校验；
以及规则表边界：字符上限 80/81、Item Name 75/76、后台词 250 字节、A+ 顺序、
否定语境（not waterproof 仍按关键词级命中）、TikTok 9 项检查。

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
AGENT = ROOT / "Agents" / "04_Listing_Agent"
CLAIM = AGENT / "scripts" / "claim_scan.py"
LINT = AGENT / "scripts" / "listing_lint.py"
EXAMPLES = AGENT / "examples"

ENV = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUTF8="1")


def run(script, args):
    return subprocess.run(
        [sys.executable, str(script)] + args,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=ENV,
    )


def claim(args):
    return run(CLAIM, args)


def lint(path, platform, as_json=True):
    args = ["--file", str(path), "--platform", platform]
    if as_json:
        args.append("--json")
    return run(LINT, args)


AMAZON = {
    "brand": "NordPulse",
    "title": "NordPulse Insulated Tumbler 16 oz Stainless Steel Cup for Coffee and Tea",
    "item_name": "NordPulse Insulated Tumbler 16 oz",
    "item_highlights": "Stainless Steel Cup for Coffee and Tea",
    "short_description": "A compact tumbler for daily coffee.",
    "description": "A compact tumbler for daily coffee. Keeps drinks warm on short commutes.",
    "bullets": [
        "Double-wall steel body keeps drinks warm for about 2 hours.",
        "Snap-on lid seals tight so the bag stays dry.",
        "Fits most car cup holders and backpack side pockets.",
        "Dishwasher-safe top rack; hand wash the body.",
        "Ships with a straw and a cleaning brush.",
    ],
    "backend_search_terms": "insulated tumbler steel cup coffee tea travel",
    "aplus_modules": [
        "Hero: NordPulse tumbler",
        "Why you will like it: keeps temperature",
        "How to use: fill and seal",
        "Details: 16 oz stainless steel",
        "In the box: tumbler, straw, brush",
    ],
    "product_attributes": {"ip_rating": "none"},
}

TIKTOK = {
    "brand": "NordPulse",
    "title": "NordPulse Insulated Tumbler 16 oz Stainless Steel Cup for Coffee",
    "short_description": "A compact tumbler for daily coffee, tea and iced drinks.",
    "bullets": [
        "Double-wall steel body keeps drinks warm for about 2 hours.",
        "Snap-on lid seals tight so the bag stays dry.",
    ],
    "product_attributes": {"ip_rating": "IPX4"},
}

ALL_TERMS_TEXT = (
    "FDA approved formula. It cures and treats and prevents illness. Clinically proven. "
    "Doctor recommended. Medical grade. 100% safe. Best pick. #1 rank. Non-toxic. "
    "Eco-friendly. Biodegradable. Antibacterial. Waterproof. Instantly. Permanent. "
    "Guaranteed. Premium. Professional. Advanced. Innovative."
)


class TempJson(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def write(self, name, payload):
        path = self.tmp / name
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        return path

    def write_bytes(self, name, content):
        path = self.tmp / name
        path.write_bytes(content)
        return path


class ClaimScanTests(TempJson):
    def test_example_is_clean(self):
        result = claim(["--file", str(EXAMPLES / "copy.txt"), "--json"])
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stderr, "")
        payload = json.loads(result.stdout)
        self.assertEqual(payload["verdict"], "PASS")
        self.assertEqual(payload["hits"], [])
        self.assertEqual(payload["counts"], {"HIGH": 0, "MEDIUM": 0, "LOW": 0})
        self.assertEqual(payload["char_count"], 1401)

    def test_all_22_rules(self):
        result = claim(["--text", ALL_TERMS_TEXT, "--json"])
        self.assertEqual(result.returncode, 1)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["verdict"], "FAIL")
        self.assertEqual(payload["counts"], {"HIGH": 16, "MEDIUM": 2, "LOW": 4})
        terms = [hit["term"] for hit in payload["hits"]]
        self.assertEqual(len(terms), 22)
        self.assertEqual(
            set(terms),
            {
                "fda approved", "cures", "treats", "prevents", "clinically proven",
                "doctor recommended", "medical grade", "100%", "best", "#1",
                "non-toxic", "eco-friendly", "biodegradable", "antibacterial",
                "waterproof", "instantly", "permanent", "guaranteed", "premium",
                "professional", "advanced", "innovative",
            },
        )

    def test_waterproof_downgraded_with_ip_rating(self):
        result = claim(["--text", "This bottle is waterproof.", "--ip-rating", "IPX4", "--json"])
        self.assertEqual(result.returncode, 0)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["verdict"], "WARN")
        self.assertEqual(payload["ip_rating"], "IPX4")
        hit = payload["hits"][0]
        self.assertEqual(hit["term"], "waterproof")
        self.assertEqual(hit["risk"], "MEDIUM")
        self.assertIn("已声明 IP 等级 IPX4", hit["reason"])

    def test_waterproof_high_without_rating(self):
        for rating in ("", "none", "n/a", "no"):
            result = claim(["--text", "This bottle is waterproof.", "--ip-rating", rating, "--json"])
            self.assertEqual(result.returncode, 1, rating)
            payload = json.loads(result.stdout)
            self.assertEqual(payload["hits"][0]["risk"], "HIGH", rating)

    def test_ip_rating_zero_counts_as_declared(self):
        """`--ip-rating 0` 在 claim_scan 里按“已声明”处理（基线一致），降为 MEDIUM。"""
        result = claim(["--text", "This bottle is waterproof.", "--ip-rating", "0", "--json"])
        self.assertEqual(result.returncode, 0)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["verdict"], "WARN")
        self.assertEqual(payload["hits"][0]["risk"], "MEDIUM")

    def test_negation_is_still_a_keyword_hit(self):
        """否定语境按关键词级记录：`not waterproof` 仍命中 waterproof（与基线一致）。"""
        result = claim(["--text", "This cup is not waterproof.", "--json"])
        self.assertEqual(result.returncode, 1)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["verdict"], "FAIL")
        self.assertEqual([hit["term"] for hit in payload["hits"]], ["waterproof"])

    def test_hyphen_and_space_interchange(self):
        for text in ("eco friendly bottle", "eco-friendly bottle"):
            payload = json.loads(claim(["--text", text, "--json"]).stdout)
            self.assertEqual([hit["term"] for hit in payload["hits"]], ["eco-friendly"])
        for text in ("clinically proven", "clinically-proven"):
            payload = json.loads(claim(["--text", text, "--json"]).stdout)
            self.assertEqual([hit["term"] for hit in payload["hits"]], ["clinically proven"])

    def test_repeated_terms_counted(self):
        payload = json.loads(claim(["--text", "premium cup, premium lid, premium straw", "--json"]).stdout)
        self.assertEqual(payload["hits"][0]["count"], 3)

    def test_human_text_header(self):
        result = claim(["--text", "premium cup"])
        self.assertEqual(result.returncode, 0)
        lines = result.stdout.splitlines()
        self.assertEqual(lines[0], "FTC / FDA 声明扫描")
        self.assertIn("IP 等级: none", lines[1])
        self.assertIn("[LOW] premium ×1", result.stdout)
        self.assertIn("总判定: WARN (HIGH 0 / MEDIUM 0 / LOW 1)", result.stdout)

    def test_missing_file(self):
        result = claim(["--file", str(self.tmp / "nope.txt"), "--json"])
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stderr, "")
        payload = json.loads(result.stdout)
        self.assertEqual(payload["status"], "INPUT_MISSING")
        self.assertEqual(payload["missing"], ["file"])

    def test_file_and_text_conflict(self):
        result = claim(["--file", str(EXAMPLES / "copy.txt"), "--text", "hi", "--json"])
        self.assertEqual(result.returncode, 2)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["status"], "INPUT_MISSING")
        self.assertEqual(payload["missing"], ["file|text"])

    def test_empty_text_treated_as_missing(self):
        result = claim(["--text", "", "--json"])
        self.assertEqual(result.returncode, 2)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["status"], "INPUT_MISSING")
        self.assertEqual(payload["missing"], ["file|text"])

    def test_non_utf8_file_exit_2(self):
        """#6 / 04 解码失败明确报错，不再抛 UnicodeDecodeError。"""
        path = self.write_bytes("gbk.txt", "未编码文本".encode("gbk"))
        result = claim(["--file", str(path), "--json"])
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stderr, "")
        payload = json.loads(result.stdout)
        self.assertEqual(payload["status"], "INPUT_ERROR")
        self.assertNotIn("missing", payload)
        self.assertIn("文件不是 UTF-8 文本", payload["message"])


class ListingLintAmazonTests(TempJson):
    def payload(self, **changes):
        data = dict(AMAZON)
        data.update(changes)
        return data

    def test_example_passes(self):
        result = lint(EXAMPLES / "listing_input.json", "amazon_us")
        self.assertEqual(result.returncode, 0)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["verdict"], "PASS")
        self.assertEqual(payload["counts"], {"PASS": 30, "WARN": 0, "FAIL": 0})
        self.assertEqual(payload["meta"]["title_limit"], 200)
        self.assertEqual(payload["meta"]["title_split"]["item_name_max"], 75)

    def test_title_79_warn_and_80_pass(self):
        """下限 80：79 字符 WARN，80 字符 PASS（未拆分时另有 TITLE_SPLIT_REQUIRED 提示）。"""
        short = ("NordPulse cup " + "x" * 100)[:79]
        payload = json.loads(lint(self.write("t79.json", self.payload(
            title=short, item_name="", item_highlights="")), "amazon_us").stdout)
        codes = [(item["level"], item["code"]) for item in payload["findings"]]
        self.assertIn(("WARN", "TITLE_TOO_SHORT"), codes)

        exact = ("NordPulse cup " + "x" * 100)[:80]
        payload = json.loads(lint(self.write("t80.json", self.payload(
            title=exact, item_name="", item_highlights="")), "amazon_us").stdout)
        codes = [(item["level"], item["code"]) for item in payload["findings"]]
        self.assertIn(("PASS", "TITLE_LENGTH"), codes)
        self.assertNotIn(("WARN", "TITLE_TOO_SHORT"), codes)

    def test_title_200_pass_201_fail(self):
        exact = ("NordPulse tumbler " + "cup " * 60)[:200]
        payload = json.loads(lint(self.write("t200.json", self.payload(
            title=exact, item_name="", item_highlights="")), "amazon_us").stdout)
        codes = [(item["level"], item["code"]) for item in payload["findings"]]
        self.assertIn(("PASS", "TITLE_LENGTH"), codes)

        over = ("NordPulse tumbler " + "cup " * 60)[:201]
        result = lint(self.write("t201.json", self.payload(
            title=over, item_name="", item_highlights="")), "amazon_us")
        self.assertEqual(result.returncode, 1)
        payload = json.loads(result.stdout)
        failed = [item["code"] for item in payload["findings"] if item["level"] == "FAIL"]
        self.assertIn("TITLE_TOO_LONG", failed)

    def test_item_name_75_and_76(self):
        ok = ("NordPulse Insulated Tumbler " + "x" * 60)[:75]
        payload = json.loads(lint(self.write("n75.json", self.payload(
            item_name=ok, item_highlights=ok[:100])), "amazon_us").stdout)
        codes = [item["code"] for item in payload["findings"] if item["level"] == "PASS"]
        self.assertIn("ITEM_NAME_LENGTH", codes)

        over = ("NordPulse Insulated Tumbler " + "x" * 60)[:76]
        result = lint(self.write("n76.json", self.payload(
            item_name=over, item_highlights=ok[:100])), "amazon_us")
        self.assertEqual(result.returncode, 1)
        payload = json.loads(result.stdout)
        self.assertIn("ITEM_NAME_TOO_LONG",
                      [item["code"] for item in payload["findings"] if item["level"] == "FAIL"])

    def test_item_highlights_125_and_126(self):
        ok = ("Stainless Steel Cup with Lid and Straw " + "x" * 120)[:125]
        payload = json.loads(lint(self.write("h125.json", self.payload(
            item_highlights=ok)), "amazon_us").stdout)
        self.assertIn("ITEM_HIGHLIGHTS_LENGTH",
                      [item["code"] for item in payload["findings"] if item["level"] == "PASS"])

        over = ("Stainless Steel Cup with Lid and Straw " + "x" * 120)[:126]
        result = lint(self.write("h126.json", self.payload(item_highlights=over)), "amazon_us")
        self.assertEqual(result.returncode, 1)
        payload = json.loads(result.stdout)
        self.assertIn("ITEM_HIGHLIGHTS_TOO_LONG",
                      [item["code"] for item in payload["findings"] if item["level"] == "FAIL"])

    def test_backend_230_warn_251_fail(self):
        warn = ("word " * 50)[:231]
        payload = json.loads(lint(self.write("b231.json", self.payload(
            backend_search_terms=warn)), "amazon_us").stdout)
        self.assertEqual(payload["verdict"], "WARN")
        self.assertIn("BACKEND_NEAR_LIMIT",
                      [item["code"] for item in payload["findings"] if item["level"] == "WARN"])

        over = ("word " * 60)[:251]
        result = lint(self.write("b251.json", self.payload(backend_search_terms=over)), "amazon_us")
        self.assertEqual(result.returncode, 1)
        payload = json.loads(result.stdout)
        self.assertIn("BACKEND_TOO_LONG",
                      [item["code"] for item in payload["findings"] if item["level"] == "FAIL"])

    def test_aplus_in_order_passes(self):
        result = lint(self.write("aplus_ok.json", self.payload()), "amazon_us")
        self.assertEqual(result.returncode, 0)
        payload = json.loads(result.stdout)
        self.assertNotIn("APLUS_ORDER",
                         [item["code"] for item in payload["findings"]])

    def test_aplus_out_of_order_fails(self):
        """#7：A+ 模块顺序异常时新增 FAIL APLUS_ORDER。"""
        result = lint(self.write("aplus_rev.json", self.payload(
            aplus_modules=list(reversed(AMAZON["aplus_modules"])))), "amazon_us")
        self.assertEqual(result.returncode, 1)
        payload = json.loads(result.stdout)
        failed = [(item["code"], item["message"]) for item in payload["findings"]
                  if item["level"] == "FAIL"]
        self.assertEqual(failed[0][0], "APLUS_ORDER")
        self.assertIn("A+ 模块顺序异常", failed[0][1])

    def test_aplus_missing_hero_fails(self):
        result = lint(self.write("aplus_nohero.json", self.payload(
            aplus_modules=AMAZON["aplus_modules"][1:])), "amazon_us")
        self.assertEqual(result.returncode, 1)
        payload = json.loads(result.stdout)
        self.assertIn("APLUS_ORDER",
                      [item["code"] for item in payload["findings"] if item["level"] == "FAIL"])

    def test_ip_conflict_waterproof_without_rating(self):
        result = lint(self.write("ipconf.json", self.payload(
            title="NordPulse Waterproof Insulated Tumbler 16 oz Stainless Steel Cup for Coffee")),
            "amazon_us")
        self.assertEqual(result.returncode, 1)
        payload = json.loads(result.stdout)
        conflicts = [item for item in payload["findings"] if item["code"] == "CLAIM_IP_CONFLICT"]
        self.assertTrue(conflicts)
        self.assertIn("Waterproof", conflicts[0]["message"])

    def test_ip_declared_skips_conflict(self):
        payload = json.loads(lint(self.write("ipok.json", self.payload(
            title="NordPulse Waterproof Insulated Tumbler 16 oz Stainless Steel Cup for Coffee",
            product_attributes={"ip_rating": "IPX4"})), "amazon_us").stdout)
        self.assertIn("IP_RATING_DECLARED",
                      [item["code"] for item in payload["findings"] if item["level"] == "PASS"])

    def test_missing_file(self):
        result = lint(self.tmp / "nope.json", "amazon_us")
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stderr, "")
        payload = json.loads(result.stdout)
        self.assertEqual(payload["status"], "INPUT_MISSING")
        self.assertEqual(payload["missing"], ["file"])

    def test_missing_fields(self):
        result = lint(self.write("missing.json", {"brand": "B", "title": "T"}), "amazon_us")
        self.assertEqual(result.returncode, 2)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["status"], "INPUT_MISSING")
        self.assertEqual(payload["missing"],
                         ["bullets", "description", "backend_search_terms", "aplus_modules"])

    def test_top_level_not_object(self):
        result = lint(self.write("array.json", []), "amazon_us")
        self.assertEqual(result.returncode, 2)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["status"], "INPUT_MISSING")
        self.assertEqual(payload["missing"], ["object"])

    def test_non_utf8_file_exit_2(self):
        """#6：解码失败明确报错 exit 2，stdout 为 JSON，stderr 为空。"""
        path = self.write_bytes("gbk.json", json.dumps(
            AMAZON, ensure_ascii=False).encode("utf-8") + b"\xff\xfe")
        result = lint(path, "amazon_us")
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stderr, "")
        payload = json.loads(result.stdout)
        self.assertEqual(payload["status"], "INPUT_ERROR")
        self.assertNotIn("missing", payload)
        self.assertIn("文件不是 UTF-8 文本", payload["message"])

    def test_human_text_output(self):
        result = lint(EXAMPLES / "listing_input.json", "amazon_us", as_json=False)
        self.assertEqual(result.returncode, 0)
        lines = result.stdout.splitlines()
        self.assertEqual(lines[0], "Amazon US Listing 自检")
        self.assertIn("总判定: PASS (FAIL 0 / WARN 0 / PASS 30)", result.stdout)
        self.assertIn("口径: 编写时公开口径，发布前按卖家中心复核。", result.stdout)


class ListingLintTiktokTests(TempJson):
    def payload(self, **changes):
        data = dict(TIKTOK)
        data.update(changes)
        return data

    def test_example_nine_checks(self):
        result = lint(EXAMPLES / "listing_input.json", "tiktok_us")
        self.assertEqual(result.returncode, 0)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["verdict"], "PASS")
        self.assertEqual(payload["counts"], {"PASS": 9, "WARN": 0, "FAIL": 0})
        codes = [item["code"] for item in payload["findings"]]
        self.assertEqual(codes, [
            "TITLE_LENGTH",
            "TITLE_WORDING",
            "TITLE_SPECIAL_CHARS",
            "TITLE_CASE",
            "TITLE_REPEAT",
            "DESC_PROMO",
            "APLUS_PRESENT",
            "TIKTOK_DESC_LENGTH",
            "CLAIM_IP_CONSISTENT",
        ])

    def test_short_description_500_and_501(self):
        ok = ("A compact tumbler for daily coffee. " * 30)[:500]
        payload = json.loads(lint(self.write("tt500.json", self.payload(
            short_description=ok)), "tiktok_us").stdout)
        self.assertIn("TIKTOK_DESC_LENGTH",
                      [item["code"] for item in payload["findings"] if item["level"] == "PASS"])

        over = ("A compact tumbler for daily coffee. " * 30)[:501]
        result = lint(self.write("tt501.json", self.payload(short_description=over)), "tiktok_us")
        self.assertEqual(result.returncode, 1)
        payload = json.loads(result.stdout)
        self.assertIn("TIKTOK_DESC_TOO_LONG",
                      [item["code"] for item in payload["findings"] if item["level"] == "FAIL"])

    def test_price_symbol_and_evasion(self):
        result = lint(self.write("ttbad.json", self.payload(
            short_description="Only $19.99 today. Link in bio for the shop.")), "tiktok_us")
        self.assertEqual(result.returncode, 1)
        payload = json.loads(result.stdout)
        failed = [item["code"] for item in payload["findings"] if item["level"] == "FAIL"]
        self.assertIn("TIKTOK_PRICE_IN_COPY", failed)
        self.assertIn("TIKTOK_EVASION", failed)

    def test_title_evasion(self):
        result = lint(self.write("tttitle.json", self.payload(
            title="NordPulse Tumbler - link in bio for price")), "tiktok_us")
        self.assertEqual(result.returncode, 1)
        payload = json.loads(result.stdout)
        self.assertIn("TIKTOK_EVASION",
                      [item["code"] for item in payload["findings"] if item["level"] == "FAIL"])

    def test_missing_description_field(self):
        result = lint(self.write("ttmissing.json", {"title": "NordPulse Tumbler"}), "tiktok_us")
        self.assertEqual(result.returncode, 2)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["missing"], ["description/short_description"])


if __name__ == "__main__":
    unittest.main()
