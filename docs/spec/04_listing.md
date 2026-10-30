# 04 Listing 文本工具 —— 规格冻结（clean-room 重写基线）

> 对象：`Agents/04_Listing_Agent/scripts/claim_scan.py`、`listing_lint.py`
> 两份脚本均为纯标准库、零配置文件，规则常量内嵌在脚本中。
> 所有退出码/计数均为实跑（Python 3.12 / Windows PowerShell 5）。

## 1. 范围与脚本

| 脚本 | 职责 | 依赖 | 退出码 |
|---|---|---|---|
| `claim_scan.py` | FTC/FDA 高风险声明关键词扫描：命中词、风险级别、原因、改写建议；不做语义判断 | 无配置；内置 22 条规则 | 0=无 HIGH；1=有 HIGH；2=输入缺失/不可读 |
| `listing_lint.py` | Amazon US / TikTok Shop US Listing 文案确定性自检：标题、五点、后台词、描述、A+、IP 一致性 | 无配置；内置平台阈值 | 0=无 FAIL（可含 WARN）；1=有 FAIL；2=输入缺失/不可读 |

两者不共享代码、不读取上游 JSON；`listing_lint` 只吃一个 Listing JSON，`claim_scan` 吃纯文本。上游是 01/02/03 产出的文案或 Listing 草稿。

## 2. CLI 契约

### 2.1 `claim_scan.py`

无子命令、无位置参数。

| 参数名 | 类型 | 必填 | 默认值 | 取值范围/枚举 | 说明 |
|---|---|---|---|---|---|
| `--file` | string | 二选一 | 无 | 任意可读文本文件 | 整个文件内容作为待扫描文本；`utf-8-sig` 读取 |
| `--text` | string | 二选一 | 无 | 任意字符串 | 直接传文案；与 `--file` 互斥 |
| `--ip-rating` | string | 否 | `"none"` | 自由文本（如 `ipx4`、`ip67`、`none`） | 仅影响 `waterproof` 的风险降级 |
| `--json` | flag | 否 | false | — | 输出机器可读 JSON |

冲突与位置参数：

1. 同时给 `--file` 与 `--text` → 固定报错 `--file 与 --text 只能二选一`，exit 2，不读文件。
2. 两者都不给 → 报错 `缺少 --file 或 --text`，exit 2。
3. 只有 `--text`（含空串 `""`）时按文本模式处理；`--text ""` 合法，输出 PASS。
4. 无位置参数；未知选项/缺值由 argparse 处理，exit 2（非 JSON 契约）。

### 2.2 `listing_lint.py`

无子命令、无位置参数。

| 参数名 | 类型 | 必填 | 默认值 | 取值范围/枚举 | 说明 |
|---|---|---|---|---|---|
| `--file` | string | 是 | 无 | 任意 Listing JSON 文件 | `utf-8-sig` 读取；顶层必须为对象 |
| `--platform` | enum | 是 | 无 | `amazon_us` / `tiktok_us`（排序后） | 决定阈值与检查集合；输入 JSON 内的 `platform` 字段被忽略 |
| `--json` | flag | 否 | false | — | 输出机器可读 JSON |

- 缺少 `--file` 或 `--platform` 由 argparse 直接报 usage 到 stderr、exit 2，**不输出**统一 JSON 错误体。
- `--platform` 大小写敏感；非法值 exit 2。

## 3. 输入契约

### 3.1 `claim_scan` 文本

- 文件：`utf-8-sig`（兼容 BOM）；非 UTF-8 中文内容触发 `UnicodeDecodeError` → exit 2、`status=INPUT_ERROR`。
- 文本原样扫描，包含换行；`char_count = len(text)`（Python 字符数，含空白/换行）。
- 不做 HTML/JSON 解析，不做语言识别；英文大小写不敏感。

### 3.2 `claim_scan` 规则表（完整数据，必须逐条保留）

匹配规则：词条按空格/连字符切分，段间允许 0 或 1 个空格/连字符（因此 `fda approved` 可命中 `fda-approved`）；大小写不敏感；前后不得紧邻字母或数字。`#1`、`100%` 按字面匹配，`100 %` 不命中。

