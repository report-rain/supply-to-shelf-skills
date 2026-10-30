#!/usr/bin/env python3
"""Amazon US / TikTok Shop US Listing 文案确定性自检（clean-room 重写）。

行为规格见 docs/spec/04_listing.md。纯标准库、无配置文件，阈值与词表内嵌。
错误信息统一写 stdout；非 UTF-8 输入按 #6 明确报错（exit 2）。
"""

import json
import os
import re
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from shared.errors import emit_json, set_json_mode

RULES_BASIS = "编写时公开口径，发布前按卖家中心复核"
SPLIT_EFFECTIVE = "2026-07-27"

HARD_PROMO = [
    "best seller", "best sellers", "best-selling", "best selling", "#1", "no.1",
    "number 1", "number one", "sale", "on sale", "free shipping", "free delivery",
    "deal", "hot deal", "hot", "discount", "clearance", "limited time", "buy now",
    "lowest price", "cheapest", "coupon", "prime day", "black friday",
]
SOFT_PROMO = [
    "best", "perfect", "premium", "revolutionary", "amazing", "ultimate",
    "superior", "top rated", "professional", "world's best", "unbeatable",
    "exclusive", "guaranteed", "flawless", "instantly",
]
TIKTOK_EVASION = [
    "link in bio", "bio link", "check my bio", "comment to get", "comment for price",
    "dm me", "whatsapp", "free giveaway", "tap the link", "shop link",
]
ALL_CAPS_ALLOW = {
    "USB", "LED", "BPA", "FCC", "UL", "IPX", "DC", "AC", "RGB", "XL", "XXL",
    "GPS", "LCD", "USB-C",
}
STOPWORDS = {
    "a", "an", "the", "and", "or", "for", "with", "to", "of", "in", "on", "by",
    "your", "you", "is", "it", "at", "from", "as", "this", "that",
}
CJK_RE = re.compile("[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")
EMOJI_RE = re.compile(
    "[\U0001F300-\U0001FAFF\u2600-\u27BF\u2B00-\u2BFF\uFE0F]"
)
PRICE_RE = re.compile(
    r"\$|\busd\b|\bdollars?\b|\bprice\b|\bsave\s+\d+%|\d+\s*%\s*off|\b\d+\s*off\b",
    re.IGNORECASE,
)
CONTACT_RE = re.compile(
    r"https?://|www\.|[\w.+-]+@[\w-]+\.[\w.]+"
    r"|\b\d{3}[-.\s]?\d{3}[-.\s]?\d{4}\b"
    r"|\b(?:[a-z0-9-]+\.)?(?:com|net|org|io|co|shop|store)\b",
    re.IGNORECASE,
)
IP_CLAIM_RE = re.compile(r"waterproof|water[ \-]?resistant|submersible|ipx\s*\d+", re.IGNORECASE)
NO_RATING = {"", "none", "no", "n/a", "na", "0"}
SPECIAL_CHARS = "~!?$%^*"

TITLE_LIMITS = {
    "amazon_us": {"max": 200, "min": 80, "label": "Amazon US"},
    "tiktok_us": {"max": 255, "min": 40, "label": "TikTok Shop US"},
}


def term_regex(term):
    segments = [part for part in re.split(r"[\s\-]+", term) if part]
    body = r"[\s\-]?".join(re.escape(segment) for segment in segments)
    return re.compile(r"(?<![A-Za-z0-9])" + body + r"(?![A-Za-z0-9])", re.IGNORECASE)


HARD_RE = [(term, term_regex(term)) for term in HARD_PROMO]
SOFT_RE = [(term, term_regex(term)) for term in SOFT_PROMO]
EVASION_RE = [(term, term_regex(term)) for term in TIKTOK_EVASION]


def find_terms(text, pairs, excluded=()):
    found = []
    for term, pattern in pairs:
        if term in excluded:
            continue
        if pattern.search(text) and term not in found:
            found.append(term)
    return found


def emit_error(status, message, missing=None, as_json=False, with_missing=True):
    if as_json:
        payload = {"status": status}
        if with_missing:
            payload["missing"] = list(missing or [])
        payload["message"] = message
        emit_json(payload)
    else:
        print(message)


