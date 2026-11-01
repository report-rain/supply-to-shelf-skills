#!/usr/bin/env python3
"""补货测算与海空运对比（clean-room 重写）。

行为规格见 docs/spec/08_fulfillment.md。纯计算器，不读文件、不写文件。
错误契约沿用 shared.errors：JSON 到 stdout，人类信息到 stderr。
"""

import datetime
import math
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from shared.args import CliArgumentParser
from shared.errors import emit_json, fail, run_main, set_json_mode
from shared.numbers import round2

TOOL = "inventory_plan"

CALC_RULES = "补货点 = 日均销量 ×（生产交期 + 安全天数）；建议量按目标水位补足后向上取 MOQ 整数倍。"
COMPARE_RULES = "判断口径：空运每天买时间的成本 = 运费差额 ÷ 缩短天数，与断货一天的毛利损失对比；毛利数据来自 02 成本模型。"


def parse_today(raw):
    if raw is None:
        return datetime.date.today()
    try:
        parsed = datetime.datetime.strptime(raw, "%Y-%m-%d").date()
    except ValueError:
        fail("--today 需为 YYYY-MM-DD，收到：{}".format(raw), missing=["today"])
    if parsed.strftime("%Y-%m-%d") != raw:
        fail("--today 需为 YYYY-MM-DD，收到：{}".format(raw), missing=["today"])
    return parsed


def round1(value):
    return round(value + 0.0, 1)


