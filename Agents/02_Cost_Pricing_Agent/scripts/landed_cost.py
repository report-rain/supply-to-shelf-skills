#!/usr/bin/env python3
"""Landed cost and pricing calculator.

Implements the behaviour frozen in docs/spec/02_cost_pricing.md. Configuration
files are the only external inputs; every amount is rounded with two decimals.
"""

import argparse
import csv
import datetime
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from shared.args import CliArgumentParser
from shared.category import load_category_map, resolve_category
from shared.config import load_json
from shared.errors import CliFailure, fail, emit_json, emit_failure, set_json_mode
from shared.numbers import round2, money

SCRIPT_DIR = Path(__file__).resolve().parent
FEES_PATH = SCRIPT_DIR / "us_fees.json"
HTS_PATH = SCRIPT_DIR / "hts_tariff.json"
MAP_PATH = ROOT / "config" / "category_map.json"

DEFAULT_PLATFORM = "amazon_us"
DEFAULT_ADS_PCT = 10.0
DEFAULT_RETURNS_PCT = 3.0
DEFAULT_TARGET_MARGIN = 25.0
DEFAULT_MOQ = 500
DEFAULT_CUSTOMS_FEE = 0.18

PEAK_START = datetime.date(2026, 10, 15)
PEAK_END = datetime.date(2027, 1, 14)
NONPEAK_START = datetime.date(2026, 1, 15)
NONPEAK_END = datetime.date(2026, 10, 14)
FUEL_EFFECTIVE = datetime.date(2026, 4, 17)
FUEL_PCT = 3.5


class Context:
    def __init__(self):
        self._fees = None
        self._hts = None
        self._map = None

    @property
    def fees(self):
        if self._fees is None:
            self._fees = load_json(str(FEES_PATH), str(FEES_PATH))
        return self._fees

    @property
    def hts(self):
        if self._hts is None:
            self._hts = load_json(str(HTS_PATH), str(HTS_PATH))
        return self._hts

    @property
    def category_map(self):
        if self._map is None:
            self._map = load_category_map(str(MAP_PATH))
        return self._map


def build_parser():
    parser = CliArgumentParser(
        prog="landed_cost.py",
        description="美国站到岸成本与定价测算（USD，中文）",
    )
    parser.add_argument(
        "--list-platforms", action="store_true", help="列出平台 referral 费率"
    )
    parser.add_argument(
        "--list-fba-tiers", action="store_true", help="列出 2026 年 FBA 档位费率"
    )
    sub = parser.add_subparsers(dest="command")

    calc = sub.add_parser("calc", help="单 SKU 到岸成本与定价")
    calc.add_argument("--factory-rmb", type=float)
    calc.add_argument("--fx", type=float)
    calc.add_argument("--freight-per-unit", type=float)
    calc.add_argument("--duty-pct", type=float)
    calc.add_argument("--hts")
    calc.add_argument("--category")
    calc.add_argument("--category-key")
    calc.add_argument("--assume-default-referral", action="store_true")
    calc.add_argument("--platform", choices=["amazon_us", "tiktok_us"])
    calc.add_argument("--referral", type=float)
    calc.add_argument("--fba-fee", type=float)
    calc.add_argument("--weight-g", type=float)
    calc.add_argument("--weight-oz", type=float)
    calc.add_argument(
        "--tier", choices=["small_standard", "large_standard", "small_bulky", "large_bulky"]
    )
    calc.add_argument("--season", choices=["auto", "nonpeak", "peak"])
    calc.add_argument("--ship-date")
    calc.add_argument("--no-fuel-surcharge", action="store_true")
    calc.add_argument("--ads-pct", type=float)
    calc.add_argument("--returns-pct", type=float)
    calc.add_argument("--price", type=float)
    calc.add_argument("--target-margin", type=float)
    calc.add_argument("--moq", type=int)
    calc.add_argument("--customs-fee-per-unit", type=float)
    calc.add_argument("--json", action="store_true")
    calc.set_defaults(handler=handle_calc)

    matrix = sub.add_parser("matrix", help="多 SKU 矩阵")
    matrix.add_argument("--file")
    matrix.add_argument("--fx", type=float)
    matrix.add_argument("--assume-default-referral", action="store_true")
    matrix.add_argument("--json", action="store_true")
    matrix.set_defaults(handler=handle_matrix)

    return parser


def num(value):
    if value is None:
        return None
    return round(value + 0.0, 2)


def parse_price_band(price):
    if price < 10:
        return "lt10"
    if price <= 50:
        return "10_50"
    return "gt50"


def platform_config(ctx, platform):
    platforms = ctx.fees.get("platforms", {})
    if platform not in platforms:
        fail(
            "不支持的 platform：{}（可选：{}）".format(platform, ", ".join(sorted(platforms))),
            code=2,
            missing=["platform"],
        )
    return platforms[platform]


