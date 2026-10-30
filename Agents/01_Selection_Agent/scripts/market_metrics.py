#!/usr/bin/env python3
"""Market sizing report for a normalized.json export.

Reads {"items": [...]} (or a bare array) and prints an equal-width price-band
report. Input errors exit 2 with a message on stdout (see docs/spec/01_selection.md).
"""

import argparse
import json
import math
import statistics
import sys

REQUIRED_FIELDS = [
    "asin",
    "title",
    "brand",
    "seller",
    "price",
    "monthly_sales",
    "monthly_revenue",
    "reviews",
    "rating",
    "bsr",
    "fulfillment",
]
STRING_FIELDS = ["asin", "title", "brand", "seller", "fulfillment"]
NUMBER_FIELDS = ["price", "monthly_sales", "monthly_revenue", "reviews", "rating", "bsr"]
INT_RENDER_FIELDS = {"reviews", "bsr"}

REVIEW_BUCKETS = [
    ("<50", lambda n: n < 50),
    ("50–99", lambda n: 50 <= n < 100),
    ("100–499", lambda n: 100 <= n < 500),
    ("≥500", lambda n: n >= 500),
]

CR3_WARNING = "⚠️ 主体数 ≤ 3，**CR3 无意义**（几乎必然接近 100%），请改用 HHI 或直接看名单。"
CR10_WARNING = "⚠️ 主体数 ≤ 10，**CR10 无意义**（几乎必然接近 100%），请改用 HHI 或直接看名单。"
TROUGH_NOTE = (
    "> 波谷 = 相邻价格带销量明显掉档，说明该价位供给/需求出现断层；"
    "是差异化切入或重新定价的候选位置，不等于可以定价的位置。"
)
FOOTER = "> 数据为第三方估算/类目导出，下单前用品牌数与真实评论门槛二次核对；价格带是观察结果，不是该定这个价。"
SAME_PRICE_ZERO_SALES_WARNING = (
    "同价样本且总月销量为 0，销量份额无法计算；价格带输出已置空。"
)


def fail(message):
    sys.stdout.write("[INPUT_MISSING] {}\n".format(message))
    raise SystemExit(2)


def round2(value):
    return round(value + 0.0, 2)


def money(value):
    return "${:,.2f}".format(value)


def raw_number(value):
    """Cast a JSON cell to float, tolerating $/,/% decoration."""
    if isinstance(value, bool):
        raise ValueError("bool")
    if isinstance(value, (int, float)):
        number = float(value)
    elif isinstance(value, str):
        text = value.strip().replace(",", "").replace("$", "").replace("%", "")
        if text == "":
            raise ValueError("empty")
        number = float(text)
    else:
        raise ValueError("type")
    if not math.isfinite(number):
        raise ValueError("non-finite")
    return number


def load_items(path):
    try:
        with open(path, "r", encoding="utf-8-sig") as handle:
            payload = json.load(handle)
    except FileNotFoundError:
        fail("找不到输入文件：{}".format(path))
    except (OSError, ValueError) as exc:
        fail("无法解析 JSON：{}（{}）".format(path, exc))

    if isinstance(payload, dict):
        items = payload.get("items")
    elif isinstance(payload, list):
        items = payload
    else:
        items = None
    if not isinstance(items, list) or not items:
        fail("items 缺失或为空：需要非空数组。")
    return items


def validate_items(items):
    problems = []
    rows = []
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            problems.append("第 {} 条不是对象".format(index + 1))
            continue
        broken = []
        for field in STRING_FIELDS:
            value = item.get(field)
            if not isinstance(value, str) or not value.strip():
                broken.append(field)
        for field in NUMBER_FIELDS:
            if field in broken:
                continue
            try:
                raw_number(item.get(field))
            except ValueError:
                broken.append(field)
        if broken:
            label = item.get("asin")
            if not isinstance(label, str) or not label.strip():
                label = "#{}".format(index + 1)
            problems.append("{} 缺少/非法字段：{}".format(label, ", ".join(sorted(set(broken)))))
            continue
        row = {"asin": item["asin"].strip(), "title": item["title"].strip()}
        for field in ("brand", "seller", "fulfillment"):
            row[field] = item[field].strip()
        for field in NUMBER_FIELDS:
            row[field] = raw_number(item.get(field))
        row["attributes"] = parse_attributes(item.get("attributes"))
        rows.append(row)
    if problems:
        fail(
            "以下商品字段不完整，已停止计算（不猜测）：\n"
            + "\n".join("  - " + line for line in problems)
            + "\n所需字段：" + ", ".join(REQUIRED_FIELDS)
        )
    return rows


