# 03 合规准入闸门 —— 规格冻结（clean-room 重写基线）

> 对象：`Agents/03_Compliance_Agent/scripts/compliance_gate.py`
> 规则来源：同目录 `compliance_rules.json`（v2.1.0，2026-10-30）+ 仓库根 `config/category_map.json`（v1.1.0）
> 本文只描述行为，不含实现代码；所有数值与退出码均来自实跑（Python 3.12 / Windows PowerShell 5）。

## 1. 范围与脚本

- 职责：给定「合规类目 + 属性标签 + 目标平台 + 已有报告 + IP 状态」，输出必需文件清单、缺失项、放行结论（PASS / CONDITIONAL / BLOCKED）与 IP 初筛。不替代律师意见，不做文件真伪核验。
- 依赖：
  - `compliance_rules.json`：59 个 `doc_library` 条目（其中 blocking=2：`fda_device_clearance`、`ftc_health_substantiation`；advisory=4：`amazon_category_approval`、`amazon_label_review`、`tiktok_category_qualification`、`tiktok_product_cert`）；16 个合规类目；13 个属性；2 个平台。
  - `config/category_map.json`：18 个映射项（含 `default`，其 `compliance_key=null`）；5 个别名。
  - `cli_common.py`：统一错误出口（`fail()` / `JsonArgumentParser`）、`--json` 模式。
  - 上游：01 选品给出 category_key、03 自己维护属性标签；02 共用映射表。无网络、无第三方库。
- 退出码：`0=PASS（即需求里的 APPROVED）`、`1=CONDITIONAL`、`2=BLOCKED`、`3=输入/参数/配置错误`。

## 2. CLI 契约

无子命令、无位置参数；全部为选项。顺序无关，重复传参有明确定义。

| 参数名 | 类型 | 必填 | 默认值 | 取值范围/枚举 | 说明 |
|---|---|---|---|---|---|
| `--category` | string | 条件必填 | 无 | 映射表 `categories` 键 / `aliases` 键 / 平台类目路径 / 规则库类目键 | 正常模式下必须提供；`--list-*` 模式下可不填。空串视为未提供 |
| `--attr` | string，可重复 | 正常模式必填 | `[]` | 规则库 `attributes` 的 13 个键 | 单次传参内按 `,`、`；`、`、`、`;` 拆分；重复传参累加。全角逗号 `，` **不**拆分（见 §6） |
| `--marketplace` | enum | 正常模式必填 | 无 | `amazon_us` / `tiktok_us` / `both` | `both` 展开为 `["amazon_us","tiktok_us"]`，顺序固定 |
| `--have` | string，可重复 | 否 | `[]` | 自由文本（报告名/别名/ID） | 同样按逗号类分隔符拆分；含 pending 标记的条目不计数 |
| `--trademark` | enum | 否 | 无（None） | `none` / `pending` / `registered_us` / `conflict` | 缺省按 `unknown` 处理并产生输入提示，不改变退出码 |
| `--patent-search-done` | string→bool | 否 | 无（None） | `true/false/yes/no/y/n/1/0/on/off`（大小写不敏感） | 缺省 = 未检索；非法值 → exit 3 |
| `--json` | flag | 否 | false | — | 成功与失败都改走 JSON 输出；错误时 stdout 为合法 JSON |
| `--list-categories` | flag | 否 | false | — | 打印可映射的 category_key 与别名，exit 0 |
| `--list-attributes` | flag | 否 | false | — | 打印 13 个属性及「含阻断级义务」标记，exit 0 |

优先级与冲突：

1. `--list-categories` 与 `--list-attributes` 同时给出时，只执行 `--list-categories`；两者都不校验 `--attr/--marketplace`。
2. 正常模式先解析类目，再校验属性非空、属性合法、marketplace 非空，顺序固定；任一失败即 exit 3，不做后续计算。
3. 参数错误（非法枚举、未知选项、缺值）由自定义 `ArgumentParser` 捕获，统一 exit 3；`--json` 出现在 argv 中时同样输出 JSON。

## 3. 输入契约

### 3.1 文件与编码

| 文件 | 编码 | 缺失/解析失败行为 |
|---|---|---|
| `compliance_rules.json` | UTF-8（严格，不兼容 BOM） | `[INPUT_MISSING]` + exit 3 |
| `config/category_map.json` | UTF-8 with BOM（`utf-8-sig`） | `[INPUT_MISSING]` + exit 3 |

路径按脚本所在目录与仓库根推导，**不支持**环境变量或 `--rules/--map` 覆盖。文件内容按 JSON 读取，无 schema 版本校验，仅读取 `_meta.version/_meta.updated/_meta.disclaimer`。

