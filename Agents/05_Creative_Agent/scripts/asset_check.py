#!/usr/bin/env python3
"""05 创意素材规格校验：图片 / 视频规格确定性检查。

无外部配置；平台阈值与人工复核清单内嵌。图片像素项依赖可选 Pillow。
退出码：0=通过（可含 WARN）、1=存在 FAIL、2=输入缺失/不可读/参数错误。
"""

import argparse
import json
import os
import sys

try:
    from PIL import Image, ImageChops

    PILLOW_OK = True
except ImportError:  # 可选依赖：缺 Pillow 时降级为文件级检查
    Image = None
    ImageChops = None
    PILLOW_OK = False

RULES_BASIS = "编写时公开口径，发布前按卖家中心复核"
FIX_SCOPE = "近白拉纯白 + 补正方形画布，不做抠图"

RULES = {
    "amazon_us": {
        "label": "Amazon US",
        "formats": ("jpg", "jpeg", "png", "tif", "tiff", "gif"),
        "max_mb": 10,
        "upload_min_edge": 500,
        "zoom_min_edge": 1000,
        "recommend_edge": 1600,
        "square": "recommended",
        "check_white": True,
        "subject_fail": 0.80,
        "subject_warn": 0.85,
    },
    "tiktok_us": {
        "label": "TikTok Shop US",
        "formats": ("jpg", "jpeg", "png", "webp"),
        "max_mb": 5,
        "upload_min_edge": 800,
        "zoom_min_edge": 800,
        "recommend_edge": 1080,
        "square": "required",
        "check_white": False,
        "subject_fail": 0.60,
    },
}

MANUAL_IMAGE = {
    "amazon_us": [
        "主图不得出现文字、水印、边框、二维码、非售配件",
        "商品主体完整可见、不裁切不遮挡，占画面 ≥85%，颜色与实物一致",
        "背景为纯白 RGB(255,255,255)（脚本仅按边缘 2% 近白比例辅助判断，仍需目视复核）",
        "多角度/细节图不得复用主图，且不得出现平台官方标识",
    ],
    "tiktok_us": [
        "图内文字避开顶部 12%、底部 20%、右侧 8–12% 的 UI 遮挡区",
        "无未授权品牌 logo、二维码、站外联系方式",
        "封面完整展示产品，主体不被裁切",
    ],
}

MANUAL_VIDEO = {
    "amazon_us": [
        "字幕避开底部播放控件区域，字号在手机端可读",
        "首帧产品完整，无黑场或纯文字开场",
        "BGM/音效具备可商用授权",
    ],
    "tiktok_us": [
        "字幕落在安全区（距底 ≥20%、距顶 ≥12%，避开右侧 UI）",
        "首帧 0.5 秒内产品可识别，前 3 秒给出核心信息",
        "BGM/音效具备可商用授权，未使用未授权品牌音乐",
    ],
}

VIDEO_FIELDS = [
    "width",
    "height",
    "duration_sec",
    "fps",
    "format",
    "has_subtitles",
    "first_frame_product",
    "aspect_ratio",
]


def emit_error(status, message, as_json):
    """输入/解码错误：stdout 输出（stderr 为空），exit 2。"""
    payload = {"status": status, "message": message}
    if as_json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(message)
    raise SystemExit(2)


def video_number(spec, field, as_json, integer=False):
    """取视频数值字段；bool / 非数字 → INPUT_ERROR exit 2（#12）。"""
    value = spec[field]
    try:
        if isinstance(value, bool):
            raise ValueError("bool")
        return int(value) if integer else float(value)
    except (TypeError, ValueError):
        emit_error(
            "INPUT_ERROR",
            "[INPUT_ERROR] 视频数值字段非法：{}={!r}（必须为数字）".format(field, value),
            as_json,
        )
        raise AssertionError("unreachable")


def add(findings, level, code, field, message):
    findings.append({"level": level, "code": code, "field": field, "message": message})


