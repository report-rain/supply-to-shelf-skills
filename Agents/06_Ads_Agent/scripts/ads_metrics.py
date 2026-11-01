#!/usr/bin/env python3
"""广告投放指标计算与诊断。

行为规格见 docs/spec/06_ads.md。只读本地报表与 02 费率元数据，不接平台 API。
错误契约沿用 shared.errors：JSON 到 stdout，人类信息到 stderr。
"""

import csv
import json
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from shared.args import CliArgumentParser
from shared.errors import emit_json, fail, run_main, set_json_mode
from shared.numbers import round2

FEE_PATH = os.path.join(ROOT, "Agents", "02_Cost_Pricing_Agent", "scripts", "us_fees.json")
SHARED_WITH = "02_Cost_Pricing_Agent/scripts/us_fees.json"

PLATFORMS = {
    "amazon_us": {
        "label": "Amazon.com US",
        "note": "Amazon US：Referral 与 FBA 费用须与 02 的 us_fees.json、卖家中心费率卡一致。",
    },
    "tiktok_us": {
        "label": "TikTok Shop US",
        "note": "TikTok Shop：以 ROAS 为主；达人佣金与平台佣金另计，未包含在本模型。",
    },
}

DISCLAIMER = "费率/阈值口径为编写时公开口径，发布前请到卖家中心与官方费率卡复核。"
MODEL_WARNING = "广告前贡献 ≤ 0：当前成本结构下无法承担广告，先回 02 调价或降本。"
CVR_MISSING = "[INPUT_MISSING] 可承受 CPC：需 --cvr（转化率 %）。"
TACOS_MISSING = "[INPUT_MISSING] TACOS：需同时提供 --ad-spend 与 --total-sales。"
RETURNS_MISSING = "[INPUT_MISSING] --returns-pct 未提供，本轮按 0% 退货预留粗算；建议补 3 与 02 对齐。"
TACOS_PAIR = "TACOS 需要 --ad-spend 与 --total-sales 同时提供。"

COLUMN_ALIASES = [
    ("campaign", ["campaign", "campaign_name", "广告名称", "广告活动", "广告组合", "计划名称"], "campaign"),
    ("impressions", ["impressions", "imps", "曝光量", "曝光", "展示量"], "impressions"),
    ("clicks", ["clicks", "点击量", "点击数", "点击"], "clicks"),
    ("spend", ["spend", "cost", "花费", "消耗", "花费金额"], "spend"),
    ("orders", ["orders", "conversions", "订单数", "订单", "成交订单"], "orders"),
    ("sales", ["sales", "gmv", "revenue", "销售额", "成交金额", "广告销售额"], "sales"),
]

REQUIRED_NAMES = ["campaign", "impressions", "clicks", "spend", "orders", "sales"]

GRADE_ORDER = {"P0": 0, "P1": 1, "P2": 2, "INFO": 3}

GLOBAL_DO_NOT_TOUCH = [
    "Listing 文案与主图：除非症状已明确指向转化承接",
    "售价与优惠：除非 02 成本模型确认仍有毛利",
    "库存与补货：与本轮广告动作无关",
]
DISCIPLINE = "一次只改一个病因；未达标不加码同一动作，3–7 天后复测。"


def load_fee_config():
    try:
        with open(FEE_PATH, "r", encoding="utf-8-sig") as handle:
            data = json.load(handle)
    except FileNotFoundError:
        fail("未找到 02 模块费率配置：{}".format(FEE_PATH), missing=[])
    except (OSError, ValueError):
        fail("02 模块费率配置无法解析：{}".format(FEE_PATH), missing=[])
    if not isinstance(data, dict):
        fail("02 模块费率配置必须是 JSON 对象：{}".format(FEE_PATH), missing=[])
    meta = data.get("_meta") if isinstance(data.get("_meta"), dict) else {}
    updated = meta.get("updated")
    if updated is None:
        updated = "[INPUT_MISSING] _meta.updated"
    sources = meta.get("sources")
    if sources is None:
        sources = []
    return {
        "path": FEE_PATH,
        "updated": updated,
        "sources": sources,
        "shared_with": SHARED_WITH,
    }