### 3.2 `compliance_rules.json` 结构

| 顶层键 | 类型 | 语义 |
|---|---|---|
| `_meta` | object | `version`、`updated`、`market`、`origin`、`disclaimer`（原样输出）、`sources`、`status_rules`（仅文档说明，不参与计算）、`have_rule`、`advisory_rule` |
| `doc_library` | map<id, Doc> | 全部文件定义；被类目/属性/平台引用 |
| `categories` | map<key, Cat> | 16 个合规类目 |
| `attributes` | map<key, Attr> | 13 个属性 |
| `marketplaces` | map<key, Mkt> | 仅 `amazon_us`、`tiktok_us` |
| `global_risk_notes` | string[] | 追加到每条结果的风险提示 |
| `ip_screening` | object | IP 初筛的条目、商标状态映射与免责提示 |

`Doc` 字段：

| 字段 | 必填 | 默认 | 语义 |
|---|---|---|---|
| `name` | 是 | — | 展示名；缺失会 KeyError（未做校验） |
| `authority` | 是 | — | 主管机构/法规；缺失会 KeyError |
| `trigger` | 否 | `""` | 触发场景文案；合并时以「；」拼接 |
| `blocking` | 否 | `false` | true = 缺失即 BLOCKED |
| `advisory` | 否 | `false` | true = 平台审核提示项，**不参与** PASS/CONDITIONAL 判定 |
| `default_status` | 否 | 无 | 未命中 `--have` 时的状态；现有仅 advisory 项填 `unknown` |
| `aliases` | 否 | `[]` | 报告名粗匹配的别名（与 `name`、`id` 一起参与匹配） |
| `sources` | 否 | `[]` | 法条/来源字符串，输出为 `citations` |
| `as_of` | 否 | `null`（输出 null） | 规则核对日期 |
| `confidence` | 否 | `"needs_review"` | 取值 `verified` / `needs_review`（未做枚举校验） |

`Cat` 字段：`label_cn`（必填）、`docs`（文档 id 数组）、`risk_notes`（字符串数组）。部分类目另有 `as_of/confidence/sources`，引擎**不读取**这三项。`Attr` 字段：`label_cn`、`docs`、`risk_notes`。`Mkt` 字段：`label`、`docs`、`risk_notes`。

16 个合规类目的基础文档集（`*` 为 blocking；实际 required 还叠加属性与平台文档，并按 id 去重）：

| 合规类目 | 文档数 | 文档 id |
|---|---|---|
| `small_appliances` | 4 | `ul_nrtl`、`cpsc_general`、`fcc_part15b`、`prop65` |
| `kitchenware` | 4 | `fda_food_contact`、`cpsc_general`、`prop65`、`ca_ab1200` |
| `electronics` | 5 | `fcc_part15b`、`ul_nrtl`、`doe_efficiency`、`cpsc_general`、`prop65` |
| `toys` | 6 | `cpc`、`astm_f963`、`tracking_label`、`phthalates`、`lead`、`prop65` |
| `beauty` | 4 | `mocra`、`mocra_gmp`、`cosmetic_label`、`prop65` |
| `textile` | 4 | `textile_1610`、`textile_fiber_label`、`cpsc_general`、`prop65` |
| `furniture` | 5 | `tb117`、`furniture_1640`、`tsca_title6`、`cpsc_general`、`prop65` |
| `pet` | 3 | `pet_material_safety`、`cpsc_general`、`prop65` |
| `sports` | 4 | `cpsc_general`、`astm_sport_standard`、`helmet_1203`、`prop65` |
| `baby` | 7 | `cpsc_general`、`cpc`、`tracking_label`、`baby_gear_registration`、`infant_sleep_standards`、`fmvss_213`、`prop65` |
| `grocery` | 5 | `fda_food_facility_reg`、`fsma_preventive_controls`、`fda_food_label`、`fsvp_importer`、`prop65` |
| `tools` | 3 | `cpsc_general`、`prop65`、`ansi_hand_tool` |
| `office` | 2 | `cpsc_general`、`prop65` |
| `jewelry` | 4 | `cpsc_general`、`prop65`、`ca_jewelry_lead`、`ftc_jewelry_guides` |
| `watches` | 2 | `cpsc_general`、`prop65` |
| `full_size_appliances` | 6 | `ul_nrtl`、`doe_efficiency`、`ftc_energy_guide`、`fcc_part15b`、`prop65`、`epa_refrigerant` |

`ip_screening`：`items[]` 每项有 `id/item/scope/authority`（固定 4 项：商标、外观专利、实用专利、Brand Registry）；`trademark_status_map` 固定映射 `none→missing`、`pending→unknown`、`registered_us→have`、`conflict→blocked`；`notes` 追加到风险提示。

