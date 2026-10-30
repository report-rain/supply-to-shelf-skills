# 01 Selection Agent — 规格冻结（clean-room 重写基线）

> 本文只描述**可观察行为**，不复制实现。所有数值来自 2026-10-30 在 Windows / Python 3.12.0 的实跑，或代码中的明确常量。
> 覆盖脚本：`Agents/01_Selection_Agent/scripts/market_metrics.py`、`normalize_export.py`、`opportunity_score.py`。

## 1. 范围与脚本

| 脚本 | 一句话职责 | 依赖 |
|---|---|---|
| `normalize_export.py` | 把 Amazon 类目导出 CSV 认列、转数字、去重后写成 `normalized.json`；不做销量推算、不补缺失值 | Python 标准库 `csv/json`；UTF-8 BOM 容忍；无项目内配置 |
| `market_metrics.py` | 读 `normalized.json`（`{"items":[...]}` 或裸数组），输出市场容量、品牌/卖家集中度、评论门槛、等宽价格带与波谷、可选属性交叉表、Top N | 仅标准库；无外部配置；运行期全局常量 `TROUGH_THRESHOLD`（默认 15.0） |
| `opportunity_score.py` | 读类目 CSV，用固定五维权重（需求 30 / 竞争 25 / 利润 25 / 合规 10 / 供给 10）给每个 ASIN 打分并汇总 | 仅标准库；无外部配置；`compliance_risk` / `supply_feasibility` 为可选列 |

管道关系：`normalize_export.py` → `normalized.json` → `market_metrics.py`；`opportunity_score.py` 直接吃原始 CSV，与 normalized.json 无耦合。三个脚本都只写 UTF-8 文本；`market_metrics.py` 和 `opportunity_score.py` 启动时尝试把 stdout 重设为 UTF-8（失败则静默忽略）。

## 2. CLI 契约

三个脚本都是独立入口，没有子命令。下列表穷举 argparse 参数；「必填」指运行期是否必须提供，而非 argparse 的 `required`。

### 2.1 `normalize_export.py`

| 参数名 | 类型 | 必填 | 默认值 | 取值范围/枚举 | 说明 |
|---|---|---|---|---|---|
| `input`（位置参数） | str | 是 | — | 存在的 CSV 路径 | 类目导出 CSV |
| `--output` | str | 否 | `<输入文件去扩展名>.normalized.json` | 可写路径 | 输出 JSON 路径；父目录必须已存在 |
| `--attributes` | str | 否 | `""` | 逗号分隔任意非空标签 | 给**所有行**统一写入同一个 `attributes` 数组；空串则不写 |
| `--severe-revenue-gap` | float | 否 | `0.10` | 任意 float（不校验负值/上限） | `monthly_revenue` 与 `price×monthly_sales` 相对偏离超过该比例时追加 warning |
| `--json` | flag | 否 | false | — | 只改变 **stdout**：打印 `{output,item_count,warnings}` 摘要；文件始终照写 |

互斥/冲突：无 argparse 级互斥。`--attributes` 中的标签会原样（trim 后）重复写入每一行；同一标签重复出现不会去重。

### 2.2 `market_metrics.py`

| 参数名 | 类型 | 必填 | 默认值 | 取值范围/枚举 | 说明 |
|---|---|---|---|---|---|
| `input`（位置参数） | str | 是 | — | 存在的 JSON 路径 | `{"items":[...]}` 或裸数组 |
| `--bins` | int | 否 | `10` | 运行期要求 ≥1 | 等宽价格带档数 |
| `--top` | int | 否 | `10` | 运行期要求 ≥1 | Top 商品条数；超过样本数则输出全部 |
| `--trough-threshold` | float | 否 | `15.0` | 任意 float（不校验负值） | 波谷判定：相邻价格带月销量环比跌幅 ≥ 该百分比（单位 %） |
| `--config-fields` | str | 否 | `None` | 逗号分隔，当前仅允许 `attributes` | 指定后要求至少一条商品有 `attributes`，否则报错 |
| `--format` | str | 否 | `md` | `md` / `json` / `both` | `both` = 先 Markdown，再分隔线 `--- JSON ---`，再 JSON |
| `--json` | flag | 否 | false | — | 等价于 `--format json`，且**覆盖**已给的 `--format` |

互斥/冲突：
- `--json` 与 `--format` 同时给时，`--json` 生效（`--format both` 也会被降为纯 JSON）。
- `--config-fields` 中出现 `attributes` 以外的任何 token → 输入错误退出 2；空 token（连续逗号、首尾逗号）被忽略。
- `--bins`/`--top` ≤0 → 输入错误退出 2；`--trough-threshold` 不校验（负值会让几乎所有下降带入选）。

### 2.3 `opportunity_score.py`

| 参数名 | 类型 | 必填 | 默认值 | 取值范围/枚举 | 说明 |
|---|---|---|---|---|---|
| `--file` | str | 是（运行期） | `None` | 存在的 CSV 路径 | 类目导出 CSV；argparse 未设 required |
| `--factory-cost-usd` | float | 是（运行期） | `None` | ≥0（负值报错） | 工厂成本 USD/件 |
| `--target-price` | float | 是（运行期） | `None` | >0（0/负值报错） | 目标零售价 USD |
| `--platform-fee-pct` | float | 否 | `15.0` | 任意 float（不校验负值/上限） | referral 估算百分比，用于利润维度 |
| `--fba-estimate` | float | 否 | `4.75` | 任意 float（不校验负值） | FBA 费估算 USD/件 |
| `--json` | flag | 否 | false | — | 输出 JSON 而非 Markdown |

互斥/冲突：无互斥参数。缺 `--file` / `--factory-cost-usd` / `--target-price` 时**一次性**列出全部缺失项后退出 2；`--target-price ≤0`、`--factory-cost-usd <0` 各自单独报错退出 2。

### 2.4 解析器与帮助行为

| 行为 | 现状 |
|---|---|
| `--help` / `-h` | 打印 argparse 帮助后退出 **0** |
| 未知参数 | argparse `unrecognized arguments` → 退出 **2**，信息为 stderr |
| `normalize_export.py` 缺位置参数 | argparse `the following arguments are required: input` → 退出 **2** |
| `market_metrics.py` 缺位置参数 | 同上，退出 **2** |
| `--bins` / `--top` 非整数 | argparse 类型错误 → 退出 **2** |
| `--severe-revenue-gap` 非 float | argparse 类型错误 → 退出 **2** |
| `--format` 非法枚举 | argparse `invalid choice` → 退出 **2** |
| 多余位置参数 | argparse 拒绝 → 退出 **2** |
| 参数错误时的 `--json` | 01 三个脚本都**不会**输出 JSON（仅 02 的 `JsonArgumentParser` 会） |