def choose_category(raw):
    notes = []
    ckey = raw.get("category_key")
    cname = raw.get("category")
    cats = raw["_map"]["categories"]

    if ckey is not None:
        if ckey not in cats:
            fail(
                "无法识别的类目：{}。请传 category_key（{}）或 Amazon 类目路径；不做模糊猜测".format(
                    ckey, ", ".join(sorted(cats))
                ),
                code=2,
                missing=["category_key"],
            )
        if cname is not None and cname != ckey:
            fail(
                "--category 与 --category-key 不一致：{} vs {}".format(cname, ckey),
                code=2,
                missing=["category_key"],
            )
        return ckey, "explicit", notes

    if cname is not None:
        key, source, note = resolve_category(raw["_map"], cname)
        if key is None:
            fail(
                "无法识别的类目：{}。请传 category_key（{}）或 Amazon 类目路径；不做模糊猜测".format(
                    cname, ", ".join(sorted(cats))
                ),
                code=2,
                missing=["category_key"],
            )
        if note:
            notes.append(note)
        return key, source, notes

    if raw.get("referral") is not None:
        return None, "explicit", notes

    if raw.get("assume_default_referral"):
        return "default", "assumed_default", notes

    fail(
        "缺少类目：请显式传 --category-key/--category（可选：{}）"
        "，或显式开启 --assume-default-referral 按 default 15% 估算".format(
            ", ".join(sorted(cats))
        ),
        code=2,
        missing=["category_key"],
    )


def lookup_hts(ctx, raw_code):
    code = raw_code.strip().replace(" ", "").rstrip(".")
    codes = ctx.hts.get("codes", {})
    candidates = [
        key for key in codes if code == key or code.startswith(key) or key.startswith(code)
    ]
    if not candidates:
        fail(
            "hts_tariff.json 未收录该 HTS：{}。已收录：{}；"
            "请改用 --duty-pct 显式传入税率（并注明报关行依据）".format(
                raw_code, "、".join(codes)
            ),
            code=2,
            missing=["hts"],
        )
    hit = sorted(candidates, key=lambda key: (len(key), key))[-1]
    return hit, codes[hit]


def tiered_amount(price, tiers):
    lower = 0.0
    total = 0.0
    applied = 0
    for tier in tiers:
        upper = tier.get("max_price_usd")
        rate = tier.get("pct", 0.0)
        if upper is None:
            portion = price - lower
            if portion > 0:
                total += portion * rate / 100.0
                applied += 1
            break
        portion = min(price, upper) - lower
        if portion > 0:
            total += portion * rate / 100.0
            applied += 1
        lower = upper
        if price <= upper:
            break
    return total, applied


def referral_amount(ctx, platform, platform_conf, cat_key, price, explicit):
    notes = []
    if explicit is not None:
        return {
            "referral_usd": round2(price * explicit / 100.0),
            "referral_pct": round2(explicit),
            "source": "explicit",
            "tiered": False,
            "category": None,
        }, notes

    if platform == "tiktok_us":
        rate = platform_conf.get("default_referral_pct", 0.0)
        promo = platform_conf.get("new_seller_promo_pct")
        window = platform_conf.get("new_seller_window_days")
        cap = platform_conf.get("new_seller_gmv_cap_usd")
        notes.append(
            "TikTok Shop US 平台佣金 {:.2f}%（2024-04-01 起）；新卖家前 {} 天可享 {:.2f}%"
            "（累计 GMV 上限 {}）；达人佣金另计".format(rate, window, promo, money(cap))
        )
        return {
            "referral_usd": round2(price * rate / 100.0),
            "referral_pct": round2(rate),
            "source": "platform_default",
            "tiered": False,
            "category": None,
        }, notes

    entry = ctx.category_map["categories"].get(cat_key, {}) if cat_key else {}
    us_key = entry.get("us_fees_key") or cat_key

    categories = platform_conf.get("categories", {})
    if us_key not in categories:
        us_key = "default"
    cat_conf = categories.get(us_key, {})

    if "tiers" in cat_conf:
        raw_amount, _applied = tiered_amount(price, cat_conf["tiers"])
        tiered = len(cat_conf["tiers"]) > 1
        if tiered:
            notes.append(
                "{} 为分段费率，按售价逐段累加得有效费率 {:.2f}%".format(
                    cat_conf.get("label", us_key), raw_amount / price * 100.0
                )
            )
    else:
        base = cat_conf.get(
            "referral_pct", platform_conf.get("default_referral_pct", 0.0)
        )
        threshold = cat_conf.get("tier_threshold_usd")
        above = cat_conf.get("above_threshold_pct")
        if threshold is not None and above is not None and price > threshold:
            raw_amount = base * threshold / 100.0 + above * (price - threshold) / 100.0
        else:
            raw_amount = price * base / 100.0
        tiered = True
        notes.append(
            "{} 为分段费率，按售价逐段累加得有效费率 {:.2f}%".format(
                cat_conf.get("label", us_key), raw_amount / price * 100.0
            )
        )

    amount = round2(raw_amount)
    effective = round2(raw_amount / price * 100.0)

    minimum = cat_conf.get("min_fee_usd")
    if minimum is None:
        minimum = platform_conf.get("min_referral_fee_usd", 0.0)
    if minimum and minimum > 0 and amount < minimum:
        notes.append(
            "计算值 {} 低于每件最低销售佣金 {}，按最低值收取".format(
                money(amount), money(round2(minimum))
            )
        )
        amount = round2(minimum)
        effective = round2(amount / price * 100.0)

    return {
        "referral_usd": amount,
        "referral_pct": effective,
        "source": "platform_category",
        "tiered": tiered,
        "category": us_key,
    }, notes


