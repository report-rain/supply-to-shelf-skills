"""05 Creative Agent 行为测试（asset_check.py）。

覆盖本批有意差异：#2 缺文件/不可读 exit 2、#3 损坏图/0 尺寸/不可解码 → 明确状态码 + exit 2；
像素类用例依赖可选 Pillow，缺失时跳过。

    python -m unittest discover -s tests -v
"""

import contextlib
import importlib.util
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "Agents" / "05_Creative_Agent" / "scripts" / "asset_check.py"
SPEC = ROOT / "Agents" / "05_Creative_Agent" / "examples" / "video_spec.json"

ENV = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUTF8="1")

try:
    from PIL import Image, ImageDraw

    PILLOW_OK = True
except ImportError:
    PILLOW_OK = False


def run(args):
    return subprocess.run(
        [sys.executable, str(SCRIPT)] + args,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=ENV,
    )


def load_module():
    spec = importlib.util.spec_from_file_location("asset_check", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class CreativeTestBase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def write_json(self, name, payload):
        path = self.tmp / name
        path.write_text(json.dumps(payload), encoding="utf-8")
        return path

    def make_image(self, name, size, box, fill=(200, 200, 200)):
        path = self.tmp / name
        canvas = Image.new("RGB", size, (255, 255, 255))
        if box:
            ImageDraw.Draw(canvas).rectangle(box, fill=fill)
        canvas.save(path)
        return path


VIDEO = {
    "width": 1080,
    "height": 1920,
    "duration_sec": 30,
    "fps": 30,
    "format": "mp4",
    "has_subtitles": True,
    "first_frame_product": True,
    "aspect_ratio": "9:16",
}


class InputErrorTests(CreativeTestBase):
    def test_missing_image_exit_2(self):
        """#2：缺图片退出码由 1 改为 2；输出仍为单条 FILE_NOT_FOUND。"""
        result = run(["no-such.png", "--platform", "amazon_us", "--json"])
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stderr, "")
        payload = json.loads(result.stdout)
        self.assertNotIn("missing", payload)
        self.assertEqual(payload["counts"], {"PASS": 0, "WARN": 0, "FAIL": 1})
        self.assertEqual(payload["findings"][0]["code"], "FILE_NOT_FOUND")
        self.assertEqual(payload["manual_checks"], [])

    def test_corrupt_image_exit_2_without_traceback(self):
        """#3：损坏图给明确状态码 + exit 2，不抛 traceback。"""
        path = self.tmp / "broken.png"
        path.write_text("not an image", encoding="utf-8")
        result = run([str(path), "--platform", "amazon_us", "--json"])
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stderr, "")
        payload = json.loads(result.stdout)
        self.assertEqual(payload["status"], "INPUT_ERROR")
        self.assertIn("图片无法解码", payload["message"])

    def test_zero_dimension_image_exit_2(self):
        """#3：0 尺寸图片走 INPUT_ERROR + exit 2（进程内模拟解码结果）。"""

        class FakeImage:
            mode = "RGB"
            size = (0, 0)

            def convert(self, mode):
                return self

            @classmethod
            def open(cls, path):
                return cls()

            @staticmethod
            def new(size, color):
                return FakeImage()

        module = load_module()
        buffer = io.StringIO()
        with mock.patch.object(module, "Image", FakeImage):
            with contextlib.redirect_stdout(buffer):
                with self.assertRaises(SystemExit) as caught:
                    module.load_rgb("fake.png", True)
        self.assertEqual(caught.exception.code, 2)
        payload = json.loads(buffer.getvalue())
        self.assertEqual(payload["status"], "INPUT_ERROR")
        self.assertIn("图片尺寸非法（0 像素）", payload["message"])

    def test_no_input_exit_2(self):
        result = run(["--platform", "amazon_us", "--json"])
        self.assertEqual(result.returncode, 2)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["status"], "INPUT_MISSING")
        self.assertIn("缺少 <image> 或 --spec", payload["message"])

    def test_zero_height_video_exit_2(self):
        """#3：视频 0 高度不再抛 ZeroDivisionError。"""
        spec = self.write_json("zero.json", dict(VIDEO, height=0))
        result = run(["--spec", str(spec), "--platform", "tiktok_us", "--json"])
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stderr, "")
        payload = json.loads(result.stdout)
        self.assertEqual(payload["status"], "INPUT_ERROR")
        self.assertIn("视频尺寸非法", payload["message"])

    def test_invalid_numeric_video_exit_2(self):
        """#12：数值字段非法不再 traceback，统一 INPUT_ERROR + exit 2。"""
        spec = self.write_json("badnum.json", dict(VIDEO, width="abc"))
        result = run(["--spec", str(spec), "--platform", "tiktok_us", "--json"])
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stderr, "")
        payload = json.loads(result.stdout)
        self.assertEqual(payload["status"], "INPUT_ERROR")
        self.assertIn("视频数值字段非法：width='abc'", payload["message"])

    def test_corrupt_json_status_input_error(self):
        """#12：JSON 语法损坏统一为 INPUT_ERROR（旧实现为 INPUT_MISSING）。"""
        path = self.tmp / "broken.json"
        path.write_text("{bad json", encoding="utf-8")
        result = run(["--spec", str(path), "--platform", "tiktok_us", "--json"])
        self.assertEqual(result.returncode, 2)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["status"], "INPUT_ERROR")
        self.assertIn("JSON 解析失败", payload["message"])

    def test_unreadable_encoding_exit_2(self):
        """#12：非 UTF-8 编码文件给明确错误，不再抛 UnicodeDecodeError。"""
        path = self.tmp / "gbk.json"
        path.write_bytes(b'{"width":1080}\xff\xfe')
        result = run(["--spec", str(path), "--platform", "tiktok_us", "--json"])
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stderr, "")
        payload = json.loads(result.stdout)
        self.assertEqual(payload["status"], "INPUT_ERROR")
        self.assertIn("文件编码不可读", payload["message"])

    def test_fix_same_path_rejected(self):
        """#14：--fix 指向原图时拒绝覆盖，exit 2。"""
        path = self.tmp / "same.png"
        path.write_bytes(b"")
        result = run([str(path), "--platform", "amazon_us", "--fix", str(path), "--json"])
        self.assertEqual(result.returncode, 2)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["status"], "INPUT_ERROR")
        self.assertIn("--fix 输出路径不能与原图相同", payload["message"])
        self.assertEqual(path.read_bytes(), b"")


