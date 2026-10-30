#!/usr/bin/env python3
"""FTC/FDA 高风险声明关键词扫描（clean-room 重写）。

行为规格见 docs/spec/04_listing.md。纯标准库、无配置文件，规则常量内嵌。
错误信息统一写 stdout（与 03/07 的 stderr 约定不同，保持旧行为）。
"""

import json
import os
import re
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from shared.errors import emit_json, set_json_mode

RULES = [
    (
        "fda approved",
        "HIGH",
        "FDA 不“批准”化妆品或食品接触类产品；该表述属不可举证的官方背书。",
        "删除。如持有食品接触材料测试报告，可改为 “meets FDA food-contact requirements for the tested materials” 并注明报告编号。",
    ),
    (
        "cures",
        "HIGH",
        "疾病治疗声明属药品/医疗器械范畴，普通商品无资质。",
        "删除疾病表述，改为客观功能与使用场景，例如 “removes everyday grime from the cup surface”。",
    ),
    (
        "treats",
        "HIGH",
        "“治疗”属药品声明；无 FDA 药品批准不得使用。",
        "删除；只描述产品怎么用、能清洁/混合什么，不描述症状改善。",
    ),
    (
        "prevents",
        "HIGH",
        "预防疾病/伤害的声明需要临床或安全证据，普通商品无法举证。",
        "删除；如为使用建议，改为 “helps keep … clean when used as directed”（仍需真实依据）。",
    ),
    (
        "clinically proven",
        "HIGH",
        "“临床验证”要求可提交的人体研究，且结论需与声明一致。",
        "仅在有研究文件时写 “tested in a 12-week consumer study with 60 participants (report available)”；否则删除。",
    ),
    (
        "doctor recommended",
        "HIGH",
        "需要可核查的推荐调查或专家背书，口头背书不算证据。",
        "删除；如确有调查，写清样本与时间，例如 “recommended by 8 of 10 dentists in a 2026 survey (n=120)”。",
    ),
    (
        "medical grade",
        "HIGH",
        "“医疗级”无统一定义，属不可举证等级声明。",
        "改为具体材质/标准，例如 “304 stainless steel housing” 或 “meets NSF/ANSI 51”。",
    ),
    (
        "100%",
        "HIGH",
        "绝对化比例无法举证；FTC 要求声明有合理依据。",
        "写明测试条件与实测值，例如 “up to 92% of grounds blended in a 30-second lab test (2026-03)”；不要写 100%。",
    ),
    (
        "best",
        "HIGH",
        "最高级比较声明需要可验证的比较基准。",
        "改为可核查事实，例如 “rated 4.7/5 by 1,200 verified buyers”（数据必须真实且可提供）。",
    ),
    (
        "#1",
        "HIGH",
        "排名声明需要平台或第三方榜单依据，且需注明榜单与时间。",
        "删除；如确有依据，写清 “#1 in Amazon’s Blenders category, 2026-08 (source: …)”（需可复核）。",
    ),
    (
        "non-toxic",
        "HIGH",
        "“无毒”是安全声明，需要成分与检测报告支撑。",
        "删除，改为具体检测结论，例如 “passed lead and cadmium migration testing (report no. …)”。",
    ),
    (
        "eco-friendly",
        "MEDIUM",
        "泛化的环保声明无法核实，FTC 要求具体、可量化的环境收益。",
        "改为具体事实，例如 “made with 30% post-consumer recycled plastic”（需供应链证明）。",
    ),
    (
        "biodegradable",
        "HIGH",
        "可降解声明需要标准与认证，且需说明处置条件。",
        "仅在有认证时写 “certified compostable to ASTM D6400”；否则删除。",
    ),
    (
        "antibacterial",
        "HIGH",
        "抗菌属 EPA 监管的农药类声明，无 EPA 注册不得用于美区销售文案。",
        "删除；改为物理清洁表述，例如 “wipes away everyday grime”。",
    ),
    (
        "waterproof",
        "HIGH",
        "防水是性能安全声明；未声明 IP 等级与测试报告，不得使用。",
        "无等级时删除；有报告时改为 “IPX4 splash-resistant (tested to IEC 60529)”。",
    ),
    (
        "instantly",
        "MEDIUM",
        "“瞬间”缺少可测时间，属无法核实的速度声明。",
        "改为可测时间，例如 “in about 30 seconds” 并注明测试条件。",
    ),
    (
        "permanent",
        "HIGH",
        "永久性效果无法保证，属绝对化承诺。",
        "改为可验证寿命，例如 “lasts up to 50 washes”（需测试依据）。",
    ),
    (
        "guaranteed",
        "HIGH",
        "结果保证属高风险承诺；只能承诺具体售后政策。",
        "改为政策表述，例如 “30-day return under store policy”；不要保证使用结果。",
    ),
    (
        "premium",
        "LOW",
        "主观修饰词，无信息量，易被判为夸大。",
        "改为具体材质或工艺，例如 “double-wall Tritan cup”。",
    ),
    (
        "professional",
        "LOW",
        "主观修饰词，除非有明确职业标准，否则不可举证。",
        "改为使用场景或参数，例如 “for 12-cup batches”。",
    ),
    (
        "advanced",
        "LOW",
        "主观修饰词，无法定义“先进”的基准。",
        "改为具体技术点，例如 “six-blade stainless steel assembly”。",
    ),
    (
        "innovative",
        "LOW",
        "主观修饰词，无法举证。",
        "改为具体结构差异，例如 “removable base with a snap-on quiet shield”。",
    ),
]

RISK_ORDER = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
NO_RATING = {"none", "no", "n/a", "na", ""}
RULES_BASIS = "编写时公开口径（FTC substantiation / FDA 声明边界），不构成法律意见，发布前由合规负责人复核"


