#!/usr/bin/env python3
"""评论、退货与账号健康运营分析（clean-room 重写）。

行为规格见 docs/spec/07_review_ops.md。纯标准库、无外部配置；关键词与阈值内嵌。
错误契约沿用 shared.errors：JSON 到 stdout，人类信息到 stderr。
"""

import csv
import json
import os
import re
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from shared.args import CliArgumentParser
from shared.errors import emit_json, fail, run_main, set_json_mode
from shared.numbers import round2

TAXONOMY = [
    {
        "name": "质量做工",
        "fixable": True,
        "keywords": [
            "leak", "leaks", "leaking", "leaked", "seal", "quality", "broke",
            "broken", "crack", "cracked", "defect", "flimsy", "cheap", "rust",
        ],
        "listing_patch": "在五点与 A+ 写清杯体/刀头材质、密封圈结构与质保边界；不得写未验证的 waterproof。",
        "creative_patch": "补密封圈/刀头细节图与锁扣测试短视频；用实拍证明防漏，不靠形容词。",
    },
    {
        "name": "尺寸容量",
        "fixable": False,
        "keywords": [
            "too small", "smaller than", "capacity", "16 oz", "size", "too big",
        ],
        "listing_patch": "标题与五点标明 16 oz 实际可用容量、杯体尺寸与适用场景；不要只写“大容量”。",
        "creative_patch": "补手持比例图、杯中刻度与常见水杯/杯架对比图。",
    },
    {
        "name": "功能故障",
        "fixable": False,
        "keywords": [
            "stopped working", "will not turn on", "button", "motor", "stuck",
            "malfunction", "won't start",
        ],
        "listing_patch": "写清按键顺序、适用食材/冰块上限与禁止干烧；把故障排查 FAQ 前置到 A+。",
        "creative_patch": "补 30 秒启动/停止演示与错误指示灯特写，减少误操作。",
    },
    {
        "name": "电池续航",
        "fixable": False,
        "keywords": ["battery", "charge", "charging", "dies", "power"],
        "listing_patch": "写明 2000mAh、充满时长、可打杯数与测试条件；续航数字必须来自实测。",
        "creative_patch": "补充电指示灯、USB-C 接口与单次续航实测画面。",
    },
    {
        "name": "清洁异味",
        "fixable": True,
        "keywords": ["hard to clean", "clean", "wash", "smell", "odor", "dirty"],
        "listing_patch": "A+ 增加三步拆洗图；只有测试通过才写 dishwasher-safe，并说明首次使用异味处理。",
        "creative_patch": "补可拆杯体、密封圈拆洗与晾干位置图；不要只写“easy to clean”。",
    },
    {
        "name": "物流包装",
        "fixable": False,
        "keywords": ["packaging", "damaged", "dented", "crushed", "box", "shipping"],
        "listing_patch": "写清包装内容与到货检查步骤；配送时效按实际 handle time 展示，不承诺做不到的日期。",
        "creative_patch": "补包装清单图与防撞结构图；外箱加检查提示卡。",
    },
    {
        "name": "描述不符",
        "fixable": True,
        "keywords": ["not as described", "misleading", "description", "photo", "picture"],
        "listing_patch": "逐条对照 spec 修标题/五点，删除超规格词；加尺寸、容量、配件对比表。",
        "creative_patch": "主图与场景图只呈现真实配置；把“包含什么/不包含什么”做成一张图。",
    },
    {
        "name": "使用门槛",
        "fixable": True,
        "keywords": ["instructions", "manual", "confusing", "complicated", "hard to use"],
        "listing_patch": "五点写清三步上手；说明适合单人 smoothie，不适合大量冰块或硬质食材。",
        "creative_patch": "加 3 步上手图、30 秒教学视频与说明书二维码。",
    },
]

REVIEWS_DISCLAIMER = "关键词归因是确定性初筛，不替代人工读评；修补前请回看原文并核对产品事实。"

RATING_ALIASES = ["rating", "stars", "score", "评分", "星级", "分数"]
TITLE_ALIASES = ["title", "review_title", "标题", "评论标题"]
BODY_ALIASES = ["body", "review", "text", "content", "内容", "评论内容", "评论"]

