# 99 · 实现决策记录与缺口回填

> 状态：阶段 5 已完成回填。默认原则是「保持基线行为」，只有用户清单、无人值守指令明确要求，或已由 `#n` 有意差异落定的项才偏离基线实现。
> 每条 D 项已给出结论、依据与落地位置；末尾「附」列出原规格中「未确认」条目的回填结果。

## D1. 退出码是否逐位保真
- 现状：01 `normalize_export.py` 所有输入错误退出 **1**（`sys.exit("字符串")`）；03 CONDITIONAL=**1**；04/05 检出问题也退出 **1**；06/07/08 业务告警退出 **0**。
- A 完全保真：下游脚本、CI、文档无需改动；代价是 1 同时表示「业务结论」和「输入错误」，无法仅凭退出码分流。
- B 修正为语义化：输入错误统一 2、业务结论独立（如 3/4 或只用 JSON 字段）；代价是所有调用方与既有测试需同步。
- 影响：01/04/05 分册 §4§6，`00_overview.md` §2.2。
- **决定：混合保真（A+B）**。输入错误统一 exit 2（#1/#2/#3/#6/#12/#14）；业务结论保留基线行为（03 `CONDITIONAL=1`/`BLOCKED=2`/未知类目 `=3`；04/05 检出问题 `=1`；06/07/08 告警 `=0`，07 仅新增可选 `--fail-on-critical` #9）。依据：用户清单只要求「输入错误退出码统一」，未要求改业务码。

## D2. 03 的状态词
- 现状：CLI/JSON 输出 `PASS / CONDITIONAL / BLOCKED`，而产品文档惯用 `APPROVED`。
- A 保持 `PASS`（与现有 JSON 消费者一致）。
- B 改为 `APPROVED` 并保留 `PASS` 作为兼容别名。利：语义直白；弊：字段值变更，需同步规则库与文档。
- 影响：`03_compliance.md` §4、§7。
- **决定：保持 A（`PASS / CONDITIONAL / BLOCKED`）**。不引入 `APPROVED` 别名；规则库与既有消费者不变。差分测试 03 十二条用例全部 SAME。

## D3. 02 是否保留既有参数 `--category`
- 现状：同时存在 `--category`（可传平台路径/别名/键）与 `--category-key`（推荐），`--platform` 仅在未显式 referral 时生效。
- A 保留双参数 + 别名 + 平台路径前缀解析（行为等价，学习成本高）。
- B 只保留 `--category-key`，既有参数报错并提示迁移。利：契约清晰；弊：破坏既有命令行与示例。
- 影响：`02_cost_pricing.md` §2、§6；`config/category_map.json` 的 aliases 是否继续维护。
- **决定：保持 A**。保留 `--category` / `--category-key` 双参数、别名与平台路径最长前缀解析；不做迁移式报错。

## D4. matrix 行级失败的汇总形态
- 现状：逐行报错、整表继续；JSON 输出 `failed_rows[]`（row/sku/message/missing）+ 成功 `rows[]`，退出 **2**；文本模式先印成功表格再汇总。
- A 保持「部分成功 = 退出 2 + 双数组」。
- B 部分成功退出 0，仅用 `failed_rows` 表达；利：批处理不中断 CI；弊：失败易被忽略。
- C 额外提供 `--fail-fast` 开关。利：兼顾两种诉求；弊：增加参数面。
- 影响：`02_cost_pricing.md` §4、§6。
- **决定：保持 A**。部分成功仍为 exit 2 + `rows[]`/`failed_rows[]`；不新增 `--fail-fast`（超出本轮授权范围）。差分测试「02 matrix 样例」按 #8 仅差异在 `customs_fee_placeholder` 与 note 前缀。

## D5. `--json` 错误里的 `status` 是否需要 `ERROR`
- 现状：所有错误都是 `INPUT_MISSING`，`ERROR` 无触发路径；03 的错误也用 `INPUT_MISSING` + 退出 3。
- A 保持单一状态（简单，调用方按退出码分流）。
- B 区分输入缺失（2）与运行时/配置错误（ERROR + 3）。利：机器可判；弊：需给每个错误点分类。
- 影响：全部分册 §4；`00_overview.md` §2.1。
- **决定：保持 A（单一 `INPUT_MISSING`）**。`ERROR` 仍无触发路径（06 §4 已记录）；调用方按退出码分流。若未来引入运行时错误分类，再单独开号。