def parse_attributes(value):
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return [str(part).strip() for part in value if str(part).strip()]
    if isinstance(value, str):
        text = value.replace("|", ",").replace(";", ",")
        return [part.strip() for part in text.split(",") if part.strip()]
    return []


def market_block(rows):
    prices = [row["price"] for row in rows]
    return {
        "items": len(rows),
        "total_monthly_sales": round2(sum(row["monthly_sales"] for row in rows)),
        "total_monthly_revenue": round2(sum(row["monthly_revenue"] for row in rows)),
        "avg_price": round2(sum(prices) / len(prices)),
        "median_price": round2(statistics.median(prices)),
        "min_price": round2(min(prices)),
        "max_price": round2(max(prices)),
    }


def concentration(rows, key, total_sales):
    entities = {}
    for row in rows:
        name = row[key]
        bucket = entities.setdefault(name, {"sales": 0.0, "revenue": 0.0, "items": 0})
        bucket["sales"] += row["monthly_sales"]
        bucket["revenue"] += row["monthly_revenue"]
        bucket["items"] += 1

    ordered = sorted(entities.items(), key=lambda pair: pair[1]["sales"], reverse=True)
    shares = []
    top = []
    for name, bucket in ordered:
        share = bucket["sales"] / total_sales * 100 if total_sales else 0.0
        shares.append(share)
        top.append(
            {
                "name": name,
                "monthly_sales": round2(bucket["sales"]),
                "sales_share_pct": round2(share),
                "monthly_revenue": round2(bucket["revenue"]),
                "items": bucket["items"],
            }
        )
    return {
        "entity_count": len(ordered),
        "cr3_pct": round2(sum(shares[:3])),
        "cr10_pct": round2(sum(shares[:10])),
        "hhi": round(sum(share * share for share in shares), 1),
        "cr3_meaningful": len(ordered) > 3,
        "cr10_meaningful": len(ordered) > 10,
        "top": top,
    }


def review_thresholds(rows, total_sales):
    result = []
    for label, test in REVIEW_BUCKETS:
        members = [row for row in rows if test(row["reviews"])]
        sales = round2(sum(row["monthly_sales"] for row in members))
        result.append(
            {
                "bucket": label,
                "items": len(members),
                "items_share_pct": round(len(members) / len(rows) * 100, 1),
                "monthly_sales": sales,
                "sales_share_pct": round(sales / total_sales * 100, 1) if total_sales else 0.0,
            }
        )
    return result


def band_label(lower, upper):
    return "${:,.2f}–${:,.2f}".format(lower, upper)


def price_bands(rows, bins):
    prices = [row["price"] for row in rows]
    low, high = min(prices), max(prices)
    total_sales = sum(row["monthly_sales"] for row in rows)

    if high == low:
        members = rows
        # 同价且总销量为 0：份额无法计算，价带置空并转为业务告警（#13）
        if total_sales == 0:
            return []
        return [
            {
                "index": 1,
                "lower": round2(low),
                "upper": round2(low),
                "label": "${:,.2f}".format(low),
                "items": len(members),
                "monthly_sales": round2(sum(row["monthly_sales"] for row in members)),
                "monthly_revenue": round2(sum(row["monthly_revenue"] for row in members)),
                "sales_share_pct": round(
                    sum(row["monthly_sales"] for row in members) / total_sales * 100, 1
                ),
            }
        ]

    width = (high - low) / bins
    bands = []
    for index in range(bins):
        lower = low + index * width
        upper = low + (index + 1) * width
        if index == bins - 1:
            members = [row for row in rows if lower <= row["price"] <= high]
        else:
            members = [row for row in rows if lower <= row["price"] < upper]
        sales = round2(sum(row["monthly_sales"] for row in members))
        bands.append(
            {
                "index": index + 1,
                "lower": round2(lower),
                "upper": round2(high if index == bins - 1 else upper),
                "label": band_label(lower, high if index == bins - 1 else upper),
                "items": len(members),
                "monthly_sales": sales,
                "monthly_revenue": round2(sum(row["monthly_revenue"] for row in members)),
                "sales_share_pct": round(sales / total_sales * 100, 1) if total_sales else 0.0,
            }
        )
    return bands