| term | risk | reason | suggestion |
|---|---|---|---|
| `fda approved` | HIGH | FDA 不“批准”化妆品或食品接触类产品；该表述属不可举证的官方背书。 | 删除。如持有食品接触材料测试报告，可改为 “meets FDA food-contact requirements for the tested materials” 并注明报告编号。 |
| `cures` | HIGH | 疾病治疗声明属药品/医疗器械范畴，普通商品无资质。 | 删除疾病表述，改为客观功能与使用场景，例如 “removes everyday grime from the cup surface”。 |
| `treats` | HIGH | “治疗”属药品声明；无 FDA 药品批准不得使用。 | 删除；只描述产品怎么用、能清洁/混合什么，不描述症状改善。 |
| `prevents` | HIGH | 预防疾病/伤害的声明需要临床或安全证据，普通商品无法举证。 | 删除；如为使用建议，改为 “helps keep … clean when used as directed”（仍需真实依据）。 |
| `clinically proven` | HIGH | “临床验证”要求可提交的人体研究，且结论需与声明一致。 | 仅在有研究文件时写 “tested in a 12-week consumer study with 60 participants (report available)”；否则删除。 |
| `doctor recommended` | HIGH | 需要可核查的推荐调查或专家背书，口头背书不算证据。 | 删除；如确有调查，写清样本与时间，例如 “recommended by 8 of 10 dentists in a 2026 survey (n=120)”。 |
| `medical grade` | HIGH | “医疗级”无统一定义，属不可举证等级声明。 | 改为具体材质/标准，例如 “304 stainless steel housing” 或 “meets NSF/ANSI 51”。 |
| `100%` | HIGH | 绝对化比例无法举证；FTC 要求声明有合理依据。 | 写明测试条件与实测值，例如 “up to 92% of grounds blended in a 30-second lab test (2026-03)”；不要写 100%。 |
| `best` | HIGH | 最高级比较声明需要可验证的比较基准。 | 改为可核查事实，例如 “rated 4.7/5 by 1,200 verified buyers”（数据必须真实且可提供）。 |
| `#1` | HIGH | 排名声明需要平台或第三方榜单依据，且需注明榜单与时间。 | 删除；如确有依据，写清 “#1 in Amazon's Blenders category, 2026-08 (source: …)”（需可复核）。 |
| `non-toxic` | HIGH | “无毒”是安全声明，需要成分与检测报告支撑。 | 删除，改为具体检测结论，例如 “passed lead and cadmium migration testing (report no. …)”。 |
| `eco-friendly` | MEDIUM | 泛化的环保声明无法核实，FTC 要求具体、可量化的环境收益。 | 改为具体事实，例如 “made with 30% post-consumer recycled plastic”（需供应链证明）。 |
| `biodegradable` | HIGH | 可降解声明需要标准与认证，且需说明处置条件。 | 仅在有认证时写 “certified compostable to ASTM D6400”；否则删除。 |
| `antibacterial` | HIGH | 抗菌属 EPA 监管的农药类声明，无 EPA 注册不得用于美区销售文案。 | 删除；改为物理清洁表述，例如 “wipes away everyday grime”。 |
| `waterproof` | HIGH | 防水是性能安全声明；无 IP 等级与测试报告不得使用。 | 无等级时删除；有报告时改为 “IPX4 splash-resistant (tested to IEC 60529)”。 |
| `instantly` | MEDIUM | “瞬间”缺少可测时间，属无法核实的速度声明。 | 改为可测时间，例如 “in about 30 seconds” 并注明测试条件。 |
| `permanent` | HIGH | 永久性效果无法保证，属绝对化承诺。 | 改为可验证寿命，例如 “lasts up to 50 washes”（需测试依据）。 |
| `guaranteed` | HIGH | 结果保证属高风险承诺；只能承诺具体售后政策。 | 改为政策表述，例如 “30-day return under store policy”；不要保证使用结果。 |
| `premium` | LOW | 主观修饰词，无信息量，易被判为夸大。 | 改为具体材质或工艺，例如 “double-wall Tritan cup”。 |
| `professional` | LOW | 主观修饰词，除非有明确职业标准，否则不可举证。 | 改为使用场景或参数，例如 “for 12-cup batches”。 |
| `advanced` | LOW | 主观修饰词，无法定义“先进”的基准。 | 改为具体技术点，例如 “six-blade stainless steel assembly”。 |
| `innovative` | LOW | 主观修饰词，无法举证。 | 改为具体结构差异，例如 “removable base with a snap-on quiet shield”。 |

统计：HIGH 16 条、MEDIUM 2 条、LOW 4 条，合计 22。

### 3.3 `listing_lint` Listing JSON