def validate_calc(args):
    if args.price <= 0:
        fail("--price 必须大于 0。", missing=[])
    if args.product_cost < 0:
        fail("--product-cost 必须大于等于 0。", missing=[])
    if not (0 < args.referral <= 100):
        fail("--referral 必须是 0–100 的百分比。", missing=[])
    if args.fba_fee < 0:
        fail("--fba-fee 必须大于等于 0。", missing=[])
    if not (0 < args.target_acos < 100):
        fail("--target-acos 必须在 0–100 之间（不含端点）。", missing=[])
    if args.ads_pct < 0:
        fail("--ads-pct 必须大于等于 0。", missing=[])
    if args.returns_pct < 0:
        fail("--returns-pct 必须大于等于 0。", missing=[])
    if args.cvr is not None and not (0 < args.cvr <= 100):
        fail("--cvr 必须是 0–100 的百分比。", missing=[])
    if args.ad_spend is not None or args.total_sales is not None:
        if args.ad_spend is None or args.total_sales is None:
            pass
        elif args.total_sales <= 0:
            fail("--total-sales 必须大于 0。", missing=[])


def build_cost_model(args):
    price = args.price
    referral_fee = price * args.referral / 100
    returns_provision = price * args.returns_pct / 100
    planned_ad_provision = price * args.ads_pct / 100
    pre_ad = price - args.product_cost - referral_fee - args.fba_fee - returns_provision
    break_even_acos = pre_ad / price
    margin_pct = round2(break_even_acos * 100)
    after_planned = round2(pre_ad - planned_ad_provision)
    break_even_roas = round2(price / pre_ad) if pre_ad > 0 else None
    target_roas = round2(100 / args.target_acos)
    affordable_cpc = None
    if args.cvr is not None:
        affordable_cpc = round2(price * (args.cvr / 100) * (args.target_acos / 100))
    tacos = None
    tacos_pct = None
    if args.ad_spend is not None and args.total_sales is not None and args.total_sales > 0:
        tacos_ratio = args.ad_spend / args.total_sales
        tacos = round(tacos_ratio, 4)
        tacos_pct = round2(tacos_ratio * 100)
    warning = MODEL_WARNING if pre_ad <= 0 else None
    return {
        "price": price,
        "product_cost": args.product_cost,
        "referral_pct": float(args.referral),
        "referral_fee": round2(referral_fee),
        "fba_fee": float(args.fba_fee),
        "returns_pct": float(args.returns_pct),
        "returns_provision": round2(returns_provision),
        "planned_ads_pct": float(args.ads_pct),
        "planned_ad_provision": round2(planned_ad_provision),
        "pre_ad_contribution": round2(pre_ad),
        "pre_ad_margin_pct": margin_pct,
        "contribution_after_planned_ads": after_planned,
        "break_even_acos": round(break_even_acos, 4),
        "break_even_acos_pct": round2(break_even_acos * 100),
        "break_even_roas": break_even_roas,
        "target_acos_pct": float(args.target_acos),
        "target_roas": target_roas,
        "cvr_pct": float(args.cvr) if args.cvr is not None else None,
        "affordable_cpc": affordable_cpc,
        "tacos": tacos,
        "tacos_pct": tacos_pct,
        "model_warning": warning,
    }


def calc_missing(args):
    missing = []
    if args.cvr is None:
        missing.append(CVR_MISSING)
    if args.ad_spend is None or args.total_sales is None:
        missing.append(TACOS_MISSING)
    return missing


def run_calc(args):
    validate_calc(args)
    fee_config = load_fee_config()
    metrics = build_cost_model(args)
    platform = PLATFORMS[args.platform]
    payload = {
        "mode": "calc",
        "platform": args.platform,
        "platform_label": platform["label"],
        "currency": "USD",
        "metrics": metrics,
        "missing": calc_missing(args),
        "platform_note": platform["note"],
        "fee_config": fee_config,
        "disclaimer": DISCLAIMER,
    }
    if args.json:
        emit_json(payload)
    else:
        render_calc_text(payload)
    return 0