REASON_CODE_ALIASES = ["reason_code", "return_reason_code", "退货原因码", "原因码", "退货原因"]
QTY_ALIASES = ["qty", "quantity", "units", "退货件数", "数量", "件数"]
REFUND_ALIASES = ["refund_amount", "refund", "amount", "退款金额", "退款总额", "金额"]

FAILURE_ACTION = "核对平台原因码与原始退货记录，再归因。"
PREVENTABLE_CODES = [
    "ARRIVED_LATE", "DAMAGED", "MISSING_PARTS", "NOT_COMPATIBLE",
    "QUALITY_UNACCEPTABLE", "WRONG_ITEM",
]

RETURN_REASONS = {
    "DEFECTIVE": {
        "label_cn": "商品有缺陷",
        "label_en": "Defective",
        "aliases": ["商品有缺陷", "有缺陷", "质量问题"],
        "preventable": False,
        "action": FAILURE_ACTION,
    },
    "NO_LONGER_NEEDED": {
        "label_cn": "不再需要",
        "label_en": "No longer needed",
        "aliases": ["不再需要", "不想要了"],
        "preventable": False,
        "action": FAILURE_ACTION,
    },
    "NOT_COMPATIBLE": {
        "label_cn": "不兼容/不适用",
        "label_en": "Not compatible",
        "aliases": ["不兼容", "不适用"],
        "preventable": True,
        "action": "补尺寸/容量/适用场景对照表，标题与五点写明不适用边界。",
    },
    "UNAUTHORIZED_PURCHASE": {
        "label_cn": "未授权购买",
        "label_en": "Unauthorized purchase",
        "aliases": ["未授权购买"],
        "preventable": False,
        "action": FAILURE_ACTION,
    },
    "MISSING_PARTS": {
        "label_cn": "缺少配件",
        "label_en": "Missing parts",
        "aliases": ["缺少配件", "缺件"],
        "preventable": True,
        "action": "A+ 与主图加包装清单；出库前逐件清点并做称重复核。",
    },
    "ARRIVED_LATE": {
        "label_cn": "到货太晚",
        "label_en": "Arrived late",
        "aliases": ["到货太晚", "配送太晚"],
        "preventable": True,
        "action": "按实际时效设置 handle time，准备备选承运商。",
    },
    "BETTER_PRICE": {
        "label_cn": "找到更低价格",
        "label_en": "Better price",
        "aliases": ["找到更低价格", "更低价格"],
        "preventable": False,
        "action": FAILURE_ACTION,
    },
    "QUALITY_UNACCEPTABLE": {
        "label_cn": "质量不可接受",
        "label_en": "Quality unacceptable",
        "aliases": ["质量不可接受"],
        "preventable": True,
        "action": "对齐 Listing 预期，收紧质检标准并排查问题批次。",
    },
    "DAMAGED": {
        "label_cn": "运输损坏",
        "label_en": "Damaged",
        "aliases": ["运输损坏", "破损"],
        "preventable": True,
        "action": "升级外箱与内衬，做跌落测试；到货破损引导拍照留证。",
    },
    "WRONG_ITEM": {
        "label_cn": "发错货",
        "label_en": "Wrong item",
        "aliases": ["发错货", "错发"],
        "preventable": True,
        "action": "变体图与 SKU 标签唯一化，打包扫码复核。",
    },
    "OTHER": {
        "label_cn": "其他/未映射",
        "label_en": "Other / Unmapped",
        "aliases": [],
        "preventable": False,
        "action": FAILURE_ACTION,
    },
}

RETURNS_DISCLAIMER = "原因码优先于自由文本；退货率必须用同期订单数做分母，跨期比较需同口径。"

HEALTH_FIELDS = [
    "odr_pct",
    "late_shipment_pct",
    "pre_fulfillment_cancel_pct",
    "negative_feedback_pct",
    "a_to_z_claims",
    "policy_violations",
]
HEALTH_PCT_FIELDS = ["odr_pct", "late_shipment_pct", "pre_fulfillment_cancel_pct", "negative_feedback_pct"]
HEALTH_COUNT_FIELDS = ["a_to_z_claims", "policy_violations"]