| 字段 | 类型 | 必填性 | 说明 / 别名 |
|---|---|---|---|
| `title` | string | amazon/tiktok 必填（见下） | 完整标题。amazon 若提供非空 `item_name`，长度校验改用拆分字段，但 `title` 仍需存在 |
| `item_name` | string | 否 | Amazon 拆分标题前半（≤75） |
| `item_highlights` | string | 否 | Amazon 拆分标题后半（≤125）；缺失仅 WARN |
| `brand` | string | amazon 必填 | 用于品牌前置位次与全大写豁免；tiktok 可选 |
| `bullets` | array<string> | amazon 必填 | 必须恰好 5 条且为数组；tiktok 忽略 |
| `description` | string | amazon 必填 | 描述正文；tiktok 作为 `short_description` 的备选 |
| `short_description` | string | tiktok 二选一 | 优先于 `description`；≤500 字符 |
| `backend_search_terms` | string | amazon 必填 | 后台搜索词，按 UTF-8 字节数限制 250 |
| `aplus_modules` | array<string> | amazon 必填 | 每个元素当作一段 A+ 文案；空数组视为缺失 |
| `product_attributes` | array 或 object | 否 | 支持 `"ip_rating:none"` 数组元素、`{"ip_rating":"none"}` 对象；键值统一小写去空格 |
| `product_id` / `platform` | 任意 | 否 | 不参与计算，`platform` 以 CLI 为准 |

必填校验（缺字段即 INPUT_MISSING，exit 2）：

- Amazon：`brand`、`title`、`bullets`、`description`、`backend_search_terms`、`aplus_modules`；空串/`null`/`[]` 均算缺失；`bullets` 为字符串时追加 `bullets(须为数组)`。
- TikTok：`title`；若 `description`/`short_description` 不是字符串则追加 `description/short_description`。TikTok 的空串描述**不**算缺失（只校验类型）；Amazon 的空串算缺失。

其他：顶层非对象 → `missing=["object"]`；JSON 解析失败 → `status=INPUT_ERROR`（无 `missing`）；文件缺失 → `missing=["file"]`。

## 4. 输出契约

### 4.1 `claim_scan` 成功 JSON

```
{
  verdict: "PASS" | "WARN" | "FAIL",
  source: "text" | <文件路径>,
  ip_rating: <原样>,
  char_count: <int>,
  counts: { "HIGH": n, "MEDIUM": n, "LOW": n },   // 按“词条”计数，非出现次数
  hits: [ { term, risk, count, reason, suggestion } ],
  meta: { rules_basis: "编写时公开口径（FTC substantiation / FDA 声明边界），不构成法律意见，发布前由合规负责人复核" }
}
```

`hits` 排序：risk（HIGH→MEDIUM→LOW）→ count 降序 → term 字典序。`hits[].count` 为该词在全文的匹配次数；`counts` 只加 1/词条。

人类可读输出（stdout）：标题行、`来源: <source>（<char_count> 字符，IP 等级: <ip_rating>）`；无命中时一行 `[PASS] 未命中高风险词`；每个命中两行 `[RISK] term ×count` + 原因/建议；末尾 `总判定: X (HIGH a / MEDIUM b / LOW c)` 与口径行。

### 4.2 `claim_scan` 失败契约

| 场景 | exit | stdout | stderr |
|---|---|---|---|
| 无 `--file/--text` | 2 | 错误体 A | 空（实测 stderr 长度 0） |
| 两者同时给 | 2 | 错误体 B | 空 |
| 文件不存在 | 2 | 错误体 C | 空 |
| 非 UTF-8 文本 | 2 | 错误体 D（**无 `missing` 键**） | 空 |
| argparse 参数错误 | 2 | 无 JSON；usage 文本 | usage |

错误体原文：

```
A {"status":"INPUT_MISSING","missing":["file|text"],"message":"[INPUT_MISSING] 缺少 --file 或 --text"}
B {"status":"INPUT_MISSING","missing":["file|text"],"message":"[INPUT_MISSING] --file 与 --text 只能二选一"}
C {"status":"INPUT_MISSING","missing":["file"],"message":"[INPUT_MISSING] 找不到文件: <path>"}
D {"status":"INPUT_ERROR","message":"[INPUT_ERROR] 文件不是 UTF-8 文本: <path>"}
```

注意：非 JSON 模式下错误信息写到 **stdout**（不是 stderr），与 `cli_common.fail()` 的约定不同。

### 4.3 `listing_lint` 成功 JSON

```
{
  platform: "amazon_us" | "tiktok_us",
  file: <路径>,
  verdict: "PASS" | "WARN" | "FAIL",
  counts: { "PASS": n, "WARN": n, "FAIL": n },     // findings 条数
  findings: [ { level: "PASS"|"WARN"|"FAIL", code, field, message } ],
  meta: {
    rules_basis: "编写时公开口径，发布前按卖家中心复核",
    title_limit: 200 | 255,
    title_split: { effective: "2026-07-27", item_name_max: 75, item_highlights_max: 125 } | null
  }
}
```