def render_calc_text(payload):
    m = payload["metrics"]
    lines = [
        "广告盈亏线 · {} · {}".format(payload["platform_label"], payload["currency"]),
        "售价 {:.2f} ｜ 产品成本 {:.2f} ｜ Referral {:.2f}% = {:.2f} ｜ FBA {:.2f}".format(
            m["price"], m["product_cost"], m["referral_pct"], m["referral_fee"], m["fba_fee"]),
        "退货预留 {:.2f}% = {:.2f} ｜ 计划广告预留 {:.2f}% = {:.2f}".format(
            m["returns_pct"], m["returns_provision"], m["planned_ads_pct"], m["planned_ad_provision"]),
        "广告前贡献 {:.2f} （占售价 {:.2f}%）".format(m["pre_ad_contribution"], m["pre_ad_margin_pct"]),
        "盈亏线 ACOS {:.2f}% ｜ 盈亏线 ROAS {}".format(
            m["break_even_acos_pct"],
            "-" if m["break_even_roas"] is None else "{:.2f}".format(m["break_even_roas"])),
        "目标 ACOS {:.2f}% ｜ 目标 ROAS {:.2f}".format(m["target_acos_pct"], m["target_roas"]),
    ]
    if m["affordable_cpc"] is not None:
        lines.append("可承受 CPC {:.2f}（售价 × CVR {:.2f}% × 目标 ACOS）".format(
            m["affordable_cpc"], m["cvr_pct"]))
    if m["tacos_pct"] is not None:
        lines.append("TACOS {:.2f}%（总广告花费 ÷ 总销售额）".format(m["tacos_pct"]))
    lines.extend(payload["missing"])
    if m["model_warning"]:
        lines.append(m["model_warning"])
    lines.append("平台提示：{}".format(payload["platform_note"]))
    lines.append("口径：{}".format(payload["disclaimer"]))
    lines.append("费率来源：{} (_meta.updated={})".format(
        payload["fee_config"]["path"], payload["fee_config"]["updated"]))
    print("\n".join(lines))


# ---- diagnose ----
def clean_number(raw):
    text = str(raw).strip().replace("$", "").replace("USD", "").replace(" ", "")
    if text in ("", "-", "—", "N/A", "n/a", "nan", "NaN"):
        return None
    sign = 1
    if text.startswith("-"):
        sign = -1
        text = text[1:]
    if "," in text and "." in text:
        if text.rfind(",") > text.rfind("."):
            text = text.replace(".", "").replace(",", ".")
        else:
            text = text.replace(",", "")
    elif "," in text:
        head, _, tail = text.rpartition(",")
        if len(tail) == 3:
            text = head + "." + tail
        else:
            text = text.replace(",", "")
    try:
        return sign * float(text)
    except ValueError:
        return None


def resolve_columns(header):
    stripped = [cell.strip().lower() for cell in header]
    resolved = {}
    for name, aliases, _ in COLUMN_ALIASES:
        for alias in aliases:
            key = alias.lower()
            if key in stripped:
                resolved[name] = stripped.index(key)
                break
    return resolved


def read_report(path):
    if not os.path.isfile(path):
        fail("找不到广告报表：{}".format(path), missing=["file"])
    try:
        handle = open(path, "r", encoding="utf-8-sig", newline="")
    except OSError:
        fail("找不到广告报表：{}".format(path), missing=["file"])
    with handle:
        reader = csv.reader(handle)
        try:
            header = next(reader)
        except StopIteration:
            fail("广告报表没有数据行：{}".format(path), missing=["file"])
        rows = []
        for row in reader:
            if not row or all(cell.strip() == "" for cell in row):
                continue
            rows.append((reader.line_num, row))
    if not rows:
        fail("广告报表没有数据行：{}".format(path), missing=["file"])
    return header, rows


def validate_columns(header):
    resolved = resolve_columns(header)
    missing = [name for name in REQUIRED_NAMES if name not in resolved]
    if missing:
        fail(
            "广告报表缺少列：{}。可用列：{}；需 {}（或对应中文列）。".format(
                "、".join(missing),
                ", ".join(cell.strip() for cell in header),
                ", ".join(REQUIRED_NAMES),
            ),
            missing=missing,
        )
    return resolved


def cell(row, index):
    if index is None or index >= len(row):
        return ""
    return row[index]


def parse_campaign_rows(header, rows, resolved):
    campaigns = []
    for line_no, row in rows:
        name = cell(row, resolved["campaign"]).strip() or "未命名"
        values = {}
        for field in ("impressions", "clicks", "orders"):
            value = clean_number(cell(row, resolved[field]))
            if value is None or value < 0:
                fail("第 {} 行 {} 为空或非法。".format(line_no, field), missing=[])
            values[field] = int(round(value))
        for field in ("spend", "sales"):
            value = clean_number(cell(row, resolved[field]))
            if value is None or value < 0:
                fail("第 {} 行 {} 为空或非法。".format(line_no, field), missing=[])
            values[field] = value
        campaigns.append({
            "campaign": name,
            "impressions": values["impressions"],
            "clicks": values["clicks"],
            "spend": values["spend"],
            "orders": values["orders"],
            "sales": values["sales"],
        })
    return campaigns