HEALTH_METRICS = [
    ("odr_pct", "订单缺陷率 ODR", 1.0, "< 1%"),
    ("late_shipment_pct", "迟发率", 4.0, "< 4%"),
    ("pre_fulfillment_cancel_pct", "下单前取消率", 2.5, "< 2.5%"),
]

HEALTH_ACTIONS = {
    ("odr_pct", "CRITICAL"): "立即停止相关 ASIN 广告，按差评/退货/纠纷归因到具体环节；7 天内出整改证据。",
    ("odr_pct", "WARN"): "ODR 已接近 1%：逐周盯紧 A-to-z 与差评，先修 Top1 病因。",
    ("late_shipment_pct", "CRITICAL"): "核对 handle time 与库存同步；切换备选承运商，先恢复时效再谈放量。",
    ("late_shipment_pct", "WARN"): "迟发率接近 4%：检查旺季/周末处理时效，预留承运商备份。",
    ("pre_fulfillment_cancel_pct", "CRITICAL"): "暂停缺货风险 SKU，修正库存同步与超卖；取消率不降不恢复广告。",
    ("pre_fulfillment_cancel_pct", "WARN"): "取消率接近 2.5%：检查库存缓冲与 listing 可售状态。",
}
OK_ACTION = "保持周检，不因短期正常而放松。"
HEALTH_OK_SUMMARY = "维持周检：ODR、迟发、取消率连续 4 周在阈值内再谈放量。"
HEALTH_DISCLAIMER = "阈值为编写时公开口径，发布前请在 Amazon 卖家中心/账户状况页复核。"


def num_text(value):
    return "{:g}".format(value)


def clean_number(raw):
    text = str(raw).strip()
    text = text.replace("$", "").replace(",", "").replace(" ", "")
    if text in ("", "-", "—", "N/A", "n/a", "nan", "NaN"):
        return None
    try:
        return float(text)
    except ValueError:
        return None


def collapse(text):
    return re.sub(r"\s+", " ", text).strip()


def snippet(title, body):
    merged = "{} / {}".format(title, body) if title else body
    return collapse(merged)[:180]


def resolve_columns(header, field_aliases):
    stripped = [cell.strip() for cell in header]
    lowered = [cell.lower() for cell in stripped]
    resolved = {}
    for name, aliases in field_aliases:
        for alias in aliases:
            key = alias.lower()
            if key in lowered:
                resolved[name] = lowered.index(key)
                break
    return resolved, stripped


def read_csv_rows(path):
    if not os.path.isfile(path):
        fail("找不到输入文件：{}".format(path), missing=["file"])
    try:
        handle = open(path, "r", encoding="utf-8-sig", newline="")
    except OSError:
        fail("找不到输入文件：{}".format(path), missing=["file"])
    with handle:
        reader = csv.reader(handle)
        try:
            header = next(reader)
        except StopIteration:
            fail("文件没有数据行：{}".format(path), missing=["file"])
        rows = []
        for row in reader:
            if not row or all(cell.strip() == "" for cell in row):
                continue
            rows.append((reader.line_num, row))
        if not rows:
            fail("文件没有数据行：{}".format(path), missing=["file"])
        return header, rows


def cell(row, index):
    if index is None or index >= len(row):
        return ""
    return row[index]


def require_columns(header, fields, labels):
    field_aliases = [(name, aliases) for name, aliases in fields]
    resolved, stripped = resolve_columns(header, field_aliases)
    missing = [name for name, _ in field_aliases if name not in resolved]
    if missing:
        first = missing[0]
        fail(
            "找不到必要列：{}。可用列：{}".format(labels[first], ", ".join(stripped)),
            missing=missing,
        )
    return resolved