class Linter:
    def __init__(self, data, platform):
        self.data = data
        self.platform = platform
        self.findings = []

    def add(self, level, code, field, message):
        self.findings.append(
            {"level": level, "code": code, "field": field, "message": message}
        )

    def pass_(self, code, field, message):
        self.add("PASS", code, field, message)

    def warn(self, code, field, message):
        self.add("WARN", code, field, message)

    def fail(self, code, field, message):
        self.add("FAIL", code, field, message)

    # ---- 标题 ----
    def check_title(self):
        platform = self.platform
        limits = TITLE_LIMITS[platform]
        title = str(self.data.get("title") or "")
        item_name = str(self.data.get("item_name") or "")
        highlights = str(self.data.get("item_highlights") or "")
        split = platform == "amazon_us" and bool(item_name)

        if platform == "amazon_us":
            if item_name:
                if len(item_name) > 75:
                    self.fail("ITEM_NAME_TOO_LONG", "item_name",
                              "Item Name {} 字符，超过上限 75".format(len(item_name)))
                else:
                    self.pass_("ITEM_NAME_LENGTH", "item_name",
                               "Item Name {} 字符，在上限 75 内".format(len(item_name)))
            if highlights:
                if len(highlights) > 125:
                    self.fail("ITEM_HIGHLIGHTS_TOO_LONG", "item_highlights",
                              "Item Highlights {} 字符，超过上限 125".format(len(highlights)))
                else:
                    self.pass_("ITEM_HIGHLIGHTS_LENGTH", "item_highlights",
                               "Item Highlights {} 字符，在上限 125 内".format(len(highlights)))
            elif item_name:
                self.warn("ITEM_HIGHLIGHTS_MISSING", "item_highlights",
                          "未提供 Item Highlights；2026-07-27 起标题由 Item Name + Item Highlights 组成")

        if split:
            effective = item_name + (" " + highlights if highlights else "")
            prefix = "合计"
        else:
            effective = title
            prefix = ""
        length = len(effective)
        if length > limits["max"]:
            self.fail("TITLE_TOO_LONG", "title",
                      "标题{} {} 字符，超过上限 {}".format(prefix, length, limits["max"]))
        elif length < limits["min"]:
            self.warn("TITLE_TOO_SHORT", "title",
                      "标题{}仅 {} 字符，低于建议下限 {}，可能漏掉核心属性词".format(
                          prefix, length, limits["min"]))
        else:
            self.pass_("TITLE_LENGTH", "title",
                       "标题{} {} 字符，在 {}-{} 区间内".format(
                           prefix, length, limits["min"], limits["max"]))

        if platform == "amazon_us" and not split and length > 75:
            self.warn("TITLE_SPLIT_REQUIRED", "title",
                      "标题 {} 字符；2026-07-27 起需拆分为 Item Name ≤75 + "
                      "Item Highlights ≤125（合计 ≤200）".format(length))

        if platform == "amazon_us":
            self.check_brand(title, "title")

        self.check_wording(title, "title", "TITLE_PROMO", "TITLE_SUBJECTIVE", "TITLE_WORDING")
        self.check_special(title)
        self.check_caps(title)
        self.check_repeat(title)

        if platform == "tiktok_us":
            hits = find_terms(title, EVASION_RE)
            if hits:
                self.fail("TIKTOK_EVASION", "title",
                          "标题出现绕规则引导: {}；TikTok 禁止站外/私信导流".format(", ".join(hits)))

        self.check_cjk_emoji(title, "title")

    def check_brand(self, title, field):
        brand = self.data.get("brand")
        if brand is None or str(brand).strip() == "":
            self.warn("BRAND_MISSING_INPUT", "brand", "未提供品牌；无法校验标题品牌位置")
            return
        brand = str(brand)
        index = title.lower().find(brand.lower())
        if index < 0:
            self.warn("BRAND_NOT_IN_TITLE", field,
                      "标题未出现品牌「{}」；Amazon 建议 Brand + 核心词开头".format(brand))
            return
        if index >= 80:
            self.warn("BRAND_TOO_LATE", field,
                      "品牌出现在第 {} 字符，超出前 80 字符".format(index + 1))
            return
        self.pass_("BRAND_PREFIX", field,
                   "品牌「{}」出现在第 {} 字符（前 80 字符内）".format(brand, index + 1))

    def check_wording(self, text, field, hard_code, soft_code, pass_code, bullet_no=None):
        hard = find_terms(text, HARD_RE)
        soft = find_terms(text, SOFT_RE, excluded=hard)
        if bullet_no is None:
            if hard:
                self.fail(hard_code, field,
                          "标题出现促销词: {}；促销信息由平台标签承载".format(", ".join(hard)))
            if soft:
                self.warn(soft_code, field,
                          "标题出现主观/绝对化词: {}；建议换成可举证参数".format(", ".join(soft)))
            if not hard and not soft:
                self.pass_(pass_code, field, "未发现促销词或主观绝对化词")
        else:
            if hard:
                self.fail(hard_code, field,
                          "第 {} 条出现促销词: {}".format(bullet_no, ", ".join(hard)))
            if soft:
                self.warn(soft_code, field,
                          "第 {} 条出现主观词: {}".format(bullet_no, ", ".join(soft)))
            if not hard and not soft:
                self.pass_(pass_code, field, "第 {} 条无促销/主观词".format(bullet_no))

    def check_special(self, title):
        hits = [char for char in SPECIAL_CHARS if char in title]
        if hits:
            self.fail("TITLE_SPECIAL_CHARS", "title",
                      "标题含特殊字符: {}".format(" ".join(hits)))
        else:
            self.pass_("TITLE_SPECIAL_CHARS", "title", "无特殊字符（~!?$%^*）")

    def check_caps(self, title):
        tokens = re.findall(r"[A-Z]{2,}", title)
        brand = self.data.get("brand")
        allowed = set(ALL_CAPS_ALLOW)
        if brand:
            allowed.update(part for part in re.findall(r"[A-Z0-9]+", str(brand).upper()))
        kept = [token for token in tokens if token not in allowed]
        if not kept:
            self.pass_("TITLE_CASE", "title", "未发现异常全大写词")
        elif len(kept) == 1:
            self.warn("TITLE_ALL_CAPS", "title", "标题含全大写词: {}".format(", ".join(kept)))
        else:
            self.fail("TITLE_ALL_CAPS", "title",
                      "标题含 {} 个全大写词: {}；除品牌/标准缩写外应正常大小写".format(
                          len(kept), ", ".join(kept)))

    def check_repeat(self, title):
        words = re.findall(r"[a-z0-9']+", title.lower())
        counts = {}
        for word in words:
            if word in STOPWORDS:
                continue
            counts[word] = counts.get(word, 0) + 1
        repeats = sorted((word for word, n in counts.items() if n >= 3),
                         key=lambda word: (-counts[word], word))
        if repeats:
            self.warn("TITLE_REPEAT", "title",
                      "标题重复词 ≥3 次: {}".format(
                          ", ".join("{}×{}".format(word, counts[word]) for word in repeats)))
        else:
            self.pass_("TITLE_REPEAT", "title", "无单词重复 ≥3 次")

    def check_cjk_emoji(self, text, field):
        chars = list(dict.fromkeys(CJK_RE.findall(text)))
        if chars:
            self.fail("CJK_CHARS", field,
                      "出现中文字符 {}；买家可见文案必须为美式英语".format("".join(chars)))
        emojis = list(dict.fromkeys(EMOJI_RE.findall(text)))
        if emojis:
            self.fail("EMOJI", field, "出现 emoji {}；平台文案不允许".format(emojis[0]))

    # ---- 五点 ----
    def check_bullets(self):
        bullets = self.data.get("bullets")
        if not isinstance(bullets, list):
            return
        if len(bullets) == 5:
            self.pass_("BULLET_COUNT", "bullets", "五点数量为 5 条")
        else:
            self.fail("BULLET_COUNT", "bullets",
                      "五点数量为 {}，必须为 5 条".format(len(bullets)))
        for index, raw in enumerate(bullets, start=1):
            text = str(raw)
            field = "bullets[{}]".format(index)
            if len(text) > 220:
                self.warn("BULLET_TOO_LONG", field,
                          "第 {} 条 {} 字符，超过建议上限 220".format(index, len(text)))
            else:
                self.pass_("BULLET_LENGTH", field,
                           "第 {} 条 {} 字符，≤220".format(index, len(text)))
            self.check_wording(text, field, "BULLET_PROMO", "BULLET_SUBJECTIVE",
                               "BULLET_WORDING", bullet_no=index)
            has_price = bool(PRICE_RE.search(text))
            has_contact = bool(CONTACT_RE.search(text))
            if has_price:
                self.fail("BULLET_PRICE", field,
                          "第 {} 条出现价格/折扣表述；价格由后台字段承载".format(index))
            if has_contact:
                self.fail("BULLET_CONTACT", field,
                          "第 {} 条出现网址/邮箱/电话；平台禁止站外联系方式".format(index))
            if not has_price and not has_contact:
                self.pass_("BULLET_CLEAN", field, "第 {} 条无价格与联系方式".format(index))
            self.check_cjk_emoji(text, field)

    # ---- 后台搜索词 ----
    def check_backend(self):
        value = self.data.get("backend_search_terms")
        if not isinstance(value, str):
            return
        size = len(value.encode("utf-8"))
        if size > 250:
            self.fail("BACKEND_TOO_LONG", "backend_search_terms",
                      "后台搜索词 {} 字节（UTF-8），超过 250 字节".format(size))
        elif size > 230:
            self.warn("BACKEND_NEAR_LIMIT", "backend_search_terms",
                      "后台搜索词 {} 字节，接近 250 字节上限".format(size))
        else:
            self.pass_("BACKEND_LENGTH", "backend_search_terms",
                       "后台搜索词 {} 字节，≤250".format(size))

        words = re.findall(r"[a-z0-9']+", value.lower())
        brand = self.data.get("brand")
        brand_words = re.findall(r"[a-z0-9]+", str(brand).lower()) if brand else []
        repeated_brand = []
        for word in brand_words:
            if word in words and word not in repeated_brand:
                repeated_brand.append(word)
        if repeated_brand:
            self.fail("BACKEND_BRAND_REPEAT", "backend_search_terms",
                      "后台搜索词重复品牌词: {}（品牌已在标题，无需重复）".format(
                          ", ".join(repeated_brand)))
        else:
            self.pass_("BACKEND_NO_BRAND", "backend_search_terms", "后台搜索词未重复品牌词")

        duplicates = []
        for word in words:
            if words.count(word) >= 2 and word not in duplicates:
                duplicates.append(word)
        if duplicates:
            self.warn("BACKEND_DUPLICATE", "backend_search_terms",
                      "后台搜索词重复单词: {}".format(", ".join(duplicates)))
        else:
            self.pass_("BACKEND_UNIQUE", "backend_search_terms", "后台搜索词无重复单词")

    # ---- 描述 / A+ ----
    def copy_text(self):
        short = self.data.get("short_description")
        desc = self.data.get("description")
        if self.platform == "tiktok_us":
            if isinstance(short, str) and short:
                return short, "short_description"
            if isinstance(desc, str):
                return desc, "short_description"
            return "", "short_description"
        return str(desc or ""), "description"

    def check_description(self):
        text, field = self.copy_text()
        hard = find_terms(text, HARD_RE, excluded=("hot",))
        if hard:
            self.warn("DESC_PROMO", "description",
                      "描述出现促销词: {}；建议移到促销工具/优惠券".format(", ".join(hard)))
        else:
            self.pass_("DESC_PROMO", "description", "描述无促销词")
        self.check_cjk_emoji(text, field)

    def check_aplus(self):
        modules = self.data.get("aplus_modules")
        if not isinstance(modules, list):
            return
        for index, raw in enumerate(modules, start=1):
            text = str(raw)
            field = "aplus_modules[{}]".format(index)
            hard = find_terms(text, HARD_RE)
            if hard:
                self.warn("APLUS_PROMO", field,
                          "A+ 模块 {} 出现促销词: {}".format(index, ", ".join(hard)))
            self.check_cjk_emoji(text, field)
        if modules:
            self.pass_("APLUS_PRESENT", "aplus_modules",
                       "提供 {} 个 A+ 模块文案".format(len(modules)))
        self.check_aplus_order(modules)

    def check_aplus_order(self, modules):
        stages = [
            ("主视觉", ["hero", "main visual", "主视觉", "cover"]),
            ("核心收益", ["benefit", "why you", "best for", "核心", "卖点"]),
            ("使用步骤", ["how to use", "step", "使用步骤", "3 steps"]),
            ("细节", ["detail", "spec", "材质", "参数", "细节"]),
            ("对比", ["compare", "compar", "对比", " vs "]),
            ("包装清单", ["in the box", "included", "what's in", "package", "包装清单", "包含"]),
            ("信任", ["warranty", "guarantee", "support", "质保", "保障", "trust"]),
        ]
        detected = []
        for index, raw in enumerate(modules, start=1):
            text = str(raw).lower()
            for order, (name, keywords) in enumerate(stages):
                if any(keyword in text for keyword in keywords):
                    detected.append((order, index, name))
                    break
        present = {name for _, _, name in detected}
        if "主视觉" not in present or "包装清单" not in present:
            self.fail("APLUS_ORDER", "aplus_modules",
                      "A+ 模块缺少主视觉或包装清单阶段，无法校验顺序")
            return
        orders = [order for order, _, _ in detected]
        if orders != sorted(orders):
            sequence = "→".join(name for _, _, name in detected)
            self.fail("APLUS_ORDER", "aplus_modules",
                      "A+ 模块顺序异常：{}；建议按 主视觉→核心收益→使用步骤→细节→对比→"
                      "包装清单→信任 排列".format(sequence))

    # ---- TikTok 短描述 ----
    def check_tiktok_copy(self):
        text, field = self.copy_text()
        length = len(text)
        if length > 500:
            self.fail("TIKTOK_DESC_TOO_LONG", field,
                      "短描述 {} 字符，超过 500".format(length))
        else:
            self.pass_("TIKTOK_DESC_LENGTH", field, "短描述 {} 字符，≤500".format(length))
        hits = find_terms(text, EVASION_RE)
        if hits:
            self.fail("TIKTOK_EVASION", field,
                      "短描述出现绕规则引导: {}".format(", ".join(hits)))
        if "$" in text:
            self.fail("TIKTOK_PRICE_IN_COPY", field,
                      "短描述含价格符号 $；价格应在商品卡字段填写")

    # ---- IP 一致性 ----
    def parse_attrs(self):
        attrs = self.data.get("product_attributes")
        if attrs is None:
            return None
        pairs = {}
        if isinstance(attrs, list):
            for item in attrs:
                if isinstance(item, str) and ":" in item:
                    key, value = item.split(":", 1)
                    pairs[key.strip().lower()] = value.strip().lower()
        elif isinstance(attrs, dict):
            for key, value in attrs.items():
                pairs[str(key).strip().lower()] = str(value).strip().lower()
        return pairs

    def check_ip(self):
        pairs = self.parse_attrs()
        if pairs is None:
            self.warn("ATTRS_MISSING", "product_attributes",
                      "未提供 product_attributes，ip_rating 一致性未校验")
            return
        if "ip_rating" not in pairs:
            self.warn("IP_RATING_UNKNOWN", "product_attributes",
                      "product_attributes 未声明 ip_rating，防水类表述未校验")
            return
        value = pairs["ip_rating"]
        if value not in NO_RATING:
            self.pass_("IP_RATING_DECLARED", "product_attributes",
                       "已声明 IP 等级；仍需核对测试报告与实际标识一致")
            return
        fields = [("title", str(self.data.get("title") or ""))]
        bullets = self.data.get("bullets")
        if isinstance(bullets, list):
            for index, raw in enumerate(bullets, start=1):
                fields.append(("bullets[{}]".format(index), str(raw)))
        text, copy_field = self.copy_text()
        fields.append((copy_field, text))
        modules = self.data.get("aplus_modules")
        if isinstance(modules, list):
            for index, raw in enumerate(modules, start=1):
                fields.append(("aplus_modules[{}]".format(index), str(raw)))

        conflicts = []
        for field, text in fields:
            match = IP_CLAIM_RE.search(text)
            if match:
                conflicts.append((field, match.group(0)))
        if conflicts:
            for field, term in conflicts:
                self.fail("CLAIM_IP_CONFLICT", field,
                          "{} 出现「{}」，但 product_attributes 声明 ip_rating: {}".format(
                              field, term, value))
        else:
            self.pass_("CLAIM_IP_CONSISTENT", "product_attributes",
                       "ip_rating: {} 且全文未出现 waterproof / water resistant 类表述".format(value))

    def run(self):
        self.check_title()
        if self.platform == "amazon_us":
            self.check_bullets()
            self.check_backend()
        self.check_description()
        self.check_aplus()
        if self.platform == "tiktok_us":
            self.check_tiktok_copy()
        self.check_ip()
        counts = {"PASS": 0, "WARN": 0, "FAIL": 0}
        for finding in self.findings:
            counts[finding["level"]] += 1
        if counts["FAIL"]:
            verdict = "FAIL"
        elif counts["WARN"]:
            verdict = "WARN"
        else:
            verdict = "PASS"
        return verdict, counts