def grade_campaign(item, break_even_roas, target_roas):
    impressions = item["impressions"]
    clicks = item["clicks"]
    spend = item["spend"]
    orders = item["orders"]
    sales = item["sales"]
    roas_raw = sales / spend if spend > 0 else None
    if impressions < 1000:
        return "INFO", "data"
    if spend <= 0:
        return "INFO", "no_spend"
    if clicks >= 30 and orders == 0:
        return "P0", "zero_orders"
    if break_even_roas is None or (roas_raw or 0.0) < break_even_roas * 0.5:
        return "P0", "below_half"
    if roas_raw < break_even_roas:
        return "P1", "below_be"
    if roas_raw < target_roas:
        return "P1", "below_target"
    return "P2", "ok"


def campaign_action(grade, reason, item, break_even_roas, target_roas):
    roas_text = "{:.2f}".format(item["roas"] or 0.0)
    if grade == "INFO":
        if reason == "data":
            action = "曝光 {} < 1,000，数据不足；继续攒数据，本轮不调出价、预算、关键词或素材。".format(
                "{:,}".format(item["impressions"]))
        else:
            action = "无有效花费，无法判断；继续攒数据，本轮不调出价、预算、关键词或素材。"
        return "不动（数据不足）", action, ["出价", "预算", "关键词结构", "Listing/素材"]
    if grade == "P0" and reason == "zero_orders":
        action = "点击 {} 仍零订单：先把预算压到最低档止血，复核主图、价格带与近期评论；广告端暂停新增关键词，不靠加预算抢救。".format(
            item["clicks"])
        return "转化承接（Listing/价格/评论）", action, ["新增关键词", "扩大预算", "大规模改素材"]
    if grade == "P0":
        cpc_text = "无法计算" if item["affordable_cpc"] is None else "{:.2f}".format(item["affordable_cpc"])
        action = "ROAS {} 低于盈亏线一半：预算降至最低可运行档，出价压到可承受 CPC {} 以内，否定高花费零单词。".format(
            roas_text, cpc_text)
        return "出价/预算", action, ["Listing 文案", "主图/视频", "售价与优惠"]
    if grade == "P1" and reason == "below_be":
        action = "ROAS {} 低于盈亏线 {:.2f}：出价下调 10–15%，否定高 ACOS 搜索词；总预算暂不动。".format(
            roas_text, break_even_roas)
        return "关键词/出价", action, ["预算总量", "Listing", "售价", "素材"]
    if grade == "P1":
        action = "ROAS {} 在盈亏线与目标 {:.2f} 之间：预算与出价都不动，只优化转化承接，3–7 天后复测。".format(
            roas_text, target_roas)
        return "转化率（Listing/评论证据）", action, ["出价", "预算", "关键词结构", "素材"]
    action = "ROAS {} ≥ 目标 {:.2f}：预算单次 +20%，出价最多 +10%；观察 3 天，ROAS 仍达标再加下一档。".format(
        roas_text, target_roas)
    return "预算", action, ["Listing", "售价", "素材", "否定词结构"]


def enrich_campaign(item, cost_model, target_roas, global_cvr):
    impressions = item["impressions"]
    clicks = item["clicks"]
    spend = item["spend"]
    orders = item["orders"]
    sales = item["sales"]
    ctr_pct = round2(clicks / impressions * 100) if impressions else 0.0
    cvr_pct = round2(orders / clicks * 100) if clicks else 0.0
    cpc = round2(spend / clicks) if clicks else None
    acos_pct = round2(spend / sales * 100) if sales else None
    roas = round2(sales / spend) if spend else None
    rate = cvr_pct
    if rate == 0 and global_cvr is not None:
        rate = global_cvr
    affordable_cpc = round2(cost_model["price"] * (rate / 100) * (cost_model["target_acos_pct"] / 100))
    enriched = {
        "campaign": item["campaign"],
        "impressions": impressions,
        "clicks": clicks,
        "spend": round2(spend),
        "orders": orders,
        "sales": round2(sales),
        "ctr_pct": ctr_pct,
        "cvr_pct": cvr_pct,
        "cpc": cpc,
        "acos_pct": acos_pct,
        "roas": roas,
        "affordable_cpc": affordable_cpc,
        "net_contribution": round2(cost_model["pre_ad_contribution"] / cost_model["price"] * sales - spend),
    }
    grade, reason = grade_campaign(item, cost_model["break_even_roas"], target_roas)
    enriched["grade"] = grade
    lever, action, do_not_touch = campaign_action(grade, reason, enriched, cost_model["break_even_roas"], target_roas)
    enriched["primary_lever"] = lever
    enriched["action"] = action
    enriched["do_not_touch"] = do_not_touch
    return enriched