# ---- reviews ----
def run_reviews(path, as_json):
    header, rows = read_csv_rows(path)
    resolved = _resolve_or_fail(header, [
        ("rating", RATING_ALIASES, "评分"),
        ("body", BODY_ALIASES, "评论内容"),
    ])
    reviewed = []
    for line_no, row in rows:
        rating_raw = cell(row, resolved["rating"])
        title = cell(row, _first_index(header, TITLE_ALIASES)).strip()
        body = cell(row, resolved["body"])
        if body.strip() == "":
            fail("第 {} 行评论内容为空。".format(line_no), missing=[])
        rating = clean_number(rating_raw)
        if rating is None or rating < 1 or rating > 5:
            fail(
                "第 {} 行评分缺失或不在 1–5 星：'{}'".format(line_no, str(rating_raw).strip()),
                missing=[],
            )
        reviewed.append({"rating": rating, "title": title, "body": body.strip()})

    total = len(reviewed)
    average = round2(sum(item["rating"] for item in reviewed) / total)
    distribution = {str(bucket): 0 for bucket in range(1, 6)}
    for item in reviewed:
        distribution[str(int(item["rating"]))] += 1

    # 计数口径为 <3 星（含 2.5 这类小数评分）；归因只对 ≤2 星做，保持旧侧行为。
    negatives = [item for item in reviewed if item["rating"] < 3]
    one_two = len(negatives)
    negative_count = one_two
    one_two_pct = round2(one_two / total * 100)
    three_pct = round2(distribution["3"] / total * 100)
    positive_pct = round2((distribution["4"] + distribution["5"]) / total * 100)

    attribution = {category["name"]: 0 for category in TAXONOMY}
    categories = []
    classified = []
    unclassified = 0
    for item in reviewed:
        if item["rating"] > 2:
            continue
        text = collapse("{} {}".format(item["title"], item["body"]).lower())
        chosen = None
        matched = []
        for category in TAXONOMY:
            hits = [keyword for keyword in category["keywords"] if keyword in text]
            if hits and (chosen is None or len(hits) > len(matched)):
                chosen = category
                matched = hits
        if chosen is None:
            unclassified += 1
            classified.append((item, None, []))
        else:
            attribution[chosen["name"]] += 1
            classified.append((item, chosen, matched))

    for category in TAXONOMY:
        count = attribution[category["name"]]
        categories.append({
            "name": category["name"],
            "fixable": category["fixable"],
            "listing_patch": category["listing_patch"],
            "creative_patch": category["creative_patch"],
            "matched_keywords": [],
            "count": count,
            "share_of_negative_pct": round2(count / negative_count * 100) if negative_count else 0.0,
            "share_of_all_pct": round2(count / total * 100),
        })

    fixable_count = sum(attribution[c["name"]] for c in TAXONOMY if c["fixable"])
    fixable_rate = round2(fixable_count / negative_count * 100) if negative_count else 0.0

    top_issues = []
    ranked = sorted(
        [(index, category) for index, category in enumerate(TAXONOMY) if attribution[category["name"]]],
        key=lambda pair: (-attribution[pair[1]["name"]], pair[0]),
    )
    for _, category in ranked[:3]:
        evidence = [
            snippet(item["title"], item["body"])
            for item, chosen, _ in classified
            if chosen is not None and chosen["name"] == category["name"]
        ][:2]
        top_issues.append({
            "name": category["name"],
            "count": attribution[category["name"]],
            "share_of_negative_pct": round2(attribution[category["name"]] / negative_count * 100),
            "fixable": category["fixable"],
            "listing_patch": category["listing_patch"],
            "creative_patch": category["creative_patch"],
            "evidence": evidence,
        })

    negative_reviews = []
    for item, chosen, matched in classified:
        negative_reviews.append({
            "rating": int(item["rating"]),
            "title": item["title"],
            "category": chosen["name"] if chosen else "未归类",
            "matched_keywords": matched if chosen else [],
            "snippet": snippet(item["title"], item["body"]),
        })

    payload = {
        "mode": "reviews",
        "file": path,
        "total_reviews": total,
        "average_rating": average,
        "rating_distribution": distribution,
        "one_two_star_count": one_two,
        "one_two_star_pct": one_two_pct,
        "negative_rate_pct": one_two_pct,
        "negative_count": negative_count,
        "negative_share_pct": one_two_pct,
        "three_star_pct": three_pct,
        "positive_pct": positive_pct,
        "attribution": attribution,
        "categories": categories,
        "unclassified_count": unclassified,
        "fixable_count": fixable_count,
        "fixable_rate_pct": fixable_rate,
        "top_issues": top_issues,
        "negative_reviews": negative_reviews,
        "rules": {
            "taxonomy": [category["name"] for category in TAXONOMY],
            "fixable": [category["name"] for category in reversed(TAXONOMY) if category["fixable"]],
            "negative_definition": "1–2 星；负面率 = 1–2 星评论 ÷ 有效评论",
            "fixable_rate_definition": "可修复类目条数 ÷ 1–2 星评论数",
        },
        "disclaimer": REVIEWS_DISCLAIMER,
    }
    if as_json:
        emit_json(payload)
    else:
        render_reviews_text(payload)
    return 0