def resolve_season(raw, notes):
    explicit = raw.get("season")
    if explicit in ("peak", "nonpeak"):
        notes.append("显式指定 --season {}".format(explicit))
        return explicit

    text = raw.get("ship_date")
    if text:
        try:
            ship = datetime.date.fromisoformat(text)
        except ValueError:
            fail(
                "--ship-date 必须是 YYYY-MM-DD：{}".format(text),
                code=2,
                missing=["ship_date"],
            )
    else:
        ship = datetime.date.today()
    if PEAK_START <= ship <= PEAK_END:
        notes.append("按 {} 落在 {} 至 {} 旺季窗口计算".format(ship, PEAK_START, PEAK_END))
        return "peak"
    if NONPEAK_START <= ship <= NONPEAK_END:
        notes.append(
            "按 {} 落在 {} 至 {} 非旺季窗口计算".format(ship, NONPEAK_START, NONPEAK_END)
        )
        return "nonpeak"
    notes.append("{} 超出 2026 已公布窗口，按非旺季估算并需复核".format(ship))
    return "nonpeak"


def fba_detail(ctx, raw, price, notes):
    explicit_fee = raw.get("fba_fee")
    weight_oz = raw.get("weight_oz")
    weight_g = raw.get("weight_g")
    if weight_oz is None and weight_g is not None:
        weight_oz = round2(weight_g / 28.3495)

    if explicit_fee is not None:
        fee = round2(explicit_fee)
        notes.append("FBA 使用显式 --fba-fee，未按尺寸档自动推导")
        return {
            "fee": fee,
            "tier": "explicit",
            "tier_label": "显式 --fba-fee",
            "season": "-",
            "band": "-",
            "base": fee,
            "surcharge": 0.0,
            "weight_oz": weight_oz,
        }

    tiers = ctx.fees.get("fba", {}).get("tiers")
    if not tiers:
        fail(
            "us_fees.json 缺少 fba.tiers，无法按重量推导 FBA 费",
            code=3,
            missing=["us_fees.json:fba.tiers"],
        )

    tier_key = raw.get("tier")
    if tier_key is None:
        tier_key = (
            "small_standard"
            if weight_oz is not None and weight_oz <= 16
            else "large_standard"
        )
    if tier_key not in tiers:
        fail(
            "未知 FBA 档位：{}（可选：{}）".format(tier_key, ", ".join(sorted(tiers))),
            code=2,
            missing=["fba_tier"],
        )

    season = resolve_season(raw, notes)
    band = parse_price_band(price)
    tier_conf = tiers[tier_key]
    if "rates" in tier_conf:
        chosen = None
        for row in tier_conf["rates"].get(season, []):
            max_oz = row.get("max_oz")
            if max_oz is None or weight_oz <= max_oz:
                chosen = row
                break
        if chosen is None:
            fail(
                "重量 {} oz 超出 {} 档上限，请换 --tier 或显式 --fba-fee".format(
                    weight_oz, tier_key
                ),
                code=2,
                missing=["weight_oz"],
            )
        if "fees" in chosen:
            base = chosen["fees"][band]
        else:
            over = chosen["over_3lb"]
            steps = max(0, math.ceil((weight_oz - 48) / 4.0))
            base = over["base"][band] + steps * over.get("per_4oz_usd", 0.0)
    else:
        extra_lb = max(0, math.ceil(weight_oz / 16.0) - 1)
        base = (
            tier_conf["base"][season][band]
            + extra_lb * tier_conf.get("per_lb_over_first_usd", 0.0)
        )

    surcharge = 0.0
    if not raw.get("no_fuel_surcharge"):
        reference = (
            datetime.date.fromisoformat(raw["ship_date"])
            if raw.get("ship_date")
            else datetime.date.today()
        )
        if reference >= FUEL_EFFECTIVE:
            surcharge = FUEL_PCT
            notes.append(
                "按 {} 起生效的燃油与物流附加费 +{:.2f}% 计提".format(
                    FUEL_EFFECTIVE, FUEL_PCT
                )
            )
    return {
        "fee": round2(base * (1 + surcharge / 100.0)),
        "tier": tier_key,
        "tier_label": tier_conf.get("label", tier_key),
        "season": season,
        "band": band,
        "base": round2(base),
        "surcharge": surcharge,
        "weight_oz": weight_oz,
    }