## D6. `claim_scan` 的错误输出通道
- 现状：`--json` 下错误 JSON 写 **stdout**，人类信息也写 stdout；与其他脚本「人类信息走 stderr」不一致。
- A 统一到 stderr + 既有 JSON 契约（行为变更，需更新测试）。
- B 原样保留（避免破坏 04 的既有消费方）。
- 影响：`04_listing.md` §4、§6。
- **决定：保持 B（原样保留）**。`claim_scan` 的错误 JSON 与人类信息都写 stdout；不改通道，避免破坏既有消费方，且未列入用户清单。

## D7. 05 缺文件的退出码
- 现状：缺图被计为 `FILE_NOT_FOUND` → FAIL → 退出 **1**；而输入文件本身缺失在文档中写作「输入错误」。
- A 保持 1（把缺图视为素材不合格）。
- B 区分「spec/文件读不到 = 2」与「图存在但违规 = 1」。利：语义清晰；弊：与现状不一致。
- 影响：`05_creative.md` §4、§6。
- **决定：按场景拆分**。输入文件缺失/不可读 → exit 2（#2 已实施）；素材缺图仍按 `FILE_NOT_FOUND` → FAIL → exit 1（保持基线行为）。依据：用户清单 §2 只覆盖输入文件。

## D8. 06/07/08 的业务告警是否使用非零退出
- 现状：P0 告警、负毛利、CRITICAL、错过补货窗口等均退出 **0**，仅体现在 JSON 字段。
- A 保持 0（脚本是计算器，不是门禁）。
- B 增加 `--strict`（有 P0/CRITICAL 时退出非零）。利：可直接接 CI；弊：新增参数与语义。
- 影响：`06_ads.md`、`07_review_ops.md`、`08_fulfillment.md` §4、§6。
- **决定：默认保持 A（exit 0）**。仅 07 新增可选 `--fail-on-critical`（#9），默认关闭；06/08 不新增 strict 开关。

## D9. 01 的业务异常退出码
- 现状：market_metrics 在「同价且总销量 0」等场景退出 **1**。
- A 保留。B 改为 0 + 警告字段。利：纯计算器语义；弊：破坏既有调用方。
- 影响：`01_selection.md` §4、§6。
- **决定：仅改已确认的崩溃边界（#13）**。「同价且 Σ销量=0」已转 `meta.status="WARNING"`、`price_bands=[]`、exit 0；其余业务异常保持基线行为，未扩大改动面。

## D10. 舍入与精度策略
- 现状：各中间量按「先 `round(x, 2)` 再进入下一步」或「全精度计算、末步取整」混用（如 02 关税以已取整 FOB 为基数）。
- A 逐位复刻现有取整位置（差分测试数字必然一致，但实现需刻意保留冗余取整）。
- B 统一为「全精度计算、输出时取整」。利：更规范；弊：末位可能差 0.01，差分测试需重新定基线。
- 影响：`02_cost_pricing.md` §5、`06_ads.md` §5、`08_fulfillment.md` §5。
- **决定：保留各模块基线口径（A）**。02 关税以已取整 FOB 为基数；06 采用「全精度中间量、输出取整」（阶段 4 差分测试固定，TikTok 64.36%）；08 沿用基线取整位置。不做全局统一，避免末位漂移。

## D11. 输入编码兼容
- 现状：全部按 `utf-8-sig` 读取；非 UTF-8（如 GBK）在 01/04/05 可能抛未捕获异常或表现为退出 1。
- A 保持严格 UTF-8（错误明确）。
- B 增加 GBK/GB18030 回退并报 `encoding_fallback` 警告。利：兼容国内导出；弊：可能掩盖脏数据。
- 影响：全部分册 §3、§6。
- **决定：严格 A（仅 `utf-8-sig`）**。不做 GBK 静默回退；01/04/05 解码失败均明确报错并 exit 2（#1/#6），避免用回退掩盖脏数据。

## D12. 共享配置的抽取（原 P1-1）
- 现状：`us_fees.json` 与 `category_map.json` 通过相对路径硬编码（`parents[2]/[3]` bootstrap）。
- A 实现时抽为可配置路径（环境变量/参数/包内资源），统一加载器。
- B 保持仓库相对路径。利：最小改动、与现状一致；弊：目录调整即断。
- 影响：全部脚本 §1、§3；`00_overview.md` §1。
- **决定：保持 B（仓库相对路径）**。沿用启动时 `parents[2]/[3]` bootstrap 与 `shared/config.py`；不引入环境变量/包资源加载器，避免改变部署契约。