def _first_index(header, aliases):
    stripped = [cell.strip().lower() for cell in header]
    for alias in aliases:
        if alias.lower() in stripped:
            return stripped.index(alias.lower())
    return None


def _resolve_or_fail(header, fields):
    resolved, stripped = resolve_columns(header, [(name, aliases) for name, aliases, _ in fields])
    missing = [name for name, _, _ in fields if name not in resolved]
    if missing:
        labels = {name: label for name, _, label in fields}
        first = missing[0]
        fail(
            "找不到必要列：{}。可用列：{}".format(labels[first], ", ".join(stripped)),
            missing=missing,
        )
    return resolved


def render_reviews_text(payload):
    fixable_names = ["质量做工", "描述不符", "清洁异味", "使用门槛"]
    lines = [
        "评论归因 · {} 条评论 ｜ 平均分 {:.2f}".format(payload["total_reviews"], payload["average_rating"]),
        "1–2 星 {} 条（{:.2f}%，负面率）｜ 3 星 {:.2f}% ｜ 4–5 星 {:.2f}%".format(
            payload["one_two_star_count"], payload["one_two_star_pct"],
            payload["three_star_pct"], payload["positive_pct"]),
        "可修复率 {}/{} = {:.2f}%（{}）".format(
            payload["fixable_count"], payload["negative_count"],
            payload["fixable_rate_pct"], "/".join(fixable_names)),
        "",
        "八类归因：",
    ]
    for category in payload["categories"]:
        lines.append("- {}：{} 条（占负面 {:.2f}%，占全部 {:.2f}%）｜{}".format(
            category["name"], category["count"], category["share_of_negative_pct"],
            category["share_of_all_pct"], "可修复" if category["fixable"] else "不可修复"))
    lines.append("")
    if payload["top_issues"]:
        lines.append("Top3 问题与修补建议：")
        for index, issue in enumerate(payload["top_issues"], start=1):
            lines.append("{}. {}（{} 条，占负面 {:.2f}%）".format(
                index, issue["name"], issue["count"], issue["share_of_negative_pct"]))
            lines.append("   Listing：{}".format(issue["listing_patch"]))
            lines.append("   素材：{}".format(issue["creative_patch"]))
            if issue["evidence"]:
                lines.append("   原文：{}".format(issue["evidence"][0]))
    else:
        lines.append("Top3 问题：无关键词命中的负面评论，需人工读评。")
    lines.append("")
    lines.append("提醒：归因是修补线索，不是甩锅；一次只改症状指向的 Listing 或素材。")
    lines.append(payload["disclaimer"])
    print("\n".join(lines))


# ---- returns ----
def normalize_reason(raw):
    text = str(raw).strip()
    if text == "":
        return "OTHER", "（空）"
    normalized = text.upper().replace(" ", "_").replace("-", "_").replace("/", "_").strip("_")
    if normalized in RETURN_REASONS:
        return normalized, text
    for code, info in RETURN_REASONS.items():
        if text in info["aliases"]:
            return code, text
    lowered = text.lower()
    for code, info in RETURN_REASONS.items():
        if lowered == info["label_cn"].lower() or lowered == code.lower():
            return code, text
    return "OTHER", text