class VideoTests(CreativeTestBase):
    def test_tiktok_spec_pass_with_manual_checks(self):
        result = run(["--spec", str(SPEC), "--platform", "tiktok_us", "--json"])
        self.assertEqual(result.returncode, 0)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["verdict"], "PASS")
        self.assertEqual(payload["counts"], {"PASS": 7, "WARN": 0, "FAIL": 0})
        self.assertEqual([item["code"] for item in payload["findings"]], [
            "VIDEO_ASPECT",
            "VIDEO_RESOLUTION",
            "VIDEO_DURATION",
            "VIDEO_FIRST_FRAME",
            "VIDEO_SUBTITLES",
            "VIDEO_FORMAT",
            "VIDEO_FPS",
        ])
        self.assertEqual(len(payload["manual_checks"]), 3)
        self.assertIsNone(payload["source_file"])
        self.assertIsNone(payload["meta"]["fix_scope"])
        self.assertEqual(payload["meta"]["image_limits"]["recommend_edge"], 1080)

    def test_amazon_rejects_9x16(self):
        result = run(["--spec", str(SPEC), "--platform", "amazon_us", "--json"])
        self.assertEqual(result.returncode, 1)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["counts"], {"PASS": 6, "WARN": 0, "FAIL": 1})
        failed = [item["code"] for item in payload["findings"] if item["level"] == "FAIL"]
        self.assertEqual(failed, ["VIDEO_ASPECT"])

    def test_low_resolution_fail(self):
        spec = self.write_json("low.json", dict(VIDEO, width=640, height=1136))
        result = run(["--spec", str(spec), "--platform", "tiktok_us", "--json"])
        self.assertEqual(result.returncode, 1)
        payload = json.loads(result.stdout)
        codes = [(item["level"], item["code"]) for item in payload["findings"]]
        self.assertIn(("FAIL", "VIDEO_RESOLUTION"), codes)

    def test_short_duration_fail(self):
        spec = self.write_json("short.json", dict(VIDEO, duration_sec=8))
        result = run(["--spec", str(spec), "--platform", "tiktok_us", "--json"])
        self.assertEqual(result.returncode, 1)
        payload = json.loads(result.stdout)
        failed = [item["code"] for item in payload["findings"] if item["level"] == "FAIL"]
        self.assertEqual(failed, ["VIDEO_DURATION"])

    def test_missing_spec_field_exit_2(self):
        spec = self.write_json("bad.json", {"width": 1080})
        result = run(["--spec", str(spec), "--platform", "tiktok_us", "--json"])
        self.assertEqual(result.returncode, 2)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["status"], "INPUT_MISSING")
        self.assertIn("缺少字段: height, duration_sec, fps, format", payload["message"])