## D13. 未核校 HTS 与兜底类目策略
- 现状：`hts_tariff.json` 中 `verified=false` 的税率仍会参与计算，只给提醒；`--assume-default-referral` 缺类目时按 default 15% 估算。
- A 保留（提醒 + 显式开关）。
- B 未核校项直接拒绝计算，除非 `--duty-pct` 覆盖；缺类目一律报错。利：更安全；弊：示例与文档大量失效。
- 影响：`02_cost_pricing.md` §5、§6、§7。
- **决定：保持 A（提醒 + 显式开关）**。`verified=false` 的 HTS 仍参与计算并给 `[WARN]`；缺类目仍需 `--assume-default-referral` 才按 15% 估算。不改为拒绝计算。

## D14. claim_scan 规则表与 03 规则库的维护形态
- 现状：04 关键词表硬编码在脚本；03 规则为独立 JSON（含 sources/as_of/confidence）。
- A 04 也外置为 JSON（可版本化、可审计）。
- B 保持脚本内常量（部署简单）。
- 影响：`04_listing.md` §3、§6；是否与 03 的合规口径合并。
- **决定：保持 B（04 脚本内常量）**。03 继续使用独立 `compliance_rules.json`；两条规则体系不在本轮合并。

## D15. 05 图片/视频异常的边界
- 现状：损坏图、0 尺寸、静态 WebP 等未完整刻画，可能触发未捕获异常。
- A 定义明确错误码并纳入契约（推荐在规格中补齐后再实现）。
- B 交由 Pillow/ffprobe 异常自然退出。
- 影响：`05_creative.md` §5、§8。
- **决定：A 已落地**。损坏图/0 尺寸/视频数值/`--fix` 同路径覆盖均有明确状态码与 exit 2（#3/#12/#14）；静态 WebP 交给 Pillow，缺 Pillow 时输出 `[WARN] PILLOW_MISSING` 并降级，不新增自研解码。

## D16. 08 海运计费与最低收费
- 现状：计费重 `max(实重, 体积重)`，存在 167 kg/CBM 换算与 1 CBM 最低收费，但不可配置；既有示例文档资金数字与命令实跑不一致（#11 已按实算 3995 / 45.97 / 10.51 / 35.46 落定，本项只剩「是否可配置」）。
- A 保持常量。B 暴露为参数并修示例。利：可复核；弊：参数面扩大。
- 影响：`08_fulfillment.md` §5、§8。
- **决定：保持 A（常量）**。167 kg/CBM 换算与 1 CBM 起收保持内置，不新增参数；示例资金数字已由 #11 按实跑 3995 / 45.97 / 10.51 / 35.46 固化。

## 附：原「未确认」条目回填

- **01 verdict 取整边界**：保持基线行为（`round2`），未单独构造临界样本；normalize 全空行/写盘失败按基线行为报错。单行 NaN/Inf 已由 #5 拒绝，见 `01_selection.md` §8.1。
- **02 HTS 短前缀匹配**：已实测并纳入差分测试 `02 calc HTS 短前缀` → SAME（`8509` 命中 `8509.40` 规则）。
- **02 类目路径歧义样例**：保持基线行为（最长前缀；同长多命中 → exit 2、`missing=["category_key"]`）；未构造歧义样本。
- **02 兼容 referral 结构分支**：保持基线行为（`--platform` 仅在未显式 referral 时影响默认值）。
- **02 matrix 非法 season**：保持基线行为（argparse `choices` 拒绝，行级失败并汇总）。
- **02 列表命令 JSON**：已实测 `--list-platforms --json` 两侧同样报 `参数错误：unrecognized arguments: --json` 并 exit 2；保持基线行为。
- **03 并列前缀歧义文案**：保持基线行为，未构造样本；现有 03 差分测试 12 条全部 SAME。
- **03 rules.json BOM**：读取使用 `utf-8-sig`，带 BOM 的规则副本可正常加载（实测 `CONDITIONAL` 正常输出）。
- **03 `rules_direct` 触发**：保持基线行为；主要分支已由 03 差分测试（PASS / CONDITIONAL / BLOCKED / 未知类目）覆盖。
- **04 `100 %`（数字与 `%` 间有空格）**：已实测 `claim_scan --text "100 % safe"` 两侧均不命中（PASS、计数全 0）；`listing_lint` 对空格写法也不报。保持基线行为，规格已写明只匹配字面 `100%`。
- **04 `BRAND_TOO_LATE` 80/81 位次**：`ITEM_NAME` 等 80/81、200/201 长度边界已由单测固定；`BRAND_TOO_LATE` 恰在 80/81 的样本仍未单独构造，保持基线行为。
- **05 静态 WebP**：保持基线行为（Pillow 可解码则按普通图片处理；不可解码 → `INPUT_ERROR` exit 2，#3）。
- **06 `status=ERROR`**：仍无触发路径，保持单一 `INPUT_MISSING`；差分测试未出现 ERROR。
- **07 行级错误是否中止整表**：按现状记录——行级问题写入结果数组、整表继续；未新增反证样本，保持基线行为。
- **08 `days=0` 截止日口径**：保持基线行为（仅已过截止日才追加「已过 N 天」后缀，见 `08_fulfillment.md` §4）；`--currency` 不校验、仅回显，保持基线行为。