def reason_entry(code, qty, refund, units, total_refund):
    info = RETURN_REASONS[code]
    return {
        "code": code,
        "label_cn": info["label_cn"],
        "label_en": info["label_en"],
        "qty": qty,
        "refund_amount": refund,
        "preventable": info["preventable"],
        "qty_share_pct": round2(qty / units * 100) if units else 0.0,
        "refund_share_pct": round2(refund / total_refund * 100) if total_refund else 0.0,
        "action": info["action"],
    }


def run_returns(path, orders, as_json):
    if orders is not None and orders <= 0:
        fail("--orders 必须大于 0，才能计算退货率。", missing=[])
    header, rows = read_csv_rows(path)
    resolved = require_columns(header, [
        ("reason_code", REASON_CODE_ALIASES),
        ("qty", QTY_ALIASES),
        ("refund_amount", REFUND_ALIASES),
    ], {
        "reason_code": "退货原因码",
        "qty": "退货件数",
        "refund_amount": "退款金额",
    })

    aggregates = {}
    unmapped = []
    returned_units = 0
    total_refund = 0
    for line_no, row in rows:
        code, original = normalize_reason(cell(row, resolved["reason_code"]))
        if code == "OTHER" and original not in unmapped:
            unmapped.append(original)
        qty_value = clean_number(cell(row, resolved["qty"]))
        if qty_value is None or qty_value <= 0 or qty_value != int(qty_value):
            fail("第 {} 行退货件数缺失或不是正整数。".format(line_no), missing=[])
        refund_value = clean_number(cell(row, resolved["refund_amount"]))
        if refund_value is None or refund_value < 0:
            fail("第 {} 行退款金额缺失或为负数。".format(line_no), missing=[])

        qty = int(qty_value)
        aggregate = aggregates.setdefault(code, {"qty": 0, "refund": 0.0})
        aggregate["qty"] += qty
        aggregate["refund"] += refund_value
        returned_units += qty
        total_refund += refund_value

    reasons = [
        reason_entry(code, aggregate["qty"], aggregate["refund"], returned_units, total_refund)
        for code, aggregate in aggregates.items()
    ]
    reasons.sort(key=lambda item: (-item["qty"], -item["refund_amount"]))
    top_reason = reasons[0] if reasons else None

    preventable = [reason for reason in reasons if reason["preventable"]]
    preventable_units = sum(reason["qty"] for reason in preventable)
    preventable_refund = round(sum(reason["refund_amount"] for reason in preventable), 2)
    preventable_share = round2(preventable_units / returned_units * 100) if returned_units else 0.0

    missing = []
    if orders is None:
        missing.append("[INPUT_MISSING] 退货率：需 --orders（同期订单数）。")
    if unmapped:
        missing.append("未映射原因码：{}；已归入 OTHER。".format("、".join(unmapped)))

    payload = {
        "mode": "returns",
        "file": path,
        "returned_units": returned_units,
        "orders": orders,
        "return_rate_pct": round2(returned_units / orders * 100) if orders else None,
        "return_rate_definition": "退货件数 ÷ 同期订单数 × 100%",
        "total_refund": round(total_refund, 2),
        "reasons": reasons,
        "top_reason": top_reason,
        "preventable": {
            "codes": PREVENTABLE_CODES,
            "units": preventable_units,
            "share_pct": preventable_share,
            "refund_amount": preventable_refund,
            "actions": [
                {"code": reason["code"], "label_cn": reason["label_cn"], "action": reason["action"]}
                for reason in preventable
            ],
        },
        "unmapped_codes": unmapped,
        "missing": missing,
        "disclaimer": RETURNS_DISCLAIMER,
    }
    if as_json:
        emit_json(payload)
    else:
        render_returns_text(payload)
    return 0


