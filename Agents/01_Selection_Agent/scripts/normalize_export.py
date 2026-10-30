#!/usr/bin/env python3
"""Category export CSV -> normalized.json (recognise columns, cast numbers, dedupe).

Input errors exit 2 and are written to stderr (see docs/spec/01_selection.md).
"""

import argparse
import csv
import json
import math
import sys
from pathlib import Path

CONTRACT_NOTE = "由 normalize_export.py 转换；销量与销售额为导出/第三方估算，不构成事实保证"

MISSING_TOKENS = {"", "-", "—", "N/A", "nan"}

# contract field -> candidate header aliases (matched case-insensitively after strip)
COLUMNS = [
    ("asin", ["asin", "ASIN"]),
    ("title", ["title", "标题", "商品标题"]),
    ("brand", ["brand", "品牌"]),
    ("seller", ["seller", "卖家", "店铺"]),
    ("price", ["price", "价格", "售价", "成交价"]),
    ("monthly_sales", ["monthly_sales", "月销量", "月销"]),
    ("monthly_revenue", ["monthly_revenue", "月销售额", "月营收"]),
    ("reviews", ["reviews", "评论数", "评价数"]),
    ("rating", ["rating", "评分", "星级"]),
    ("bsr", ["bsr", "BSR", "类目排名"]),
    ("fulfillment", ["fulfillment", "配送方式", "发货方式"]),
]

INT_FIELDS = {"monthly_sales", "monthly_revenue", "reviews", "bsr"}
STRING_FIELDS = {"asin", "title", "brand", "seller", "fulfillment"}


def fail(message):
    sys.stderr.write("[INPUT_MISSING] {}\n".format(message))
    raise SystemExit(2)


def clean_numeric(raw):
    return raw.strip().replace(",", "").replace("$", "").replace("%", "")


def resolve_columns(header):
    """Return {contract field: column index}; raise on missing columns."""
    lookup = {}
    for index, name in enumerate(header):
        key = name.strip().lower()
        if key and key not in lookup:
            lookup[key] = index

    bindings = {}
    missing = []
    for field, aliases in COLUMNS:
        found = None
        for alias in aliases:
            key = alias.strip().lower()
            if key in lookup:
                found = lookup[key]
                break
        if found is None:
            missing.append(field)
        else:
            bindings[field] = found

    if missing:
        fail("CSV 缺少列：{}；现有表头：{}".format(missing, header))
    return bindings


def parse_number(raw, field, row_number):
    text = raw.strip()
    if text in MISSING_TOKENS:
        fail("第 {} 行缺少 {}；不补数，请回导出表核对".format(row_number, field))
    cleaned = clean_numeric(raw)
    try:
        value = float(cleaned)
    except ValueError:
        fail("第 {} 行 {}='{}' 不是数字".format(row_number, field, raw))
    if not math.isfinite(value):
        fail("第 {} 行 {}='{}' 不是有限数值（NaN/Inf）".format(row_number, field, raw))
    if field in INT_FIELDS:
        return int(value)
    return value


def read_rows(path):
    try:
        with open(path, "r", encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.reader(handle))
    except FileNotFoundError:
        fail("找不到文件：{}".format(path))
    except OSError as exc:
        fail("无法读取文件：{}（{}）".format(path, exc))
    except UnicodeDecodeError as exc:
        fail("文件编码无法按 UTF-8 解析：{}（{}）".format(path, exc))
    return rows


def build_payload(source_name, items, warnings):
    return {
        "meta": {
            "source_file": source_name,
            "item_count": len(items),
            "currency": "USD",
            "note": CONTRACT_NOTE,
        },
        "items": items,
        "warnings": warnings,
    }


def attribute_list(raw):
    return [part.strip() for part in raw.split(",") if part.strip()]


def run(args):
    rows = read_rows(args.input)
    if len(rows) == 0 or not any(cell.strip() for cell in rows[0]):
        fail("CSV 没有表头")

    header = rows[0]
    bindings = resolve_columns(header)

    data_rows = rows[1:]
    if not data_rows:
        fail("CSV 没有数据行")

    items = []
    warnings = []
    seen = set()
    limit = getattr(args, "severe_revenue_gap", 0.10)

    for offset, row in enumerate(data_rows):
        row_number = offset + 2
        if not row:
            continue
        if len(row) < len(header):
            row = row + [""] * (len(header) - len(row))

        asin = row[bindings["asin"]].strip()
        if not asin:
            fail("第 {} 行 asin 为空".format(row_number))
        if asin in seen:
            warnings.append("第 {} 行 ASIN {} 重复，已保留首次出现".format(row_number, asin))
            continue
        seen.add(asin)

        item = {"asin": asin}
        for field in ("title", "brand", "seller", "fulfillment"):
            item[field] = row[bindings[field]].strip()
        for field in ("monthly_sales", "monthly_revenue", "reviews", "bsr", "rating", "price"):
            item[field] = parse_number(row[bindings[field]], field, row_number)

        expected = item["price"] * item["monthly_sales"]
        if expected != 0:
            delta = abs(item["monthly_revenue"] - expected) / expected
            if delta > limit:
                warnings.append(
                    "{} monthly_revenue={:.2f} 与 price×sales={:.2f} 偏离 >{:.0f}%，请核对导出".format(
                        asin, item["monthly_revenue"], expected, limit * 100
                    )
                )

        if args.attributes:
            item["attributes"] = attribute_list(args.attributes)
        items.append(item)

    return items, warnings


def main():
    parser = argparse.ArgumentParser(description="类目导出 CSV → normalized.json")
    parser.add_argument("input", help="类目导出 CSV")
    parser.add_argument("--output", help="输出 JSON（默认 <输入名>.normalized.json）")
    parser.add_argument(
        "--attributes",
        default="",
        help="给全部行统一打的属性标签，逗号分隔；不填则不写 attributes",
    )
    parser.add_argument(
        "--severe-revenue-gap",
        type=float,
        default=0.10,
        help="monthly_revenue 与 price×sales 偏离超过该比例时告警（默认 0.10）",
    )
    parser.add_argument("--json", action="store_true", help="仅输出 JSON 摘要")
    args = parser.parse_args()

    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass

    items, warnings = run(args)

    dest = args.output
    if dest is None:
        dest = str(Path(args.input).with_suffix(".normalized.json"))
    payload = build_payload(Path(args.input).name, items, warnings)
    try:
        with open(dest, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
    except OSError as exc:
        fail("无法写出 {}（{}）".format(dest, exc))

    if args.json:
        print(
            json.dumps(
                {"output": dest, "item_count": len(items), "warnings": warnings},
                ensure_ascii=False,
                indent=2,
            )
        )
    else:
        print("✅ 已写出 {}（{} 个 ASIN）".format(dest, len(items)))
        for warning in warnings:
            print("  ⚠️  " + warning)
        print("下一步：python scripts/market_metrics.py {} --bins 10 --top 10".format(dest))
    return 0


if __name__ == "__main__":
    sys.exit(main())