def troughs(bands, threshold):
    candidates = []
    for position in range(1, len(bands)):
        previous = bands[position - 1]["monthly_sales"]
        current = bands[position]["monthly_sales"]
        if previous <= 0 or current >= previous:
            continue
        drop = (previous - current) / previous * 100
        if drop >= threshold:
            candidates.append(
                {
                    "band_index": bands[position]["index"],
                    "label": bands[position]["label"],
                    "prev_monthly_sales": previous,
                    "monthly_sales": current,
                    "drop_pct": round(drop, 1),
                    "items": bands[position]["items"],
                }
            )
    total = len(candidates)
    candidates.sort(key=lambda item: item["drop_pct"], reverse=True)
    shown = sorted(candidates[:5], key=lambda item: item["band_index"])
    return shown, total


def attribute_cross_table(rows, total_sales):
    table = {}
    for row in rows:
        for value in set(row["attributes"]):
            bucket = table.setdefault(value, {"items": 0, "sales": 0.0, "revenue": 0.0, "price": 0.0})
            bucket["items"] += 1
            bucket["sales"] += row["monthly_sales"]
            bucket["revenue"] += row["monthly_revenue"]
            bucket["price"] += row["price"]
    result = []
    for name, bucket in table.items():
        result.append(
            {
                "attribute": name,
                "items": bucket["items"],
                "monthly_sales": round2(bucket["sales"]),
                "monthly_revenue": round2(bucket["revenue"]),
                "avg_price": round2(bucket["price"] / bucket["items"]),
                "sales_share_pct": round(bucket["sales"] / total_sales * 100, 1) if total_sales else 0.0,
            }
        )
    result.sort(key=lambda item: item["monthly_sales"], reverse=True)
    return result


def top_products(rows, top):
    ordered = sorted(rows, key=lambda row: row["monthly_sales"], reverse=True)[:top]
    return [
        {
            "asin": row["asin"],
            "title": row["title"],
            "brand": row["brand"],
            "seller": row["seller"],
            "price": round2(row["price"]),
            "monthly_sales": round2(row["monthly_sales"]),
            "monthly_revenue": round2(row["monthly_revenue"]),
            "reviews": int(row["reviews"]),
            "rating": round2(row["rating"]),
            "bsr": int(row["bsr"]),
            "fulfillment": row["fulfillment"],
        }
        for row in ordered
    ]


def compute(rows, bins, top, want_attributes, threshold):
    total_sales = sum(row["monthly_sales"] for row in rows)
    market = market_block(rows)
    bands = price_bands(rows, bins)
    shown, total_troughs = troughs(bands, threshold)
    meta = {
        "generated_by": "market_metrics.py",
        "currency": "USD",
        "bins": bins,
        "trough_threshold_pct": threshold,
        "trough_candidates_total": total_troughs,
        "trough_bands_shown": len(shown),
    }
    same_price = max(row["price"] for row in rows) == min(row["price"] for row in rows)
    if same_price and total_sales == 0:
        meta["status"] = "WARNING"
        meta["warnings"] = [SAME_PRICE_ZERO_SALES_WARNING]
    payload = {
        "meta": meta,
        "market": market,
        "brand_concentration": concentration(rows, "brand", total_sales),
        "seller_concentration": concentration(rows, "seller", total_sales),
        "review_thresholds": review_thresholds(rows, total_sales),
        "price_bands": bands,
        "troughs": shown,
        "top_products": top_products(rows, top),
        "attribute_cross_table": attribute_cross_table(rows, total_sales) if want_attributes else None,
    }
    return payload