def render_returns_text(payload):
    lines = ["退货归因 · {} 件 ｜ 退款 {:.2f} USD".format(
        payload["returned_units"], payload["total_refund"])]
    if payload["orders"]:
        lines.append("退货率 {:.2f}%（{} ÷ {} 订单）".format(
            payload["return_rate_pct"], payload["returned_units"], payload["orders"]))
    else:
        lines.append("退货率 [INPUT_MISSING]：需 --orders（同期订单数）")
    lines.append("可预防退货 {}/{} = {:.2f}%（退款 {:.2f} USD）".format(
        payload["preventable"]["units"], payload["returned_units"],
        payload["preventable"]["share_pct"], payload["preventable"]["refund_amount"]))
    lines.append("")
    lines.append("Top 原因：")
    for reason in payload["reasons"][:5]:
        lines.append("- {} [{}]：{} 件（{:.2f}%），退款 {:.2f}｜{}".format(
            reason["label_cn"], reason["code"], reason["qty"], reason["qty_share_pct"],
            reason["refund_amount"], "可预防" if reason["preventable"] else "不可预防"))
    actions = payload["preventable"]["actions"]
    if actions:
        lines.append("")
        lines.append("可预防动作：")
        for action in actions:
            lines.append("- {}：{}".format(action["label_cn"], action["action"]))
    if payload["missing"]:
        lines.append("")
        lines.extend(payload["missing"])
    lines.append(payload["disclaimer"])
    print("\n".join(lines))


# ---- health ----
def metric_status(value, threshold):
    if value >= threshold:
        return "CRITICAL"
    if value >= threshold * 0.8:
        return "WARN"
    return "OK"


def run_health(path, fail_on_critical, as_json):
    if not os.path.isfile(path):
        fail("找不到输入文件：{}".format(path), missing=["file"])
    try:
        with open(path, "r", encoding="utf-8-sig") as handle:
            data = json.loads(handle.read())
    except OSError:
        fail("找不到输入文件：{}".format(path), missing=["file"])
    except ValueError as exc:
        fail("账号健康文件无法读取或不是合法 JSON：{}".format(exc), missing=["file"])

    if not isinstance(data, dict):
        fail("账号健康 JSON 顶层必须是对象。", missing=["file"])

    missing = [key for key in HEALTH_FIELDS if key not in data]
    if missing:
        fail("账号健康 JSON 缺少字段：{}".format(", ".join(missing)), missing=missing)

    for key in HEALTH_PCT_FIELDS:
        value = data[key]
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            fail("字段 {} 必须是数字。".format(key), missing=[])
        if value < 0:
            fail("字段 {} 不能为负数。".format(key), missing=[])

    for key in HEALTH_COUNT_FIELDS:
        value = data[key]
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            fail("字段 {} 必须是整数。".format(key), missing=[])
        if value != int(value):
            fail("字段 {} 必须是整数。".format(key), missing=[])
        if value < 0:
            fail("字段 {} 不能为负数。".format(key), missing=[])

    metrics = []
    critical_count = 0
    warn_count = 0
    actions = []
    for key, label, threshold, rule in HEALTH_METRICS:
        value = data[key]
        status = metric_status(value, threshold)
        if status == "CRITICAL":
            critical_count += 1
        elif status == "WARN":
            warn_count += 1
        action = OK_ACTION if status == "OK" else HEALTH_ACTIONS[(key, status)]
        metrics.append({
            "key": key,
            "label": label,
            "value": value,
            "unit": "%",
            "threshold": threshold,
            "rule": rule,
            "status": status,
            "distance_to_threshold_pct": round2(threshold - value),
            "action": action,
        })
        if status != "OK":
            actions.append("{} {}%（{}）：{}".format(label, num_text(value), status, action))

    negative_value = data["negative_feedback_pct"]
    context_metrics = [
        {
            "key": "negative_feedback_pct",
            "label": "差评率",
            "value": negative_value,
            "unit": "%",
            "status": "INFO",
            "note": "无独立阈值；作为 ODR 的先行指标周检。",
        },
        {
            "key": "a_to_z_claims",
            "label": "A-to-z 索赔",
            "value": data["a_to_z_claims"],
            "unit": "件",
            "status": "WARN" if data["a_to_z_claims"] > 0 else "OK",
            "note": "计数不是比率；需按订单量与原因逐笔复核。",
        },
        {
            "key": "policy_violations",
            "label": "政策违规",
            "value": data["policy_violations"],
            "unit": "项",
            "status": "CRITICAL" if data["policy_violations"] > 0 else "OK",
            "note": "任何一项政策违规都按生存线处理。",
        },
    ]
    for item in context_metrics:
        if item["status"] == "CRITICAL":
            critical_count += 1
        elif item["status"] == "WARN":
            warn_count += 1

    if data["a_to_z_claims"] > 0:
        actions.append("A-to-z 索赔 {} 件：逐笔核对原因，回流 07 评论/退货归因，不只回复个案。".format(
            num_text(data["a_to_z_claims"])))
    if data["policy_violations"] > 0:
        actions.append("政策违规 {} 项：立即停售相关 Listing，先整改并保留证据，再走申诉。".format(
            num_text(data["policy_violations"])))
    if not actions:
        actions.append(HEALTH_OK_SUMMARY)

    grade = "CRITICAL" if critical_count else ("WARN" if warn_count else "OK")
    grade_label = {"CRITICAL": "生存线告警", "WARN": "接近阈值", "OK": "正常"}[grade]

    payload = {
        "mode": "health",
        "file": path,
        "grade": grade,
        "grade_label": grade_label,
        "critical_count": critical_count,
        "warn_count": warn_count,
        "metrics": metrics,
        "context_metrics": context_metrics,
        "actions": actions,
        "thresholds": {key: rule for key, _, _, rule in HEALTH_METRICS},
        "disclaimer": HEALTH_DISCLAIMER,
    }
    if as_json:
        emit_json(payload)
    else:
        render_health_text(payload)
    return 1 if (fail_on_critical and grade == "CRITICAL") else 0


