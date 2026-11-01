#!/usr/bin/env python3
"""US market compliance pre-screen.

Implements docs/spec/03_compliance.md: rule-library driven document checklist,
PASS / CONDITIONAL / BLOCKED status, and exit codes 0 / 1 / 2 / 3.
"""

import datetime
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from shared.args import CliArgumentParser
from shared.category import normalize_path
from shared.errors import CliFailure, fail, emit_json, emit_failure, set_json_mode

SCRIPT_DIR = Path(__file__).resolve().parent
RULES_PATH = SCRIPT_DIR / "compliance_rules.json"
MAP_PATH = ROOT / "config" / "category_map.json"

STATUS_CN = {"have": "已具备", "missing": "缺失", "unknown": "待确认", "blocked": "blocked"}
PENDING_MARKERS = (
    "pending", "待出", "待定", "申请中", "办理中", "进行中", "审核中",
    "in progress", "awaiting",
)
TRUE_WORDS = {"true", "yes", "y", "1", "on"}
FALSE_WORDS = {"false", "no", "n", "0", "off"}


def load_rules():
    try:
        with open(RULES_PATH, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except FileNotFoundError:
        fail("找不到合规规则库：{}".format(RULES_PATH), code=3)
    except (OSError, ValueError) as exc:
        fail("合规规则库无法解析：{}（{}）".format(RULES_PATH, exc), code=3)


def load_map():
    try:
        with open(MAP_PATH, "r", encoding="utf-8-sig") as handle:
            return json.load(handle)
    except FileNotFoundError:
        fail("找不到类目映射文件：{}".format(MAP_PATH), code=3)
    except (OSError, ValueError) as exc:
        fail("类目映射文件无法解析：{}（{}）".format(MAP_PATH, exc), code=3)


def build_parser():
    parser = CliArgumentParser(
        prog="compliance_gate.py",
        description="美国市场准入合规初筛",
        error_exit_code=3,
    )
    parser.add_argument("--category")
    parser.add_argument("--attr", action="append", default=[])
    parser.add_argument("--marketplace", choices=["amazon_us", "tiktok_us", "both"])
    parser.add_argument("--have", action="append", default=[])
    parser.add_argument(
        "--trademark",
        choices=["none", "pending", "registered_us", "conflict"],
    )
    parser.add_argument("--patent-search-done")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--list-categories", action="store_true")
    parser.add_argument("--list-attributes", action="store_true")
    return parser


def split_values(values):
    items = []
    for value in values:
        for part in re.split(r"[,;；、]", value):
            part = part.strip()
            if part:
                items.append(part)
    return items


def normalize_name(value):
    text = value.lower()
    text = re.sub(r"[^\w .\-/]", " ", text, flags=re.UNICODE)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def resolve_category(raw, category_map, rules):
    categories = category_map.get("categories", {})
    aliases = category_map.get("aliases", {})

    if raw in categories:
        return raw, "explicit"

    if raw in aliases and aliases[raw] in categories:
        target = aliases[raw]
        sys.stderr.write(
            "[WARN] 类目旧键 {} 已映射为 category_key={}\n".format(raw, target)
        )
        return target, "alias"

    wanted = normalize_path(raw)
    longest = 0
    matches = []
    for key, entry in categories.items():
        for prefix in entry.get("platform_paths", []) or []:
            normalized = normalize_path(prefix)
            if wanted == normalized or wanted.startswith(normalized + " >"):
                if len(normalized) > longest:
                    longest = len(normalized)
                    matches = [key]
                elif len(normalized) == longest:
                    matches.append(key)
    distinct = set(matches)
    if len(distinct) > 1:
        fail("类目路径存在歧义：{}".format(raw), code=3)
    if distinct:
        key = matches[0]
        sys.stderr.write(
            "[WARN] 收到平台类目路径，已映射为 category_key={}\n".format(key)
        )
        return key, "platform_path"

    if raw in rules.get("categories", {}):
        return raw, "rules_direct"

    fail(
        "无法识别的类目：{}。可选 category_key：{}；也接受 Amazon 类目路径。".format(
            raw, "、".join(sorted(key for key in categories if key != "default"))
        ),
        code=3,
    )


def parse_bool(value):
    lowered = value.strip().lower()
    if lowered in TRUE_WORDS:
        return True
    if lowered in FALSE_WORDS:
        return False
    fail(
        "patent_search_done 非法：{}（可用 true/false/yes/no/y/n/1/0/on/off）".format(
            value
        ),
        code=3,
    )


def merge_docs(rules, category_label, attributes, marketplaces):
    library = rules["doc_library"]
    groups = [("category:" + category_label, rules["categories"][category_label]["docs"])]
    for attr in attributes:
        groups.append(("attr:" + attr, rules["attributes"][attr]["docs"]))
    for marketplace in marketplaces:
        groups.append(
            ("marketplace:" + marketplace, rules["marketplaces"][marketplace]["docs"])
        )

    ordered = []
    index = {}
    for group, doc_ids in groups:
        for doc_id in doc_ids:
            source = library[doc_id]
            if doc_id not in index:
                item = {
                    "id": doc_id,
                    "name": source.get("name"),
                    "authority": source.get("authority"),
                    "trigger": source.get("trigger", ""),
                    "blocking": bool(source.get("blocking", False)),
                    "advisory": bool(source.get("advisory", False)),
                    "sources": [group],
                    "citations": list(source.get("sources", [])),
                    "as_of": source.get("as_of"),
                    "confidence": source.get("confidence", "needs_review"),
                    "_default_status": source.get("default_status"),
                    "_aliases": list(source.get("aliases", [])),
                }
                index[doc_id] = item
                ordered.append(item)
            else:
                item = index[doc_id]
                trigger = source.get("trigger", "")
                if trigger and trigger not in item["trigger"]:
                    item["trigger"] = (
                        "{}{}".format(item["trigger"] + "；", trigger)
                        if item["trigger"]
                        else trigger
                    )
                if group not in item["sources"]:
                    item["sources"].append(group)
                for citation in source.get("sources", []) or []:
                    if citation not in item["citations"]:
                        item["citations"].append(citation)
                item["blocking"] = item["blocking"] or bool(
                    source.get("blocking", False)
                )
    return ordered


def ip_screening(rules, trademark, trademark_provided, patent_done):
    items = rules["ip_screening"]["items"]
    mapping = rules["ip_screening"]["trademark_status_map"]
    results = []

    if trademark_provided:
        trademark_status = mapping[trademark]
    else:
        trademark_status = "unknown"

    if trademark_status == "missing":
        trademark_note = "尚未做商标检索：无法排除与他人注册 / 申请中商标冲突。"
    elif trademark_status == "have":
        trademark_note = "已有美国注册商标：仍需核对注册类别与产品用途是否匹配。"
    elif trademark_status == "blocked":
        trademark_note = "已识别商标冲突：未经许可不得销售，需改品牌或取得授权。"
    elif trademark_provided:
        trademark_note = "商标状态未明确：{} 不产生可诉权利，也不能阻止他人注册。".format(
            trademark
        )
    else:
        trademark_note = "未提供商标状态：无法判断商标可用性与被投诉风险。"

    patent_status = "have" if patent_done else "unknown"
    design_note = (
        "已完成外观专利初筛，仍需律师复核权利要求比对。"
        if patent_status == "have"
        else "未做外观专利检索：外形相似不等于侵权，但被投诉下架的概率高。"
    )
    utility_note = (
        "已完成实用专利初筛，仍需做 FTO 意见。"
        if patent_status == "have"
        else "未做实用专利检索：结构 / 原理层面的专利风险未评估。"
    )

    registry_status = {
        "have": "unknown",
        "blocked": "blocked",
    }.get(trademark_status, "missing")
    if registry_status == "blocked":
        registry_note = "品牌存在冲突，无法正常备案与维权。"
    elif registry_status == "unknown":
        registry_note = "有美国注册商标才可申请 Brand Registry；备案不等于已获批。"
    else:
        registry_note = "无美国注册商标，无法备案 Brand Registry，被跟卖时缺少平台工具。"

    actions = {
        "us_trademark": "到 USPTO 做文字 + 图形检索，并核对注册类别；注册申请周期通常 8-14 个月。",
        "us_design_patent": "按产品外形特征检索 US Design Patent，重点看杯体、刀头、按键布局。",
        "us_utility_patent": "按结构关键词做 FTO 初筛；命中近似专利时请专利律师出意见。",
        "amazon_brand_registry": "先完成商标注册，再提交 Brand Registry；同步准备包装与 Listing 的品牌一致性材料。",
    }
    notes = {
        "us_trademark": trademark_note,
        "us_design_patent": design_note,
        "us_utility_patent": utility_note,
        "amazon_brand_registry": registry_note,
    }
    statuses = {
        "us_trademark": trademark_status,
        "us_design_patent": patent_status,
        "us_utility_patent": patent_status,
        "amazon_brand_registry": registry_status,
    }

    for entry in items:
        status = statuses[entry["id"]]
        results.append(
            {
                "id": entry["id"],
                "item": entry["item"],
                "scope": entry["scope"],
                "authority": entry["authority"],
                "status": status,
                "blocked": status == "blocked",
                "note": notes[entry["id"]],
                "action": actions[entry["id"]],
            }
        )
    return results, trademark_status


def evaluate(args):
    rules = load_rules()
    category_map = load_map()

    if args.category is None:
        fail("缺少 --category（必填）", code=3)
    category_key, category_source = resolve_category(
        args.category, category_map, rules
    )
    entry = category_map["categories"].get(category_key)
    compliance_key = entry.get("compliance_key") if entry else None
    if not compliance_key or compliance_key not in rules["categories"]:
        fail(
            "类目 {}（category_key={}）在合规规则库中没有对应类目；可选：{}。"
            "请人工确认后改传合规类目键。".format(
                args.category,
                category_key,
                "、".join(sorted(rules["categories"])),
            ),
            code=3,
        )

    attributes = split_values(args.attr)
    if not attributes:
        fail(
            "缺少字段：attributes。属性标签由选品阶段填写，缺失会导致漏掉阻断级义务。",
            code=3,
        )
    unknown_attrs = [a for a in attributes if a not in rules["attributes"]]
    if unknown_attrs:
        fail(
            "未知属性：{}。可选：{}".format(
                "、".join(unknown_attrs), "、".join(rules["attributes"])
            ),
            code=3,
        )
    if not args.marketplace:
        fail("缺少字段：marketplace。可选：amazon_us / tiktok_us / both", code=3)

    marketplaces = (
        ["amazon_us", "tiktok_us"]
        if args.marketplace == "both"
        else [args.marketplace]
    )

    raw_have = split_values(args.have)
    input_warnings = []
    effective_have = []
    for item in raw_have:
        lowered = item.lower()
        if any(marker in lowered for marker in PENDING_MARKERS):
            input_warnings.append(
                "[INPUT_MISSING] {} 含 pending 标记，按未具备处理".format(item)
            )
        else:
            effective_have.append(item)

    trademark_provided = args.trademark is not None
    if trademark_provided:
        trademark_value = args.trademark
        trademark_display = trademark_value
    else:
        trademark_value = None
        trademark_display = "未提供"
        input_warnings.append(
            "[INPUT_MISSING] trademark_status 未提供，按未做商标检索处理。"
        )

    if args.patent_search_done is None:
        patent_done = False
        patent_display = "未提供"
        input_warnings.append(
            "[INPUT_MISSING] patent_search_done 未提供，按未完成检索处理。"
        )
    else:
        patent_done = parse_bool(args.patent_search_done)
        patent_display = patent_done

    docs = merge_docs(rules, compliance_key, attributes, marketplaces)

    normalized_have = [normalize_name(item) for item in effective_have]
    for doc in docs:
        candidates = [doc["id"], doc["name"], *doc["_aliases"]]
        matched = False
        for candidate in candidates:
            normalized = normalize_name(str(candidate))
            if not normalized:
                continue
            for provided in normalized_have:
                if normalized in provided or provided in normalized:
                    matched = True
                    break
            if matched:
                break
        if matched:
            doc["status"] = "have"
        elif doc["_default_status"]:
            doc["status"] = doc["_default_status"]
        else:
            doc["status"] = "missing"

    real = [doc for doc in docs if not doc["advisory"]]
    advisories = [doc for doc in docs if doc["advisory"]]
    not_have = [doc for doc in real if doc["status"] != "have"]
    blocking_missing = [
        doc for doc in real if doc["blocking"] and doc["status"] != "have"
    ]

    ip_items, trademark_status = ip_screening(
        rules, trademark_value, trademark_provided, patent_done
    )
    ip_blocked = sum(1 for item in ip_items if item["blocked"])

    if blocking_missing or ip_blocked > 0:
        status = "BLOCKED"
    elif not_have:
        status = "CONDITIONAL"
    else:
        status = "PASS"

    risk_notes = []
    groups = [rules["categories"][compliance_key]]
    groups += [rules["attributes"][attr] for attr in attributes]
    groups += [rules["marketplaces"][marketplace] for marketplace in marketplaces]
    for group in groups:
        for note in group.get("risk_notes", []) or []:
            if note not in risk_notes:
                risk_notes.append(note)
    for note in rules.get("global_risk_notes", []) or []:
        if note not in risk_notes:
            risk_notes.append(note)
    for note in rules["ip_screening"].get("notes", []) or []:
        if note not in risk_notes:
            risk_notes.append(note)

    generated_for = {
        "category": compliance_key,
        "category_label": rules["categories"][compliance_key].get("label_cn"),
        "marketplace": "+".join(marketplaces),
        "marketplace_labels": [
            rules["marketplaces"][marketplace].get("label", marketplace)
            for marketplace in marketplaces
        ],
        "attributes": attributes,
        "attribute_labels": [
            rules["attributes"][attr].get("label_cn") for attr in attributes
        ],
        "have_reports": effective_have,
        "trademark_status": trademark_display,
        "patent_search_done": patent_display,
        "category_key": category_key,
        "category_source": category_source,
    }

    public_docs = []
    for doc in docs:
        public_docs.append(
            {
                "id": doc["id"],
                "name": doc["name"],
                "authority": doc["authority"],
                "trigger": doc["trigger"],
                "blocking": doc["blocking"],
                "advisory": doc["advisory"],
                "status": doc["status"],
                "sources": doc["sources"],
                "citations": doc["citations"],
                "as_of": doc["as_of"],
                "confidence": doc["confidence"],
            }
        )

    payload = {
        "tool": "compliance_gate",
        "version": rules["_meta"].get("version"),
        "rules_updated": rules["_meta"].get("updated"),
        "generated_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "generated_for": generated_for,
        "status": status,
        "counts": {
            "required": len(real),
            "have": len(real) - len(not_have),
            "missing": sum(1 for doc in not_have if doc["status"] == "missing"),
            "unknown": sum(1 for doc in not_have if doc["status"] == "unknown"),
            "blocking_missing": len(blocking_missing),
            "ip_blocked": ip_blocked,
            "advisory": len(advisories),
        },
        "required_docs": public_docs,
        "missing": [
            {
                "id": doc["id"],
                "name": doc["name"],
                "authority": doc["authority"],
                "blocking": doc["blocking"],
                "status": doc["status"],
            }
            for doc in not_have
        ],
        "advisory_items": [
            {"id": doc["id"], "name": doc["name"], "status": doc["status"]}
            for doc in advisories
        ],
        "risk_notes": risk_notes,
        "ip_screening": ip_items,
        "input_warnings": input_warnings,
        "disclaimer": rules["_meta"].get("disclaimer"),
    }
    return payload, rules


CONDITIONAL_TEXT = "CONDITIONAL —— 放行补齐模式：先办缺失文件，齐全后再上架"
PASS_TEXT = "PASS —— 现有文件覆盖本次筛查的全部义务，可进入平台类目审核"
BLOCKED_TEXT = "BLOCKED —— 存在阻断级缺失，未解决前不得上架"


def doc_tag(doc):
    if doc.get("advisory"):
        return "平台"
    if doc.get("blocking"):
        return "阻断"
    return "补办"


def render_human(payload, rules):
    generated = payload["generated_for"]
    counts = payload["counts"]
    docs = payload["required_docs"]
    conclusion = {
        "PASS": PASS_TEXT,
        "CONDITIONAL": CONDITIONAL_TEXT,
        "BLOCKED": BLOCKED_TEXT,
    }[payload["status"]]
    exit_code = {"PASS": 0, "CONDITIONAL": 1, "BLOCKED": 2}[payload["status"]]

    lines = [
        "=== 美国市场准入合规初筛 ===",
        "类目：{}（{}）｜市场：{}｜属性：{}".format(
            generated["category"],
            generated["category_label"],
            " + ".join(generated["marketplace_labels"]),
            "、".join(generated["attribute_labels"]) or "无",
        ),
        "已有报告：{}".format("、".join(generated["have_reports"]) or "无"),
        "",
        "结论：{}".format(conclusion),
        "统计：必需文件 {}｜已具备 {}｜缺失 {}｜待确认 {}｜阻断级缺失 {}｜平台审核提示 {}".format(
            counts["required"], counts["have"], counts["missing"],
            counts["unknown"], counts["blocking_missing"], counts["advisory"],
        ),
    ]
    if counts["ip_blocked"]:
        lines.append(
            "阻断来源：IP 初筛识别到 {} 项冲突（详见下方 IP 初筛）".format(
                counts["ip_blocked"]
            )
        )
    lines += ["", "必需文件清单："]
    for doc in docs:
        lines.append(
            "  [{}][{}] {}".format(
                STATUS_CN.get(doc["status"], doc["status"]), doc_tag(doc), doc["name"]
            )
        )
        lines.append(
            "        主管：{}｜触发：{}".format(
                doc["authority"], doc["trigger"] or "-"
            )
        )
    if payload["missing"]:
        lines += ["", "缺失 / 待确认（按优先级）："]
        for number, doc in enumerate(payload["missing"], start=1):
            level = "阻断级" if doc.get("blocking") else "可补办"
            lines.append(
                "  {}. {}（{}，当前 {}）".format(
                    number, doc["name"], level,
                    STATUS_CN.get(doc["status"], doc["status"]),
                )
            )
    lines += ["", "IP 初筛（不是法律意见，冲突判定需律师复核）："]
    for item in payload["ip_screening"]:
        lines.append(
            "  [{}] {} —— {}".format(
                STATUS_CN.get(item["status"], item["status"]), item["item"], item["note"]
            )
        )
        lines.append("        动作：{}".format(item["action"]))
    if payload["input_warnings"]:
        lines += ["", "输入提示："]
        for warning in payload["input_warnings"]:
            lines.append("  - {}".format(warning))
    lines += ["", "风险提示："]
    for note in payload["risk_notes"]:
        lines.append("  - {}".format(note))
    lines += [
        "",
        "口径：{}".format(payload["disclaimer"]),
        "退出码：0=PASS 1=CONDITIONAL 2=BLOCKED 3=输入错误（当前 {}）".format(exit_code),
    ]
    print("\n".join(lines))


def print_categories(category_map, rules):
    lines = ["可用 category_key（--category）：", ""]
    lines.append("  {:<24} {:<22} {}".format("category_key", "合规类目", "说明"))
    for key in sorted(category_map.get("categories", {})):
        if key == "default":
            continue
        entry = category_map["categories"][key]
        lines.append(
            "  {:<24} {:<22} {}".format(
                key, entry.get("compliance_key") or "-", entry.get("label", "")
            )
        )
    aliases = category_map.get("aliases", {})
    lines += [
        "",
        "旧键别名：{}".format(
            "、".join("{}→{}".format(alias, target) for alias, target in aliases.items())
        ),
        "也可直接传 Amazon 类目路径（如 Home & Kitchen > Kitchen & Dining > Small Appliances > Blenders）。",
    ]
    print("\n".join(lines))


def print_attributes(rules):
    lines = ["可用属性（--attr，逗号分隔）："]
    for key in rules["attributes"]:
        entry = rules["attributes"][key]
        blocking = any(
            rules["doc_library"][doc_id].get("blocking", False)
            for doc_id in entry.get("docs", [])
        )
        suffix = "（含阻断级义务）" if blocking else ""
        lines.append("  {:<21}{}{}".format(key, entry.get("label_cn", ""), suffix))
    print("\n".join(lines))


def main(argv):
    set_json_mode("--json" in argv)
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
        if args.list_categories:
            print_categories(load_map(), load_rules())
            return 0
        if args.list_attributes:
            print_attributes(load_rules())
            return 0
        payload, rules = evaluate(args)
        if args.json:
            emit_json(payload)
        else:
            render_human(payload, rules)
        return {"PASS": 0, "CONDITIONAL": 1, "BLOCKED": 2}[payload["status"]]
    except CliFailure as exc:
        emit_failure(exc)
        return exc.code


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