def run_diagnose(args):
    if args.price <= 0:
        fail("--price 必须大于 0。", missing=[])
    if args.product_cost < 0:
        fail("--product-cost 必须大于等于 0。", missing=[])
    if not (0 < args.referral <= 100):
        fail("--referral 必须是 0–100 的百分比。", missing=[])
    if args.fba_fee < 0:
        fail("--fba-fee 必须大于等于 0。", missing=[])
    if not (0 < args.target_acos < 100):
        fail("--target-acos 必须在 0–100 之间（不含端点）。", missing=[])
    if args.ads_pct is not None and args.ads_pct < 0:
        fail("--ads-pct 必须大于等于 0。", missing=[])
    if args.returns_pct is not None and args.returns_pct < 0:
        fail("--returns-pct 必须大于等于 0。", missing=[])
    if args.cvr is not None and not (0 < args.cvr <= 100):
        fail("--cvr 必须是 0–100 的百分比。", missing=[])

    fee_config = load_fee_config()
    header, rows = read_report(args.file)
    resolved = validate_columns(header)
    raw_items = parse_campaign_rows(header, rows, resolved)

    class ModelArgs(object):
        pass

    model_args = ModelArgs()
    model_args.price = args.price
    model_args.product_cost = args.product_cost
    model_args.referral = args.referral
    model_args.fba_fee = args.fba_fee
    model_args.target_acos = args.target_acos
    model_args.ads_pct = args.ads_pct if args.ads_pct is not None else 0.0
    model_args.returns_pct = args.returns_pct if args.returns_pct is not None else 0.0
    model_args.cvr = args.cvr
    model_args.ad_spend = None
    model_args.total_sales = None
    cost_model = build_cost_model(model_args)

    target_roas = cost_model["target_roas"]
    campaigns = [enrich_campaign(item, cost_model, target_roas, args.cvr) for item in raw_items]
    campaigns.sort(key=lambda item: (GRADE_ORDER[item["grade"]], item["roas"] if item["roas"] is not None else -1))

    total_spend = round2(sum(item["spend"] for item in raw_items))
    total_sales = round2(sum(item["sales"] for item in raw_items))
    total_impressions = sum(item["impressions"] for item in raw_items)
    total_clicks = sum(item["clicks"] for item in raw_items)
    total_orders = sum(item["orders"] for item in raw_items)
    total = {
        "campaigns": len(raw_items),
        "impressions": total_impressions,
        "clicks": total_clicks,
        "spend": total_spend,
        "orders": total_orders,
        "sales": total_sales,
        "roas": round2(total_sales / total_spend) if total_spend else None,
        "tacos_pct": round2(total_spend / total_sales * 100) if total_sales else None,
        "net_contribution": round2(cost_model["pre_ad_contribution"] / cost_model["price"] * total_sales - total_spend),
    }
    counts = {"P0": 0, "P1": 0, "P2": 0, "INFO": 0}
    for item in campaigns:
        counts[item["grade"]] += 1

    missing = []
    if cost_model["model_warning"]:
        missing.append(cost_model["model_warning"])
    if args.returns_pct is None:
        missing.append(RETURNS_MISSING)

    payload = {
        "mode": "diagnose",
        "platform": args.platform,
        "platform_label": PLATFORMS[args.platform]["label"],
        "currency": "USD",
        "file": args.file,
        "cost_model": cost_model,
        "target_roas": target_roas,
        "total": total,
        "priority_counts": counts,
        "campaigns": campaigns,
        "global_do_not_touch": GLOBAL_DO_NOT_TOUCH,
        "discipline": DISCIPLINE,
        "missing": missing,
        "platform_note": PLATFORMS[args.platform]["note"],
        "fee_config": fee_config,
        "disclaimer": DISCLAIMER,
    }
    if args.json:
        emit_json(payload)
    else:
        render_diagnose_text(payload)
    return 0


