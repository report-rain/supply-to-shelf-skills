#!/usr/bin/env python3
"""Deterministic five-dimension opportunity score for an Amazon category export.

Errors are written to stdout and exit 2 (see docs/spec/01_selection.md).
"""

import argparse
import csv
import json
import math
import statistics
import sys

REQUIRED_COLUMNS = ["asin", "price", "monthly_sales", "reviews", "rating", "seller"]
OPTIONAL_COLUMNS = ["compliance_risk", "supply_feasibility"]
WEIGHTS = {"demand": 30, "competition": 25, "profit": 25, "compliance": 10, "supply": 10}
DIMENSION_ORDER = ["demand", "competition", "profit", "compliance", "supply"]

HEADER = """# 美国站选品机会评分

## 0. 权重与口径

- 固定权重：**需求 30 / 竞争 25 / 利润 25 / 合规 10 / 供给 10**
- 目标价：{target}；工厂成本：{factory}；平台费估算：referral {fee:.1f}% + FBA 估算 {fba}
- 利润维度净利率：{margin:.1f}%（该项对所有 ASIN 相同，用于判断项目可行性，不用于横向比较 ASIN）
- verdict：Go ≥ 75 / Watch 60–74 / No-Go < 60
- 评分来自脚本确定性公式，不依赖模型主观判断"""

FORMULA = """## 3. 评分口径

- 需求 30：月销/2000 饱和占 60%，月销 ÷ 累计评论（≥0.5 视为动销强）占 40%
- 竞争 25：评论（1000 条归零）50%、头部卖家份额（60% 归零）25%、评分（4.8 归零）25%
- 利润 25：净利率 ÷ 30% 封顶；平台费为估算值，实际按卖家中心费率复核
- 合规 10：compliance_risk 0–5，0 得 100 分、5 得 0 分
- 供给 10：supply_feasibility 0–5，5 得 100 分、0 得 0 分

> 提醒：①评论门槛决定冷启动预算；②价格带是观察结果不是定价指令；③合规风险 ≥4 或认证缺失时按一票否决，不因总分过 75 而放行。"""


def fail(message):
    sys.stdout.write("[INPUT_MISSING] {}\n".format(message))
    raise SystemExit(2)


def money(value):
    return "${:,.2f}".format(value)


def round2(value):
    return round(value + 0.0, 2)


def clamp(value):
    return max(0.0, min(1.0, value))


def clean_number(raw):
    return raw.strip().replace(",", "").replace("$", "").replace("%", "")


def read_csv(path):
    try:
        with open(path, "r", encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.reader(handle))
    except FileNotFoundError:
        fail("找不到输入文件：{}".format(path))
    except OSError as exc:
        fail("无法读取文件：{}（{}）".format(path, exc))
    except UnicodeDecodeError as exc:
        fail("文件编码无法按 UTF-8 解析：{}（{}）".format(path, exc))

    if not rows or not any(cell.strip() for cell in rows[0]):
        fail("CSV 没有表头，无法确定列。")
    header = [cell.strip() for cell in rows[0]]

    missing = [column for column in REQUIRED_COLUMNS if column not in header]
    if missing:
        fail(
            "CSV 缺少必需列：{}\n"
            "必需列：{}\n"
            "可选列：compliance_risk（缺省 2.0/5）、supply_feasibility（缺省 3.0/5）".format(
                ", ".join(missing), ", ".join(REQUIRED_COLUMNS)
            )
        )
    if not rows[1:]:
        fail("CSV 没有数据行。")
    return header, rows[1:]


def percentile(values, pct):
    if not values:
        return 0.0
    ordered = sorted(values)
    k = (len(ordered) - 1) * pct / 100.0
    low = int(math.floor(k))
    high = int(math.ceil(k))
    if low == high:
        return ordered[low]
    return ordered[low] * (high - k) + ordered[high] * (k - low)