### 3.3 `category_map.json` 结构

- `_meta`：`updated/version/note/sources`，仅文档用途。
- `categories.<key>`：`label`、`us_fees_key`、`compliance_key`（可为 `null`）、`platform_paths`（字符串数组）。`compliance_key` 必须存在于规则库 `categories`。
- `aliases`：5 条旧键 → 映射键：`small_appliance→small_appliances`、`kitchenware→home_kitchen`、`textile→clothing`、`apparel→clothing`、`home-and-kitchen→home_kitchen`。
- 18 个映射项的实际指向（`default` 的 `compliance_key=null`，调用即 exit 3）：

| category_key | compliance_key | platform_paths 示例 |
|---|---|---|
| `home_kitchen` | `kitchenware` | `Home & Kitchen` |
| `small_appliances` | `small_appliances` | `Home & Kitchen > Kitchen & Dining > Small Appliances`、`Small Appliances` |
| `electronics` | `electronics` | `Electronics`、`Consumer Electronics` |
| `electronics_accessories` | `electronics` | `Electronics > Accessories`、`Cell Phones & Accessories` |
| `clothing` | `textile` | `Clothing, Shoes & Jewelry > Clothing`、`Clothing` |
| `beauty` | `beauty` | `Beauty & Personal Care`、`Beauty` |
| `baby` | `baby` | `Baby`、`Baby Products` |
| `grocery` | `grocery` | `Grocery & Gourmet Food`、`Grocery` |
| `toys` | `toys` | `Toys & Games` |
| `sports` | `sports` | `Sports & Outdoors` |
| `tools` | `tools` | `Tools & Home Improvement`、`Home Improvement` |
| `office` | `office` | `Office Products` |
| `pet` | `pet` | `Pet Supplies` |
| `furniture` | `furniture` | `Home & Kitchen > Furniture`、`Furniture` |
| `jewelry` | `jewelry` | `Clothing, Shoes & Jewelry > Jewelry`、`Jewelry` |
| `watches` | `watches` | `Clothing, Shoes & Jewelry > Watches`、`Watches` |
| `full_size_appliances` | `full_size_appliances` | `Appliances > Full-size Appliances`、`Appliances` |
| `default` | `null` | 无 |

注意映射键 `clothing` 的 `compliance_key` 是 `textile`，因此输出 `generated_for.category` / 组标签为 `category:textile`，而 `category_key=clothing`。

### 3.4 类目解析优先级（严格顺序，不做模糊猜测）

1. **显式键**：输入与 `categories` 的键完全相等（大小写敏感）。`source=explicit`。
2. **别名**：输入与 `aliases` 键完全相等，且其目标在 `categories` 中。`source=alias`；向 stderr 打一条 `[WARN] 类目旧键 … 已映射为 …`。
3. **平台路径前缀**：先归一化（小写、`>`/`|` 变成 ` > `、压缩空白），再与每个 `platform_paths` 的归一化值比较。命中条件为完全相等或 `输入.startswith(前缀 + " >")`；取**最长前缀**对应的键。`source=platform_path`；向 stderr 打 `[WARN] 收到平台类目路径 …`。
   - 若最长长度出现两个不同键并列，视为歧义，不取任何一个（当前映射表不存在可触发并列的前缀，见 §8）。
4. **规则库直通**：以上都失败但输入与 `rules["categories"]` 的键完全相等，返回该键，`source=rules_direct`（现有 16 个规则类目均已被映射/别名覆盖，实际不可达）。
5. 仍失败 → `[INPUT_MISSING]`，exit 3。
6. 解析到映射键后，若 `compliance_key` 为 `null` 或不在规则库 → `[INPUT_MISSING]`，exit 3；`default` 因此始终报错。

### 3.5 报告匹配与属性

- `--have` 条目先过滤 pending：命中 `pending / 待出 / 待定 / 申请中 / 办理中 / 进行中 / 审核中 / in progress / awaiting`（大小写不敏感、子串匹配）即视为未具备，并写入 `input_warnings`。
- 有效条目与每份文档的 `id`、`name`、`aliases` 逐一比较，**双向包含**即算命中。归一化规则：转小写、仅保留字母数字与空格及 `.` `-` `/`，其余字符变空格，压缩空白。因此 `UL 认证` 可命中 `ul_nrtl` 的别名 `ul 认证`；`UN38.3` 与 `un383` 不互相匹配（保留点号）。
- `--attr` 去空、去重与否由输入决定；属性重复会重复触发同名文档但最终按 id 合并。
- 未提供 `trademark` / `patent-search-done` 不阻断计算，仅在 `input_warnings` 记录。