def run_calc(args):
    if args.daily_sales < 0:
        fail("daily_sales 不能为负，收到：{}".format(args.daily_sales), missing=["daily_sales"])
    if args.lead_time_days <= 0:
        fail(
            "lead_time_days 必须大于 0，收到：{}（生产交期缺失无法算补货点）".format(args.lead_time_days),
            missing=["lead_time_days"],
        )
    if args.safety_days < 0:
        fail("safety_days 不能为负，收到：{}".format(args.safety_days), missing=["safety_days"])
    if args.stock < 0:
        fail("stock 不能为负，收到：{}".format(args.stock), missing=["stock"])
    if args.moq <= 0:
        fail("moq 必须大于 0，收到：{}".format(args.moq), missing=["moq"])
    if args.inbound_interval_days < 0:
        fail(
            "inbound_interval_days 不能为负，收到：{}".format(args.inbound_interval_days),
            missing=["inbound_interval_days"],
        )
    if args.unit_cost is not None and args.unit_cost <= 0:
        fail("unit_cost 必须大于 0，收到：{}".format(args.unit_cost), missing=["unit_cost"])
    today = parse_today(args.today)

    daily = args.daily_sales
    lead = args.lead_time_days
    safety = args.safety_days
    stock = args.stock
    moq = args.moq
    interval = args.inbound_interval_days

    reorder_point = round1(daily * (lead + safety))
    target_stock = round1(daily * (lead + safety + interval))
    if daily > 0:
        days_of_cover = round1(stock / daily)
        stockout_date = today + datetime.timedelta(days=int(math.floor(stock / daily)))
        order_deadline = stockout_date - datetime.timedelta(days=lead)
        days_until_deadline = (order_deadline - today).days
        deadline_passed = days_until_deadline < 0
        coverage_after = round1((stock + 0) / daily)
    else:
        days_of_cover = None
        stockout_date = None
        order_deadline = None
        days_until_deadline = None
        deadline_passed = False
        coverage_after = None

    if daily == 0:
        suggested = 0
    else:
        gap = target_stock - stock
        if gap <= 0:
            suggested = 0
        else:
            suggested = int(math.ceil(gap / moq) * moq)

    if daily > 0:
        coverage_after = round1((stock + suggested) / daily)

    if args.unit_cost is None:
        capital_required = None
    elif daily == 0:
        capital_required = 0.0
    else:
        capital_required = round2(suggested * args.unit_cost)

    if daily == 0:
        risk_level = "N/A"
    elif days_of_cover < lead:
        risk_level = "HIGH"
    elif days_of_cover < lead + safety:
        risk_level = "MEDIUM"
    else:
        risk_level = "LOW"

    notes = []
    if daily == 0:
        notes.append("日均销量为 0：不做补货建议。请确认是尚未上架，还是销量数据缺失。")
        if stock == 0:
            notes.append("当前库存为 0 且无销量，无法判断断货影响。")
    else:
        if risk_level == "HIGH":
            notes.append("当前可售 {:.1f} 天 < 生产交期 {} 天：补货未到就会断货，必须立即下单并评估空运补急。".format(
                days_of_cover, lead))
        elif risk_level == "MEDIUM":
            notes.append("当前可售 {:.1f} 天低于补货点 {:.0f} 件（{:.1f} 天）：已进入补货窗口，本周内下单。".format(
                days_of_cover, reorder_point, float(lead + safety)))
        else:
            notes.append("库存高于补货点，按计划下单即可。")
        if stock == 0:
            notes.append("当前库存为 0：已处于断货状态，断货期间权重恢复慢，优先空运补急。")
        if suggested == 0:
            notes.append("库存已高于目标水位 {:.0f} 件，暂不需要下单；继续下单会形成压货。请核对在途与在库。".format(
                target_stock))
        if deadline_passed:
            notes.append("下单截止日已过 {} 天：正常海运已赶不上，需与工厂确认现货 / 加急，并用空运覆盖缺口。".format(
                -days_until_deadline))

    def date_text(value):
        return value.strftime("%Y-%m-%d") if value else None

    payload = {
        "tool": TOOL,
        "mode": "calc",
        "today": today.strftime("%Y-%m-%d"),
        "inputs": {
            "daily_sales": float(daily),
            "lead_time_days": lead,
            "safety_days": safety,
            "stock": stock,
            "moq": moq,
            "inbound_interval_days": interval,
            "unit_cost": float(args.unit_cost) if args.unit_cost is not None else None,
            "currency": args.currency,
        },
        "reorder_point": reorder_point,
        "days_of_cover": days_of_cover,
        "expected_stockout_date": date_text(stockout_date),
        "order_deadline": date_text(order_deadline),
        "order_deadline_passed": deadline_passed,
        "days_until_deadline": days_until_deadline,
        "target_stock": target_stock,
        "suggested_order_qty": suggested,
        "coverage_after_order_days": coverage_after,
        "capital_required": capital_required,
        "risk_level": risk_level,
        "notes": notes,
    }
    if args.json:
        emit_json(payload)
    else:
        render_calc_text(payload, args.currency)
    return 0


def render_calc_text(payload, currency):
    data = payload["inputs"]
    lines = ["=== 补货测算（基准日 {}）===".format(payload["today"])]
    lines.append("日均销量 {:.1f}｜生产交期 {} 天｜安全天数 {} 天｜当前库存 {}｜MOQ {}｜发运间隔 {} 天".format(
        data["daily_sales"], data["lead_time_days"], data["safety_days"],
        data["stock"], data["moq"], data["inbound_interval_days"]))
    lines.append("")
    lines.append("补货点（reorder_point）：{:.1f} 件".format(payload["reorder_point"]))
    if payload["days_of_cover"] is None:
        lines.append("当前可售天数：无法计算（日均销量为 0）")
        lines.append("预计断货日：无法计算")
    else:
        lines.append("当前可售天数：{:.1f} 天".format(payload["days_of_cover"]))
        lines.append("预计断货日：{}".format(payload["expected_stockout_date"]))
    lines.append("建议下单量：{} 件（按 MOQ {} 向上取整）".format(
        payload["suggested_order_qty"], data["moq"]))
    if payload["order_deadline"]:
        passed = (
            "（已过 {} 天，需立即下单）".format(-payload["days_until_deadline"])
            if payload["order_deadline_passed"] else ""
        )
        lines.append("下单截止日：{}{}".format(payload["order_deadline"], passed))
    if payload["coverage_after_order_days"] is not None:
        lines.append("下单后覆盖天数：{:.1f} 天".format(payload["coverage_after_order_days"]))
    if payload["capital_required"] is not None:
        lines.append("下单资金占用：{} {:.2f}".format(currency, payload["capital_required"]))
    lines.append("断货风险等级：{}".format(payload["risk_level"]))
    if payload["notes"]:
        lines.append("")
        lines.append("提示：")
        for note in payload["notes"]:
            lines.append("  - {}".format(note))
    lines.append("")
    lines.append("口径：{}".format(CALC_RULES))
    print("\n".join(lines))