def compute_sku(ctx, raw):
    notes = []
    assumptions = []
    quiet = raw.get("_quiet_defaults", False)

    factory = raw.get("factory_rmb")
    fx = raw.get("fx")
    freight_raw = raw.get("freight_per_unit")
    price = raw.get("price")

    if factory < 0:
        fail(
            "factory-rmb 不能为负，收到：{}".format(factory),
            code=2,
            missing=["factory_rmb"],
        )
    if fx <= 0:
        fail("fx 必须 > 0，收到：{}".format(fx), code=2, missing=["fx"])
    if price <= 0:
        fail("price 必须 > 0，收到：{}".format(price), code=2, missing=["price"])

    ads = raw.get("ads_pct")
    if ads is None:
        if not quiet:
            notes.append("未提供 --ads-pct，按默认 10.0% 计算")
        ads = DEFAULT_ADS_PCT
    returns = raw.get("returns_pct")
    if returns is None:
        if not quiet:
            notes.append("未提供 --returns-pct，按默认 3.0% 计算")
        returns = DEFAULT_RETURNS_PCT
    target = raw.get("target_margin")
    if target is None:
        if not quiet:
            notes.append("未提供 --target-margin，按默认 25.0% 反算目标价")
        target = DEFAULT_TARGET_MARGIN
    moq = raw.get("moq")
    if moq is None:
        if not quiet:
            notes.append("未提供 --moq，按默认 500 件计算占款")
        moq = DEFAULT_MOQ
    customs_raw = raw.get("customs_fee_per_unit")
    customs_placeholder = customs_raw is None
    if customs_placeholder:
        notes.append(
            "[WARN] 未提供 --customs-fee-per-unit，报关杂费按默认 $0.18/件计算"
        )
        customs_raw = DEFAULT_CUSTOMS_FEE

    if raw.get("duty_pct") is not None:
        duty_pct = raw["duty_pct"]
        duty_source = "explicit"
        hts_key = None
        mfn = None
        section = None
    else:
        hts_key, entry = lookup_hts(ctx, raw.get("hts"))
        mfn = entry.get("mfn_pct", 0.0)
        section = entry.get("section301_pct", 0.0)
        duty_pct = mfn + section
        duty_source = "hts"
        if not entry.get("verified", False):
            notes.append(
                "HTS {} 为未核校示例（未含 2026 附加层），必须用 --duty-pct 覆盖后再定价".format(
                    hts_key
                )
            )

    platform = raw.get("platform") or DEFAULT_PLATFORM
    platform_conf = platform_config(ctx, platform)
    if raw.get("platform") is None:
        notes.append("未提供 --platform，按 amazon_us 计算")

    if platform == "tiktok_us":
        cat_key = raw.get("category_key") or raw.get("category")
        cat_source = "explicit"
    else:
        cat_key, cat_source, cat_notes = choose_category(raw)
        notes.extend(cat_notes)
        if cat_source == "assumed_default":
            assumptions.append(
                "referral 按 default 15% 估算（--assume-default-referral）"
            )
            notes.append(
                "[WARN] referral 按 default 15% 估算（--assume-default-referral）；"
                "必须按真实类目复核"
            )

    fob = round2(factory * fx)
    duty_usd = round2(fob * duty_pct / 100.0)
    freight = round2(freight_raw)
    customs = round2(customs_raw)
    landed = round2(fob + freight + duty_usd + customs)

    referral, referral_notes = referral_amount(
        ctx, platform, platform_conf, cat_key, price, raw.get("referral")
    )
    notes.extend(referral_notes)

    fba = fba_detail(ctx, raw, price, notes)

    referral_usd = referral["referral_usd"]
    ads_usd = round2(price * ads / 100.0)
    returns_usd = round2(price * returns / 100.0)

    variable_pct = referral["referral_pct"] + ads + returns
    if variable_pct >= 100:
        fail(
            "referral + 广告 + 退货合计 ≥ 100%，无法计算盈亏价",
            code=2,
            missing=["referral|ads_pct|returns_pct"],
        )
    break_even = round2((landed + fba["fee"]) / (1 - variable_pct / 100.0))

    if variable_pct + target >= 100:
        fail(
            "referral + 广告 + 退货 + 目标净利率合计 ≥ 100%，无法反算目标价；"
            "请降低 target-margin 或复核费率",
            code=2,
            missing=["target_margin"],
        )
    target_price = round2((landed + fba["fee"]) / (1 - (variable_pct + target) / 100.0))

    if referral["tiered"]:
        notes.append(
            "盈亏价/目标价使用当前售价下的有效 referral 费率近似反算；分段费率建议用 calc 逐价复核。"
        )

    net = round2(price - landed - referral_usd - fba["fee"] - ads_usd - returns_usd)
    margin = round2(net / price * 100.0)
    contribution = round2(price - landed - referral_usd - fba["fee"])
    price_gap = round2(price - target_price)
    reached = price >= target_price
    cash = round2(landed * moq)

    return {
        "inputs": {
            "factory_rmb": num(factory),
            "fx_cny_usd": fx,
            "freight_per_unit_usd": freight,
            "customs_fee_per_unit_usd": customs,
            "customs_fee_placeholder": customs_placeholder,
            "duty_pct": num(duty_pct),
            "duty_source": duty_source,
            "hts": hts_key,
            "mfn_pct": mfn,
            "section301_pct": section,
            "platform": platform,
            "category": cat_key if platform == "tiktok_us" else referral["category"],
            "category_key": cat_key,
            "category_source": cat_source,
            "referral_pct": referral["referral_pct"],
            "referral_source": referral["source"],
            "fba_fee_usd": fba["fee"],
            "fba_tier": fba["tier"],
            "fba_tier_label": fba["tier_label"],
            "fba_season": fba["season"],
            "fba_price_band": fba["band"],
            "fba_base_fee_usd": fba["base"],
            "fba_surcharge_pct": fba["surcharge"],
            "weight_oz": fba["weight_oz"],
            "ads_pct": num(ads),
            "returns_pct": num(returns),
            "price_usd": num(price),
            "target_margin_pct": num(target),
            "moq": moq,
        },
        "costs": {
            "fob_usd": fob,
            "freight_usd": freight,
            "duty_usd": duty_usd,
            "customs_fee_usd": customs,
            "landed_cost_usd": landed,
        },
        "fees": {
            "referral_usd": referral_usd,
            "referral_pct_effective": referral["referral_pct"],
            "fba_fee_usd": fba["fee"],
            "ads_usd": ads_usd,
            "returns_usd": returns_usd,
        },
        "profit": {
            "net_profit_usd": net,
            "net_margin_pct": margin,
            "contribution_per_unit_usd": contribution,
        },
        "pricing": {
            "break_even_price_usd": break_even,
            "target_price_usd": target_price,
            "price_gap_usd": price_gap,
            "target_price_reached": reached,
        },
        "cash": {"moq": moq, "cash_required_usd": cash},
        "summary": {
            "net_margin_pct": margin,
            "break_even_price": break_even,
            "target_price": target_price,
            "cash_required": cash,
            "contribution_per_unit": contribution,
        },
        "assumptions": assumptions,
        "notes": notes,
    }