def term_pattern(term):
    segments = [part for part in re.split(r"[\s\-]+", term) if part]
    body = r"[\s\-]?".join(re.escape(segment) for segment in segments)
    return re.compile(r"(?<![A-Za-z0-9])" + body + r"(?![A-Za-z0-9])", re.IGNORECASE)


PATTERNS = [(term, risk, reason, suggestion, term_pattern(term))
            for term, risk, reason, suggestion in RULES]


def emit_error(status, message, missing=None, as_json=False, with_missing=True):
    if as_json:
        payload = {"status": status}
        if with_missing:
            payload["missing"] = list(missing or [])
        payload["message"] = message
        emit_json(payload)
    else:
        print(message)


def scan(text, ip_rating):
    hits = []
    for term, risk, reason, suggestion, pattern in PATTERNS:
        count = len(pattern.findall(text))
        if not count:
            continue
        if term == "waterproof":
            if ip_rating and ip_rating.strip().lower() not in NO_RATING:
                risk = "MEDIUM"
                reason = (
                    "已声明 IP 等级 {}；仍需测试报告与产品标识一致，"
                    "且 “waterproof” 表述强于等级本身。".format(ip_rating)
                )
                suggestion = "改为精确等级表述，例如 “IPX4 splash-resistant (tested to IEC 60529)”。"
            else:
                reason = "防水是性能安全声明；未声明 IP 等级与测试报告，不得使用。"
                suggestion = "无等级时删除；有报告时改为 “IPX4 splash-resistant (tested to IEC 60529)”。"
        hits.append(
            {
                "term": term,
                "risk": risk,
                "count": count,
                "reason": reason,
                "suggestion": suggestion,
            }
        )

    hits.sort(key=lambda hit: (RISK_ORDER[hit["risk"]], -hit["count"], hit["term"]))
    counts = {"HIGH": 0, "MEDIUM": 0, "LOW": 0}
    for hit in hits:
        counts[hit["risk"]] += 1
    if counts["HIGH"]:
        verdict = "FAIL"
    elif counts["MEDIUM"] or counts["LOW"]:
        verdict = "WARN"
    else:
        verdict = "PASS"
    return verdict, counts, hits


def render_text(source, text, ip_rating, verdict, counts, hits):
    lines = [
        "FTC / FDA 声明扫描",
        "来源: {}（{} 字符，IP 等级: {}）".format(source, len(text), ip_rating),
    ]
    if not hits:
        lines.append("[PASS] 未命中高风险词")
    for hit in hits:
        lines.append("[{}] {} ×{}".format(hit["risk"], hit["term"], hit["count"]))
        lines.append("  原因: {}".format(hit["reason"]))
        lines.append("  建议: {}".format(hit["suggestion"]))
    lines.append("")
    lines.append(
        "总判定: {} (HIGH {} / MEDIUM {} / LOW {})".format(
            verdict, counts["HIGH"], counts["MEDIUM"], counts["LOW"]
        )
    )
    lines.append("口径: 关键词级筛查，不替代法律意见；发布前由合规负责人复核。")
    print("\n".join(lines))


def read_text_file(path):
    try:
        with open(path, "r", encoding="utf-8-sig") as handle:
            return handle.read()
    except UnicodeDecodeError:
        return None


def main(argv):
    as_json = "--json" in argv
    set_json_mode(as_json)

    source_file = None
    text = None
    ip_rating = "none"
    index = 0
    while index < len(argv):
        arg = argv[index]
        if arg == "--json":
            index += 1
            continue
        if arg in ("--file", "--text", "--ip-rating"):
            if index + 1 >= len(argv):
                print("参数错误：{} 需要值".format(arg))
                return 2
            value = argv[index + 1]
            if arg == "--file":
                source_file = value
            elif arg == "--text":
                text = value
            else:
                ip_rating = value
            index += 2
            continue
        print("参数错误：无法识别的参数 {}".format(arg))
        return 2

    if source_file is not None and text is not None:
        emit_error(
            "INPUT_MISSING",
            "[INPUT_MISSING] --file 与 --text 只能二选一",
            ["file|text"],
            as_json,
        )
        return 2
    if source_file is None and text is None:
        emit_error(
            "INPUT_MISSING",
            "[INPUT_MISSING] 缺少 --file 或 --text",
            ["file|text"],
            as_json,
        )
        return 2

    if text is not None and text == "":
        emit_error(
            "INPUT_MISSING",
            "[INPUT_MISSING] 缺少 --file 或 --text",
            ["file|text"],
            as_json,
        )
        return 2

    if source_file is not None:
        if not os.path.isfile(source_file):
            emit_error(
                "INPUT_MISSING",
                "[INPUT_MISSING] 找不到文件: {}".format(source_file),
                ["file"],
                as_json,
            )
            return 2
        text = read_text_file(source_file)
        if text is None:
            emit_error(
                "INPUT_ERROR",
                "[INPUT_ERROR] 文件不是 UTF-8 文本: {}".format(source_file),
                [],
                as_json,
                with_missing=False,
            )
            return 2
        source = source_file
    else:
        source = "text"

    verdict, counts, hits = scan(text, ip_rating)

    if as_json:
        emit_json(
            {
                "verdict": verdict,
                "source": source,
                "ip_rating": ip_rating,
                "char_count": len(text),
                "counts": counts,
                "hits": hits,
                "meta": {"rules_basis": RULES_BASIS},
            }
        )
    else:
        render_text(source, text, ip_rating, verdict, counts, hits)

    return 1 if counts["HIGH"] else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
