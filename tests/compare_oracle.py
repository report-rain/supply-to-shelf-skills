#!/usr/bin/env python3
"""新旧仓库对拍 harness（第二批起复用）。

用法：
    python tests/compare_oracle.py --old-repo ..\\supply-to-shelf-skills
    python tests/compare_oracle.py --old-repo ..\\supply-to-shelf-skills --agent 01

对拍口径：
- 退出码必须一致；
- stdout 若两侧都能解析为 JSON，则按 JSON 语义比较（忽略 key 顺序）；
- 否则按文本逐行比较（统一换行、去掉首尾空白）；
- 落盘产物（如 normalized.json）按 JSON 语义比较；
- 差异只有在 `intended`（#1–#14）里登记过才算 INTENDED_DIFF，否则记为 REGRESSION，
  进程以退出码 1 结束，提示修复而不是接受。
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
NEW_REPO = os.path.dirname(HERE)

ENV = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUTF8="1")

INTENDED = {
    "#1": "01 输入错误退出码 1→2",
    "#2": "05 缺文件/不可读退出码 1→2",
    "#3": "05 损坏图/0 尺寸/不可解码 → 明确状态码 + exit 2",
    "#4": "01 单行脏数据报行号列名并 exit 2",
    "#5": "01 NaN/Inf 显式校验",
    "#6": "04 解码失败明确报错 exit 2",
    "#7": "04 A+ 模块顺序校验",
    "#9": "07 新增 --fail-on-critical（默认关）",
    "#10": "08 --carrying-rate-pct 0–100 校验",
    "#11": "08 文档 4995/4335 以实算为准",
    "#12": "05 视频输入异常统一 INPUT_ERROR + exit 2，无 traceback",
    "#13": "01 market_metrics 同价零销量转 WARNING，价带置空",
    "#14": "05 --fix 指向原图时拒绝覆盖 exit 2",
}


def script_path(repo, rel):
    return os.path.join(repo, rel)


def run(repo, cwd, rel, args):
    proc = subprocess.run(
        [sys.executable, script_path(repo, rel)] + args,
        cwd=cwd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=ENV,
    )
    return proc.returncode, proc.stdout or "", proc.stderr or ""


def normalize_text(text, work):
    text = text.replace("\r\n", "\n").replace(work, "<WORK>")
    return "\n".join(line.rstrip() for line in text.strip().split("\n"))


def try_json(text):
    try:
        return json.loads(text)
    except ValueError:
        return None


def compare_stdout(old_out, new_out, old_work, new_work):
    old_json = try_json(old_out)
    new_json = try_json(new_out)
    if old_json is not None and new_json is not None:
        return old_json == new_json, "json"
    return normalize_text(old_out, old_work) == normalize_text(new_out, new_work), "text"


def compare_outputs(case, old_work, new_work):
    diffs = []
    for rel in case.get("outputs", []):
        old_file = os.path.join(old_work, rel)
        new_file = os.path.join(new_work, rel)
        if not os.path.isfile(old_file) or not os.path.isfile(new_file):
            if os.path.isfile(old_file) != os.path.isfile(new_file):
                diffs.append("产物 {} 仅一侧存在".format(rel))
            continue
        with open(old_file, "r", encoding="utf-8") as handle:
            old_data = json.load(handle)
        with open(new_file, "r", encoding="utf-8") as handle:
            new_data = json.load(handle)
        if old_data != new_data:
            diffs.append("产物 {} 语义不一致".format(rel))
    return diffs


def build_images(work):
    """生成图片样本；无 Pillow 返回 False。"""
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        return False
    samples = {
        "img_amz.png": ((1600, 1600), (200, 200, 1400, 1400)),
        "img_tt.png": ((800, 800), (50, 50, 750, 750)),
        "img_blank.png": ((300, 300), None),
        "img_ok.png": ((1600, 1600), (100, 100, 1500, 1500)),
        "img_aspect.png": ((1600, 1200), (144, 150, 1456, 1050)),
        "img_tt34.png": ((900, 1200), (50, 100, 850, 1100)),
    }
    for name, (size, box) in samples.items():
        canvas = Image.new("RGB", size, (255, 255, 255))
        if box:
            ImageDraw.Draw(canvas).rectangle(box, fill=(200, 200, 200))
        canvas.save(os.path.join(work, name))
    with open(os.path.join(work, "img_corrupt.png"), "w", encoding="utf-8") as handle:
        handle.write("not an image")
    return True


def write_video_specs(work):
    base = {
        "width": 1080,
        "height": 1920,
        "duration_sec": 30,
        "fps": 30,
        "format": "mp4",
        "has_subtitles": True,
        "first_frame_product": True,
        "aspect_ratio": "9:16",
    }
    specs = {
        "spec_base.json": base,
        "spec_lowres.json": dict(base, width=640, height=1136),
        "spec_noflags.json": dict(base, has_subtitles=False, first_frame_product=False),
        "spec_zero_h.json": dict(base, height=0),
        "spec_badnum.json": dict(base, width="abc"),
        "spec_bad.json": {"width": 1080},
        "spec_field.json": dict(base, aspect_ratio="0.75"),
    }
    for name, data in specs.items():
        with open(os.path.join(work, name), "w", encoding="utf-8") as handle:
            json.dump(data, handle)
    with open(os.path.join(work, "spec_syntax.json"), "w", encoding="utf-8") as handle:
        handle.write("{bad json")


SELECTION = "Agents/01_Selection_Agent"
CREATIVE = "Agents/05_Creative_Agent"

CASES = [
    {
        "id": "01-normalize 基准 28 行",
        "script": SELECTION + "/scripts/normalize_export.py",
        "args": ["sample_category_export.csv", "--attributes", "portable,usb"],
        "files": {"sample_category_export.csv": SELECTION + "/examples/sample_category_export.csv"},
        "outputs": ["sample_category_export.normalized.json"],
    },
    {
        "id": "01-normalize 空 CSV",
        "script": SELECTION + "/scripts/normalize_export.py",
        "args": ["empty.csv"],
        "make": {"empty.csv": ""},
        "intended": ["#1"],
    },
    {
        "id": "01-normalize 缺列",
        "script": SELECTION + "/scripts/normalize_export.py",
        "args": ["missing.csv"],
        "make": {"missing.csv": "asin,title,price\nB0X,T,1.00\n"},
        "intended": ["#1"],
    },
    {
        "id": "01-normalize 单行脏数据",
        "script": SELECTION + "/scripts/normalize_export.py",
        "args": ["dirty.csv"],
        "files": {"dirty.csv": SELECTION + "/examples/sample_category_export.csv"},
        "pre_edit": ("dirty.csv", ",29.99,4200,125958.00,", ",abc,4200,125958.00,"),
        "intended": ["#4"],
    },
    {
        "id": "01-normalize NaN",
        "script": SELECTION + "/scripts/normalize_export.py",
        "args": ["nan.csv"],
        "make": {
            "nan.csv": (
                "asin,title,brand,seller,price,monthly_sales,monthly_revenue,reviews,rating,bsr,fulfillment\n"
                "B0X,T,B,S,nan,100,1000.00,10,4.0,100,FBA\n"
            )
        },
        "intended": ["#1"],
    },
    {
        "id": "01-normalize Inf",
        "script": SELECTION + "/scripts/normalize_export.py",
        "args": ["inf.csv"],
        "make": {
            "inf.csv": (
                "asin,title,brand,seller,price,monthly_sales,monthly_revenue,reviews,rating,bsr,fulfillment\n"
                "B0X,T,B,S,inf,100,1000.00,10,4.0,100,FBA\n"
            )
        },
        "intended": ["#5"],
    },
    {
        "id": "01-normalize 负价",
        "script": SELECTION + "/scripts/normalize_export.py",
        "args": ["negative.csv"],
        "files": {"negative.csv": SELECTION + "/examples/sample_category_export.csv"},
        "pre_edit": ("negative.csv", ",29.99,4200,", ",-29.99,4200,"),
    },
    {
        "id": "01-normalize BOM+CRLF+空行",
        "script": SELECTION + "/scripts/normalize_export.py",
        "args": ["bomcrlf.csv"],
        "make_sig": {
            "bomcrlf.csv": (
                "asin,title,brand,seller,price,monthly_sales,monthly_revenue,"
                "reviews,rating,bsr,fulfillment\r\n"
                "B0X,T,B,S,29.99,100,2999.00,10,4.0,100,FBA\r\n\r\n"
            )
        },
        "outputs": ["bomcrlf.normalized.json"],
    },
    {
        "id": "01-market_metrics 基准",
        "script": SELECTION + "/scripts/normalize_export.py",
        "args": ["sample_category_export.csv", "--attributes", "portable,usb"],
        "files": {"sample_category_export.csv": SELECTION + "/examples/sample_category_export.csv"},
        "outputs": ["sample_category_export.normalized.json"],
        "then": [
            (SELECTION + "/scripts/market_metrics.py",
             ["sample_category_export.normalized.json", "--bins", "10", "--top", "10", "--json"]),
            (SELECTION + "/scripts/market_metrics.py",
             ["sample_category_export.normalized.json", "--bins", "10", "--top", "10"]),
        ],
    },
    {
        "id": "01-opportunity_score 基准",
        "script": SELECTION + "/scripts/opportunity_score.py",
        "args": ["--file", "sample_category_export.csv", "--factory-cost-usd", "6.5", "--target-price", "34.99"],
        "files": {"sample_category_export.csv": SELECTION + "/examples/sample_category_export.csv"},
        "then": [
            (SELECTION + "/scripts/opportunity_score.py",
             ["--file", "sample_category_export.csv", "--factory-cost-usd", "6.5", "--target-price", "34.99", "--json"]),
        ],
    },
    {
        "id": "01-market_metrics 缺字段",
        "script": SELECTION + "/scripts/market_metrics.py",
        "args": ["bad.json", "--bins", "10", "--top", "10", "--json"],
        "make": {
            "bad.json": json.dumps(
                {
                    "meta": {"item_count": 1},
                    "items": [{"asin": "B0X", "title": "T", "brand": "B", "seller": "S", "price": 1.0,
                               "monthly_sales": 1.0, "monthly_revenue": 1.0, "reviews": 1, "rating": 4.0,
                               "bsr": 1, "attributes": ["a"]}],
                    "warnings": [],
                },
                ensure_ascii=False,
            )
        },
    },
    {
        "id": "01-market_metrics 同价零销量",
        "script": SELECTION + "/scripts/market_metrics.py",
        "args": ["zero_sales.json", "--json"],
        "make": {
            "zero_sales.json": json.dumps(
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
            )
        },
        "intended": ["#13"],
    },
    {
        "id": "05 视频 TikTok 规范",
        "script": CREATIVE + "/scripts/asset_check.py",
        "args": ["--spec", "spec_base.json", "--platform", "tiktok_us", "--json"],
        "make_video": True,
    },
    {
        "id": "05 视频 Amazon 9:16",
        "script": CREATIVE + "/scripts/asset_check.py",
        "args": ["--spec", "spec_base.json", "--platform", "amazon_us", "--json"],
        "make_video": True,
    },
    {
        "id": "05 视频 低分辨率",
        "script": CREATIVE + "/scripts/asset_check.py",
        "args": ["--spec", "spec_lowres.json", "--platform", "tiktok_us", "--json"],
        "make_video": True,
    },
    {
        "id": "05 视频 首帧/字幕缺失",
        "script": CREATIVE + "/scripts/asset_check.py",
        "args": ["--spec", "spec_noflags.json", "--platform", "tiktok_us", "--json"],
        "make_video": True,
    },
    {
        "id": "05 视频 aspect 字段不一致",
        "script": CREATIVE + "/scripts/asset_check.py",
        "args": ["--spec", "spec_field.json", "--platform", "tiktok_us", "--json"],
        "make_video": True,
    },
    {
        "id": "05 视频 spec 缺字段",
        "script": CREATIVE + "/scripts/asset_check.py",
        "args": ["--spec", "spec_bad.json", "--platform", "tiktok_us", "--json"],
        "make_video": True,
    },
    {
        "id": "05 视频 数值字段非法",
        "script": CREATIVE + "/scripts/asset_check.py",
        "args": ["--spec", "spec_badnum.json", "--platform", "tiktok_us", "--json"],
        "make_video": True,
        "intended": ["#12"],
    },
    {
        "id": "05 视频 JSON 损坏",
        "script": CREATIVE + "/scripts/asset_check.py",
        "args": ["--spec", "spec_syntax.json", "--platform", "tiktok_us", "--json"],
        "make_video": True,
        "intended": ["#12"],
    },
    {
        "id": "05 视频 编码不可读",
        "script": CREATIVE + "/scripts/asset_check.py",
        "args": ["--spec", "spec_gbk.json", "--platform", "tiktok_us", "--json"],
        "make_bytes": {"spec_gbk.json": b'{"width":1080,"height":1920}\xff\xfe'},
        "intended": ["#12"],
    },
    {
        "id": "05 视频 0 高度",
        "script": CREATIVE + "/scripts/asset_check.py",
        "args": ["--spec", "spec_zero_h.json", "--platform", "tiktok_us", "--json"],
        "make_video": True,
        "intended": ["#3"],
    },
    {
        "id": "05 图片 Amazon 主体 75%",
        "script": CREATIVE + "/scripts/asset_check.py",
        "args": ["img_amz.png", "--platform", "amazon_us", "--json"],
        "make_image": True,
    },
    {
        "id": "05 图片 Amazon 人类可读",
        "script": CREATIVE + "/scripts/asset_check.py",
        "args": ["img_amz.png", "--platform", "amazon_us"],
        "make_image": True,
    },
    {
        "id": "05 图片 TikTok 800×800",
        "script": CREATIVE + "/scripts/asset_check.py",
        "args": ["img_tt.png", "--platform", "tiktok_us", "--json"],
        "make_image": True,
    },
    {
        "id": "05 图片 空白 300×300",
        "script": CREATIVE + "/scripts/asset_check.py",
        "args": ["img_blank.png", "--platform", "amazon_us", "--json"],
        "make_image": True,
    },
    {
        "id": "05 图片 非正方形",
        "script": CREATIVE + "/scripts/asset_check.py",
        "args": ["img_aspect.png", "--platform", "amazon_us", "--json"],
        "make_image": True,
    },
    {
        "id": "05 图片 TikTok 3:4",
        "script": CREATIVE + "/scripts/asset_check.py",
        "args": ["img_tt34.png", "--platform", "tiktok_us", "--json"],
        "make_image": True,
    },
    {
        "id": "05 图片 缺文件",
        "script": CREATIVE + "/scripts/asset_check.py",
        "args": ["no-such.png", "--platform", "amazon_us", "--json"],
        "make_image": True,
        "intended": ["#2"],
    },
    {
        "id": "05 图片 损坏文件",
        "script": CREATIVE + "/scripts/asset_check.py",
        "args": ["img_corrupt.png", "--platform", "amazon_us", "--json"],
        "make_image": True,
        "intended": ["#3"],
    },
    {
        "id": "05 --fix 重查",
        "script": CREATIVE + "/scripts/asset_check.py",
        "args": ["img_amz.png", "--platform", "amazon_us", "--fix", "fixed.png", "--json"],
        "make_image": True,
    },
    {
        "id": "05 --fix 指向原图",
        "script": CREATIVE + "/scripts/asset_check.py",
        "args": ["img_amz.png", "--platform", "amazon_us", "--fix", "img_amz.png", "--json"],
        "make_image": True,
        "intended": ["#14"],
    },
    {
        "id": "05 缺入参",
        "script": CREATIVE + "/scripts/asset_check.py",
        "args": ["--platform", "amazon_us", "--json"],
    },
    {
        "id": "05 image 与 spec 互斥",
        "script": CREATIVE + "/scripts/asset_check.py",
        "args": ["img_amz.png", "--spec", "spec_base.json", "--platform", "amazon_us", "--json"],
        "make_image": True,
        "make_video": True,
    },
]


def prepare(case, repo, work):
    os.makedirs(work, exist_ok=True)
    for rel, source in case.get("files", {}).items():
        target = os.path.join(work, rel)
        os.makedirs(os.path.dirname(target) or work, exist_ok=True)
        shutil.copyfile(os.path.join(repo, source), target)
    for rel, content in case.get("make", {}).items():
        with open(os.path.join(work, rel), "w", encoding="utf-8") as handle:
            handle.write(content)
    for rel, content in case.get("make_bytes", {}).items():
        with open(os.path.join(work, rel), "wb") as handle:
            handle.write(content)
    if case.get("pre_edit"):
        rel, old, new = case["pre_edit"]
        path = os.path.join(work, rel)
        with open(path, "r", encoding="utf-8") as handle:
            text = handle.read()
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(text.replace(old, new, 1))
    for rel, content in case.get("make_sig", {}).items():
        with open(os.path.join(work, rel), "w", encoding="utf-8-sig", newline="") as handle:
            handle.write(content)
    if case.get("make_image"):
        build_images(work)
    if case.get("make_video"):
        write_video_specs(work)


def execute(repo, case, work):
    code, out, err = run(repo, work, case["script"], case["args"])
    extra = []
    for rel, args in case.get("then", []):
        extra.append(run(repo, work, rel, args))
    return code, out, err, extra


def main():
    parser = argparse.ArgumentParser(description="新旧实现黑盒对拍")
    parser.add_argument("--old-repo", required=True, help="旧仓库根目录")
    parser.add_argument("--new-repo", default=NEW_REPO, help="新仓库根目录（默认按本文件位置推断）")
    parser.add_argument("--agent", help="只跑指定前缀的用例（01 / 05）")
    parser.add_argument("--keep", action="store_true", help="保留下拍临时目录")
    args = parser.parse_args()

    old_repo = os.path.abspath(args.old_repo)
    new_repo = os.path.abspath(args.new_repo)
    root = tempfile.mkdtemp(prefix="oracle_")

    rows = []
    failures = 0
    for case in CASES:
        if args.agent and not case["id"].startswith(args.agent):
            continue
        old_work = os.path.join(root, "case_{:02d}".format(len(rows) + 1), "old")
        new_work = os.path.join(root, "case_{:02d}".format(len(rows) + 1), "new")
        prepare(case, new_repo, old_work)
        prepare(case, new_repo, new_work)
        old_code, old_out, _, old_extra = execute(old_repo, case, old_work)
        new_code, new_out, _, new_extra = execute(new_repo, case, new_work)

        notes = []
        if old_code != new_code:
            notes.append("exit {}→{}".format(old_code, new_code))
        same, kind = compare_stdout(old_out, new_out, old_work, new_work)
        if not same:
            notes.append("{} 不一致".format(kind))
        notes.extend(compare_outputs(case, old_work, new_work))
        for index, (ocode, oout, _) in enumerate(old_extra):
            ncode, nout, _ = new_extra[index]
            if ocode != ncode:
                notes.append("附加 #{} exit {}→{}".format(index + 1, ocode, ncode))
            extra_same, extra_kind = compare_stdout(oout, nout, old_work, new_work)
            if not extra_same:
                notes.append("附加 #{} {} 不一致".format(index + 1, extra_kind))

        intended = case.get("intended", [])
        if not notes:
            verdict = "SAME"
        elif intended:
            verdict = "INTENDED_DIFF"
        else:
            verdict = "REGRESSION"
            failures += 1
        rows.append((case["id"], old_code, new_code, " / ".join(notes) or "-", verdict, ",".join(intended) or "-"))

    print("{:<28} {:>4} {:>4}  {:<40} {:<15} {}".format("用例", "旧", "新", "差异", "判定", "编号"))
    print("-" * 104)
    for row in rows:
        print("{:<28} {:>4} {:>4}  {:<40} {:<15} {}".format(*row))
    same_count = sum(1 for row in rows if row[4] == "SAME")
    intended_count = sum(1 for row in rows if row[4] == "INTENDED_DIFF")
    print("-" * 104)
    print("SAME {} / INTENDED_DIFF {} / REGRESSION {}".format(same_count, intended_count, failures))
    if intended_count:
        print("已登记差异：")
        for key, text in INTENDED.items():
            print("  {} {}".format(key, text))

    if not args.keep:
        shutil.rmtree(root, ignore_errors=True)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