def render_calc(payload):
    i = payload["inputs"]
    c = payload["costs"]
    f = payload["fees"]
    p = payload["profit"]
    pr = payload["pricing"]
    price = i["price_usd"]

    if i["duty_source"] == "hts":
        duty_line = "- 关税：HTS {} → MFN {:.2f}% + Section 301 {:.2f}% = **{:.2f}%**".format(
            i["hts"], i["mfn_pct"] or 0.0, i["section301_pct"] or 0.0, i["duty_pct"]
        )
    else:
        duty_line = "- 关税：显式 --duty-pct **{:.2f}%**（未使用 HTS 推导）".format(
            i["duty_pct"]
        )

    if i["fba_tier"] == "explicit":
        fba_line = "- FBA：**{}**（显式 --fba-fee）".format(money(i["fba_fee_usd"]))
    else:
        season_cn = "旺季" if i["fba_season"] == "peak" else "非旺季"
        fba_line = "- FBA：{} / {} / {} 档；基准 {} + 燃油附加 {:.2f}% → **{}**（{} oz）".format(
            i["fba_tier_label"],
            season_cn,
            i["fba_price_band"],
            money(i["fba_base_fee_usd"]),
            i["fba_surcharge_pct"],
            money(i["fba_fee_usd"]),
            i["weight_oz"],
        )

    def share(amount):
        return "{:.2f}%".format(amount / price * 100.0)

    gap = pr["price_gap_usd"]
    if pr["target_price_reached"]:
        gap_text = "高于目标价 {}".format(money(gap))
    else:
        gap_text = "低于目标价 {}".format(money(abs(gap)))

    lines = [
        "# 到岸成本与定价测算",
        "",
        "## 1. 输入与口径",
        "",
        "- 工厂价：¥{:,.2f} / 件；汇率：1 CNY = {:.4f} USD；MOQ：{} 件".format(
            i["factory_rmb"], i["fx_cny_usd"], i["moq"]
        ),
        "- 售价：{}；广告：{:.2f}%；退货：{:.2f}%".format(
            money(price), i["ads_pct"], i["returns_pct"]
        ),
        duty_line,
        "- 平台：{}；类目：{}（来源：{}）；referral 有效费率：**{:.2f}%**".format(
            i["platform"],
            i["category_key"] or "-",
            i["category_source"],
            i["referral_pct"],
        ),
        fba_line,
        "- 目标净利率：{:.2f}%；报关杂费：{} / 件".format(
            i["target_margin_pct"], money(i["customs_fee_per_unit_usd"])
        ),
        "",
    ]
    for note in payload["notes"]:
        lines.append("- {}".format(note))
    lines += [
        "",
        "## 2. 到岸成本拆解",
        "",
        "| 成本项 | 金额 | 说明 |",
        "|---|---|---|",
        "| FOB（出厂价折美元） | {} | ¥{:,.2f} × {:.4f} |".format(
            money(c["fob_usd"]), i["factory_rmb"], i["fx_cny_usd"]
        ),
        "| 头程物流 | {} | 单件分摊 |".format(money(c["freight_usd"])),
        "| 关税 | {} | {:.2f}% × FOB |".format(money(c["duty_usd"]), i["duty_pct"]),
        "| 报关杂费 | {} | 单件固定值，需按货代报价替换 |".format(
            money(c["customs_fee_usd"])
        ),
        "| **到岸成本** | **{}** | 含 FOB + 头程 + 关税 + 杂费 |".format(
            money(c["landed_cost_usd"])
        ),
        "",
        "## 3. 定价与利润",
        "",
        "| 项 | 金额 | 占售价 |",
        "|---|---|---|",
        "| 售价 | {} | 100.00% |".format(money(price)),
        "| 到岸成本 | {} | {} |".format(
            money(c["landed_cost_usd"]), share(c["landed_cost_usd"])
        ),
        "| 平台佣金（{:.2f}%） | {} | {} |".format(
            i["referral_pct"], money(f["referral_usd"]), share(f["referral_usd"])
        ),
        "| FBA 费 | {} | {} |".format(
            money(f["fba_fee_usd"]), share(f["fba_fee_usd"])
        ),
        "| 广告（{:.2f}%） | {} | {} |".format(
            i["ads_pct"], money(f["ads_usd"]), share(f["ads_usd"])
        ),
        "| 退货（{:.2f}%） | {} | {} |".format(
            i["returns_pct"], money(f["returns_usd"]), share(f["returns_usd"])
        ),
        "| **净利** | **{}** | **{:.2f}%** |".format(
            money(p["net_profit_usd"]), p["net_margin_pct"]
        ),
        "| 每件贡献毛利（广告/退货前） | {} | — |".format(
            money(p["contribution_per_unit_usd"])
        ),
        "",
        "> 净利率 {:.2f}%；目标净利率 {:.2f}%；差额 {:.2f} 个百分点。".format(
            p["net_margin_pct"],
            i["target_margin_pct"],
            p["net_margin_pct"] - i["target_margin_pct"],
        ),
        "",
        "## 4. 底线价与现金流",
        "",
        "| 项 | 数值 | 含义 |",
        "|---|---|---|",
        "| 盈亏价 | {} | 低于此价每单亏钱（净利 = 0） |".format(
            money(pr["break_even_price_usd"])
        ),
        "| 目标价（按目标净利反算） | {} | 当前价 {}，{} |".format(
            money(pr["target_price_usd"]), money(price), gap_text
        ),
        "| MOQ 占款（按到岸成本） | {} | {} 件 × 到岸成本；不含广告/运营现金 |".format(
            money(payload["cash"]["cash_required_usd"]), i["moq"]
        ),
        "",
        "> 盈亏价公式：P₀ = (到岸成本 + FBA) ÷ (1 − referral − 广告 − 退货)。目标价公式同上，分母再减目标净利率。",
        "> 关税/费率均为时点口径：Section 301、IEEPA、芬太尼相关关税、对等关税、AD/CVD 及 HTS 归类必须由报关行复核；平台费率与 FBA 档位发布前按卖家中心复核。",
    ]
    print("\n".join(lines))