注意：`opportunity_score.py` 的三个业务必填参数在 argparse 层全是可选，所以 `--help` 显示为可选；缺失检查发生在主流程，输出是自定义中文提示而非 argparse 的 `required` 文案。

## 3. 输入契约

### 3.1 通用编码与数值清洗

- 三个脚本的 CSV/JSON 都以 `utf-8-sig` 打开，**容忍 UTF-8 BOM**；无 BOM 的 UTF-8 正常。
- CSV 表头与单元格做 `strip()`；`opportunity_score.py` 与 `landed_cost.py` 还会重建表头名（去空白）。
- 数值清洗：去掉英文逗号 `,`、美元符号 `$`（`normalize_export.py` 额外去掉 `%`），再 `strip()`；`"$1,200.50"` → `1200.5`。
- `normalize_export.py` 的占位空值集合：`""`、`"-"`、`"—"`、`"N/A"`、`"nan"`（大小写敏感，仅这些字面量）→ 视为缺值并退出。
- `market_metrics.py` 视 `None` / `""` 为缺值；其它字符串按上述规则转 float，无法转则记为「非数字」。

### 3.2 `normalize_export.py` 输入 CSV

必需列（契约字段，缺任一列即退出 1）：

| 字段 | 语义 | 单位/类型 | 允许缺失/别名 |
|---|---|---|---|
| `asin` | 商品 ASIN | str | 别名 `ASIN`；行内为空 → 退出 1 |
| `title` | 标题 | str | 别名 `标题`、`商品标题`；可为空串 |
| `brand` | 品牌 | str | 别名 `品牌`；可为空串 |
| `seller` | 卖家 | str | 别名 `卖家`、`店铺`；可为空串 |
| `price` | 售价 | USD，float | 别名 `价格`、`售价`、`成交价` |
| `monthly_sales` | 月销量 | 件，int | 别名 `月销量`、`月销` |
| `monthly_revenue` | 月销售额 | USD，int | 别名 `月销售额`、`月营收` |
| `reviews` | 累计评论数 | 条，int | 别名 `评论数`、`评价数` |
| `rating` | 评分 | 0–5，float | 别名 `评分`、`星级` |
| `bsr` | 类目排名 | int | 别名 `bsr`、`BSR`、`类目排名` |
| `fulfillment` | 配送方式 | str（FBA/FBM 等） | 别名 `配送方式`、`发货方式`；可为空串 |

列名解析规则：候选别名逐个小写、`strip()` 后与表头比较；命中第一个候选即绑定。表头中重复同名时使用**第一个**出现者。大小写不敏感。
行级规则：
- `asin` 为空 → 立即退出 1（不继续后续行）。
- 同一 ASIN 再次出现 → 追加 warning「第 N 行 ASIN X 重复，已保留首次出现」，跳过该行，不报错。
- 数字列按 3.1 清洗；`monthly_sales`/`monthly_revenue`/`reviews`/`bsr` 用 `int(float(...))`，**截断小数**（`200.9 → 200`）；其余用 float。
- `monthly_revenue` 偏离 `price×monthly_sales` 超过 `--severe-revenue-gap`（严格 `>`，且 `price×sales ≠ 0`）→ 追加 warning，不中断。
- 表头存在但无数据行 → 退出 1；文件为空 / 无表头 → 退出 1。

### 3.3 `market_metrics.py` 输入 JSON

顶层：对象且含 `items`，或直接是数组；`items` 必须为非空数组，否则退出 2。

每项必须是对象，且包含 11 个必填字段：

| 字段 | 语义 | 类型/单位 | 缺失/替代 |
|---|---|---|---|
| `asin`,`title`,`brand`,`seller`,`fulfillment` | 标识与配送 | str | 不可缺；缺失或空串均报错 |
| `price` | 售价 | USD | 不可缺；可为带 `$`/`,` 的字符串 |
| `monthly_sales` | 月销量 | 件 | 不可缺 |
| `monthly_revenue` | 月销售额 | USD | 不可缺 |
| `reviews` | 评论数 | 条 | 不可缺；输出时 `int()` 截断 |
| `rating` | 评分 | 0–5 | 不可缺 |
| `bsr` | 类目排名 | int | 不可缺；输出时 `int()` 截断 |
| `attributes`（可选） | 属性标签 | 数组、元组，或逗号/竖线/分号分隔字符串 | 仅 `--config-fields attributes` 时需要；每个值 trim，空值丢弃 |

`attributes` 字符串分隔符：`|` 与 `;` 先替换为 `,`，再按 `,` 切分；数组中空串被丢弃；解析结果为空视为无属性。
校验阶段会聚合所有行错误再退出：非对象行记「第 N 条不是对象」；缺字段/非数字记「ASIN 或 #N 缺少/非法字段：...」（字段名排序去重）。

### 3.4 `opportunity_score.py` 输入 CSV

- 必需列：`asin`、`price`、`monthly_sales`、`reviews`、`rating`、`seller`（**不支持中文别名**，列名精确匹配，比较前已 strip）。
- 可选列：`compliance_risk`（0–5，风险越高越差；缺省 2.0）、`supply_feasibility`（0–5，越高越可行；缺省 3.0）。
- 其余列忽略（`title` 若存在则写入输出，否则空串）。
- 完全空白行（所有单元格为空）跳过；行内数字清洗同 3.1。
- 行级必填：`asin`、`seller` 不能为空；数值为空或非数字 → 记错误。**所有行错误聚合后**一次性退出 2。
- 表头存在但无数据行 → 退出 2；文件不存在 → 退出 2。
- 若 `compliance_risk` / `supply_feasibility` 列存在但某行单元格为空，该行按 2.0 / 3.0 计并在 `defaults` 里追加提示。

### 3.5 输入能力矩阵（三个脚本互不通用）