def image_limits(platform):
    rules = RULES[platform]
    return {
        "upload_min_edge": rules["upload_min_edge"],
        "zoom_min_edge": rules["zoom_min_edge"],
        "recommend_edge": rules["recommend_edge"],
        "max_mb": rules["max_mb"],
        "square": rules["square"],
        "formats": list(rules["formats"]),
    }


def decode_error(path, as_json):
    emit_error(
        "INPUT_ERROR",
        "[INPUT_ERROR] 图片无法解码（文件损坏或非图片）: {}".format(path),
        as_json,
    )


def load_rgb(path, as_json):
    """读取为 RGB；动图标记与尺寸一并返回。解码失败 → INPUT_ERROR exit 2。"""
    try:
        opened = Image.open(path)
        animated = bool(getattr(opened, "is_animated", False))
        if opened.mode in ("RGBA", "LA", "P"):
            rgba = opened.convert("RGBA")
            canvas = Image.new("RGB", rgba.size, (255, 255, 255))
            canvas.paste(rgba, mask=rgba.split()[-1])
            rgb = canvas
        else:
            rgb = opened.convert("RGB")
    except (OSError, ValueError, SyntaxError, AttributeError):
        decode_error(path, as_json)
        raise AssertionError("unreachable")
    if rgb.size[0] <= 0 or rgb.size[1] <= 0:
        emit_error(
            "INPUT_ERROR",
            "[INPUT_ERROR] 图片尺寸非法（0 像素）: {}（{}x{}）".format(path, rgb.size[0], rgb.size[1]),
            as_json,
        )
    return rgb, animated


def edge_white_ratio(rgb):
    """四条边带（宽 max(1, round(min(w,h)*2%))）中三通道均 ≥240 的像素占比。"""
    width, height = rgb.size
    band = max(1, round(min(width, height) * 0.02))
    px = rgb.load()
    total = 0
    white = 0
    for y in range(band):
        for x in range(width):
            total += 1
            r, g, b = px[x, y]
            if r >= 240 and g >= 240 and b >= 240:
                white += 1
    for y in range(height - band, height):
        for x in range(width):
            total += 1
            r, g, b = px[x, y]
            if r >= 240 and g >= 240 and b >= 240:
                white += 1
    for x in range(band):
        for y in range(height):
            total += 1
            r, g, b = px[x, y]
            if r >= 240 and g >= 240 and b >= 240:
                white += 1
    for x in range(width - band, width):
        for y in range(height):
            total += 1
            r, g, b = px[x, y]
            if r >= 240 and g >= 240 and b >= 240:
                white += 1
    return white / total


def subject_ratio(rgb):
    """主体包围盒最长边 / 画面最长边；整图无主体返回 None。"""
    width, height = rgb.size
    diff = ImageChops.difference(rgb, Image.new("RGB", rgb.size, (255, 255, 255)))
    mask = diff.convert("L").point(lambda value: 255 if value > 15 else 0)
    bbox = mask.getbbox()
    if bbox is None:
        return None
    box_w = bbox[2] - bbox[0]
    box_h = bbox[3] - bbox[1]
    return max(box_w, box_h) / max(width, height)