### 3.6 `required_docs` 合并规则

顺序：类目 `docs`（原序）→ 属性按用户传入顺序 → 平台（`both` 时 amazon_us 在前、tiktok_us 在后）。按文档 id 去重并保留首次出现位置：

- 首次出现：写入全部字段，`sources=[组标签]`，`citations=doc.sources`。
- 再次出现：`trigger` 若新值非空且不是已有子串，则用「；」追加；`sources` **仅在组标签尚未存在时**追加（同一属性的重复传参不会重复记来源）；`citations` 取并集；`blocking` 取逻辑或。`advisory`、`name`、`authority`、`as_of`、`confidence` 保持首次值。
- 组标签格式固定：`category:<compliance_key>`、`attr:<属性键>`、`marketplace:<平台键>`。

## 4. 输出契约

### 4.1 成功 JSON（`--json`）

```
{
  tool: "compliance_gate",
  version: <_meta.version>,
  rules_updated: <_meta.updated>,
  generated_at: "YYYY-MM-DD HH:MM:SS"（本地时间，非 ISO）,
  generated_for: {
    category, category_label,
    marketplace: "amazon_us" | "tiktok_us" | "amazon_us+tiktok_us",
    marketplace_labels: string[],
    attributes: string[], attribute_labels: string[],
    have_reports: string[],            // 已剔除 pending
    trademark_status: <值> | "未提供",
    patent_search_done: <bool> | "未提供",
    category_key, category_source      // 计算完成后追加
  },
  status: "PASS" | "CONDITIONAL" | "BLOCKED",
  counts: { required, have, missing, unknown, blocking_missing, ip_blocked, advisory },
  required_docs: [
    { id, name, authority, trigger, blocking, advisory, status,
      sources[], citations[], as_of, confidence }
  ],
  missing: [ { id, name, authority, blocking, status } ],   // 仅非 advisory
  advisory_items: [ { id, name, status } ],
  risk_notes: string[],              // 去重后的类目+属性+平台+全局+IP 提示
  ip_screening: [
    { id, item, scope, authority, status, blocked, note, action }
  ],
  input_warnings: string[],
  disclaimer: <_meta.disclaimer>
}
```

### 4.2 人类可读（无 `--json`，全部 stdout）

标题 `=== 美国市场准入合规初筛 ===`；依次为：类目/市场/属性行、已有报告行、空行、`结论：<中文结论>`、统计行、可选「阻断来源」行、`必需文件清单`（每项 `[状态][标签] 名称` + `主管…｜触发…`）、`缺失 / 待确认（按优先级）` 编号列表、`IP 初筛（不是法律意见…）` 每项状态/说明/动作、`输入提示`、`风险提示`、`口径`、`退出码：0=PASS 1=CONDITIONAL 2=BLOCKED 3=输入错误（当前 N）`。状态中文固定为 `已具备/缺失/待确认`；标签固定为 `平台/阻断/补办`。行级条件（阻断来源触发、等级词、空段省略）见 §4.5。

### 4.3 失败契约

`--json` 时 **stdout 输出合法 JSON**、stderr 输出人类信息：

```
{"status": "INPUT_MISSING", "missing": [...], "message": "..."}
```

- 03 的所有 `fail()` 调用都**不传** `missing`，因此 `missing` 恒为 `[]`；字段名只出现在 message 文本里。
- 无 `--json` 时 stdout 为空，仅 stderr 有 `[INPUT_MISSING] <去标签后的信息>`。
- 参数错误也走同一契约（`status=INPUT_MISSING`，message 前缀「参数错误：」），usage 另写 stderr。

### 4.4 退出码矩阵

| 场景 | 退出码 | stdout | stderr |
|---|---|---|---|
| status=PASS | 0 | 文本或 JSON | 无（平台路径/别名 WARN 除外） |
| status=CONDITIONAL | 1 | 文本或 JSON | 同上 |
| status=BLOCKED | 2 | 文本或 JSON | 同上 |
| 未知类目 / `default` / compliance_key 非法 | 3 | `--json` 时 JSON；否则空 | `[INPUT_MISSING]` |
| 缺 category / attr / marketplace | 3 | 同上 | `[INPUT_MISSING]` |
| 未知属性、参数枚举非法、bool 非法 | 3 | 同上 | `[INPUT_MISSING]` |
| 规则/映射文件缺失或 JSON 坏 | 3 | 同上 | `[INPUT_MISSING]` |
| `--list-categories` / `--list-attributes` | 0 | 列表文本 | 无 |