人类可读：`<平台> Listing 自检`、`文件: …`、逐条 `[LEVEL] CODE (field): message`、空行、`总判定: … (FAIL a / WARN b / PASS c)`、口径行。

### 4.4 `listing_lint` 失败与退出码

| 场景 | exit | stdout |
|---|---|---|
| 文件不存在 | 2 | `--json`：`{"status":"INPUT_MISSING","missing":["file"],"message":"[INPUT_MISSING] 找不到文件: …"}` |
| JSON 语法错误 | 2 | `{"status":"INPUT_ERROR","message":"[INPUT_ERROR] JSON 解析失败: …"}`（无 missing） |
| 顶层非对象 | 2 | `{"status":"INPUT_MISSING","missing":["object"],"message":"[INPUT_MISSING] 顶层必须是 JSON 对象"}` |
| 缺必填字段 | 2 | `{"status":"INPUT_MISSING","missing":[…],"message":"[INPUT_MISSING] 缺少字段: …"}` |
| 非 UTF-8 文件 | **1** | 未捕获 `UnicodeDecodeError`，Python traceback 到 stderr（实测 PowerShell 退出码 1） |
| 有 FAIL finding | 1 | 正常 JSON/文本 |
| 仅 WARN 或全 PASS | 0 | 正常 JSON/文本 |
| 缺 `--platform` / 非法平台 | 2 | 无统一 JSON；argparse usage 到 stderr |

`listing_lint` 的上述错误信息在非 JSON 模式下也写到 **stdout**，stderr 为空（实测非 UTF-8 例外，traceback 走 stderr）。

## 5. 计算规则

### 5.1 `claim_scan`

1. 逐词条构造正则并 `findall`；计数为 0 跳过。每个词条最多产出一条 hit（同词不重复）。
2. `waterproof` 特判：若 `--ip-rating` 非空且小写后不在 `{"none","no","n/a","na",""}`，则 `risk` 降为 MEDIUM，原因改为「已声明 IP 等级 <值>…」，建议改为精确等级表述；否则保持 HIGH 并改写原因为「未声明 IP 等级与测试报告…」。**注意 `"0"` 不在豁免集合**。
3. `counts` 按降级后的 `hits[].risk` 统计词条数；出现次数保留在 `hit.count`。
4. `verdict`：任一 HIGH → FAIL；否则任一 MEDIUM/LOW → WARN；否则 PASS。
5. 退出码只看 HIGH 词条数：存在 HIGH → 1，否则 0。MEDIUM/LOW 永远不影响退出码。

### 5.2 `listing_lint` 平台阈值

| 参数 | amazon_us | tiktok_us |
|---|---|---|
| 标题上限 | 200（`item_name` 75 + `item_highlights` 125） | 255 |
| 标题建议下限 | 80 | 40 |
| 单条 bullet 上限 | 220 | 不检查 |
| bullet 数量 | 必须 5 | 不检查 |
| 后台搜索词 | ≤250 UTF-8 字节（>230 WARN） | 不检查 |
| 短描述 | 不检查 | ≤500 |
| 品牌前置 | 前 80 字符 | 不检查 |

### 5.3 `listing_lint` 全部检查项

**标题（两平台通用）**

| code | level | 判定 |
|---|---|---|
| `TITLE_TOO_LONG` | FAIL | 长度 > 上限；Amazon 拆分模式下为 `item_name + " " + item_highlights` 的组合长度 |
| `TITLE_TOO_SHORT` | WARN | 长度 < 下限 |
| `TITLE_LENGTH` | PASS | 在 `[下限, 上限]` 内 |
| `TITLE_PROMO` | FAIL | 命中 HARD_PROMO 任一 |
| `TITLE_SUBJECTIVE` | WARN | 命中 SOFT_PROMO 任一 |
| `TITLE_WORDING` | PASS | 两类都未命中 |
| `TITLE_SPECIAL_CHARS` | FAIL/PASS | 含 `~ ! ? $ % ^ *` 任一字符；否则 PASS |
| `TITLE_ALL_CAPS` | FAIL/WARN/PASS | 全大写词（`[A-Z]{2,}`，排除 ALL_CAPS_ALLOWLIST 与品牌 token）≥2 个 → FAIL；1 个 → WARN；0 → PASS |
| `TITLE_REPEAT` | WARN/PASS | 去掉 STOPWORDS 后的词频 ≥3 → WARN |
| `CJK_CHARS` | FAIL | 标题含 CJK（含扩展 A 区） |
| `EMOJI` | FAIL | 命中 emoji 正则 |
| `TITLE_SPLIT_REQUIRED` | WARN | 仅 Amazon 非拆分路径，且长度 >75：提示 2026-07-27 起需拆标题 |
| `TIKTOK_EVASION` | FAIL | 仅 TikTok，标题命中站外导流短语 |