def parse_rows(header, rows):
    index = {name: position for position, name in enumerate(header)}
    errors = []
    defaults = []
    records = []

    has_risk = "compliance_risk" in index
    has_supply = "supply_feasibility" in index
    if has_risk:
        defaults.append("检测到 compliance_risk 列：按行读取（0–5，数值越高风险越高）")
    else:
        defaults.append(
            "[默认值提示] 未找到 compliance_risk 列 → 全部按 2.0/5（合规中性）计，需 03 复核"
        )
    if has_supply:
        defaults.append("检测到 supply_feasibility 列：按行读取（0–5，数值越高越可行）")
    else:
        defaults.append(
            "[默认值提示] 未找到 supply_feasibility 列 → 全部按 3.0/5（供给中性）计，需核验打样/交期/MOQ"
        )

    for offset, row in enumerate(rows):
        row_number = offset + 2
        if all(not cell.strip() for cell in row):
            continue
        if len(row) < len(header):
            row = row + [""] * (len(header) - len(row))

        errors_here = 0
        asin = row[index["asin"]].strip()
        seller = row[index["seller"]].strip()
        if not asin:
            errors.append("第 {} 行 asin 为空".format(row_number))
            errors_here += 1
        if not seller:
            errors.append("第 {} 行 seller 为空".format(row_number))
            errors_here += 1

        numbers = {}
        for column in ("price", "monthly_sales", "reviews", "rating"):
            raw = row[index[column]]
            if not raw.strip():
                errors.append("第 {} 行 {} 为空".format(row_number, column))
                errors_here += 1
                continue
            try:
                value = float(clean_number(raw))
            except ValueError:
                errors.append("第 {} 行 {} 不是数字：{}".format(row_number, column, raw.strip()))
                errors_here += 1
                continue
            if not math.isfinite(value):
                errors.append("第 {} 行 {} 不是有限数值：{}".format(row_number, column, raw.strip()))
                errors_here += 1
                continue
            numbers[column] = value

        risk = 2.0
        if has_risk:
            raw = row[index["compliance_risk"]].strip()
            if raw:
                try:
                    risk = float(clean_number(raw))
                except ValueError:
                    errors.append("第 {} 行 compliance_risk 不是数字：{}".format(row_number, raw))
                    errors_here += 1
                else:
                    if not math.isfinite(risk):
                        errors.append("第 {} 行 compliance_risk 不是有限数值：{}".format(row_number, raw))
                        errors_here += 1
            else:
                defaults.append("第 {} 行 compliance_risk 为空 → 按 2.0 计".format(row_number))

        supply = 3.0
        if has_supply:
            raw = row[index["supply_feasibility"]].strip()
            if raw:
                try:
                    supply = float(clean_number(raw))
                except ValueError:
                    errors.append(
                        "第 {} 行 supply_feasibility 不是数字：{}".format(row_number, raw)
                    )
                    errors_here += 1
                else:
                    if not math.isfinite(supply):
                        errors.append(
                            "第 {} 行 supply_feasibility 不是有限数值：{}".format(row_number, raw)
                        )
                        errors_here += 1
            else:
                defaults.append("第 {} 行 supply_feasibility 为空 → 按 3.0 计".format(row_number))

        if errors_here:
            continue
        title = row[index["title"]].strip() if "title" in index else ""
        records.append(
            {
                "asin": asin,
                "title": title,
                "seller": seller,
                "price": numbers["price"],
                "monthly_sales": numbers["monthly_sales"],
                "reviews": int(numbers["reviews"]),
                "rating": numbers["rating"],
                "compliance_risk": risk,
                "supply_feasibility": supply,
            }
        )

    if errors:
        fail(
            "以下行无法解析，已停止：\n"
            + "\n".join("  - " + line for line in errors)
        )
    return records, defaults


def score_rows(records, factory_cost, target_price, fee_pct, fba):
    referral = target_price * fee_pct / 100.0
    profit_usd = target_price - factory_cost - referral - fba
    margin_pct = profit_usd / target_price * 100.0 if target_price else -100.0
    profit_score = clamp(margin_pct / 30.0) * 100.0

    total_sales = sum(record["monthly_sales"] for record in records)
    top_seller_sales = 0.0
    if total_sales > 0:
        by_seller = {}
        for record in records:
            by_seller[record["seller"]] = by_seller.get(record["seller"], 0.0) + record["monthly_sales"]
        top_seller_sales = max(by_seller.values())
    top_seller_share = top_seller_sales / total_sales if total_sales > 0 else 0.0

    rows = []
    for record in records:
        sales_component = clamp(record["monthly_sales"] / 2000.0)
        momentum = record["monthly_sales"] / max(record["reviews"], 1)
        momentum_component = clamp(momentum / 0.5)
        demand = 100.0 * (0.60 * sales_component + 0.40 * momentum_component)

        review_component = clamp(1 - record["reviews"] / 1000.0) * 100.0
        seller_component = clamp(1 - top_seller_share / 0.60) * 100.0
        rating_component = clamp((4.80 - record["rating"]) / 0.80) * 100.0
        competition = 0.50 * review_component + 0.25 * seller_component + 0.25 * rating_component

        compliance = clamp((5.0 - record["compliance_risk"]) / 5.0) * 100.0
        supply = clamp(record["supply_feasibility"] / 5.0) * 100.0

        total = (
            WEIGHTS["demand"] * demand
            + WEIGHTS["competition"] * competition
            + WEIGHTS["profit"] * profit_score
            + WEIGHTS["compliance"] * compliance
            + WEIGHTS["supply"] * supply
        ) / 100.0
        if total >= 75:
            verdict = "Go"
        elif total >= 60:
            verdict = "Watch"
        else:
            verdict = "No-Go"

        rows.append(
            {
                "asin": record["asin"],
                "title": record["title"],
                "seller": record["seller"],
                "price": round2(record["price"]),
                "monthly_sales": round(record["monthly_sales"], 0) + 0.0,
                "reviews": record["reviews"],
                "rating": round2(record["rating"]),
                "compliance_risk": round2(record["compliance_risk"]),
                "supply_feasibility": round2(record["supply_feasibility"]),
                "score": round(total, 1),
                "dimensions": {
                    "demand": round(demand, 1),
                    "competition": round(competition, 1),
                    "profit": round(profit_score, 1),
                    "compliance": round(compliance, 1),
                    "supply": round(supply, 1),
                },
                "verdict": verdict,
            }
        )

    rows.sort(key=lambda row: (-row["score"], -row["monthly_sales"], row["asin"]))
    return rows, profit_usd, margin_pct, top_seller_share