def render_diagnose_text(payload):
    total = payload["total"]
    counts = payload["priority_counts"]
    model = payload["cost_model"]
    lines = [
        "广告诊断 · {} · {} 个 campaign".format(payload["platform_label"], total["campaigns"]),
        "盈亏线 ROAS {} ｜ 目标 ROAS {:.2f} ｜ 盈亏线 ACOS {:.2f}%".format(
            "-" if model["break_even_roas"] is None else "{:.2f}".format(model["break_even_roas"]),
            payload["target_roas"], model["break_even_acos_pct"]),
        "整体 ROAS {} ｜ TACOS {} ｜ 净贡献 {:.2f} USD".format(
            "-" if total["roas"] is None else "{:.2f}".format(total["roas"]),
            "-" if total["tacos_pct"] is None else "{:.2f}".format(total["tacos_pct"]),
            total["net_contribution"]),
        "分级：P0 {} ｜ P1 {} ｜ P2 {} ｜ INFO {}".format(
            counts["P0"], counts["P1"], counts["P2"], counts["INFO"]),
        "",
    ]
    for item in payload["campaigns"]:
        lines.append("[{}] {} ｜ ROAS {} ｜ ACOS {} ｜ 花费 {:.2f} ｜ 订单 {}".format(
            item["grade"], item["campaign"],
            "-" if item["roas"] is None else "{:.2f}".format(item["roas"]),
            "-" if item["acos_pct"] is None else "{:.2f}%".format(item["acos_pct"]),
            item["spend"], item["orders"]))
        lines.append("  杠杆：{}".format(item["primary_lever"]))
        lines.append("  动作：{}".format(item["action"]))
        lines.append("  本轮不动：{}".format("、".join(item["do_not_touch"])))
    lines.append("")
    lines.append("本轮明确不动（全局）：")
    for entry in payload["global_do_not_touch"]:
        lines.append("- {}".format(entry))
    lines.append(payload["discipline"])
    if payload["missing"]:
        for entry in payload["missing"]:
            lines.append(entry)
    lines.append("平台提示：{}".format(payload["platform_note"]))
    lines.append("口径：{}".format(payload["disclaimer"]))
    lines.append("费率来源：{} (_meta.updated={})".format(
        payload["fee_config"]["path"], payload["fee_config"]["updated"]))
    print("\n".join(lines))


def build_parser():
    parser = CliArgumentParser(prog="ads_metrics.py", description="广告投放指标诊断与盈亏线计算")
    sub = parser.add_subparsers(dest="command", required=True)

    calc = sub.add_parser("calc", description="广告盈亏线 / 目标 ROAS / TACOS")
    calc.add_argument("--platform", required=True, choices=["amazon_us", "tiktok_us"])
    calc.add_argument("--price", type=float, required=True)
    calc.add_argument("--product-cost", type=float, required=True)
    calc.add_argument("--referral", type=float, required=True)
    calc.add_argument("--fba-fee", type=float, required=True)
    calc.add_argument("--target-acos", type=float, required=True)
    calc.add_argument("--ads-pct", type=float, required=True)
    calc.add_argument("--returns-pct", type=float, required=True)
    calc.add_argument("--cvr", type=float)
    calc.add_argument("--ad-spend", type=float)
    calc.add_argument("--total-sales", type=float)
    calc.add_argument("--json", action="store_true")

    diagnose = sub.add_parser("diagnose", description="campaign 报表诊断")
    diagnose.add_argument("--file", required=True)
    diagnose.add_argument("--platform", required=True, choices=["amazon_us", "tiktok_us"])
    diagnose.add_argument("--price", type=float, required=True)
    diagnose.add_argument("--product-cost", type=float, required=True)
    diagnose.add_argument("--referral", type=float, required=True)
    diagnose.add_argument("--fba-fee", type=float, required=True)
    diagnose.add_argument("--target-acos", type=float, required=True)
    diagnose.add_argument("--ads-pct", type=float)
    diagnose.add_argument("--returns-pct", type=float)
    diagnose.add_argument("--cvr", type=float)
    diagnose.add_argument("--json", action="store_true")
    return parser


def main(argv):
    set_json_mode("--json" in argv)
    args = build_parser().parse_args(argv)
    if args.command == "calc":
        return run_calc(args)
    return run_diagnose(args)


if __name__ == "__main__":
    sys.exit(run_main(lambda: main(sys.argv[1:])))