**Amazon 拆分标题 / 品牌**

| code | level | 判定 |
|---|---|---|
| `ITEM_NAME_TOO_LONG` / `ITEM_NAME_LENGTH` | FAIL/PASS | `item_name` 长度 vs 75 |
| `ITEM_HIGHLIGHTS_TOO_LONG` / `ITEM_HIGHLIGHTS_LENGTH` | FAIL/PASS | `item_highlights` 长度 vs 125 |
| `ITEM_HIGHLIGHTS_MISSING` | WARN | 未提供 `item_highlights` |
| `BRAND_MISSING_INPUT` | WARN | `brand` 缺失 |
| `BRAND_NOT_IN_TITLE` | WARN | 小写品牌不是标题子串 |
| `BRAND_TOO_LATE` | WARN | 品牌首次出现下标 ≥80（消息按 1-based 报「第 N 字符」） |
| `BRAND_PREFIX` | PASS | 品牌出现在前 80 字符内 |

**Bullets（仅 Amazon，且 `bullets` 为数组）**

| code | level | 判定 |
|---|---|---|
| `BULLET_COUNT` | FAIL/PASS | 必须恰好 5 条 |
| `BULLET_TOO_LONG` / `BULLET_LENGTH` | WARN/PASS | 单条 >220 / ≤220 |
| `BULLET_PRICE` | FAIL | 命中价格正则：`$`、`usd`、`dollars`、`price`、`save <n>%`、`<n> off` |
| `BULLET_CONTACT` | FAIL | 命中 URL（http/www/常见 TLD）、邮箱、电话 |
| `BULLET_PROMO` | FAIL | 命中 HARD_PROMO |
| `BULLET_SUBJECTIVE` | WARN | 命中 SOFT_PROMO |
| `BULLET_WORDING` | PASS | 无促销/主观词 |
| `BULLET_CLEAN` | PASS | 无价格与联系方式 |
| `CJK_CHARS` / `EMOJI` | FAIL | 买家可见文本检查 |

**后台搜索词（仅 Amazon，且值为字符串）**

| code | level | 判定 |
|---|---|---|
| `BACKEND_TOO_LONG` | FAIL | UTF-8 字节 >250 |
| `BACKEND_NEAR_LIMIT` | WARN | 231–250 字节 |
| `BACKEND_LENGTH` | PASS | ≤230 字节 |
| `BACKEND_BRAND_REPEAT` | FAIL | 品牌拆词后任一词出现在后台词 |
| `BACKEND_NO_BRAND` | PASS | 未重复品牌 |
| `BACKEND_DUPLICATE` | WARN | 任一单词在后台词中出现 ≥2 次 |
| `BACKEND_UNIQUE` | PASS | 无重复单词 |

**描述 / A+（两平台都会跑；TikTok 也检查 description）**

| code | level | 判定 |
|---|---|---|
| `DESC_PROMO` | WARN/PASS | 描述命中 HARD_PROMO（**排除单词 `hot`**） |
| `APLUS_PROMO` | WARN | A+ 模块命中同一列表 |
| `APLUS_PRESENT` | PASS | 提供了非空 A+ 数组 |
| `CJK_CHARS` / `EMOJI` | FAIL | 描述与每个 A+ 模块 |

**TikTok 专属**

| code | level | 判定 |
|---|---|---|
| `TIKTOK_DESC_TOO_LONG` / `TIKTOK_DESC_LENGTH` | FAIL/PASS | `short_description`（缺省回落到 `description`）长度 vs 500 |
| `TIKTOK_EVASION` | FAIL | 短描述命中站外导流短语 |
| `TIKTOK_PRICE_IN_COPY` | FAIL | 短描述含 `$` |

**IP 一致性（两平台）**

| code | level | 判定 |
|---|---|---|
| `ATTRS_MISSING` | WARN | 无 `product_attributes` |
| `IP_RATING_UNKNOWN` | WARN | 有属性但无 `ip_rating` |
| `CLAIM_IP_CONFLICT` | FAIL | 声明 `ip_rating` 为无等级（`""/none/no/n/a/na/0`），但标题/五点/描述/A+（TikTok 加短描述）命中 `waterproof/water resistant/submersible/ipx N`；每个字段各报一条 |
| `CLAIM_IP_CONSISTENT` | PASS | 声明无等级且全文无上述表述 |
| `IP_RATING_DECLARED` | PASS | 声明了具体等级（仍需人工核对报告） |