## 有意差异（intended diffs）

> 本清单是用户明确批准的、允许偏离基线实现的行为集合。**清单之外**的任何 stdout/stderr/退出码/JSON 差异一律视为回归。
> 阶段 1（骨架 + 02 + 03）已实施 #8；阶段 2（01 + 05）已实施 #1–#5；阶段 2.5 已实施 #12–#14；阶段 3（04 + 07）已实施 #6、#7、#9；阶段 4（06 + 08）已实施 #10–#11。

| # | 模块 | 基线行为 | 当前行为 | 依据 | 影响面 | 本轮状态 |
|---|---|---|---|---|---|---|
| 1 | 01 | `sys.exit("字符串")` → 退出码 1；错误信息打到 stderr | 统一为退出码 2（与 02–08 一致），错误信息仍走 stderr | 用户清单 §1：错误退出码统一 | 01 全部参数/输入错误用例；成功路径不变 | **已实施**：`Agents/01_Selection_Agent/scripts/normalize_export.py`（`fail()` → stderr + `SystemExit(2)`）、`market_metrics.py`、`opportunity_score.py`；测试 `tests/test_selection.py::NormalizeExportTests` |
| 2 | 05 | 缺文件/不可读 → 退出码 1 | 退出码 2 | 用户清单 §2；05 SKILL.md 声明 2 | 05 文件缺失分支；成功路径不变 | **已实施**：`Agents/05_Creative_Agent/scripts/asset_check.py`（`run_image` 缺图分支 `missing_source=True`、`1 if FAIL else 0` 之外单独置 2）；测试 `tests/test_creative.py::InputErrorTests` |
| 3 | 05 | 损坏图 / 0 尺寸 / 不可解码 → 抛 traceback | 返回明确状态码 + exit 2，不抛 traceback | 用户清单 §3 | 05 图片/视频异常路径 | **已实施**：`asset_check.py` 的 `load_rgb()`（`INPUT_ERROR`「图片无法解码…」/「图片尺寸非法（0 像素）」）与 `run_video` 宽高校验（`INPUT_ERROR`「视频尺寸非法」）；测试 `tests/test_creative.py::InputErrorTests`（0 尺寸用 `mock` 覆盖） |
| 4 | 01 | 单行脏数据（非数字等）中途异常退出 | 报具体行号与列名，exit 2，不静默产出错误数值 | 用户清单 §4 | 01 单行校验；成功行数值不变 | **已实施**：`normalize_export.py` 的 `parse_number`（`第 N 行 price='abc' 不是数字`）；测试 `tests/test_selection.py::NormalizeExportTests::test_dirty_row_reports_line_and_column` |
| 5 | 01 | NaN/Inf 进入计算并静默产出 | 显式校验并报错，不进入计算 | 用户清单 §5 | 01 数值校验 | **已实施**：`normalize_export.py` 的 `parse_number`（`math.isfinite` → `第 N 行 price='inf' 不是有限数值（NaN/Inf）`）；测试 `tests/test_selection.py::NormalizeExportTests::test_nan_rejected`/`test_inf_rejected` |
| 6 | 04 | GBK 等解码失败 → 原始 traceback（`listing_lint` 退出 1） | 明确错误信息 + exit 2（`INPUT_ERROR`，无 `missing`） | 用户清单 §6 | 04 listing_lint 读取路径 | **已实施**：`listing_lint.py` 的 `main()` 捕获 `UnicodeDecodeError`；`claim_scan.py` 同口径（基线已如此）。测试 `tests/test_listing.py::ListingLintAmazonTests::test_non_utf8_file_exit_2` 等 |
| 7 | 04 | 未校验 A+ 模块顺序，缺模块/乱序仍可通过 | 按文档承诺的顺序校验；缺必需模块或顺序错误判 FAIL | 用户清单 §7 | 04 A+ 校验结果（原先可通过的组合可能转为 FAIL）；其余校验不变 | **已实施**：`listing_lint.py` 的 `check_aplus_order()`（7 阶段识别；缺主视觉/包装清单或序非递增 → `APLUS_ORDER` FAIL）；测试 `tests/test_listing.py::ListingLintAmazonTests::test_aplus_out_of_order_fails`/`test_aplus_missing_hero_fails` |
| 8 | 02 | 未显式传 `--customs-fee-per-unit` 时，note 为「未提供 --customs-fee-per-unit，报关杂费按默认 $0.18/件计算」，JSON 无占位标记 | note 前面加 `[WARN] `；`inputs` 新增 `customs_fee_placeholder: true/false`（显式传入时为 false） | 用户清单 §8：占位值须显式告警并可机读识别 | calc 的 `notes[]` 与 `inputs`；matrix 的 `rows[].notes[]` 与 `rows[].inputs`；其余字段与数值不变 | **已实施** |
| 9 | 07 | 无此开关，CRITICAL 也退出 0 | 新增 `--fail-on-critical`：开启时 CRITICAL 退出 1；默认关闭保持基线行为 | 用户清单 §9 | 07 默认路径不变；仅新开关生效时改变退出码 | **已实施**：`Agents/07_Review_Ops_Agent/scripts/review_ops.py`（`health` 子命令退出码 `1 if (fail_on_critical and grade == "CRITICAL") else 0`）；测试 `tests/test_review_ops.py::HealthTests::test_fail_on_critical_flag` |
| 10 | 08 | `--carrying-rate-pct` 无上限（负值已拒绝） | 取值校验 0–100，负值与 >100 各自 exit 2；0 仍合法 | 用户清单 §10 | 08 参数校验；合法区间内结果不变 | **已实施**：`inventory_plan.py` 的 `run_compare()`（`<0` 保留既有文案，`>100` 报「必须在 0–100 之间」）；测试 `tests/test_fulfillment.py::CompareTests::test_carrying_rate_above_hundred_fails`、`test_carrying_rate_zero_is_allowed`；差分测试用例「08 compare 资金费率 200」标记 INTENDED #10 |
| 11 | 08 | 既有示例文档资金数字与命令不一致（写 4995/4335，实算 3995） | 以脚本实算为准：`units=500`、`unit-cost=7.99` → 货值 3995、海运资金 45.97、空运 10.51、差额 35.46 | 用户清单 §11 | 仅文档；脚本行为不变 | **已实施**：`docs/spec/08_fulfillment.md` §5.2、§6、§7.2、§8 均以实跑值为准；不复制既有文档原文 |
| 12 | 05 | 视频数值字段非法 / JSON 损坏 / 编码不可读 → traceback + exit 1 | 全部输入异常统一 `status=INPUT_ERROR` + exit 2，无 traceback | 无人值守指令阶段 2.5 | 05 视频 spec 解析与数值校验；成功路径不变 | **已实施**：`asset_check.py` 的 `video_number()`、`run_video()` 异常分支；测试 `tests/test_creative.py::InputErrorTests` 四条 |
| 13 | 01 | 同价且 Σ销量=0 → `ZeroDivisionError` exit 1 | 转业务告警：`meta.status="WARNING"`、`price_bands=[]`、exit 0 | 无人值守指令阶段 2.5 | market 该边界；其他样本输出不变 | **已实施**：`market_metrics.py` 的 `price_bands()`/`compute()`；测试 `tests/test_selection.py::BaselineTests::test_market_metrics_same_price_zero_sales_warns` |
| 14 | 05 | `--fix` 指向原图会覆盖源文件 | 拒绝覆盖，`status=INPUT_ERROR` + exit 2 | 无人值守指令阶段 2.5 | 05 `--fix` 同路径分支；其他路径不变 | **已实施**：`asset_check.py` 的 `run_image()`；测试 `tests/test_creative.py::InputErrorTests::test_fix_same_path_rejected` |

补充说明（#7 与 #11 的编号对应）：
- #7 04 A+ 模块顺序：基线实现未校验模块顺序。新行为——补上顺序校验，缺必需模块或顺序错误判 FAIL。依据：用户清单 §7；影响面：04 A+ 校验结果（原先可通过的组合可能转为 FAIL）。本轮状态：已实施（见上表第 7 行）。

### 明确不修（保持基线行为）
- 01 粗筛用 4.75 估 FBA、02 精算 5.93：分层设计，非 bug。
- 03 `CONDITIONAL=1` / `BLOCKED=2` / 未知类目 `=3`：已文档化。
- 06/07/08 业务告警退出 0：业务语义（07 仅新增可选开关）。
- 不做任何重构、命名、目录调整。