def handle_calc(args, ctx):
    missing = []
    if args.factory_rmb is None:
        missing.append("--factory-rmb")
    if args.fx is None:
        missing.append("--fx")
    if args.freight_per_unit is None:
        missing.append("--freight-per-unit")
    if args.fba_fee is None and args.weight_g is None and args.weight_oz is None:
        missing.append("--fba-fee 或 --weight-g/--weight-oz")
    if args.price is None:
        missing.append("--price")
    if args.duty_pct is None and args.hts is None:
        missing.append("--duty-pct 或 --hts")
    if missing:
        fail(
            "calc 缺少参数：{}。最小输入：--factory-rmb --fx --freight-per-unit --price，"
            "以及 --duty-pct/--hts 和 --fba-fee/--weight-g，以及 --category-key/--category".format(
                ", ".join(missing)
            ),
            code=2,
            missing=missing,
        )

    raw = {
        "factory_rmb": args.factory_rmb,
        "fx": args.fx,
        "freight_per_unit": args.freight_per_unit,
        "duty_pct": args.duty_pct,
        "hts": args.hts,
        "category": args.category,
        "category_key": args.category_key,
        "assume_default_referral": args.assume_default_referral,
        "platform": args.platform,
        "referral": args.referral,
        "fba_fee": args.fba_fee,
        "weight_g": args.weight_g,
        "weight_oz": args.weight_oz,
        "tier": args.tier,
        "season": args.season,
        "ship_date": args.ship_date,
        "no_fuel_surcharge": args.no_fuel_surcharge,
        "ads_pct": args.ads_pct,
        "returns_pct": args.returns_pct,
        "price": args.price,
        "target_margin": args.target_margin,
        "moq": args.moq,
        "customs_fee_per_unit": args.customs_fee_per_unit,
        "_map": ctx.category_map,
    }
    payload = compute_sku(ctx, raw)
    if args.json:
        emit_json(payload)
    else:
        render_calc(payload)
    return 0


def cell(row, name):
    value = row.get(name)
    if value is None:
        return None
    value = value.strip()
    return value if value else None


def parse_float(value, row_no, column):
    if value is None:
        return None
    text = value.replace(",", "").replace("$", "").strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        fail(
            "第 {} 行 {} 不是数字：{}".format(row_no, column, value),
            code=2,
            missing=[],
        )