**固定词表**

- HARD_PROMO：`best seller`、`best sellers`、`best-selling`、`best selling`、`#1`、`no.1`、`number 1`、`number one`、`sale`、`on sale`、`free shipping`、`free delivery`、`deal`、`hot deal`、`hot`、`discount`、`clearance`、`limited time`、`buy now`、`lowest price`、`cheapest`、`coupon`、`prime day`、`black friday`。
- SOFT_PROMO：`best`、`perfect`、`premium`、`revolutionary`、`amazing`、`ultimate`、`superior`、`top rated`、`professional`、`world's best`、`unbeatable`、`exclusive`、`guaranteed`、`flawless`、`instantly`。
- TIKTOK_EVASION：`link in bio`、`bio link`、`check my bio`、`comment to get`、`comment for price`、`dm me`、`whatsapp`、`free giveaway`、`tap the link`、`shop link`。
- 全大写豁免：`USB, LED, BPA, FCC, UL, IPX, DC, AC, RGB, XL, XXL, GPS, LCD, USB-C` + 品牌大写形式。
- 停用词：`a, an, the, and, or, for, with, to, of, in, on, by, your, you, is, it, at, from, as, this, that`。

### 5.4 `listing_lint` 汇总

1. 每项检查独立追加 finding；通过项也计 PASS，因此 `counts.PASS` 是「通过检查条数」，不是检查项总数。
2. `verdict = FAIL if counts.FAIL>0 else (WARN if counts.WARN>0 else PASS)`。
3. 退出码 = `1 if counts.FAIL>0 else 0`；WARN 不改变退出码。
4. TikTok 不跑五点/后台/品牌前置/拆分标题；Amazon 不跑短描述与 TikTok 导流词（标题除外）。

## 6. 已知行为与坑（现状）