| 输入 | normalize | market | opportunity |
|---|---|---|---|
| CSV（英文契约列名） | ✅ 必需 | ❌ | ✅ 必需 |
| CSV（中文/别名表头） | ✅ | ❌ | ❌ |
| `{"items":[...]}` JSON | ❌ | ✅ | ❌ |
| 裸数组 JSON | ❌ | ✅ | ❌ |
| 数值含 `$`/`,` | ✅ | ✅ | ✅ |
| 数值含 `%` | ✅ 清洗后按数字 | ✅ 仅数字字段 | ✅ 仅数字字段 |
| `attributes` 数组/分隔字符串 | 由 `--attributes` 统一生成 | ✅ 读取 | ❌ 忽略 |
| `compliance_risk`/`supply_feasibility` | ❌ 忽略 | ❌ 忽略 | ✅ 可选 |
| UTF-8 BOM | ✅ | ✅ | ✅ |
| 重复 ASIN | 去重并告警 | 照算 | 照算 |
| 全空行 | 未跳过（见 §6） | N/A | 跳过 |

## 4. 输出契约

### 4.1 `normalize_export.py` 成功输出

写文件（UTF-8，无 BOM，2 空格缩进）结构：

```
{
  "meta": {"source_file": str(输入文件名，不含路径), "item_count": int, "currency": "USD", "note": str},
  "items": [ {asin,title,brand,seller,fulfillment: str;
              price,rating: float; monthly_sales,monthly_revenue,reviews,bsr: int;
              attributes?: [str]} ],
  "warnings": [str]
}
```

字段顺序（实测）：先 5 个字符串字段 `asin,title,brand,seller,fulfillment`，再 6 个数值字段 `monthly_sales,monthly_revenue,reviews,bsr,rating,price`，最后可选 `attributes`。数值不做 `$`/千分位格式化，JSON 原值输出；`meta.note` 为固定文案「由 normalize_export.py 转换；销量与销售额为导出/第三方估算，不构成事实保证」。
stdout：默认 `✅ 已写出 <dest>（N 个 ASIN）` + 每条 warning（`  ⚠️  ...`）+ 一行「下一步：python scripts/market_metrics.py <dest> --bins 10 --top 10」；`--json` 时只打印 `{output,item_count,warnings}`。

### 4.2 `market_metrics.py` 成功 JSON

```
{
  "meta": {generated_by:"market_metrics.py", currency:"USD", bins:int,
           trough_threshold_pct:float, trough_candidates_total:int, trough_bands_shown:int},
  "market": {items:int, total_monthly_sales:num(2), total_monthly_revenue:num(2),
             avg_price:num(2), median_price:num(2), min_price:num(2), max_price:num(2)},
  "brand_concentration": <concentration>,
  "seller_concentration": <concentration>,
  "review_thresholds": [{bucket:str, items:int, items_share_pct:num(1),
                          monthly_sales:num(2), sales_share_pct:num(1)}],
  "price_bands": [{index:int, lower:num(2), upper:num(2), label:str, items:int,
                   monthly_sales:num(2), monthly_revenue:num(2), sales_share_pct:num(1)}],
  "troughs": [{band_index:int, label:str, prev_monthly_sales:num(2),
               monthly_sales:num(2), drop_pct:num(1), items:int}],
  "top_products": [{asin,title,brand,seller,fulfillment:str, price:num(2),
                     monthly_sales:num(2), monthly_revenue:num(2), reviews:int,
                     rating:num(2), bsr:int}],
  "attribute_cross_table": null | [{attribute:str, items:int, monthly_sales:num(2),
                     monthly_revenue:num(2), avg_price:num(2), sales_share_pct:num(1)}]
}
```

`<concentration>` = `{entity_count:int, cr3_pct:num(2), cr10_pct:num(2), hhi:num(1),
cr3_meaningful:bool, cr10_meaningful:bool, top:[{name, monthly_sales:num(2),
sales_share_pct:num(2), monthly_revenue:num(2), items:int}]}`；`top` 含全部主体，按销量降序，人类报告只取前 10。
`review_thresholds` 固定四档顺序：`<50`、`50–99`、`100–499`、`≥500`。
`price_bands` 的 `label` 为 `$lower–$upper`（两位小数 + 千分位）；**唯一例外**：全样本同价时只有 1 档，`label` 退化为单值 `$price`（如 `$29.99`）。

人类可读（Markdown）结构要点：
1. 标题 `# 美国站类目市场测算`；头部列出样本数、金额口径、集中度口径（HHI 0–10,000）。
2. `## 1. 市场容量`：两列表（指标/数值），总月销量与销售额、均价（简单平均）、中位价、价格区间。
3. `## 2./3. 品牌/卖家集中度`：CR3、CR10、HHI、主体数；主体数 ≤3/≤10 时追加 ⚠️ 无意义提示；主体表前 10，列为主体/月销量/销量份额/月销售额/商品数。
4. `## 4. 评论门槛分布`：四档，列含商品数、商品数占比、月销量、销量占比。
5. `## 5. 价格带分布（等宽 N 档）`：`#`、价格带、商品数、月销量、销量占比、月销售额。
6. `## 6. 价格带波谷候选`：跌幅 ≥ 阈值且最多 5 带；无候选时输出一句「梯度相对平滑」。
7. 可选 `## 7. 属性交叉表`（仅 `--config-fields attributes`）。
8. 最后 `## N. Top N 商品` 表：ASIN/标题/价格/月销量/评论/评分/BSR/配送；标题超过 46 字符截为前 43 + `...`。
9. 末尾脚注：数据为第三方估算，价格带是观察结果不是定价指令。

### 4.3 `opportunity_score.py` 成功 JSON

```
{
 "meta": {generated_by:"opportunity_score.py", currency:"USD",
          weights:{demand:30,competition:25,profit:25,compliance:10,supply:10},
          factory_cost_usd:num(2), target_price_usd:num(2), platform_fee_pct:float,
          fba_estimate_usd:float, profit_usd:num(2), profit_margin_pct:num(1),
          rows:int, columns:[str]},
 "defaults": [str],
 "rows": [{asin,title,seller:str, price:num(2), monthly_sales:num(0), reviews:int,
           rating:num(2), compliance_risk:num(2), supply_feasibility:num(2),
           score:num(1), dimensions:{demand,competition,profit,compliance,supply:num(1)},
           verdict:"Go"|"Watch"|"No-Go"}],
 "summary": {verdict_counts:{Go:int,Watch:int,"No-Go":int},
             entry_price_band:{low:num(2),high:num(2),median:num(2),basis:str},
             top3:[{asin,title,price:num(2),score:num(1),verdict:str}],
             dimension_averages:{...:num(1)},
             triple_veto_reasons:[str]}
}
```