### 4.5 人类输出细节（probe，2026-10-30）

**「阻断来源」行**

- 文案：`阻断来源：IP 初筛识别到 {ip_blocked} 项冲突（详见下方 IP 初筛）`，紧跟统计行之后。
- **触发条件（实测）：只要 `ip_blocked > 0` 就输出，与 `blocking_missing` 是否非空无关。**

| 场景 | blocking_missing | ip_blocked | 是否输出 | 实测 |
|---|---|---|---|---|
| 仅 IP 冲突（`office` + `food_contact` 文件全齐 + `--trademark conflict`） | 0 | 2 | 是 | 统计行后为「阻断来源：…2 项冲突」 |
| 仅阻断级文档缺失（`office` + `medical_claim`，无 `--have`） | 2 | 0 | 否 | 统计行后直接进入「缺失 / 待确认」 |
| 两者同时存在（`medical_claim` + `--trademark conflict`） | 2 | 2 | **是** | 统计行后仍输出「阻断来源：…2 项冲突」 |
| IP 冲突 + 非阻断文档缺失（`food_contact` 无 `--have` + conflict） | 0 | 2 | 是 | 同第一行 |

理由：该行只说明「BLOCKED 的 IP 侧来源」；文档侧的阻断级缺失已在下方 `缺失 / 待确认` 列表逐条标注 `阻断级`，两者是不同维度，不应因文档阻断而隐藏 IP 来源。

> 注：该条件曾一度被实现为 `ip_blocked > 0 且 blocking_missing == 0`，已按本表修正，见 §9。

**缺失项等级词与「当前状态」**

`缺失 / 待确认（按优先级）：` 每项格式：`  {序号}. {name}（{等级}，当前 {状态}）`；序号从 1 起，顺序与 `required_docs` 一致（不按等级重排）。

| 文档 `blocking` | 等级词 |
|---|---|
| `true` | `阻断级` |
| `false`（含缺省） | `可补办` |

`当前 {状态}`：`缺失`（status=missing）、`待确认`（status=unknown）。现状规则库中 `default_status=unknown` 只出现在 4 个 advisory 文档，而 advisory 不进入 `missing` 列表，因此实际只会出现 `当前 缺失`；`待确认` 分支保留但当前不可达。

实测（`office` + `medical_claim`，无 `--have`）：

```
缺失 / 待确认（按优先级）：
  1. 消费品安全合规自证（CPSA）（可补办，当前 缺失）
  2. 加州 Prop 65 警告标签或暴露评估（可补办，当前 缺失）
  3. FDA 器械分类与 510(k) / 豁免确认（阻断级，当前 缺失）
  4. FTC 健康 / 功效声明实证材料（阻断级，当前 缺失）
```

**三段（含标题）独立省略**

| 段 | 标题 | 输出条件 | 为空时表现 |
|---|---|---|---|
| 缺失列表 | `缺失 / 待确认（按优先级）：` | `missing` 非空 | 整段省略：连标题、前置空行都不输出 |
| 输入提示 | `输入提示：` | `input_warnings` 非空 | 整段省略 |
| 风险提示 | `风险提示：` | 恒输出（至少含 `global_risk_notes` 与 IP 提示） | — |

实测对照：

| 用例 | 缺失段 | 输入提示段 |
|---|---|---|
| PASS（12 份齐全 + `--trademark none` + `--patent-search-done true`） | 省略 | 省略 |
| CONDITIONAL（`office` + `food_contact`，无 `--have`，未传 trademark/patent） | 输出（1 项，`可补办`） | 输出（2 条） |
| BLOCKED（`office` + `medical_claim`，未传 trademark/patent） | 输出（4 项：2 `可补办` + 2 `阻断级`） | 输出（2 条） |

输入提示两条固定文案（仅字段缺失时出现）：`[INPUT_MISSING] trademark_status 未提供，按未做商标检索处理。`、`[INPUT_MISSING] patent_search_done 未提供，按未完成检索处理。`

## 5. 计算规则

1. 每份文档状态：命中有效 `--have` → `have`；否则取 `default_status`，再否则 `missing`。advisory 项通常因此为 `unknown`。
2. 划分集合：`real = 非 advisory`；`not_have = real 中 status != have`；`blocking_missing = real 中 blocking 且 status != have`；`advisory = advisory 文档`。
3. IP 初筛状态：
   - 商标项 = `trademark_status_map[trademark]`；未提供时按 `unknown`。备注按最终状态取：missing / unknown / have / blocked 四套文案，未提供时 unknown 文案改写为「未提供商标状态…」。
   - 外观/实用专利 = `have` 当且仅当 `patent_search_done is True`，否则 `unknown`。
   - Brand Registry：商标为 `have` → `unknown`；`blocked` → `blocked`；其余（含 missing/unknown/未提供）→ `missing`。`blocked` 布尔仅当状态为 `blocked`。
   - `ip_blocked = ip_screening 中 blocked=true 的数量`。