def required_missing(data, platform):
    missing = []
    if not isinstance(data, dict):
        return ["object"]
    if platform == "amazon_us":
        for key in ("brand", "title", "bullets", "description",
                    "backend_search_terms", "aplus_modules"):
            value = data.get(key)
            if value is None or value == "" or value == []:
                missing.append(key)
    else:
        title = data.get("title")
        if title is None or title == "":
            missing.append("title")
        desc = data.get("description")
        short = data.get("short_description")
        if not isinstance(desc, str) and not isinstance(short, str):
            missing.append("description/short_description")
    bullets = data.get("bullets")
    if isinstance(bullets, str):
        missing.append("bullets(须为数组)")
    return missing


def render_text(platform, path, findings, verdict, counts):
    lines = [
        "{} Listing 自检".format(TITLE_LIMITS[platform]["label"]),
        "文件: {}".format(path),
    ]
    for finding in findings:
        lines.append("[{}] {} ({}): {}".format(
            finding["level"], finding["code"], finding["field"], finding["message"]))
    lines.append("")
    lines.append("总判定: {} (FAIL {} / WARN {} / PASS {})".format(
        verdict, counts["FAIL"], counts["WARN"], counts["PASS"]))
    lines.append("口径: {}。".format(RULES_BASIS))
    print("\n".join(lines))