`rows` 排序：`score` 降序 → `monthly_sales` 降序 → `asin` 升序。
人类可读结构：`# 美国站选品机会评分`；`## 0. 权重与口径`（目标价、工厂成本、referral、FBA、净利率、verdict 阈值、缺列提示）；`## 1. 逐 ASIN 评分`（12 列：ASIN/标题/价格/月销/评论/评分/需求/竞争/利润/合规/供给/结论，标题超 34 字符截前 31+`...`）；`## 2. 汇总`（结论分布、建议切入价格带、Top3、三条否决理由有序列表）；`## 3. 评分口径`（五维文字说明 + 脚注）。

> **表格列语义（已探测，probe 2026-10-30）**：数据行的「评分」列实际输出的是**五维总分**（`**80.5**` 加粗），原始 `rating` 不入表；表头仍保留 12 列、数据行也是 12 个值，因此列名与内容存在一处错位。新实现按此逐字复刻，不做「修正」。


### 4.4 失败契约与退出码（现状）

三个脚本都**没有**实现统一的 `--json` 错误 JSON；`--json` 只影响成功路径。失败现状：

| 脚本 | 错误信息去向 | 格式 | 退出码 |
|---|---|---|---|
| `normalize_export.py` | **stderr**（`sys.exit("字符串")` 的隐式行为） | 纯文本 `[INPUT_MISSING] ...`，无 JSON | ~~1~~ → **2**（旧实现 1；本批 #1 已实施，见 `99_gap_and_decisions.md`） |
| `market_metrics.py` | **stdout** | 纯文本 `[INPUT_MISSING] ...` | **2** |
| `opportunity_score.py` | **stdout** | 纯文本 `[INPUT_MISSING] ...` | **2** |
| `market_metrics.py` 未捕获异常（如除零） | stderr | Python traceback | **1** |

> 本批有意差异（已实施）：#1 normalize 输入错误 1→2；#4 行级脏数据必须报「第 N 行 + 列名」并 exit 2；#5 NaN/Inf 显式校验、不进入计算。消息文案与去向保持不变，只改退出码与校验严格度。


典型输入错误场景与退出码：

| 场景 | 脚本 | 退出码 | 观察 |
|---|---|---|---|
| 输入文件不存在 | normalize | **2** | stderr `[INPUT_MISSING] 找不到文件：...` |
| 输入文件不存在 | market / opportunity | 2 | stdout 提示 + 用法建议 |
| 文件为空/无表头 | normalize | **2** | stderr `[INPUT_MISSING] CSV 没有表头` |
| 表头存在但无数据 | normalize | **2** | stderr `CSV 没有数据行` |
| 表头存在但无数据 | opportunity | 2 | stdout `CSV 没有数据行。` |
| 缺必需列 | normalize | **2** | stderr 列出缺列与现有表头 |
| 缺必需列 | opportunity | 2 | stdout 列出缺列 + 可选列说明 |
| 单行脏数据 | normalize | **2** | stderr `第 N 行 <列名>='原值' 不是数字`（#4） |
| NaN/Inf 数值 | normalize | **2** | stderr `第 N 行缺少 <列名>`（NaN 视作缺值）/ `... 不是有限数值（NaN/Inf）`（#5） |
| 缺必填字段/非数字 | market | 2 | stdout 聚合全部行错误后退出 |
| `--bins`/`--top` <1、`--config-fields` 未知、缺 attributes | market | 2 | stdout |
| 缺三个运行期参数 | opportunity | 2 | stdout 一次列全 |
| `--target-price ≤0` / `--factory-cost-usd <0` | opportunity | 2 | stdout |
| JSON 解析失败、items 缺失/为空 | market | 2 | stdout |
| 全样本总月销量=0 且所有价格相同 | market | 1 | `ZeroDivisionError` traceback（见 §6，本批刻意未改） |

### 4.5 输出路由与编码

| 维度 | normalize | market | opportunity |
|---|---|---|---|
| 默认 stdout | 人类摘要 + 下一步命令 | Markdown | Markdown |
| `--json` stdout | 摘要 JSON | 完整结果 JSON | 完整结果 JSON |
| `--format both` | 不支持 | MD + `--- JSON ---` + JSON | 不支持 |
| 文件落盘 | 始终写 `normalized.json` | 不写文件 | 不写文件 |
| 错误去向 | stderr | stdout | stdout |
| 错误时是否仍落盘 | 否（写文件在校验之后） | — | — |
| 控制台编码 | 尝试 `sys.stdout.reconfigure(utf-8)` | 同左 | 同左 |
| JSON 缩进 | 2 空格 | 2 空格（`--format json`/`--json`） | 2 空格 |

`--format both` 的分隔行是固定字面量 `--- JSON ---`（前后各一空行）；机器解析时应以该行切分，而不是搜索第一个 `{`。

## 5. 计算规则

### 5.1 `normalize_export.py`

- 数字转换：清洗后 `float`；4 个整数字段 `int(float(x))`（向零截断，非四舍五入）。
- 偏离告警：`expect = price × monthly_sales`；当 `expect ≠ 0` 且 `|monthly_revenue − expect| / expect > severe_revenue_gap` 时告警。`expect = 0` 时跳过。
- 去重：以首次出现的 ASIN 为准；后续重复行整行丢弃（不参与任何输出）。
- `meta.item_count` = 去重后条目数；`meta.source_file` 只写文件名。
- 输出路径：给了 `--output` 用它；否则 `Path(input).with_suffix(".normalized.json")`（会替换最后一个扩展名，如 `a.csv` → `a.normalized.json`）。

### 5.2 `market_metrics.py`

定义：样本行 `r`；`S = Σ monthly_sales`；`R = Σ monthly_revenue`；`P = [price]`。