4. 结论优先级（互斥，自上而下）：
   - `BLOCKED`：`blocking_missing` 非空 **或** `ip_blocked > 0`。即使其他文件齐全、甚至 blocking 文档被 `--have` 命中，只要商标 `conflict` 仍 BLOCKED。
   - `CONDITIONAL`：无上述阻断，但 `not_have` 非空（含 status=unknown）。
   - `PASS`：所有 `real` 文档均为 `have`。advisory 全为 unknown 不影响。
5. 统计：`required=len(real)`；`have=len(real)-len(not_have)`；`missing=not_have 中 status=missing`；`unknown=not_have 中 status=unknown`；`blocking_missing=len(blocking_missing)`；`ip_blocked` 同上；`advisory=len(advisory)`。
6. 风险提示：类目 risk_notes → 属性 risk_notes（用户顺序）→ 平台 risk_notes（marketplace 顺序）→ `global_risk_notes` → `ip_screening.notes`，按字符串完全相等去重，保留首次出现。
7. 退出码映射：`PASS→0`、`CONDITIONAL→1`、`BLOCKED→2`；与 `--json` 无关。

判定示例（均为实跑）：

| 输入 | required/have/missing | blocking_missing / ip_blocked | status → exit |
|---|---|---|---|
| `small_appliances` + `lithium_battery`（无 `--have`） | 12 / 0 / 12 | 0 / 0 | CONDITIONAL → 1 |
| `small_appliances` + 3 属性（12 份报告全给） | 12 / 12 / 0 | 0 / 0 | PASS → 0 |
| `office` + `medical_claim` | 4 / 0 / 4 | 2 / 0 | BLOCKED → 2 |
| `office` + `food_contact` + `--trademark conflict`（4 份全给） | 4 / 4 / 0 | 0 / 2 | BLOCKED → 2 |
| `office` + `food_contact` @ tiktok（4 份全给） | 4 / 4 / 0 | 0 / 0 | PASS → 0 |


## 6. 已知行为与坑（现状）

| # | 现象 | 触发条件 | 现状行为（实测） | 建议 |
|---|---|---|---|---|
| 1 | CONDITIONAL 用 1 | 存在可补办缺失、无阻断 | exit 1；JSON `status=CONDITIONAL`；例：small_appliances + 3 属性无 `--have`，counts required=12/have=0/missing=12 | 保留（与测试 `test_03_conditional_still_exit_1` 绑定） |
| 2 | BLOCKED 用 2 | blocking 文档缺失或 IP 冲突 | exit 2；例：office+medical_claim → required=4/missing=4/blocking_missing=2；`--trademark conflict` → ip_blocked=2 | 保留 |
| 3 | 未知类目 exit 3 | `Automotive` 等映射不到 | exit 3；`--json` 时 stdout 合法 JSON，`status=INPUT_MISSING`，`missing=[]` | 保留；建议补 `missing:["category"]` |
| 4 | `--json` 错误时 stdout 是 JSON | 任意 fail | stdout JSON、stderr 人类文本；无 `--json` 时 stdout 完全为空 | 保留 |
| 5 | 错误 JSON 的 `missing` 恒空 | 03 未向 `fail()` 传 missing | 仅 message 含字段名；与 02/06/07 的契约不一致 | 建议修正 |
| 6 | 参数错误码是 3 而非 2 | 非法 `--marketplace` 等 | 自定义 parser `error_code=3`；JSON `status=INPUT_MISSING` | 保留（避免与 BLOCKED 混淆） |
| 7 | 列表模式忽略必填校验 | 同时 `--list-categories` | 缺 attr/marketplace 也 exit 0；两个 list 标志时 categories 优先 | 保留，文档需写明 |
| 8 | 平台路径/别名映射会写 stderr | source=platform_path/alias | `[WARN] …` 写 stderr，stdout 干净；exit 不变 | 保留 |
| 9 | 全角逗号不拆属性 | `--attr "a，b"` | 整串当作一个属性 → 未知属性 exit 3；message 原样回显 | 建议修正或文档强调 |
| 10 | `--have` 内含逗号会被拆 | 报告名含 `,` | 被拆成多条，可能漏匹配 | 建议提供 `--have-file` 或转义 |
| 11 | pending 不计数但仍报「缺失」 | `--have "CPSC（办理中）"` | 该条写入 input_warnings；状态仍 missing；exit 1 | 保留，语义符合 `_meta.have_rule` |
| 12 | `both` 平台文档翻倍 | `--marketplace both` | required 增加两份平台文档；advisory=4；marketplace 字段为 `amazon_us+tiktok_us` | 保留 |
| 13 | `default` 永远报错 | 传 `--category default` | compliance_key 为 null → exit 3 | 保留（映射表注释即此意） |
| 14 | 规则文件 BOM 不兼容 | rules.json 带 BOM | 按代码推断 `utf-8` 严格读取 → JSONDecodeError → exit 3（未实测）；map 用 `utf-8-sig` 不受影响 | 建议统一 `utf-8-sig` |
| 15 | 状态名是 PASS 不是 APPROVED | 成功 | JSON/文本均写 `PASS`；退出码 0 | 文档需注明等价关系 |
| 16 | 重复属性会重复标签 | `--attr lithium_battery --attr lithium_battery` | 文档按 id 合并；`generated_for.attributes` 与 labels 出现重复项 | 建议去重 |
| 17 | `--list-categories` 不列 `default` | 直接调用 | 只列 17 个可映射键（映射到 16 个合规类目，`electronics` 与 `electronics_accessories` 共用）；别名单独一行 | 保留 |
| 18 | `rules_direct` 分支不可达 | 现有规则库键均被覆盖 | 走 alias 或 mapping；无法实测触发 | 重写时可删除或保留兼容 |
| 19 | 映射表注释与实现矛盾 | 阅读 `_meta.note` | 注释称 platform_paths「仅用于展示，不参与计算」，但 03 实际按最长路径前缀解析（实测 Blenders 路径 → small_appliances） | 建议修正注释，重写以代码为准 |
| 20 | `us_fees_key` 对 03 无意义 | 任意输入 | 03 只读 `label/compliance_key/platform_paths`，`us_fees_key` 完全不参与 | 保留字段供 02 使用 |