def handle_matrix(args, ctx):
    if args.file is None:
        fail("matrix 缺少参数：--file", code=2, missing=["file"])
    if args.fx is None:
        fail("matrix 缺少参数：--fx", code=2, missing=["fx"])
    if args.fx <= 0:
        fail("fx 必须 > 0", code=2, missing=["fx"])

    path = Path(args.file)
    if not path.exists():
        fail("找不到 SKU 文件：{}".format(args.file), code=2, missing=["file"])

    with open(path, "r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            fail("CSV 没有表头", code=2, missing=["file"])
        headers = [name.strip() for name in reader.fieldnames]
        rows = [{key: row.get(key) for key in reader.fieldnames} for row in reader]

    required = ["sku", "factory_rmb", "freight_per_unit", "price"]
    absent = [name for name in required if name not in headers]
    if absent:
        fail(
            "SKU CSV 缺少必需列：{}。必需列：sku, factory_rmb, freight_per_unit, price；"
            "关税列：duty_pct 或 hts；FBA 列：fba_fee 或 weight_g".format("、".join(absent)),
            code=2,
            missing=absent,
        )
    if "duty_pct" not in headers and "hts" not in headers:
        fail(
            "SKU CSV 缺少关税列：duty_pct 或 hts 至少一个",
            code=2,
            missing=["duty_pct|hts"],
        )
    if "fba_fee" not in headers and "weight_g" not in headers and "weight_oz" not in headers:
        fail(
            "SKU CSV 缺少 FBA 列：fba_fee 或 weight_g/weight_oz 至少一个",
            code=2,
            missing=["fba_fee|weight_g"],
        )
    if not rows:
        fail("SKU CSV 没有数据行", code=2, missing=["file"])

    successes = []
    failures = []
    for index, row in enumerate(rows, start=2):
        sku = cell(row, "sku")
        try:
            if sku is None:
                fail("第 {} 行 sku 为空".format(index), code=2, missing=[])
            numbers = {
                name: parse_float(cell(row, name), index, name)
                for name in (
                    "factory_rmb", "freight_per_unit", "price", "ads_pct",
                    "returns_pct", "target_margin", "customs_fee_per_unit",
                    "duty_pct", "fba_fee", "weight_g", "weight_oz", "referral",
                )
            }
            for name in ("factory_rmb", "freight_per_unit", "price"):
                if numbers[name] is None:
                    fail(
                        "第 {} 行 {} 为空".format(index, name),
                        code=2,
                        missing=[],
                    )
            if numbers["duty_pct"] is None and cell(row, "hts") is None:
                fail(
                    "第 {} 行 duty_pct 与 hts 均为空".format(index),
                    code=2,
                    missing=[],
                )
            if (
                numbers["fba_fee"] is None
                and numbers["weight_g"] is None
                and numbers["weight_oz"] is None
            ):
                fail(
                    "第 {} 行 fba_fee 与 weight_g/weight_oz 均为空".format(index),
                    code=2,
                    missing=[],
                )

            platform = cell(row, "platform")

            moq_raw = cell(row, "moq")
            moq = None
            if moq_raw is not None:
                moq = int(float(moq_raw.replace(",", "").replace("$", "")))

            season = cell(row, "season")
            if season not in ("peak", "nonpeak"):
                season = None

            raw = {
                "factory_rmb": numbers["factory_rmb"],
                "fx": args.fx,
                "freight_per_unit": numbers["freight_per_unit"],
                "duty_pct": numbers["duty_pct"],
                "hts": cell(row, "hts"),
                "category": cell(row, "category"),
                "category_key": cell(row, "category_key"),
                "assume_default_referral": args.assume_default_referral,
                "platform": platform,
                "referral": numbers["referral"],
                "fba_fee": numbers["fba_fee"],
                "weight_g": numbers["weight_g"],
                "weight_oz": numbers["weight_oz"],
                "tier": cell(row, "fba_tier"),
                "season": season,
                "ship_date": cell(row, "ship_date"),
                "no_fuel_surcharge": bool(cell(row, "no_fuel_surcharge")),
                "ads_pct": numbers["ads_pct"],
                "returns_pct": numbers["returns_pct"],
                "price": numbers["price"],
                "target_margin": numbers["target_margin"],
                "moq": moq,
                "customs_fee_per_unit": numbers["customs_fee_per_unit"],
                "_map": ctx.category_map,
                "_quiet_defaults": True,
            }
            payload = compute_sku(ctx, raw)
            if payload["pricing"]["target_price_reached"]:
                judgement = "达标"
            elif payload["pricing"]["break_even_price_usd"] <= numbers["price"]:
                judgement = "低于目标净利"
            else:
                judgement = "亏损"
            payload["sku"] = sku
            payload["judgement"] = judgement
            successes.append(payload)
        except CliFailure as exc:
            failures.append(
                {
                    "row": index,
                    "sku": sku,
                    "message": exc.message,
                    "missing": exc.missing,
                }
            )

    meta = {
        "generated_by": "landed_cost.py matrix",
        "fx_cny_usd": args.fx,
        "defaults": "未提供列按默认：ads_pct 10.0% / returns_pct 3.0% / target_margin 25.0% / moq 500 / 报关杂费 $0.18",
        "rows": len(successes),
    }

    if failures:
        merged = sorted({name for failure in failures for name in failure["missing"]})
        parts = []
        for failure in failures:
            if failure["sku"]:
                prefix = "第 {} 行（{}）：".format(failure["row"], failure["sku"])
            else:
                prefix = "第 {} 行：".format(failure["row"])
            parts.append(prefix + failure["message"])
        message = "以下 SKU 行无法计算（整表其余行已继续）：" + "；".join(parts)
        payload = {
            "status": "INPUT_MISSING",
            "missing": merged,
            "message": message,
            "failed_rows": failures,
            "rows": successes,
        }
        if args.json:
            emit_json(payload)
        else:
            render_matrix(meta, successes, failures)
            sys.stderr.write("[INPUT_MISSING] {}\n".format(message))
        return 2

    payload = {"meta": meta, "rows": successes}
    if args.json:
        emit_json(payload)
    else:
        render_matrix(meta, successes, failures)
    return 0


def render_matrix(meta, rows, failures):
    lines = [
        "# SKU 到岸成本与定价矩阵",
        "",
        "- 汇率：1 CNY = {:.4f} USD；金额单位 USD".format(meta["fx_cny_usd"]),
        "- {}".format(meta["defaults"]),
        "",
        "| SKU | 到岸成本 | 售价 | 净利/件 | 净利率 | 盈亏价 | 目标价 | MOQ占款 | 判断 |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for row in rows:
        lines.append(
            "| {} | {} | {} | {} | {}% | {} | {} | {} | {} |".format(
                row["sku"],
                money(row["costs"]["landed_cost_usd"]),
                money(row["inputs"]["price_usd"]),
                money(row["profit"]["net_profit_usd"]),
                row["profit"]["net_margin_pct"],
                money(row["pricing"]["break_even_price_usd"]),
                money(row["pricing"]["target_price_usd"]),
                money(row["cash"]["cash_required_usd"]),
                row["judgement"],
            )
        )
    total_cash = round2(sum(row["cash"]["cash_required_usd"] for row in rows))
    lines += ["", "- 合计 MOQ 占款（按到岸成本）：{}".format(money(total_cash))]
    if rows:
        best = max(rows, key=lambda item: item["profit"]["net_margin_pct"])
        worst = min(rows, key=lambda item: item["profit"]["net_margin_pct"])
        lines.append(
            "- 净利率最高：{}（{}%）；最低：{}（{}%）".format(
                best["sku"], best["profit"]["net_margin_pct"],
                worst["sku"], worst["profit"]["net_margin_pct"],
            )
        )
    unverified = sorted(
        row["sku"]
        for row in rows
        if any("为未核校示例" in note for note in row.get("notes", []))
    )
    lines += [
        "",
        "> 判断口径：售价 ≥ 目标价 = 达标；≥ 盈亏价但 < 目标价 = 低于目标净利；< 盈亏价 = 亏损。",
    ]
    if unverified:
        lines.append(
            "> **关税口径提醒**：{} 使用未核校的 HTS 示例税率，正式报价前必须用 --duty-pct 覆盖。".format(
                "、".join(unverified)
            )
        )
    lines.append("> 价格、费率与税率均为时点值，发布前按卖家中心与报关行复核。")
    if failures:
        lines += ["", "## 无法计算的行（已跳过，整表继续）", ""]
        for failure in failures:
            lines.append("- 第 {} 行（{}）：{}".format(failure["row"], failure["sku"], failure["message"]))
    print("\n".join(lines))


def print_platforms(ctx):
    fees = ctx.fees
    meta = fees.get("_meta", {})
    lines = [
        "# 平台费率速查",
        "",
        "- 口径日期：{}；币种：{}".format(
            meta.get("updated", "-"), meta.get("currency", "USD")
        ),
        "- {}".format(meta.get("disclaimer", "")),
        "",
    ]
    for key, platform in fees.get("platforms", {}).items():
        lines.append("## {}（{}）".format(platform.get("name", key), key))
        lines.append("")
        lines.append(
            "- 默认 referral：{:.2f}%；每件最低销售佣金：{}".format(
                platform.get("default_referral_pct", 0.0),
                money(platform.get("min_referral_fee_usd", 0.0)),
            )
        )
        categories = platform.get("categories")
        if categories:
            lines += ["", "| 类目 key | 类目 | referral 分段 | 备注 |", "|---|---|---|---|"]
            for ckey, cvalue in categories.items():
                lines.append(
                    "| {} | {} | {} | {} |".format(
                        ckey,
                        cvalue.get("label", ""),
                        render_referral_segments(cvalue),
                        cvalue.get("note", ""),
                    )
                )
        elif platform.get("note"):
            lines.append("")
            lines.append("- 备注：{}".format(platform["note"]))
        lines.append("")
    print("\n".join(lines))


def render_referral_segments(category):
    tiers = category.get("tiers")
    if not tiers:
        return "{:.1f}%".format(category.get("referral_pct", 0.0))
    if len(tiers) == 1:
        return "{:.1f}%".format(tiers[0].get("pct", 0.0))
    parts = []
    prev = None
    for tier in tiers:
        pct_value = "{:.1f}%".format(tier.get("pct", 0.0))
        ceiling = tier.get("max_price_usd")
        if ceiling is None:
            parts.append(">{} 部分 {}".format(money(prev), pct_value))
        elif prev is None:
            parts.append("≤{} 部分 {}".format(money(ceiling), pct_value))
        else:
            parts.append("{}–{} 部分 {}".format(money(prev), money(ceiling), pct_value))
        prev = ceiling
    return "<br>".join(parts)


def print_fba_tiers(ctx):
    fba = ctx.fees.get("fba", {})
    fba_meta = fba.get("_meta", {})
    lines = [
        "# FBA 尺寸档速查（2026 年）",
        "",
        "- 口径日期：{}".format(fba_meta.get("updated", "-")),
        "- 非旺季：{} 至 {}".format(NONPEAK_START, NONPEAK_END),
        "- 旺季：{} 至 {}".format(PEAK_START, PEAK_END),
        "- 燃油与物流附加费：{}%，自 {} 起".format(
            fba.get("fuel_surcharge_pct", FUEL_PCT),
            fba.get("fuel_surcharge_effective", FUEL_EFFECTIVE),
        ),
        "- **{}**".format(fba_meta.get("note", "")),
        "",
    ]
    for season, title in (("nonpeak", "非旺季"), ("peak", "旺季")):
        lines += [
            "## {}（价格档 <$10 / $10–$50 / >$50）".format(title),
            "",
            "| 档位 | 发货重量 | <$10 | $10–$50 | >$50 |",
            "|---|---|---|---|---|",
        ]
        for key, tier in fba.get("tiers", {}).items():
            if "rates" not in tier:
                continue
            prev_oz = None
            for row in tier["rates"].get(season, []):
                if "fees" in row:
                    rates = row["fees"]
                    max_oz = row.get("max_oz")
                    if prev_oz is None:
                        weight = "≤{} oz".format(max_oz)
                    else:
                        weight = "{}–{} oz".format(prev_oz, max_oz)
                    lines.append(
                        "| {} | {} | {} | {} | {} |".format(
                            tier.get("label", key), weight,
                            money(rates["lt10"]), money(rates["10_50"]), money(rates["gt50"]),
                        )
                    )
                    prev_oz = max_oz
                else:
                    over = row["over_3lb"]
                    per = money(over["per_4oz_usd"])
                    lines.append(
                        "| {} | 3–20 lb | {} | {} | {} |".format(
                            tier.get("label", key),
                            "{} + {}/4oz".format(money(over["base"]["lt10"]), per),
                            "{} + {}/4oz".format(money(over["base"]["10_50"]), per),
                            "{} + {}/4oz".format(money(over["base"]["gt50"]), per),
                        )
                    )
                    prev_oz = row.get("max_oz")
        lines.append("")
    print("\n".join(lines))


def main(argv):
    set_json_mode("--json" in argv)
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
        ctx = Context()
        if args.list_platforms:
            print_platforms(ctx)
            return 0
        if args.list_fba_tiers:
            print_fba_tiers(ctx)
            return 0
        if getattr(args, "handler", None) is None:
            parser.print_help(sys.stdout)
            fail("缺少子命令：calc 或 matrix", code=2, missing=[])
        return args.handler(args, ctx)
    except CliFailure as exc:
        emit_failure(exc)
        return exc.code


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