- 市场容量：`items = n`；`total_monthly_sales = round(S,2)`；`total_monthly_revenue = round(R,2)`；均价 = `round(mean(P),2)`（简单算术平均，非加权）；中位价 = `round(median(P),2)`；最小/最大价 = `round(min/max,2)`。
- 集中度（品牌、卖家各算一次）：按实体聚合 `sales`、`revenue`、`count`；按 `sales` 降序；份额 `share_i = sales_i / S × 100`（`S=0` 时为 0）；`CR3 = Σ 前3 share`、`CR10 = Σ 前10 share`、`HHI = Σ share_i²`（百分数平方，范围 0–10,000）；`entity_count` = 主体数；`cr3_meaningful = entity_count > 3`，`cr10_meaningful = entity_count > 10`；`hhi` 保留 1 位，其余保留 2 位。
- 评论门槛：四档用 `reviews` 判定：`<50`、`50≤x<100`、`100≤x<500`、`≥500`；`items_share_pct = round(该档商品数/n×100,1)`；`sales_share_pct = round(该档销量/S×100,1)`，`S=0` 时 0.0。
- 价格带（等宽）：
  - 若 `max(P) == min(P)`：只输出 1 档，`lower=upper=该价`，全部商品入档；**该分支对 `sales_share_pct` 未做 `S=0` 保护**（见 §6）。
  - 否则 `width = (max−min)/bins`；第 i 档（i=0..bins−1）`lower = min+i×width`，`upper = min+(i+1)×width`；非末档取 `lower ≤ price < upper`，末档取 `lower ≤ price ≤ max`；输出 `lower/upper` 各 `round(,2)`，`label` 用**未取整**的边界格式化。
  - 月度汇总与 `sales_share_pct` 同 §5.2 口径，`S=0` 时 0.0。
- 波谷：仅比较相邻档（i≥1）。若 `prev ≤ 0` 或 `cur ≥ prev` 跳过；否则 `drop = (prev−cur)/prev×100`；`drop ≥ threshold` 入选。候选按 `drop` 降序取前 5，再按 `band_index` 升序输出；`trough_candidates_total` = 入选前总数（可 >5），`trough_bands_shown` = 实际输出数。
- 属性交叉表：仅统计有属性的行；每个不同属性值聚合；同一行同一属性值只计一次（`set(values)`）；`items` 为该属性值覆盖的商品数；`avg_price = price_sum / items`（按商品计，不按销量加权）；按 `monthly_sales` 降序；`sales_share_pct` 分母为**全样本** S。
- Top 商品：按 `monthly_sales` 降序取前 `top`；`reviews`/`bsr` 用 `int`（截断），`rating/price/sales/revenue` 保留 2 位。
- 缺失/边界：总销量为 0 时除 `price_bands` 同价分支外均有保护；负数价格/销量不校验；重复 ASIN 不去重。

### 5.3 `opportunity_score.py`

五维分数均为 0–100，`clamp(x)=max(0,min(1,x))`。

- 需求（权重 30）：`sales_comp = clamp(monthly_sales / 2000)`；`momentum = monthly_sales / max(reviews, 1)`；`momentum_comp = clamp(momentum / 0.5)`；`demand = 100 × (0.60×sales_comp + 0.40×momentum_comp)`。
- 竞争（权重 25，分数越高越好切入）：`review_comp = clamp(1 − reviews/1000) × 100`；`top_seller_share = 最大卖家月销量 / 总月销量`（总销量为 0 时 0）；`seller_comp = clamp(1 − top_seller_share/0.60) × 100`；`rating_comp = clamp((4.80 − rating)/0.80) × 100`；`competition = 0.50×review_comp + 0.25×seller_comp + 0.25×rating_comp`。
- 利润（权重 25，所有 ASIN 共用）：`referral = target_price × platform_fee_pct/100`；`profit_usd = target_price − factory_cost − referral − fba_estimate`；`margin_pct = profit_usd / target_price × 100`（目标价为 0 时 −100，但入口已拒绝 ≤0）；`profit_score = clamp(margin_pct/30) × 100`（净利率 ≥30% 满分）。
- 合规（权重 10）：`clamp((5 − compliance_risk)/5) × 100`。
- 供给（权重 10）：`clamp(supply_feasibility/5) × 100`。
- 总分：`total = (30×demand + 25×competition + 25×profit + 10×compliance + 10×supply) / 100`，范围 0–100，输出 `round(,1)`。
- verdict：`≥75 Go`；`60–74.x Watch`；`<60 No-Go`。判定基于**未取整**总分，输出分数取 1 位小数（可能出现 74.95 显示 75.0 但 verdict Watch 的边界现象，未实测）。
- 行内字段取整：`price/rating/compliance_risk/supply_feasibility` 2 位，`monthly_sales` 0 位，`reviews` `int()` 截断，五维与总分 1 位。
- 汇总：`verdict_counts` 直接计数；`dimension_averages` 为**各行已取整维度值**的算术平均再取 1 位；三条否决理由 = 平均分最低的 3 个维度（升序；同分按 dict 插入顺序 demand→competition→profit→compliance→supply 稳定排序）。
- 切入价格带：候选集 = 有 Go 则仅 Go 行，否则有 Watch 则仅 Watch 行，否则全部行；对候选 `price` 排序后取线性插值百分位 `P25`、`P75` 与中位数，均 2 位；`basis` 对应三选一文案。若 `low == high`，令 `low = round(low×0.95,2)`、`high = round(high×1.05,2)`。
- 百分位插值：`k=(n−1)×p/100`；`floor/ceil` 相等时取该元素，否则 `v[low]×(high−k)+v[high]×(k−low)`。

### 5.4 样例算例复核（用于新实现对拍）