@unittest.skipUnless(PILLOW_OK, "需要 Pillow（可选依赖）：pip install -r requirements.txt")
class ImageTests(CreativeTestBase):
    def test_blank_png_reports_too_small_and_subject_not_found(self):
        path = self.make_image("blank.png", (300, 300), None)
        result = run([str(path), "--platform", "amazon_us", "--json"])
        self.assertEqual(result.returncode, 1)
        payload = json.loads(result.stdout)
        codes = [item["code"] for item in payload["findings"] if item["level"] == "FAIL"]
        self.assertEqual(codes, ["IMAGE_TOO_SMALL", "SUBJECT_NOT_FOUND"])
        self.assertEqual(payload["counts"], {"PASS": 4, "WARN": 0, "FAIL": 2})

    def test_normal_png_all_pass(self):
        path = self.make_image("ok.png", (1600, 1600), (100, 100, 1500, 1500))
        result = run([str(path), "--platform", "amazon_us", "--json"])
        self.assertEqual(result.returncode, 0)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["verdict"], "PASS")
        self.assertEqual(payload["counts"], {"PASS": 6, "WARN": 0, "FAIL": 0})
        self.assertEqual(payload["source_file"], str(path))

    def test_subject_too_small(self):
        path = self.make_image("small.png", (1600, 1600), (200, 200, 1400, 1400))
        result = run([str(path), "--platform", "amazon_us", "--json"])
        self.assertEqual(result.returncode, 1)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["counts"], {"PASS": 5, "WARN": 0, "FAIL": 1})
        self.assertEqual(payload["findings"][-1]["code"], "SUBJECT_TOO_SMALL")
        self.assertIn("75.1%", payload["findings"][-1]["message"])

    def test_tiktok_800_warn_only(self):
        path = self.make_image("tt.png", (800, 800), (50, 50, 750, 750))
        result = run([str(path), "--platform", "tiktok_us", "--json"])
        self.assertEqual(result.returncode, 0)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["verdict"], "WARN")
        self.assertEqual(payload["counts"], {"PASS": 4, "WARN": 1, "FAIL": 0})

    def test_human_readable_lines(self):
        path = self.make_image("small.png", (1600, 1600), (200, 200, 1400, 1400))
        result = run([str(path), "--platform", "amazon_us"])
        self.assertEqual(result.returncode, 1)
        lines = result.stdout.splitlines()
        self.assertEqual(lines[0], "图片规格检查 · Amazon US")
        self.assertEqual(lines[1], "文件: {}".format(path))
        self.assertIn("[FAIL] SUBJECT_TOO_SMALL (image):", result.stdout)
        self.assertIn("总判定: FAIL (FAIL 1 / WARN 0 / PASS 5)", result.stdout)
        self.assertIn("口径: 编写时公开口径，发布前按卖家中心复核。", result.stdout)


if __name__ == "__main__":
    unittest.main()