def fix_image(source, dest, as_json):
    """近白拉纯白 + 补正方形白底画布（不抠图）。"""
    rgb, _ = load_rgb(source, as_json)
    width, height = rgb.size
    px = rgb.load()
    for y in range(height):
        for x in range(width):
            r, g, b = px[x, y]
            px[x, y] = (
                255 if r >= 240 else r,
                255 if g >= 240 else g,
                255 if b >= 240 else b,
            )
    side = max(width, height)
    canvas = Image.new("RGB", (side, side), (255, 255, 255))
    canvas.paste(rgb, ((side - width) // 2, (side - height) // 2))
    folder = os.path.dirname(os.path.abspath(dest))
    try:
        os.makedirs(folder, exist_ok=True)
        ext = dest.lower().rsplit(".", 1)[-1] if "." in os.path.basename(dest) else ""
        if ext in ("jpg", "jpeg"):
            canvas.save(dest, format="JPEG", quality=92)
        else:
            canvas.save(dest, format="PNG")
    except OSError:
        emit_error(
            "INPUT_ERROR",
            "[INPUT_ERROR] 修正图写入失败: {}".format(dest),
            as_json,
        )
    return side


def check_image(path, platform, as_json):
    """对已存在的图片做文件级与像素级检查，返回 findings。"""
    rules = RULES[platform]
    findings = []
    try:
        size_bytes = os.path.getsize(path)
    except OSError:
        emit_error(
            "INPUT_ERROR",
            "[INPUT_ERROR] 图片不可读: {}".format(path),
            as_json,
        )
    size_mb = size_bytes / (1024 * 1024)
    if size_mb > rules["max_mb"]:
        add(
            findings,
            "FAIL",
            "IMAGE_FILE_TOO_LARGE",
            "image",
            "文件 {:.2f} MB，超过 {} MB 上限".format(size_mb, rules["max_mb"]),
        )
    else:
        add(
            findings,
            "PASS",
            "IMAGE_FILE_SIZE",
            "image",
            "文件 {:.2f} MB，≤{} MB".format(size_mb, rules["max_mb"]),
        )

    ext = os.path.splitext(path)[1].lower().lstrip(".")
    if ext not in rules["formats"]:
        add(
            findings,
            "FAIL",
            "IMAGE_FORMAT",
            "image",
            "扩展名 .{} 不在允许格式内：{}".format(ext, " / ".join(rules["formats"])),
        )
    else:
        add(findings, "PASS", "IMAGE_FORMAT", "image", "格式 .{} 允许".format(ext))

    if not PILLOW_OK:
        add(
            findings,
            "WARN",
            "PILLOW_MISSING",
            "image",
            "Pillow 未安装，跳过尺寸/比例/白底/主体占比等像素项；安装后重跑",
        )
        return findings

    rgb, animated = load_rgb(path, as_json)
    width, height = rgb.size

    if animated:
        add(
            findings,
            "FAIL",
            "IMAGE_ANIMATED",
            "image",
            "检测到动图；Amazon/TikTok 商品图需静态图，封面请导出静态帧",
        )

    long_edge = max(width, height)
    if long_edge < rules["upload_min_edge"]:
        add(
            findings,
            "FAIL",
            "IMAGE_TOO_SMALL",
            "image",
            "分辨率 {}x{}，最长边 {} 低于可上传下限 {}".format(
                width, height, long_edge, rules["upload_min_edge"]
            ),
        )
    elif long_edge < rules["zoom_min_edge"]:
        add(
            findings,
            "WARN",
            "IMAGE_NO_ZOOM",
            "image",
            "分辨率 {}x{}，最长边 {} 未达 {}，无法启用放大镜".format(
                width, height, long_edge, rules["zoom_min_edge"]
            ),
        )
    elif long_edge < rules["recommend_edge"]:
        add(
            findings,
            "WARN",
            "IMAGE_BELOW_RECOMMENDED",
            "image",
            "分辨率 {}x{}，最长边 {} 低于推荐值 {}".format(
                width, height, long_edge, rules["recommend_edge"]
            ),
        )
    else:
        add(
            findings,
            "PASS",
            "IMAGE_SIZE",
            "image",
            "分辨率 {}x{}，最长边 {} ≥ 推荐值 {}".format(
                width, height, long_edge, rules["recommend_edge"]
            ),
        )

    ratio = width / float(height)
    if platform == "amazon_us":
        if abs(ratio - 1) > 0.01:
            add(
                findings,
                "WARN",
                "IMAGE_ASPECT",
                "image",
                "比例 {:.3f}，非正方形；Amazon 推荐 1:1，非正方形会裁切留白".format(ratio),
            )
        else:
            add(findings, "PASS", "IMAGE_ASPECT", "image", "比例 {:.3f}，1:1".format(ratio))
    else:
        if abs(ratio - 1) <= 0.01:
            add(
                findings,
                "PASS",
                "IMAGE_ASPECT",
                "image",
                "比例 {:.3f}，1:1 符合 800×800 要求".format(ratio),
            )
        elif abs(ratio - 0.75) <= 0.0075:
            add(findings, "PASS", "IMAGE_ASPECT", "image", "比例 {:.3f}，3:4 允许".format(ratio))
        else:
            add(
                findings,
                "FAIL",
                "IMAGE_ASPECT",
                "image",
                "比例 {:.3f}，TikTok Shop 商品图需 1:1（或允许的 3:4）".format(ratio),
            )

    if rules["check_white"]:
        white_ratio = edge_white_ratio(rgb)
        if white_ratio < 0.98:
            add(
                findings,
                "FAIL",
                "MAIN_EDGE_NOT_WHITE",
                "image",
                "边缘 2% 近白占比 {:.1f}%，低于 98%（主图需纯白背景）".format(white_ratio * 100),
            )
        else:
            add(
                findings,
                "PASS",
                "MAIN_EDGE_WHITE",
                "image",
                "边缘 2% 近白占比 {:.1f}%，≥98%".format(white_ratio * 100),
            )

    box_ratio = subject_ratio(rgb)
    if box_ratio is None:
        add(
            findings,
            "FAIL",
            "SUBJECT_NOT_FOUND",
            "image",
            "未检测到非白主体（整图接近纯白）",
        )
    elif platform == "amazon_us":
        if box_ratio < rules["subject_fail"]:
            add(
                findings,
                "FAIL",
                "SUBJECT_TOO_SMALL",
                "image",
                "主体最长边占画面 {:.1f}%，低于 80%（官方要求约 85%）".format(box_ratio * 100),
            )
        elif box_ratio < rules["subject_warn"]:
            add(
                findings,
                "WARN",
                "SUBJECT_BELOW_85",
                "image",
                "主体最长边占画面 {:.1f}%，低于官方 85% 指引".format(box_ratio * 100),
            )
        elif box_ratio > 0.98:
            add(
                findings,
                "WARN",
                "SUBJECT_EDGE_RISK",
                "image",
                "主体最长边占画面 {:.1f}%，接近画边，注意不得裁切".format(box_ratio * 100),
            )
        else:
            add(
                findings,
                "PASS",
                "SUBJECT_RATIO",
                "image",
                "主体最长边占画面 {:.1f}%，≥85%".format(box_ratio * 100),
            )
    else:
        if box_ratio < rules["subject_fail"]:
            add(
                findings,
                "FAIL",
                "SUBJECT_TOO_SMALL",
                "image",
                "主体最长边占画面 {:.1f}%，低于 60%".format(box_ratio * 100),
            )
        else:
            add(
                findings,
                "PASS",
                "SUBJECT_RATIO",
                "image",
                "主体最长边占画面 {:.1f}%，≥60%".format(box_ratio * 100),
            )
    return findings


def check_video(spec, platform):
    findings = []
    width = int(spec["width"])
    height = int(spec["height"])
    duration = float(spec["duration_sec"])
    fps = float(spec["fps"])
    fmt = str(spec["format"]).strip().lower().lstrip(".")
    has_subtitles = bool(spec["has_subtitles"])
    first_frame = bool(spec["first_frame_product"])
    declared = str(spec["aspect_ratio"]).strip()

    ratio = width / float(height)

    if platform == "amazon_us":
        sixteen_nine = 16.0 / 9.0
        in_16_9 = abs(ratio - sixteen_nine) <= sixteen_nine * 0.01
        in_1_1 = abs(ratio - 1) <= 0.01
        if in_16_9 or in_1_1:
            add(findings, "PASS", "VIDEO_ASPECT", "video", "画面 {:.3f}，符合 16:9 或 1:1".format(ratio))
        else:
            add(
                findings,
                "FAIL",
                "VIDEO_ASPECT",
                "video",
                "画面 {:.3f}，Amazon 视频要求 16:9 或 1:1".format(ratio),
            )

        if duration > 60:
            add(
                findings,
                "FAIL",
                "VIDEO_DURATION",
                "video",
                "时长 {:.1f}s，超过 60s".format(duration),
            )
        else:
            add(findings, "PASS", "VIDEO_DURATION", "video", "时长 {:.1f}s，≤60s".format(duration))

        if min(width, height) < 720:
            add(
                findings,
                "WARN",
                "VIDEO_RESOLUTION",
                "video",
                "分辨率 {}x{} 短边低于 720，手机端不清晰".format(width, height),
            )
        else:
            add(
                findings,
                "PASS",
                "VIDEO_RESOLUTION",
                "video",
                "分辨率 {}x{}，可用".format(width, height),
            )

        if first_frame:
            add(findings, "PASS", "VIDEO_FIRST_FRAME", "video", "首帧已声明产品出镜")
        else:
            add(findings, "WARN", "VIDEO_FIRST_FRAME", "video", "首帧未出现产品，建议前 3 秒展示")

        if has_subtitles:
            add(findings, "PASS", "VIDEO_SUBTITLES", "video", "已声明含字幕")
        else:
            add(findings, "WARN", "VIDEO_SUBTITLES", "video", "无字幕，建议补字幕")
    else:
        if abs(ratio - 0.5625) > 0.5625 * 0.01:
            add(
                findings,
                "FAIL",
                "VIDEO_ASPECT",
                "video",
                "画面 {:.3f}，TikTok 视频要求 9:16（1080×1920）".format(ratio),
            )
        else:
            add(findings, "PASS", "VIDEO_ASPECT", "video", "画面 {:.3f}，符合 9:16".format(ratio))

        if width < 720 or height < 1280:
            add(
                findings,
                "FAIL",
                "VIDEO_RESOLUTION",
                "video",
                "分辨率 {}x{} 低于最低要求 720×1280".format(width, height),
            )
        elif width == 1080 and height == 1920:
            add(
                findings,
                "PASS",
                "VIDEO_RESOLUTION",
                "video",
                "分辨率 {}×{}，符合推荐值".format(width, height),
            )
        else:
            add(
                findings,
                "WARN",
                "VIDEO_RESOLUTION_RECOMMENDED",
                "video",
                "分辨率 {}x{}，推荐 1080×1920".format(width, height),
            )

        if duration < 9 or duration > 60:
            add(
                findings,
                "FAIL",
                "VIDEO_DURATION",
                "video",
                "时长 {:.1f}s，TikTok 视频要求 9–60s".format(duration),
            )
        else:
            add(findings, "PASS", "VIDEO_DURATION", "video", "时长 {:.1f}s，在 9–60s 内".format(duration))

        if first_frame:
            add(findings, "PASS", "VIDEO_FIRST_FRAME", "video", "首帧已声明产品出镜")
        else:
            add(findings, "FAIL", "VIDEO_FIRST_FRAME", "video", "首帧未出现产品；TikTok 前 3 秒定点击")

        if has_subtitles:
            add(findings, "PASS", "VIDEO_SUBTITLES", "video", "已声明含字幕（仍需人工确认安全区）")
        else:
            add(findings, "WARN", "VIDEO_SUBTITLES", "video", "无字幕；无声播放场景会丢失信息")

        if declared not in ("9:16", "9x16", "0.5625"):
            add(
                findings,
                "WARN",
                "VIDEO_ASPECT_FIELD",
                "aspect_ratio",
                "aspect_ratio 字段为 {}，与 9:16 不一致".format(declared),
            )

    if fmt not in ("mp4", "mov"):
        add(
            findings,
            "WARN",
            "VIDEO_FORMAT",
            "format",
            "格式 {} 非 mp4/mov，上传前建议转码".format(fmt),
        )
    else:
        add(findings, "PASS", "VIDEO_FORMAT", "format", "格式 {}，平台可接受".format(fmt))

    if fps < 24 or fps > 60:
        add(findings, "WARN", "VIDEO_FPS", "fps", "帧率 {:.0f}，建议 24–60fps".format(fps))
    else:
        add(findings, "PASS", "VIDEO_FPS", "fps", "帧率 {:.0f}，在 24–60fps".format(fps))

    return findings


def summarize(findings):
    counts = {"PASS": 0, "WARN": 0, "FAIL": 0}
    for item in findings:
        counts[item["level"]] += 1
    if counts["FAIL"] > 0:
        verdict = "FAIL"
    elif counts["WARN"] > 0:
        verdict = "WARN"
    else:
        verdict = "PASS"
    return counts, verdict


def print_human(mode, platform, path, findings, manual):
    print("{}规格检查 · {}".format("图片" if mode == "image" else "视频", RULES[platform]["label"]))
    print("文件: {}".format(path))
    for item in findings:
        print("[{}] {} ({}): {}".format(item["level"], item["code"], item["field"], item["message"]))
    for note in manual:
        print("[MANUAL] {}".format(note))
    counts, verdict = summarize(findings)
    print("")
    print(
        "总判定: {} (FAIL {} / WARN {} / PASS {})".format(
            verdict, counts["FAIL"], counts["WARN"], counts["PASS"]
        )
    )
    print("口径: {}。".format(RULES_BASIS))


def run_video(args):
    if not os.path.isfile(args.spec):
        emit_error("INPUT_MISSING", "[INPUT_MISSING] 找不到文件: {}".format(args.spec), args.json)
    try:
        with open(args.spec, "r", encoding="utf-8-sig") as handle:
            spec = json.load(handle)
    except json.JSONDecodeError as exc:
        emit_error(
            "INPUT_ERROR",
            "[INPUT_ERROR] JSON 解析失败: {}".format(exc),
            args.json,
        )
        raise AssertionError("unreachable")
    except UnicodeDecodeError:
        emit_error(
            "INPUT_ERROR",
            "[INPUT_ERROR] 文件编码不可读（需 UTF-8）: {}".format(args.spec),
            args.json,
        )
        raise AssertionError("unreachable")
    except OSError:
        emit_error("INPUT_ERROR", "[INPUT_ERROR] 文件无法读取: {}".format(args.spec), args.json)

    if not isinstance(spec, dict):
        emit_error("INPUT_ERROR", "[INPUT_ERROR] 顶层必须是 JSON 对象", args.json)

    missing = [
        field
        for field in VIDEO_FIELDS
        if field not in spec or spec[field] is None or spec[field] == ""
    ]
    if missing:
        emit_error(
            "INPUT_MISSING",
            "[INPUT_MISSING] 缺少字段: {}".format(", ".join(missing)),
            args.json,
        )

    width = video_number(spec, "width", args.json, integer=True)
    height = video_number(spec, "height", args.json, integer=True)
    duration = video_number(spec, "duration_sec", args.json)
    fps = video_number(spec, "fps", args.json)
    if width <= 0 or height <= 0:
        emit_error(
            "INPUT_ERROR",
            "[INPUT_ERROR] 视频尺寸非法：{}×{}（宽高必须为正数）".format(spec["width"], spec["height"]),
            args.json,
        )

    normalized = dict(spec, width=width, height=height, duration_sec=duration, fps=fps)
    findings = check_video(normalized, args.platform)
    counts, verdict = summarize(findings)
    payload = {
        "mode": "video",
        "platform": args.platform,
        "file": args.spec,
        "source_file": None,
        "verdict": verdict,
        "counts": counts,
        "findings": findings,
        "manual_checks": MANUAL_VIDEO[args.platform],
        "meta": {
            "pillow": PILLOW_OK,
            "rules_basis": RULES_BASIS,
            "image_limits": image_limits(args.platform),
            "fix_scope": None,
        },
    }
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print_human("video", args.platform, args.spec, findings, MANUAL_VIDEO[args.platform])
    return 1 if counts["FAIL"] > 0 else 0


def run_image(args):
    if args.fix:
        same_source = os.path.normcase(os.path.abspath(args.fix)) == os.path.normcase(
            os.path.abspath(args.image)
        )
        if same_source:
            emit_error(
                "INPUT_ERROR",
                "[INPUT_ERROR] --fix 输出路径不能与原图相同，请改用其他输出路径: {}".format(args.fix),
                args.json,
            )
        if not PILLOW_OK:
            emit_error(
                "INPUT_MISSING",
                "[INPUT_MISSING] --fix 需要 Pillow，当前未安装",
                args.json,
            )
        if not os.path.isfile(args.image):
            emit_error(
                "INPUT_MISSING",
                "[INPUT_MISSING] 找不到图片: {}".format(args.image),
                args.json,
            )

    findings = []
    checked_path = args.image
    missing_source = False
    if args.fix:
        side = fix_image(args.image, args.fix, args.json)
        add(
            findings,
            "PASS",
            "FIX_SAVED",
            "image",
            "已生成修正图 {}（{}x{}，白底+正方形）".format(args.fix, side, side),
        )
        checked_path = args.fix
        findings.extend(check_image(checked_path, args.platform, args.json))
        manual = MANUAL_IMAGE[args.platform]
    elif not os.path.isfile(args.image):
        # 缺图片：保留既有输出形态（单条 FILE_NOT_FOUND），退出码改为 2（#2）
        missing_source = True
        add(findings, "FAIL", "FILE_NOT_FOUND", "image", "找不到图片: {}".format(args.image))
        manual = []
    else:
        findings = check_image(args.image, args.platform, args.json)
        manual = MANUAL_IMAGE[args.platform]

    counts, verdict = summarize(findings)
    payload = {
        "mode": "image",
        "platform": args.platform,
        "file": checked_path,
        "source_file": args.image,
        "verdict": verdict,
        "counts": counts,
        "findings": findings,
        "manual_checks": manual,
        "meta": {
            "pillow": PILLOW_OK,
            "rules_basis": RULES_BASIS,
            "image_limits": image_limits(args.platform),
            "fix_scope": FIX_SCOPE if args.fix else None,
        },
    }
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print_human("image", args.platform, checked_path, findings, manual)

    if counts["FAIL"] > 0:
        return 2 if missing_source else 1
    return 0


def main():
    parser = argparse.ArgumentParser(description="05 创意素材规格校验（图片 / 视频）")
    parser.add_argument("image", nargs="?", help="待检查图片路径")
    parser.add_argument("--spec", help="视频规格 JSON")
    parser.add_argument("--platform", required=True, choices=["amazon_us", "tiktok_us"], help="目标平台")
    parser.add_argument("--fix", help="修正图输出路径（仅图片）")
    parser.add_argument("--json", action="store_true", help="输出机器可读 JSON")
    args = parser.parse_args()

    if args.image and args.spec:
        emit_error("INPUT_MISSING", "[INPUT_MISSING] <image> 与 --spec 只能二选一", args.json)
    if not args.image and not args.spec:
        emit_error("INPUT_MISSING", "[INPUT_MISSING] 缺少 <image> 或 --spec", args.json)
    if args.spec and args.fix:
        emit_error(
            "INPUT_MISSING",
            "[INPUT_MISSING] --fix 仅用于图片，不能与 --spec 同用",
            args.json,
        )

    if args.spec:
        return run_video(args)
    return run_image(args)


if __name__ == "__main__":
    sys.exit(main())