## 7. 对拍基准（必须可复现）

统一前缀（PowerShell 5，逐条执行，勿用 `&&`）：

```powershell
$env:PYTHONIOENCODING='utf-8'
python Agents/03_Compliance_Agent/scripts/compliance_gate.py ...
```

1. **Amazon 平台路径成功解析（映射到 small_appliances，CONDITIONAL）**

```powershell
python Agents/03_Compliance_Agent/scripts/compliance_gate.py --category "Home & Kitchen > Kitchen & Dining > Small Appliances > Blenders" --attr lithium_battery,food_contact,mains_power --marketplace amazon_us --json
```

期望：exit 1；`status=CONDITIONAL`；`generated_for.category=small_appliances`、`category_key=small_appliances`、`category_source=platform_path`；`counts.required=12`、`have=0`、`missing=12`、`unknown=0`、`blocking_missing=0`、`advisory=2`；stderr 有平台路径 WARN。

2. **同类目全齐（PASS，exit 0）**

```powershell
python Agents/03_Compliance_Agent/scripts/compliance_gate.py --category small_appliances --attr lithium_battery,food_contact,mains_power --marketplace amazon_us --have "UL 认证（UL 982）","CPSC 消费品安全自证","FCC Part 15 Subpart B SDoC","加州 Prop 65 警告标签","UN38.3 Test Summary","MSDS 安全数据表","UN3481 Class 9 电池标签","UL 2054 电池组测试","FDA 食品接触符合性声明","食品接触迁移测试报告","NEMA 5-15P 插头合规","DOE Level VI 能效报告" --json
```

期望：exit 0；`status=PASS`；`counts.required=12`、`have=12`、`missing=0`、`unknown=0`、`advisory=2`；`missing=[]`。

3. **未知类目（exit 3）**

```powershell
python Agents/03_Compliance_Agent/scripts/compliance_gate.py --category Automotive --attr lithium_battery --marketplace amazon_us --json
```

期望：exit 3；stdout 合法 JSON：`status=INPUT_MISSING`、`missing=[]`、message 以「无法识别的类目：Automotive」开头并列出 17 个可选键；stderr `[INPUT_MISSING]` 同文案。

4. **CONDITIONAL 一例（exit 1）**

```powershell
python Agents/03_Compliance_Agent/scripts/compliance_gate.py --category small_appliances --attr lithium_battery --marketplace amazon_us --json
```

期望：exit 1；`status=CONDITIONAL`；required 至少包含 `ul_nrtl/cpsc_general/fcc_part15b/prop65/un38_3/sds_lithium/battery_transport_label/battery_safety_test`；`blocking_missing=0`。

5. **BLOCKED：阻断级文档缺失（exit 2）**