def summarize(rows, target_price):
    counts = {"Go": 0, "Watch": 0, "No-Go": 0}
    for row in rows:
        counts[row["verdict"]] += 1

    averages = {}
    for dimension in DIMENSION_ORDER:
        average = sum(row["dimensions"][dimension] for row in rows) / len(rows)
        averages[dimension] = round(average, 1)

    if counts["Go"]:
        candidates = [row for row in rows if row["verdict"] == "Go"]
        basis = "Go 候选价格 P25–P75"
    elif counts["Watch"]:
        candidates = [row for row in rows if row["verdict"] == "Watch"]
        basis = "Watch 候选价格 P25–P75"
    else:
        candidates = list(rows)
        basis = "全样本价格 P25–P75"

    prices = [row["price"] for row in candidates]
    low = round2(percentile(prices, 25))
    high = round2(percentile(prices, 75))
    median = round2(statistics.median(prices))
    if low == high:
        low = round2(low * 0.95)
        high = round2(high * 1.05)

    band = {"low": low, "high": high, "median": median, "basis": basis}
    return counts, band, averages


def veto_reasons(rows, averages):
    ranked = sorted(DIMENSION_ORDER, key=lambda name: averages[name])
    total_sales = sum(row["monthly_sales"] for row in rows)
    expensive = [row for row in rows if row["reviews"] >= 500]
    share_500 = (
        sum(row["monthly_sales"] for row in expensive) / total_sales * 100 if total_sales else 0.0
    )
    median_reviews = statistics.median([row["reviews"] for row in rows])
    by_seller = {}
    for row in rows:
        by_seller[row["seller"]] = by_seller.get(row["seller"], 0.0) + row["monthly_sales"]
    top_share = max(by_seller.values()) / total_sales * 100 if total_sales else 0.0

    templates = {
        "demand": "需求（30 分项均值 {avg:.1f}）：月销/2000 饱和与动销强度双低，需求侧支撑不足",
        "competition": (
            "竞争（25 分项均值 {avg:.1f}）：≥500 评论商品占样本销量 {share:.1f}%，"
            "中位评论数 {median}；头部卖家销量份额 {top:.1f}%，新链接冷启动的评论门槛与广告成本被低估"
        ),
        "profit": "利润（25 分项均值 {avg:.1f}）：净利率低于 30% 封顶线，扣掉广告与退货后可能为负",
        "compliance": (
            "合规（10 分项均值 {avg:.1f}）：compliance_risk 缺省 2.0/5 只代表“未核验”而非“低风险”；"
            "认证、UN38.3、Prop 65、商标/专利任一未过，按一票否决处理"
        ),
        "supply": (
            "供给（10 分项均值 {avg:.1f}）：supply_feasibility 缺省 3.0/5 只代表“未核验”；"
            "打样、起订量、交期、良率与备选工厂均未验证"
        ),
    }
    reasons = []
    for name in ranked[:3]:
        reasons.append(
            templates[name].format(
                avg=averages[name], share=share_500, median="%g" % median_reviews, top=top_share
            )
        )
    return reasons


def truncate(text, limit):
    if len(text) > limit:
        return text[: limit - 3] + "..."
    return text