def truncate(text, limit):
    if len(text) > limit:
        return text[: limit - 3] + "..."
    return text


def render_concentration(lines, index, title, block):
    lines.append("## {}. {}".format(index, title))
    lines.append("")
    lines.append("- CR3：{:.1f}%（Top3 主体合计销量份额）".format(block["cr3_pct"]))
    lines.append("- CR10：{:.1f}%".format(block["cr10_pct"]))
    lines.append("- HHI：{:,.1f}（0–10,000，越高越集中）".format(block["hhi"]))
    lines.append("- 主体数：{}".format(block["entity_count"]))
    if not block["cr3_meaningful"]:
        lines.append("  - " + CR3_WARNING)
    if not block["cr10_meaningful"]:
        lines.append("  - " + CR10_WARNING)
    lines.append("")
    lines.append("| 主体 | 月销量 | 销量份额 | 月销售额 | 商品数 |")
    lines.append("|---|---|---|---|---|")
    for item in block["top"][:10]:
        lines.append(
            "| {} | {:,.0f} | {:.1f}% | {} | {} |".format(
                item["name"],
                item["monthly_sales"],
                item["sales_share_pct"],
                money(item["monthly_revenue"]),
                item["items"],
            )
        )
    lines.append("")


def render_report(payload, bins, top, threshold):
    lines = []
    lines.append("# 美国站类目市场测算")
    lines.append("")
    lines.append("- 样本商品数：{}".format(payload["market"]["items"]))
    lines.append("- 金额口径：USD；月销/月销售额均为样本内合计（第三方估算值，非平台官方结算数）")
    lines.append("- 集中度口径：按**月销量**计算份额；HHI 取 0–10,000")
    lines.append("")
    lines.append("## 1. 市场容量")
    lines.append("")
    lines.append("| 指标 | 数值 |")
    lines.append("|---|---|")
    lines.append("| 总月销量 | {:,.0f} 件 |".format(payload["market"]["total_monthly_sales"]))
    lines.append("| 总月销售额 | {} |".format(money(payload["market"]["total_monthly_revenue"])))
    lines.append("| 均价（简单平均） | {} |".format(money(payload["market"]["avg_price"])))
    lines.append("| 中位价 | {} |".format(money(payload["market"]["median_price"])))
    lines.append(
        "| 价格区间 | {}–{} |".format(
            money(payload["market"]["min_price"]), money(payload["market"]["max_price"])
        )
    )
    lines.append("")
    render_concentration(lines, 2, "品牌集中度", payload["brand_concentration"])
    render_concentration(lines, 3, "卖家集中度", payload["seller_concentration"])

    lines.append("## 4. 评论门槛分布")
    lines.append("")
    lines.append("| 评论数区间 | 商品数 | 商品数占比 | 月销量 | 销量占比 |")
    lines.append("|---|---|---|---|---|")
    for item in payload["review_thresholds"]:
        lines.append(
            "| {} | {} | {:.1f}% | {:,.0f} | {:.1f}% |".format(
                item["bucket"],
                item["items"],
                item["items_share_pct"],
                item["monthly_sales"],
                item["sales_share_pct"],
            )
        )
    lines.append("")

    lines.append("## 5. 价格带分布（等宽 {} 档）".format(bins))
    lines.append("")
    if not payload["price_bands"]:
        lines.append("> ⚠️ " + SAME_PRICE_ZERO_SALES_WARNING)
        lines.append("")
    lines.append("| # | 价格带 | 商品数 | 月销量 | 销量占比 | 月销售额 |")
    lines.append("|---|---|---|---|---|---|")
    for band in payload["price_bands"]:
        lines.append(
            "| {} | {} | {} | {:,.0f} | {:.1f}% | {} |".format(
                band["index"],
                band["label"],
                band["items"],
                band["monthly_sales"],
                band["sales_share_pct"],
                money(band["monthly_revenue"]),
            )
        )
    lines.append("")

    lines.append(
        "## 6. 价格带波谷候选（环比跌幅 ≥ {:.1f}%，最多 5 带）".format(threshold)
    )
    lines.append("")
    if payload["troughs"]:
        lines.append("| 价格带 | 月销量 | 环比跌幅 | 商品数 |")
        lines.append("|---|---|---|---|")
        for item in payload["troughs"]:
            lines.append(
                "| {} | {:,.0f} | {:.1f}% | {} |".format(
                    item["label"],
                    item["monthly_sales"],
                    item["drop_pct"],
                    item["items"],
                )
            )
        lines.append("")
        lines.append(TROUGH_NOTE)
    else:
        lines.append("本次样本未检测到跌幅 ≥ 阈值的相邻价格带，价格梯度相对平滑。")
    lines.append("")

    section = 7
    if payload["attribute_cross_table"] is not None:
        lines.append("## {}. 属性交叉表（可选）".format(section))
        lines.append("")
        lines.append("| 属性 | 商品数 | 月销量 | 销量占比 | 均价 | 月销售额 |")
        lines.append("|---|---|---|---|---|---|")
        for item in payload["attribute_cross_table"]:
            lines.append(
                "| {} | {} | {:,.0f} | {:.1f}% | {} | {} |".format(
                    item["attribute"],
                    item["items"],
                    item["monthly_sales"],
                    item["sales_share_pct"],
                    money(item["avg_price"]),
                    money(item["monthly_revenue"]),
                )
            )
        lines.append("")
        section += 1

    lines.append("## {}. Top {} 商品（按月销量）".format(section, len(payload["top_products"])))
    lines.append("")
    lines.append("| ASIN | 标题 | 价格 | 月销量 | 评论 | 评分 | BSR | 配送 |")
    lines.append("|---|---|---|---|---|---|---|---|")
    for item in payload["top_products"]:
        lines.append(
            "| {} | {} | {} | {:,.0f} | {} | {:.2f} | {} | {} |".format(
                item["asin"],
                truncate(item["title"], 46),
                money(item["price"]),
                item["monthly_sales"],
                item["reviews"],
                item["rating"],
                item["bsr"],
                item["fulfillment"],
            )
        )
    lines.append("")
    lines.append(FOOTER)
    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser(description="美国站类目市场测算（USD，中文报告）")
    parser.add_argument("input", help='normalized.json 路径（{"items": [...]} 或裸数组）')
    parser.add_argument("--bins", type=int, default=10, help="价格带等宽分箱数，默认 10")
    parser.add_argument("--top", type=int, default=10, help="Top 商品数量，默认 10")
    parser.add_argument(
        "--trough-threshold", type=float, default=15.0, help="波谷检测跌幅阈值（%），默认 15"
    )
    parser.add_argument("--config-fields", help="可选交叉表字段，目前支持 attributes")
    parser.add_argument("--format", choices=["md", "json", "both"], default="md", help="输出格式，默认 md")
    parser.add_argument("--json", action="store_true", help="等价于 --format json")
    args = parser.parse_args()

    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass

    if args.bins < 1:
        fail("--bins 必须 ≥ 1")
    if args.top < 1:
        fail("--top 必须 ≥ 1")

    want_attributes = False
    if args.config_fields:
        tokens = [token.strip() for token in args.config_fields.split(",") if token.strip()]
        unsupported = [token for token in tokens if token != "attributes"]
        if unsupported:
            fail("--config-fields 不支持：{}（目前仅支持 attributes）".format(", ".join(unsupported)))
        want_attributes = "attributes" in tokens

    rows = validate_items(load_items(args.input))

    if want_attributes and not any(row["attributes"] for row in rows):
        fail(
            "指定了 --config-fields attributes，但 items 中没有任何 attributes 字段。\n"
            "请补充 attributes（数组或逗号分隔字符串），或去掉该参数。"
        )

    payload = compute(rows, args.bins, args.top, want_attributes, args.trough_threshold)

    mode = "json" if args.json else args.format
    if mode == "json":
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    elif mode == "both":
        sys.stdout.write(render_report(payload, args.bins, args.top, args.trough_threshold))
        sys.stdout.write("\n--- JSON ---\n\n")
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        sys.stdout.write(render_report(payload, args.bins, args.top, args.trough_threshold))
    return 0


if __name__ == "__main__":
    sys.exit(main())