def build_parser():
    import argparse

    parser = argparse.ArgumentParser(prog="listing_lint.py",
                                     description="Amazon/TikTok Listing 文案自检")
    parser.add_argument("--file", required=True)
    parser.add_argument("--platform", required=True, choices=["amazon_us", "tiktok_us"])
    parser.add_argument("--json", action="store_true")
    return parser


def main(argv):
    as_json = "--json" in argv
    set_json_mode(as_json)
    parser = build_parser()
    args = parser.parse_args(argv)

    path = args.file
    if not os.path.isfile(path):
        emit_error("INPUT_MISSING", "[INPUT_MISSING] 找不到文件: {}".format(path),
                   ["file"], as_json)
        return 2
    try:
        with open(path, "r", encoding="utf-8-sig") as handle:
            raw = handle.read()
    except UnicodeDecodeError:
        emit_error("INPUT_ERROR", "[INPUT_ERROR] 文件不是 UTF-8 文本: {}".format(path),
                   [], as_json, with_missing=False)
        return 2
    try:
        data = json.loads(raw)
    except ValueError as exc:
        emit_error("INPUT_ERROR", "[INPUT_ERROR] JSON 解析失败: {}".format(exc),
                   [], as_json, with_missing=False)
        return 2

    missing = required_missing(data, args.platform)
    if missing:
        if missing == ["object"]:
            emit_error("INPUT_MISSING", "[INPUT_MISSING] 顶层必须是 JSON 对象",
                       missing, as_json)
        else:
            emit_error("INPUT_MISSING", "[INPUT_MISSING] 缺少字段: {}".format(
                ", ".join(missing)), missing, as_json)
        return 2

    linter = Linter(data, args.platform)
    verdict, counts = linter.run()
    findings = linter.findings

    if as_json:
        meta = {
            "rules_basis": RULES_BASIS,
            "title_limit": TITLE_LIMITS[args.platform]["max"],
            "title_split": (
                {"effective": SPLIT_EFFECTIVE, "item_name_max": 75,
                 "item_highlights_max": 125}
                if args.platform == "amazon_us" else None
            ),
        }
        emit_json(
            {
                "platform": args.platform,
                "file": path,
                "verdict": verdict,
                "counts": counts,
                "findings": findings,
                "meta": meta,
            }
        )
    else:
        render_text(args.platform, path, findings, verdict, counts)
    return 1 if counts["FAIL"] else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