def render(rows, meta, defaults, counts, band, averages, reasons):
    lines = []
    lines.append(
        HEADER.format(
            target=money(meta["target_price_usd"]),
            factory=money(meta["factory_cost_usd"]),
            fee=meta["platform_fee_pct"],
            fba=money(meta["fba_estimate_usd"]),
            margin=meta["profit_margin_pct"],
        )
    )
    if defaults:
        lines.append("")
        lines.append("**缺列与默认值提示**")
        lines.append("")
        for note in defaults:
            lines.append("- " + note)
    lines.append("")
    lines.append("## 1. 逐 ASIN 评分")
    lines.append("")
    lines.append(
        "| ASIN | 标题 | 价格 | 月销 | 评论 | 评分 | 需求 | 竞争 | 利润 | 合规 | 供给 | 结论 |"
    )
    lines.append("|---|---|---|---|---|---|---|---|---|---|---|---|")
    for row in rows:
        dimensions = row["dimensions"]
        lines.append(
            "| {} | {} | {} | {} | {} | {} | {:.1f} | {:.1f} | {:.1f} | {:.1f} | {:.1f} | {} |".format(
                row["asin"],
                truncate(row["title"], 34),
                money(row["price"]),
                int(row["monthly_sales"]),
                row["reviews"],
                "**{:.1f}**".format(row["score"]),
                dimensions["demand"],
                dimensions["competition"],
                dimensions["profit"],
                dimensions["compliance"],
                dimensions["supply"],
                row["verdict"],
            )
        )
    lines.append("")
    lines.append("## 2. 汇总")
    lines.append("")
    lines.append(
        "- 结论分布：Go {} / Watch {} / No-Go {}（共 {} 个 ASIN）".format(
            counts["Go"], counts["Watch"], counts["No-Go"], len(rows)
        )
    )
    lines.append(
        "- 建议切入价格带：**{}–{}**（中位 {}，口径：{}）".format(
            money(band["low"]), money(band["high"]), money(band["median"]), band["basis"]
        )
    )
    lines.append("- Top3 候选：")
    for row in rows[:3]:
        lines.append(
            "  - {} {}｜{}｜{:.1f} 分｜{}".format(
                row["asin"], row["title"], money(row["price"]), row["score"], row["verdict"]
            )
        )
    lines.append("")
    lines.append("### 三条否决理由（按最弱维度排序）")
    lines.append("")
    for position, reason in enumerate(reasons, start=1):
        lines.append("{}. {}".format(position, reason))
    lines.append("")
    lines.append(FORMULA)
    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser(description="美国站选品机会评分（五维确定性评分）")
    parser.add_argument("--file", help="Amazon 类目导出 CSV")
    parser.add_argument("--factory-cost-usd", type=float, help="工厂成本（USD/件，含税出厂价换算）")
    parser.add_argument("--target-price", type=float, help="目标零售价（USD）")
    parser.add_argument(
        "--platform-fee-pct", type=float, default=15.0, help="平台费估算百分比，默认 15（Amazon US referral）"
    )
    parser.add_argument("--fba-estimate", type=float, default=4.75, help="FBA 费估算（USD/件），默认 4.75")
    parser.add_argument("--json", action="store_true", help="输出 JSON")
    args = parser.parse_args()

    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass

    missing_args = []
    if args.file is None:
        missing_args.append("--file")
    if args.factory_cost_usd is None:
        missing_args.append("--factory-cost-usd")
    if args.target_price is None:
        missing_args.append("--target-price")
    if missing_args:
        fail(
            "缺少参数：{}\n"
            "最小输入：--file <csv> --factory-cost-usd <usd> --target-price <usd>".format(
                ", ".join(missing_args)
            )
        )
    if args.target_price <= 0:
        fail("--target-price 必须 > 0")
    if args.factory_cost_usd < 0:
        fail("--factory-cost-usd 不能为负")

    header, data = read_csv(args.file)
    records, defaults = parse_rows(header, data)
    if not records:
        fail("CSV 没有数据行。")

    rows, profit_usd, margin_pct, top_share = score_rows(
        records, args.factory_cost_usd, args.target_price, args.platform_fee_pct, args.fba_estimate
    )
    counts, band, averages = summarize(rows, args.target_price)
    reasons = veto_reasons(rows, averages)

    meta = {
        "generated_by": "opportunity_score.py",
        "currency": "USD",
        "weights": dict(WEIGHTS),
        "factory_cost_usd": round2(args.factory_cost_usd),
        "target_price_usd": round2(args.target_price),
        "platform_fee_pct": args.platform_fee_pct,
        "fba_estimate_usd": args.fba_estimate,
        "profit_usd": round2(profit_usd),
        "profit_margin_pct": round(margin_pct, 1),
        "rows": len(rows),
        "columns": header,
    }
    summary = {
        "verdict_counts": counts,
        "entry_price_band": band,
        "top3": [
            {
                "asin": row["asin"],
                "title": row["title"],
                "price": row["price"],
                "score": row["score"],
                "verdict": row["verdict"],
            }
            for row in rows[:3]
        ],
        "dimension_averages": averages,
        "triple_veto_reasons": reasons,
    }
    payload = {"meta": meta, "defaults": defaults, "rows": rows, "summary": summary}

    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        sys.stdout.write(render(rows, meta, defaults, counts, band, averages, reasons))
    return 0


if __name__ == "__main__":
    sys.exit(main())