def render_health_text(payload):
    lines = [
        "账号健康 · {}（{}）".format(payload["grade_label"], payload["grade"]),
        "核心阈值：ODR <1% ｜ 迟发 <4% ｜ 下单前取消 <2.5%",
    ]
    for metric in payload["metrics"]:
        lines.append("- {}：{}%（阈值 {}） → {}，距阈值 {:+.2f} 个百分点".format(
            metric["label"], num_text(metric["value"]), metric["rule"],
            metric["status"], metric["distance_to_threshold_pct"]))
    lines.append("- {}：{}% → INFO（{}）".format(
        payload["context_metrics"][0]["label"],
        num_text(payload["context_metrics"][0]["value"]),
        payload["context_metrics"][0]["note"]))
    lines.append("- {}：{} {} → {}（{}）".format(
        payload["context_metrics"][1]["label"],
        num_text(payload["context_metrics"][1]["value"]),
        payload["context_metrics"][1]["unit"],
        payload["context_metrics"][1]["status"],
        payload["context_metrics"][1]["note"]))
    lines.append("- {}：{} {} → {}（{}）".format(
        payload["context_metrics"][2]["label"],
        num_text(payload["context_metrics"][2]["value"]),
        payload["context_metrics"][2]["unit"],
        payload["context_metrics"][2]["status"],
        payload["context_metrics"][2]["note"]))
    lines.append("")
    lines.append("动作：")
    for action in payload["actions"]:
        lines.append("- {}".format(action))
    lines.append(payload["disclaimer"])
    print("\n".join(lines))


def build_parser():
    parser = CliArgumentParser(prog="review_ops.py", description="评论、退货与账号健康运营分析")
    sub = parser.add_subparsers(dest="command", required=True, parser_class=CliArgumentParser)

    reviews = sub.add_parser("reviews", description="评论归因")
    reviews.add_argument("--file", required=True)
    reviews.add_argument("--json", action="store_true")

    returns = sub.add_parser("returns", description="退货归因")
    returns.add_argument("--file", required=True)
    returns.add_argument("--orders", type=int)
    returns.add_argument("--json", action="store_true")

    health = sub.add_parser("health", description="账号健康阈值检查")
    health.add_argument("--file", required=True)
    health.add_argument("--fail-on-critical", action="store_true")
    health.add_argument("--json", action="store_true")
    return parser


def main(argv):
    set_json_mode("--json" in argv)
    args = build_parser().parse_args(argv)
    if args.command == "reviews":
        return run_reviews(args.file, args.json)
    if args.command == "returns":
        return run_returns(args.file, args.orders, args.json)
    return run_health(args.file, args.fail_on_critical, args.json)


if __name__ == "__main__":
    sys.exit(run_main(lambda: main(sys.argv[1:])))