| # | 现象 | 触发条件 | 现状行为（实测） | 建议 |
|---|---|---|---|---|
| 1 | `claim_scan` 无输入 exit 2 | 不带 `--file/--text` | exit 2；`--json` 时 stdout 合法 JSON、`missing` 为 `file/text` 单元素标识 | 保留 |
| 2 | 两个来源互斥 exit 2 | 同时给 `--file` 与 `--text` | exit 2；不读文件，直接报「只能二选一」 | 保留 |
| 3 | HIGH 才影响退出码 | 仅 MEDIUM/LOW 命中 | `verdict=WARN` 但 exit **0**；例：`premium/professional/advanced` → exit 0 | 保留（文档需强调） |
| 4 | HIGH → exit 1 | 任一 HIGH | `verdict=FAIL`，exit 1 | 保留 |
| 5 | 解码失败 exit 2 但无 `missing` | GBK 中文文件 | `{"status":"INPUT_ERROR","message":"[INPUT_ERROR] 文件不是 UTF-8 文本: …"}`；stderr 为空 | 建议补 `missing:["file"]` |
| 6 | 错误信息走 stdout | 非 JSON 模式的全部输入错误 | 实测 stderr 长度 0，message 打到 stdout | 建议改为 stderr（与 03 对齐） |
| 7 | `--ip-rating 0` 被当作“已声明等级” | `--ip-rating 0` | `waterproof` 降为 MEDIUM，输出「已声明 IP 等级 0」；exit 0 | 建议把 `0` 加入无等级集合 |
| 8 | GBK 纯 ASCII 文件不报错 | 文件仅含 ASCII | 能正常解码，扫描继续 | 属正常，编码探测仅按 UTF-8 |
| 9 | 匹配允许连字符/空格互换 | `fda-approved`、`non toxic` | 命中 `fda approved` / `non-toxic`（实测前者命中） | 保留 |
| 10 | `100 %` 不命中 | 数字与百分号间有空格 | 按当前正则不匹配（代码推导，未实测） | 重写时明确词形 |
| 11 | 计数为“词条数” | 同一词出现多次 | `counts.HIGH` 只 +1，`hit.count` 才反映次数 | 保留，字段命名需说明 |
| 12 | `listing_lint` FAIL → exit 1 | 任一 FAIL | 例：210 字符标题 + 1 条 bullets → FAIL 2、WARN 3、exit 1 | 保留 |
| 13 | 仅 WARN → exit 0 | 无 FAIL | verdict=WARN、exit 0 | 保留 |
| 14 | `verdict` 与退出码非一一对应 | verdict=WARN | 也可能 exit 0；不是 1 | 文档需列映射表 |
| 15 | 非 UTF-8 直接 traceback | Listing JSON 用 GBK 中文 | 未捕获 `UnicodeDecodeError`，退出码 **1**（非 2），无 JSON | 必须修正 |
| 16 | 缺 `--platform` 无 JSON 契约 | 不传或传非法值 | argparse usage 到 stderr，exit 2，stdout 空 | 建议统一错误出口 |
| 17 | `item_name` 存在时忽略 `title` 长度 | Amazon 且 `item_name` 非空 | 用 `item_name + item_highlights` 校验；但 `title` 仍属必填 | 文档写明双轨 |
| 18 | 拆分标题必填项 | 只给 `item_name`/`item_highlights` | 缺 `title` → INPUT_MISSING（required_fields 仍要 `title`） | 建议放宽 |
| 19 | TikTok 空描述不报缺失但会回落 | `short_description=""` + 有 `description` | 必填按类型通过；检查阶段 `or` 回落到 `description` 继续跑长度/促销/导流检查；两者都空时长度为 0 | 建议明确空串语义 |
| 20 | `bullets` 字符串被额外报错 | `bullets:"..."` | 必填列表本身通过（非空），随后追加 `bullets(须为数组)` 一项进 missing；不会重复列出 `bullets` | 建议在检查前提早拦截 |
| 20a | TikTok 也被 `bullets` 类型规则波及 | TikTok + `bullets:"..."` | `missing` 追加 `bullets(须为数组)` → INPUT_MISSING，尽管 TikTok 本不检查五点 | 建议按平台限定 |
| 21 | 描述里的价格/联系方式不检查 | 描述含 `$`、URL | 只有 bullets 查价格与联系方式；TikTok 另查 `$` | 建议补齐 |
| 22 | 描述与 A+ 的促销词只 WARN | 命中 HARD_PROMO | 不导致 exit 1（`hot` 被排除） | 保留 |
| 23 | `TOO_LONG` 检查不可达 | 所有 `scan_buyer_text` 调用均未传 `max_chars` | 该 code 永不产生 | 重写时可删 |
| 24 | 全大写 FAIL 阈值 | 2 个及以上全大写词 | 同一词重复两次也计 2 → FAIL | 建议按去重词计 |
| 25 | 品牌位置按首次子串 | 品牌在标题中晚出现 | 下标 ≥80 → WARN；消息报 1-based 位次 | 保留 |
| 26 | 后台词类型漂移 | `backend_search_terms` 为数组/对象 | 必填校验可能通过（非空），但检查被整体跳过 | 建议类型校验 |
| 27 | `product_attributes` 形态宽容 | 数组/对象/`k:v` 字符串 | 统一小写；`ip_rating:none` 触发全文 IP 冲突扫描 | 保留 |

## 7. 对拍基准（必须可复现）

统一前缀：

```powershell
$env:PYTHONIOENCODING='utf-8'
```

### 7.1 `claim_scan`

1. **仓库样例（PASS，exit 0）**

```powershell
python Agents/04_Listing_Agent/scripts/claim_scan.py --file Agents/04_Listing_Agent/examples/copy.txt --json
```

期望：exit 0；`verdict=PASS`；`source` 为相对路径；`char_count=1401`；`counts={HIGH:0,MEDIUM:0,LOW:0}`；`hits=[]`；`ip_rating="none"`。

2. **多风险词（FAIL，exit 1）**

```powershell
python Agents/04_Listing_Agent/scripts/claim_scan.py --text "Our waterproof blender is the best, 100% non-toxic and eco-friendly. Instantly blends. Premium advanced innovative design." --json
```

期望：exit 1；`verdict=FAIL`；`counts={HIGH:4,MEDIUM:2,LOW:3}`；HIGH 词为 `100%`、`best`、`non-toxic`、`waterproof`；MEDIUM 为 `eco-friendly`、`instantly`；LOW 为 `advanced`、`innovative`、`premium`。

3. **IP 降级（WARN，exit 0）**

```powershell
python Agents/04_Listing_Agent/scripts/claim_scan.py --text "waterproof design" --ip-rating ipx4 --json
python Agents/04_Listing_Agent/scripts/claim_scan.py --text "waterproof design" --json
```

期望：第一条 exit 0、`verdict=WARN`、`waterproof.risk=MEDIUM`、count=1；第二条 exit 1、`verdict=FAIL`、risk=HIGH。

4. **输入错误**