**市场容量**：28 条样本 `Σsales=38,680`、`Σrevenue=1,527,531`，均价 = 所有 `price` 的算术平均 = 45.28，中位价 = 排序后第 14/15 位均值 = 32.49。
**集中度（品牌）**：25 个品牌；把品牌销量求和后降序，前 3 名合计 16,100 件 → `16,100/38,680×100=41.62`；前 10 名合计 28,200 件 → 72.91；HHI = 各品牌销量占比百分数的平方和 = 816.82（输出 816.8）。
**价格带**：`(149.99−19.99)/10 = 13.00`，故边界为 19.99、32.99、45.99……149.99；价格恰在边界的样本进入**较高**档（左闭右开），仅最后一档右端闭合；`sales_share_pct` 分母恒为全样本 38,680。
**波谷**：对每对相邻档，`drop=(prev−cur)/prev×100`；样本中 5 组及格（阈值 15），全部展示；若及格数 >5，只显示 `drop` 最大的 5 组，再按档位升序排列。
**单商品**：价格 29.99、销量 1,000、评论 260、评分 3.9：
- `demand = 100×(0.60×clamp(1000/2000) + 0.40×clamp((1000/260)/0.5)) = 100×(0.30+0.40) = 70.0`（样本 Top1 销量 1,300/评论 260 时为 79.0）。
- `competition = 0.5×74.0 + 0.25×69.41 + 0.25×100 = 79.4`（`review_comp=(1−260/1000)×100=74`；**全表最大卖家** BlendJet Official 占 7,100/38,680=18.36% → `(1−0.1836/0.60)×100=69.41`；`rating_comp=(4.8−3.9)/0.8×100` 截顶 100）。注意：卖家集中项用的是**全样本最大卖家**，不是该行自己的卖家。
- 利润（共用）：`referral=29.99×15%=4.4985`；`profit=29.99−5.32−4.4985−4.75=15.4215→15.42`；`margin=51.4`；`profit_score=100`。
- 合规/供给：无列 → 2.0/3.0 → 60/60。
- 总分：`(30×79.0+25×79.4+25×100+10×60+10×60)/100=80.5`（实测 B0GREENTECH=80.5）。
**切入价带（单行 29.99）**：候选仅 1 条，P25=P75=median=29.99 → low=28.49、high=31.49。
**利润维度与价格无关**：同一参数下所有行 `profit` 维度相同（100.0），因此利润不是区分项，只影响否决理由。

## 6. 已知行为与坑（现状）

| # | 现象 | 触发条件 | 现状行为（含实测退出码/输出） | 新实现建议 |
|---|---|---|---|---|
| 1 | 字符串异常导致退出码 1 | `normalize_export.py` 任意输入错误 | 旧实现 `sys.exit("[INPUT_MISSING] ...")`：消息写 **stderr**、退出码 **1**；`--json` 不产生 JSON。本批已改为显式 `SystemExit(2)`，文案不变（#1） | 已实施：见 #1 |
| 2 | 缺文件/空 CSV/缺列/坏数字均退出 1 | normalize | 旧实测四种场景均 EXIT=1、stdout 为空；新实现同类场景 EXIT=2，stderr 文案逐字保持 | 已实施：见 #1 |
| 3 | 错误输出走 stdout | market / opportunity | `[INPUT_MISSING]` 打到 stdout；无 JSON 错误对象 | 保持旧样（本批不改） |
| 4 | 全样本 0 销量 + 全部同价 → 崩溃 | `market_metrics.py`，`max(price)==min(price)` 且 `Σmonthly_sales==0` | `ZeroDivisionError` traceback（price_bands 同价分支无保护），EXIT=**1** | 本批刻意保真未加保护，属规格缺口（见 §8） |
| 5 | 0 销量 + 不同价 | 同上但价格不同 | EXIT=0，所有份额 0.0，HHI 0.0，CR3 0.0 | 保留 |
| 6 | `--json` 覆盖 `--format` | `--format both --json` | 只输出 JSON，Markdown 被丢弃 | 保留（文档写明优先级） |
| 7 | 错误一次性聚合 | market 字段校验、opportunity 行解析 | 汇总所有行错误后一次退出；不是首错即停 | 保留，便于修数据 |
| 8 | 可选列缺省但静默 | opportunity 无 `compliance_risk` / `supply_feasibility` | 分别按 2.0/3.0 计；`defaults` 与报告显式提示「未核验≠低风险」 | 保留提示 |
| 9 | 可选列存在但单元格空 | opportunity | 该行按 2.0/3.0，并在 `defaults` 追加逐行提示 | 保留 |
| 10 | 切入价带单值扩张 | 候选价格 P25=P75 | low×0.95、high×1.05（实测单行 29.99 → 28.49–31.49） | 保留，写入口径 |
| 11 | 总分为 1 位小数但 verdict 用原值 | 边界 59.95/74.95 | 可能出现显示 60.0 却是 No-Go / 显示 75.0 却是 Watch；**边界未实测** | 明确阈值比较精度，或在输出中给未取整分 |
| 12 | 负数不校验 | market 的 price/sales、opportunity 的 fee/fba/rating/reviews | 照算；可能出现负份额、负分（clamp 后 0）、负 momentum | 新实现补业务校验或明确允许 |
| 13 | 重复 ASIN 处理两套口径 | normalize 去重；market 不去重 | normalize 丢弃后续重复行并告警；market 同一 ASIN 重复计入 | 统一「入口去重」或文档说明 |
| 14 | 表头别名大小写不敏感 | normalize | `ASIN`/`asin` 均可；未知别名不报错，只是缺列 | 保留 |
| 15 | 整数字段截断 | normalize / opportunity | `int(float())` 向零截断；`reviews=200.9 → 200` | 保留或改为显式取整策略 |
| 16 | 空行处理不同 | opportunity 跳过全空行；normalize 未跳过全空行 | **已探测（probe，2026-10-30）**：真正的空行（`csv.reader` 返回 `[]`）旧实现**跳过**；由 11 个空字段组成的行（`,,,,,,,,,,`）不跳过，报 `第 2 行 asin 为空`。新实现按此复刻：`if not row: continue` | 保留（已与旧实现对拍） |
| 17 | `market_metrics.py` 输入支持带 `$`/`,` 数字字符串 | JSON 中 `price:"$19.99"` | 正常解析（代码明确）；输出为 float | 保留 |
| 18 | `attributes` 交叉表按全样本分母 | 仅部分行有属性 | 属性行销量份额分母仍为全样本 S，份额合计可 <100% | 文档写明，避免误读 |

### 6.1 退出码总表（按脚本 × 场景）

| 场景 | normalize | market | opportunity |
|---|---|---|---|
| 成功（含 `--json`） | 0 | 0 | 0 |
| `--help` | 0 | 0 | 0 |
| 文件不存在 | 2 | 2 | 2 |
| 空文件 / 无表头 | 2 | 2（非法 JSON/空文件） | 2（无表头） |
| 有表头/顶层但无数据行 | 2 | 2（`items` 为空） | 2 |
| 缺必需列/字段 | 2 | 2 | 2 |
| 行级非数字 / NaN / Inf | 2（首错即停） | 2（聚合） | 2（聚合） |
| argparse 参数非法 | 2 | 2 | 2 |
| 业务参数越界（bins/top/target/cost） | — | 2 | 2 |
| 运行期未捕获异常 | 1（如写文件失败，未实测） | 1（除零） | 未见已知路径 |