def run_compare(args):
    if args.units <= 0:
        fail("units 必须大于 0，收到：{}".format(args.units), missing=["units"])
    if args.weight_kg <= 0:
        fail("weight-kg 必须大于 0，收到：{}".format(args.weight_kg), missing=["weight_kg"])
    if args.cbm_per_unit < 0:
        fail("cbm-per-unit 不能为负，收到：{}".format(args.cbm_per_unit), missing=["cbm_per_unit"])
    if args.sea_days <= 0 or args.air_days <= 0:
        fail("sea-days / air-days 必须大于 0", missing=["sea_days", "air_days"])
    if args.sea_rate_per_kg is None and args.sea_rate_per_cbm is None:
        fail(
            "缺少字段：sea-rate-per-kg 或 sea-rate-per-cbm（海运报价至少给一个）",
            missing=["sea_rate_per_kg|sea_rate_per_cbm"],
        )
    if args.sea_rate_per_kg is not None and args.sea_rate_per_kg <= 0:
        fail("sea-rate-per-kg 必须大于 0，收到：{}".format(args.sea_rate_per_kg),
             missing=["sea_rate_per_kg"])
    if args.air_rate_per_kg <= 0:
        fail("air-rate-per-kg 必须大于 0，收到：{}".format(args.air_rate_per_kg),
             missing=["air_rate_per_kg"])
    if args.sea_rate_per_cbm is not None and args.sea_rate_per_cbm <= 0:
        fail("sea-rate-per-cbm 必须大于 0", missing=["sea_rate_per_cbm"])
    if args.unit_cost is not None and args.unit_cost <= 0:
        fail("unit-cost 必须大于 0，收到：{}".format(args.unit_cost), missing=["unit_cost"])
    if args.carrying_rate_pct < 0:
        fail("carrying-rate-pct 不能为负", missing=["carrying_rate_pct"])
    if args.carrying_rate_pct > 100:
        fail("carrying-rate-pct 必须在 0–100 之间", missing=["carrying_rate_pct"])
    today = parse_today(args.today)

    units = args.units
    weight = args.weight_kg
    cbm_per_unit = args.cbm_per_unit
    total_weight = round1(units * weight)
    total_cbm = round(units * cbm_per_unit, 3)
    density = round1(total_weight / total_cbm) if total_cbm else None
    volumetric = round1(total_cbm * 167)
    chargeable = round1(max(total_weight, volumetric))

    if args.sea_rate_per_cbm is not None:
        sea_total = round2(max(total_cbm, 1.0) * args.sea_rate_per_cbm)
        sea_basis = "按体积重（CBM，LCL 最低 1 CBM 起算）"
    else:
        sea_total = round2(total_weight * args.sea_rate_per_kg)
        sea_basis = "按重量（kg）"
    air_total = round2(chargeable * args.air_rate_per_kg)
    sea_per_unit = round(sea_total / units, 3)
    air_per_unit = round(air_total / units, 3)
    diff_total = round2(air_total - sea_total)
    diff_per_unit = round(diff_total / units, 3)
    premium_pct = round1(diff_total / sea_total * 100)
    days_saved = args.sea_days - args.air_days
    cost_per_day = round2(diff_total / days_saved) if days_saved > 0 else None

    capital = None
    if args.unit_cost is not None:
        inventory_value = round2(units * args.unit_cost)
        sea_capital = round2(inventory_value * args.sea_days / 365 * args.carrying_rate_pct / 100)
        air_capital = round2(inventory_value * args.air_days / 365 * args.carrying_rate_pct / 100)
        capital = {
            "inventory_value": inventory_value,
            "carrying_rate_pct": round1(args.carrying_rate_pct),
            "sea_capital_cost": sea_capital,
            "air_capital_cost": air_capital,
            "capital_diff": round2(sea_capital - air_capital),
            "currency": args.currency,
        }

    if days_saved <= 0:
        recommendation = "空运无时效优势：按总成本选更低的一方。"
    elif premium_pct <= 25:
        recommendation = "空运溢价可接受：优先空运，用更短在途压低断货风险。"
    elif premium_pct <= 80:
        recommendation = "海空组合：首批 / 紧急批次空运，常规批次海运。"
    else:
        recommendation = "海运为主，空运只用于断货补急；下单用空运前先算断货毛利损失是否大于溢价。"

    notes = []
    if args.sea_rate_per_cbm is not None and total_cbm < 1:
        notes.append("海运 LCL 按最低 1 CBM 起算，本批 {:.2f} CBM 触发最低收费。".format(total_cbm))
    if volumetric > total_weight:
        notes.append("空运计费重取体积重 {:.1f} kg（1 CBM ≈ 167 kg），高于实重 {:.1f} kg。".format(
            volumetric, total_weight))
    if capital is not None:
        notes.append("资金占用差按年化 {:.1f}% 资金成本折算，仅计在途时间差，不含仓储与滞销风险。".format(
            capital["carrying_rate_pct"]))
    notes.append(COMPARE_RULES)

    sea_eta = (today + datetime.timedelta(days=args.sea_days)).strftime("%Y-%m-%d")
    air_eta = (today + datetime.timedelta(days=args.air_days)).strftime("%Y-%m-%d")

    payload = {
        "tool": TOOL,
        "mode": "compare",
        "today": today.strftime("%Y-%m-%d"),
        "inputs": {
            "units": units,
            "weight_kg_per_unit": float(weight),
            "cbm_per_unit": float(cbm_per_unit),
            "sea_rate_per_kg": float(args.sea_rate_per_kg) if args.sea_rate_per_kg is not None else None,
            "air_rate_per_kg": float(args.air_rate_per_kg),
            "sea_days": args.sea_days,
            "air_days": args.air_days,
            "unit_cost": float(args.unit_cost) if args.unit_cost is not None else None,
            "currency": args.currency,
        },
        "cargo": {
            "total_weight_kg": total_weight,
            "total_cbm": total_cbm,
            "density_kg_per_cbm": density,
            "air_volumetric_kg": volumetric,
            "air_chargeable_kg": chargeable,
        },
        "sea": {
            "total": sea_total,
            "per_unit": sea_per_unit,
            "transit_days": args.sea_days,
            "eta": sea_eta,
            "charge_basis": sea_basis,
        },
        "air": {
            "total": air_total,
            "per_unit": air_per_unit,
            "transit_days": args.air_days,
            "eta": air_eta,
            "charge_basis": "按计费重（实重与体积重取大）",
        },
        "diff": {
            "total": diff_total,
            "per_unit": diff_per_unit,
            "premium_pct": premium_pct,
            "days_saved": days_saved,
            "cost_per_day_saved": cost_per_day,
        },
        "capital": capital,
        "recommendation": recommendation,
        "notes": notes,
    }
    if args.json:
        emit_json(payload)
    else:
        render_compare_text(payload)
    return 0