```powershell
python Agents/04_Listing_Agent/scripts/claim_scan.py --json
python Agents/04_Listing_Agent/scripts/claim_scan.py --file Agents/04_Listing_Agent/examples/copy.txt --text "hello" --json
python Agents/04_Listing_Agent/scripts/claim_scan.py --file no-such.txt --json
```

期望：三条均 exit 2；JSON 的 `missing` 分别为 `["file|text"]`（缺少）、`["file|text"]`（互斥）、`["file"]`（不存在）。

5. **非 UTF-8**

```powershell
$gbk=[System.Text.Encoding]::GetEncoding('GBK')
[System.IO.File]::WriteAllText("$env:TEMP\gbk_cn.txt", '这款搅拌机 waterproof', $gbk)
python Agents/04_Listing_Agent/scripts/claim_scan.py --file "$env:TEMP\gbk_cn.txt" --json
```

期望：exit 2；`status=INPUT_ERROR`；无 `missing` 键；message 含「文件不是 UTF-8 文本」。

### 7.2 `listing_lint`

1. **Amazon 样例（PASS，exit 0）**

```powershell
python Agents/04_Listing_Agent/scripts/listing_lint.py --file Agents/04_Listing_Agent/examples/listing_input.json --platform amazon_us --json
```

期望：exit 0；`verdict=PASS`；`counts={PASS:30,WARN:0,FAIL:0}`；`meta.title_limit=200`；`meta.title_split={effective:"2026-07-27",item_name_max:75,item_highlights_max:125}`。

2. **TikTok 同一样例（PASS，exit 0）**

```powershell
python Agents/04_Listing_Agent/scripts/listing_lint.py --file Agents/04_Listing_Agent/examples/listing_input.json --platform tiktok_us --json
```

期望：exit 0；`verdict=PASS`；`counts={PASS:9,WARN:0,FAIL:0}`；`meta.title_limit=255`；`meta.title_split=null`；findings 只含标题 5 项 + DESC_PROMO + APLUS_PRESENT + TIKTOK_DESC_LENGTH + CLAIM_IP_CONSISTENT。

3. **缺字段（exit 2）**

```powershell
$j='{"title":"NordPulse","bullets":"not-array"}'
[System.IO.File]::WriteAllText("$env:TEMP\lint_bad.json",$j)
python Agents/04_Listing_Agent/scripts/listing_lint.py --file "$env:TEMP\lint_bad.json" --platform amazon_us --json
```

期望：exit 2；`missing=["brand","description","backend_search_terms","aplus_modules","bullets(须为数组)"]`。

4. **FAIL（exit 1）**

```powershell
$j2='{"brand":"NordPulse","title":"' + ('A'*210) + '","bullets":["x"],"description":"desc","backend_search_terms":"a","aplus_modules":["m"]}'
[System.IO.File]::WriteAllText("$env:TEMP\lint_fail.json",$j2)
python Agents/04_Listing_Agent/scripts/listing_lint.py --file "$env:TEMP\lint_fail.json" --platform amazon_us --json
```

期望：exit 1；`verdict=FAIL`；`counts={PASS:11,WARN:4,FAIL:2}`；FAIL 至少含 `TITLE_TOO_LONG`、`BULLET_COUNT`；WARN 含 `TITLE_SPLIT_REQUIRED`、`BRAND_NOT_IN_TITLE`、`TITLE_ALL_CAPS`、`ATTRS_MISSING`。

5. **文件/语法错误**

```powershell
python Agents/04_Listing_Agent/scripts/listing_lint.py --file no-such.json --platform amazon_us --json
python Agents/04_Listing_Agent/scripts/listing_lint.py --file Agents/04_Listing_Agent/examples/copy.txt --platform amazon_us --json
```

期望：两者均 exit 2；第一条 `missing=["file"]`，第二条 `status=INPUT_ERROR` 且无 `missing`。

## 8. 未完整刻画 / 待确认

- `100 %`（数字与 `%` 之间有空格）是否命中未实测，仅按正则推导为不命中。
- `listing_lint` 的 `TITLE_SPLIT_REQUIRED`、`BRAND_TOO_LATE` 边界（恰好在第 80/81 字符）未单独构造用例。
- `product_attributes` 为对象且含重复大小写键、数组元素无冒号时的覆盖顺序未穷举。
- HARD_PROMO 中 `#1` 的子串边界（如 `#10`）未实测。
- `claim_scan` 的 `--text` 含 BOM 字符、`\r\n` 与 `char_count` 的关系未单独验证。
- `listing_lint` 对非字符串 `title`、`brand` 的强制 `str()` 行为未实测。
- 两份脚本的 argparse 错误均不走统一 JSON 契约，重写时需产品确认是否修正。