### 6.2 新实现必须保持的行为清单

1. `normalize_export.py` 的去重语义是「保留首次出现」，且警告带原始行号。
2. `market_metrics.py` 的均价是**简单平均**，不是销量加权；文档和字段名不得暗示加权。
3. 集中度 `cr3_meaningful` / `cr10_meaningful` 是「主体数 >3 / >10」，不是「份额是否足够高」。
4. 波谷输出顺序是「先取跌幅最大的 5 个，再按价格带升序」，不是纯按跌幅展示。
5. Top 商品的 `reviews`/`bsr` 是截断取整，不是四舍五入。
6. `opportunity_score.py` 的利润维度是**全表共用值**，不随 ASIN 价格变化。
7. 卖家集中度项使用全表最大卖家份额；单行输入会显著压低竞争分。
8. 切入价格带优先用 Go 行；无 Go 用 Watch；两者都无才用全表。
9. 所有百分比字段在 JSON 中是 0–100 的数值，不是 0–1 小数。
10. 三个脚本的 stdout 都是人可读的最终产物（JSON 或 Markdown），不得混入日志行。

## 7. 对拍基准（可复现）

工作目录：仓库根 `e:\SKILLS\supply-to-shelf-skills`；Python 3.12.0。

### 7.1 normalize：示例 CSV → normalized.json

```powershell
python Agents/01_Selection_Agent/scripts/normalize_export.py Agents/01_Selection_Agent/examples/sample_category_export.csv --output $env:TEMP\norm.json
```

- 输入要点：28 行、11 列、UTF-8 CSV；首行表头与契约字段同名。
- 期望：EXIT=0；stdout 首行 `✅ 已写出 <dest>（28 个 ASIN）`；JSON `meta.item_count=28`、`items` 28 条、`warnings=[]`。
- 追加验证：`--attributes lithium_battery,food_contact --json` → 每条 item 多出同名数组；stdout 摘要 `item_count=28`。
- 重复 ASIN 用例：两行同 `B0X` → EXIT=0、`item_count=2`、warning「第 3 行 ASIN B0X 重复，已保留首次出现」。

### 7.2 market：示例 normalized.json

```powershell
python Agents/01_Selection_Agent/scripts/market_metrics.py $env:TEMP\norm.json --json
```

- 输入要点：7.1 生成的 `{"meta":...,"items":[28]}`。
- 期望（实测）：EXIT=0；
  - `market.items=28`、`total_monthly_sales=38680.0`、`total_monthly_revenue=1527531.0`、`avg_price=45.28`、`median_price=32.49`、价格区间 `$19.99–$149.99`；
  - `brand_concentration.entity_count=25`、`cr3_pct=41.62`、`cr10_pct=72.91`、`hhi=816.8`；
  - `meta.trough_candidates_total=5`、`meta.trough_bands_shown=5`；
  - `attribute_cross_table=null`。
- Markdown 对拍：`# 美国站类目市场测算`，总月销量显示 `38,680 件`，总月销售额 `$1,527,531.00`。
- 单样本裸数组用例：1 条商品 → EXIT=0、`cr3_pct=100.0`、`hhi=10000.0`、`cr3_meaningful=false`。

### 7.3 opportunity：示例 CSV

```powershell
python Agents/01_Selection_Agent/scripts/opportunity_score.py --file Agents/01_Selection_Agent/examples/sample_category_export.csv --factory-cost-usd 5.32 --target-price 29.99 --json
```

- 输入要点：28 行、无 `compliance_risk`/`supply_feasibility` 列。
- 期望（实测）：EXIT=0；
  - `meta.rows=28`；`meta.profit_usd=15.42`；`meta.profit_margin_pct=51.4`；
  - `summary.verdict_counts = {Go:10, Watch:15, No-Go:3}`；
  - `summary.entry_price_band = {low:23.24, high:27.74, median:25.49, basis:"Go 候选价格 P25–P75"}`；
  - `summary.top3` = B0GREENTECH 80.5 Go / B0CORDLESS 78.4 Go / B0TRAVELBLEND 78.0 Go；
  - `summary.dimension_averages` = demand 70.0 / competition 51.0 / profit 100.0 / compliance 60.0 / supply 60.0；
  - `defaults` 两条默认值提示。

### 7.4 失败用例

| 命令要点 | 期望 |
|---|---|
| `normalize_export.py $env:TEMP\nofile.csv` | EXIT=1；stderr 含 `找不到文件` |
| `normalize_export.py <仅表头 CSV>` | EXIT=1；stderr `CSV 没有数据行` |
| `normalize_export.py <price=abc CSV>` | EXIT=1；stderr `第 2 行 price='abc' 不是数字` |
| `market_metrics.py $env:TEMP\nonexistent.json` | EXIT=2；stdout `[INPUT_MISSING] 找不到输入文件` |
| `market_metrics.py <norm.json> --bins 0` | EXIT=2；stdout `--bins 必须 ≥ 1` |
| `market_metrics.py <norm.json> --config-fields attributes` | EXIT=2；stdout 提示无 attributes |
| `market_metrics.py <缺 fulfillment 的 1 条 JSON>` | EXIT=2；stdout `B0X 缺少/非法字段：fulfillment` |
| `market_metrics.py <同价且总销量 0 的 JSON>` | EXIT=1；stderr `ZeroDivisionError` traceback |
| `opportunity_score.py --file <不存在>` | EXIT=2；stdout `找不到输入文件` |
| `opportunity_score.py --file <示例> --factory-cost-usd 5.32 --target-price 0` | EXIT=2；stdout `--target-price 必须 > 0` |
| `opportunity_score.py --file <示例> --factory-cost-usd -1 --target-price 29.99` | EXIT=2；stdout `--factory-cost-usd 不能为负` |
| `opportunity_score.py --file <缺 seller 列的 CSV>` | EXIT=2；stdout 缺列 + 必需列清单 |
| `opportunity_score.py --file <行含 price=abc>` | EXIT=2；stdout `第 3 行 price 不是数字：abc` |
| `opportunity_score.py --file <表头但无数据>` | EXIT=2；stdout `CSV 没有数据行。` |

### 7.5 最小对拍输入样例

单商品 normalized JSON（`market_metrics.py` 应输出 CR3=CR10=100、HHI=10000、`cr3_meaningful=false`）：