def render_compare_text(payload):
    data = payload["inputs"]
    cargo = payload["cargo"]
    sea = payload["sea"]
    air = payload["air"]
    diff = payload["diff"]
    lines = ["=== 头程方式对比（{} 件，基准日 {}）===".format(data["units"], payload["today"])]
    lines.append("单件 {:.2f} kg / {:.5f} CBM｜合计 {:.1f} kg / {:.3f} CBM｜密度 {}".format(
        data["weight_kg_per_unit"], data["cbm_per_unit"], cargo["total_weight_kg"],
        cargo["total_cbm"],
        "-" if cargo["density_kg_per_cbm"] is None else "{:.1f} kg/CBM".format(cargo["density_kg_per_cbm"])))
    lines.append("")
    lines.append("海运：{} {:.2f}｜单件 {} {:.2f}｜{} 天｜ETA {}｜{}".format(
        data["currency"], sea["total"], data["currency"], sea["per_unit"],
        sea["transit_days"], sea["eta"], sea["charge_basis"]))
    lines.append("空运：{} {:.2f}｜单件 {} {:.2f}｜{} 天｜ETA {}｜计费重 {:.1f} kg".format(
        data["currency"], air["total"], data["currency"], air["per_unit"],
        air["transit_days"], air["eta"], cargo["air_chargeable_kg"]))
    lines.append("差额：{} {:.2f}（单件 {} {:.2f}，{:+.1f}%）｜时效差 {} 天".format(
        data["currency"], diff["total"], data["currency"], diff["per_unit"],
        diff["premium_pct"], diff["days_saved"]))
    lines.append("每天买时间的成本：{}".format(
        "-" if diff["cost_per_day_saved"] is None else "{} {:.2f}".format(
            data["currency"], diff["cost_per_day_saved"])))
    capital = payload["capital"]
    if capital is not None:
        lines.append("资金占用：货值 {} {:.2f}｜海运在途资金成本 {} {:.2f}｜空运 {} {:.2f}｜差额 {} {:.2f}".format(
            data["currency"], capital["inventory_value"], data["currency"], capital["sea_capital_cost"],
            data["currency"], capital["air_capital_cost"], data["currency"], capital["capital_diff"]))
    lines.append("")
    lines.append("建议：{}".format(payload["recommendation"]))
    if payload["notes"]:
        lines.append("")
        lines.append("提示：")
        for note in payload["notes"]:
            lines.append("  - {}".format(note))
    print("\n".join(lines))