```powershell
python Agents/03_Compliance_Agent/scripts/compliance_gate.py --category office --attr medical_claim --marketplace amazon_us --json
```

期望：exit 2；`status=BLOCKED`；`counts.required=4`、`missing=4`、`blocking_missing=2`、`ip_blocked=0`；missing 含 `fda_device_clearance`、`ftc_health_substantiation`。

6. **BLOCKED：商标冲突（exit 2，文件全齐也会阻断）**

```powershell
python Agents/03_Compliance_Agent/scripts/compliance_gate.py --category office --attr food_contact --marketplace amazon_us --trademark conflict --have "CPSC 消费品安全自证","加州 Prop 65 警告标签","FDA 食品接触符合性声明","食品接触迁移测试报告" --json
```

期望：exit 2；`status=BLOCKED`；`counts.have=4`、`missing=0`、`blocking_missing=0`、`ip_blocked=2`（us_trademark 与 amazon_brand_registry 均为 blocked）。

7. **TikTok PASS（exit 0，advisory 仍 unknown）**

```powershell
python Agents/03_Compliance_Agent/scripts/compliance_gate.py --category office --attr food_contact --marketplace tiktok_us --have "CPSC 消费品安全自证","加州 Prop 65 警告标签","FDA 食品接触符合性声明","食品接触迁移测试报告" --json
```

期望：exit 0；`status=PASS`；`counts.required=4`、`have=4`、`advisory=2`；`advisory_items` 两项 status=unknown。

8. **列表与参数错误**

```powershell
python Agents/03_Compliance_Agent/scripts/compliance_gate.py --list-categories
python Agents/03_Compliance_Agent/scripts/compliance_gate.py --category small_appliances --marketplace amazon_us --json
python Agents/03_Compliance_Agent/scripts/compliance_gate.py --category small_appliances --attr bogus_attr --marketplace amazon_us --json
python Agents/03_Compliance_Agent/scripts/compliance_gate.py --category small_appliances --attr lithium_battery --json
python Agents/03_Compliance_Agent/scripts/compliance_gate.py --category small_appliances --attr lithium_battery --marketplace bogus --json
```

期望：`--list-categories` exit 0，输出 17 个可映射键（表头 + 别名行 + 路径提示）；其余四项均 exit 3，`--json` 时 stdout 为合法 JSON。

## 8. 未完整刻画 / 待确认

- **并列前缀歧义**：代码在「两个不同键的最长前缀等长」时放弃解析，但当前 `category_map.json` 无法构造出该输入，实际报错文案与退出码未实测（按逻辑应为 exit 3）。
- **`rules_direct` 分支**：现有 16 个规则类目全部被显式键/别名/路径覆盖，无法实测其输出（`category_key` 与 `category` 相同、`category_source=rules_direct`）。
- **rules.json 带 BOM 的实测**：仅按 `encoding="utf-8"` 推断为失败，未构造文件验证。
- **`--list-attributes` 的完整输出**：未逐行核对 13 条标记文案，仅按代码确认格式。
- **`--have` 归一化对中文标点/全角字符的边界**：只验证了常见英文缩写与中文报告名，未穷举。
- **重复属性、`--have` 重复条目的最终字段顺序**：未单独实测。
- **03 的失败 JSON 是否要求 `missing` 语义**：现状恒为 `[]`，重写时需产品确认是否补字段。

## 9. 探测发现的实现偏差（已裁决：以旧行为为准）

本轮黑盒探测（2026-10-30，`office` + `medical_claim` + `--trademark conflict`）发现新实现一度多加了 `blocking_missing == 0` 守卫。**已确认按旧行为修正**：删除该守卫，`ip_blocked > 0` 即输出「阻断来源」行，与 `blocking_missing` 无关（即 §4.5 表格第三行）。

| 项 | 旧行为（基准） | 曾出现的偏差 | 现状 |
|---|---|---|---|
| 「阻断来源」行触发条件 | `ip_blocked > 0` 即输出 | 额外要求 `blocking_missing == 0`，两者同时存在时不输出 | **已对齐旧行为** |

- 实现位置：`Agents/03_Compliance_Agent/scripts/compliance_gate.py` 的 `render_human()`（统计行之后的分支，条件为 `if counts["ip_blocked"]:`）。
- 测试位置：`tests/test_cli.py::ComplianceGateTests::test_blocking_source_line_when_both_causes`（`office` + `medical_claim` + `--trademark conflict`，断言 `阻断级缺失 2` 且 stdout 含「阻断来源：IP 初筛识别到 2 项冲突」）。
- 影响面：仅人类可读输出；JSON 与退出码（2）不受影响。