```json
{"items":[{"asin":"B0TEST0001","title":"Test Blender","brand":"TestBrand","seller":"TestSeller",
 "price":29.99,"monthly_sales":1000,"monthly_revenue":29990,"reviews":260,"rating":3.9,
 "bsr":120,"fulfillment":"FBA"}]}
```

命令：`python Agents/01_Selection_Agent/scripts/market_metrics.py <上述文件> --bins 1 --top 1 --json` → EXIT=0，`price_bands` 仅 1 档且 `lower=upper=29.99`、`label="$29.99"`（`Σsales>0`，不会触发除零）。

单行 opportunity CSV（全表只有一个卖家 → 卖家份额 100%，竞争维度卖家项为 0）：

```csv
asin,price,monthly_sales,reviews,rating,seller
B0TEST0001,29.99,1000,260,3.9,TestSeller
```

命令：`python Agents/01_Selection_Agent/scripts/opportunity_score.py --file <上述文件> --factory-cost-usd 5.32 --target-price 29.99 --json` → EXIT=0，实测 `score=73.9`、`verdict=Watch`、`verdict_counts={Go:0,Watch:1,No-Go:0}`、`entry_price_band={low:28.49,high:31.49,median:29.99,basis:"Watch 候选价格 P25–P75"}`。
这与 28 行样本的差异正说明：竞争维度依赖**全表卖家集中度**，单行样本会得到 0 分；用单行数据对拍时必须写死该结论，不能拿 80.5 做期望。

最小 normalize CSV（11 列齐全）：任意一行即可复现 `item_count=1`、无 warning；若把 `price` 改成 `abc` 应 EXIT=2 且 stderr 指向第 2 行（#4）。

## 8. 未完整刻画/待确认

1. **verdict 边界精度**：总分先 `round(,1)` 输出，但 verdict 用未取整值；59.95–60.0、74.95–75.0 的实际归属未实测，规格需明确。
2. **NaN / Infinity**：洗清后 `float("nan")` / `float("inf")` 在旧实现会被接受（`Infinity` 会写进 JSON，非法 JSON）。**本批已实施（#5）**：`math.isfinite` 显式校验，NaN 走缺值分支、Inf 报「不是有限数值（NaN/Inf）」，两者都 exit 2。`opportunity_score.py` 的同类校验也已生效（`compliance_risk` / `supply_feasibility` 非有限值报错）。
3. **重复表头**：同一 CSV 出现两列同名时取第一个；未实测 csv 模块的 `None` 键/多余列处理。
4. **normalize 全空行**：已探测（probe，2026-10-30）。真正的空行（`[]`）被跳过；11 个空字段的行报 `第 2 行 asin 为空`。新实现已复刻并纳入对拍用例。
5. **`attributes` 字符串中的空白与重复值**：已探测：`--attributes "a,a , "` → `["a","a"]`（去空、不去重）。全角逗号、换行等未覆盖。
6. **属性交叉表 `avg_price`**：按商品简单平均而非销量加权，是否为新实现期望口径需产品确认。
7. **市场报告中的 `trough_threshold` 负值/极大值**：无校验，行为按公式外推，未实测。
8. **opportunity 对 `rating > 5` 或负值**：clamp 后可能得 0 分或 100 分，业务上是否允许未定义。
9. **货币**：三个脚本都写死 USD；是否需支持其它币种未在代码中出现。
10. **stdout UTF-8 重设失败**（非 Windows/受限终端）时的降级行为未实测。
11. **写文件失败**：`--output` 指向不存在目录或无写权限时，代码未做兜底；是否为 traceback/退出 1 未实测。
12. **多扩展名输入文件名**：已探测：`myfile.tar.csv` → `myfile.tar.normalized.json`（`with_suffix` 只替换最后一个扩展名）。
13. **非 UTF-8 编码（如 GBK）**：以 `utf-8-sig` 打开会抛 `UnicodeDecodeError`；新实现捕获后报 `[INPUT_MISSING] 无法读取文件：...`、exit 2，但编码探测/回退仍未实现。
14. **标题截断的字符口径**：按 Python 字符数（Unicode code point）截断，非显示宽度；中文与 emoji 的视觉宽度未处理。

### 8.1 探测记录（probe，2026-10-30）

| 行为点 | 探测输入 | 旧实现输出/退出码 | 新实现 |
|---|---|---|---|
| 空 CSV | 0 字节文件 | stderr `[INPUT_MISSING] CSV 没有表头`，exit 1 | 同文案，exit 2（#1） |
| 仅表头 | 表头一行 | stderr `CSV 没有数据行`，exit 1 | 同文案，exit 2（#1） |
| 缺列 | `asin,title,price` | stderr `CSV 缺少列：['brand', ...]；现有表头：[...]`，exit 1 | 同文案，exit 2（#1） |
| 单行脏数据 | `price='abc'` | stderr `第 2 行 price='abc' 不是数字`，exit 1 | 同文案，exit 2（#4） |
| NaN | `price=nan` | stderr `第 2 行缺少 price；不补数，请回导出表核对`，exit 1 | 同文案，exit 2（#1/#5） |
| Inf | `price=inf` | 照收，写出 `Infinity` 非法 JSON，exit 0 | 报 `第 2 行 price='inf' 不是有限数值（NaN/Inf）`，exit 2（#5） |
| 负价 | `price=-29.99` | 照收并写出，exit 0 | 同（不做业务拦截） |
| BOM + CRLF | UTF-8 BOM + `\r\n` | 正常解析，exit 0 | 同 |
| 空行 | 真空白行 | 跳过，exit 0 | 同（`if not row: continue`） |
| 默认输出名 | `myfile.tar.csv` | `myfile.tar.normalized.json` | 同 |
| market 字段不全 | 缺 `fulfillment` | stdout `以下商品字段不完整，已停止计算（不猜测）：\n  - B0X 缺少/非法字段：fulfillment`，exit 2 | 同 |
| market 同价 + 0 销量 | 单档价格、Σ销量=0 | `ZeroDivisionError` traceback，exit 1 | 刻意保留（清单外不得改） |
| opportunity 基准 | 28 行示例 | Go 10 / Watch 15 / No-Go 3；Top1 `B0GREENTECH 80.5`；价带 23.24–27.74（中位 25.49） | 同（JSON 与 Markdown 逐字一致） |