def build_parser():
    parser = CliArgumentParser(prog="inventory_plan.py", description="美国站补货测算与海空运对比。")
    sub = parser.add_subparsers(dest="command")

    calc = sub.add_parser("calc", help="补货点 / 断货日 / 建议下单量")
    calc.add_argument("--daily-sales", type=float, required=True)
    calc.add_argument("--lead-time-days", type=int, required=True)
    calc.add_argument("--safety-days", type=int, default=0)
    calc.add_argument("--stock", type=int, default=0)
    calc.add_argument("--moq", type=int, required=True)
    calc.add_argument("--inbound-interval-days", type=int, default=0)
    calc.add_argument("--unit-cost", type=float)
    calc.add_argument("--currency", default="USD")
    calc.add_argument("--today")
    calc.add_argument("--json", action="store_true")

    compare = sub.add_parser("compare", help="海运 vs 空运")
    compare.add_argument("--units", type=int, required=True)
    compare.add_argument("--weight-kg", type=float, required=True)
    compare.add_argument("--cbm-per-unit", type=float, default=0.0)
    compare.add_argument("--sea-rate-per-kg", type=float)
    compare.add_argument("--air-rate-per-kg", type=float, required=True)
    compare.add_argument("--sea-rate-per-cbm", type=float)
    compare.add_argument("--sea-days", type=int, required=True)
    compare.add_argument("--air-days", type=int, required=True)
    compare.add_argument("--unit-cost", type=float)
    compare.add_argument("--carrying-rate-pct", type=float, default=12)
    compare.add_argument("--currency", default="USD")
    compare.add_argument("--today")
    compare.add_argument("--json", action="store_true")
    return parser


def main(argv):
    set_json_mode("--json" in argv)
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help()
        fail("缺少子命令：calc 或 compare", missing=["command"])
    if args.command == "calc":
        return run_calc(args)
    return run_compare(args)


if __name__ == "__main__":
    sys.exit(run_main(lambda: main(sys.argv[1:])))
