# 05 创意素材规格校验 —— 规格冻结（clean-room 重写基线）

> 对象：`Agents/05_Creative_Agent/scripts/asset_check.py`
> 无配置文件；平台阈值与人工检查清单内嵌在脚本中。图片像素项依赖 Pillow，缺省时降级。
> 所有退出码/计数均来自实跑（Python 3.12 + Pillow 10.4.0 / Windows PowerShell 5）。

## 1. 范围与脚本

- 职责：
  - 图片模式：校验单张商品图的文件大小、扩展名、像素尺寸、长宽比、Amazon 主图边缘白底、主体占比，并给出人工复核清单。
  - 视频模式：按 `--spec` 的 JSON 规格校验分辨率、比例、时长、首帧、字幕、格式、帧率，并给出人工复核清单。
  - `--fix`：仅图片，做「近白拉纯白 + 补正方形白底画布」，不做抠图、不生成缺失内容。
- 依赖：Python 标准库；可选 `PIL.Image`、`PIL.ImageChops`。无上游 JSON/YAML 依赖。
- 退出码：`0=通过（可含 WARN）`、`1=存在 FAIL`、`2=输入缺失/不可读/参数错误`。

## 2. CLI 契约

无子命令；图片用位置参数，视频用 `--spec`，两者互斥。

| 参数名 | 类型 | 必填 | 默认值 | 取值范围/枚举 | 说明 |
|---|---|---|---|---|---|
| `image`（位置参数） | path | 与 `--spec` 二选一 | 无 | 任意文件路径 | 待检查图片；扩展名参与格式校验。只能出现一个 |
| `--spec` | path | 与 `image` 二选一 | 无 | JSON 文件 | 视频规格；字段见 §3.2 |
| `--platform` | enum | 是 | 无 | `amazon_us` / `tiktok_us`（按字典序） | 决定图片/视频阈值与人工清单 |
| `--fix` | path | 否 | 无 | 输出文件路径 | 仅图片；生成修正图后**重新检查修正图** |
| `--json` | flag | 否 | false | — | 输出机器可读 JSON |

冲突与优先级（任一命中即 exit 2，不执行检查）：

1. `image` 与 `--spec` 同时给出 → `[INPUT_MISSING] <image> 与 --spec 只能二选一`。
2. 两者都不给 → `[INPUT_MISSING] 缺少 <image> 或 --spec`。
3. `--spec` 与 `--fix` 同时给出 → `[INPUT_MISSING] --fix 仅用于图片，不能与 --spec 同用`。
4. `--fix` 需要 Pillow；未安装 → `[INPUT_MISSING] --fix 需要 Pillow，当前未安装`。
5. `--fix` 模式下源图片不存在 → `[INPUT_MISSING] 找不到图片: …`，exit 2。
6. 不给 `--fix` 时源图片不存在 → 生成一条 `FILE_NOT_FOUND` FAIL，退出码 **2**（旧实现 1；本批 #2 已实施，输出形态不变）。
7. `--fix` 输出路径与源图片相同（含大小写/相对路径差异）→ `[INPUT_ERROR] --fix 输出路径不能与原图相同，请改用其他输出路径: …`，exit 2（#14；旧实现会覆盖原图）。
8. `--platform` 缺失/非法由 argparse 处理，exit 2，无统一 JSON。

## 3. 输入契约

### 3.1 图片

- 路径存在且为文件；不校验 MIME，仅按扩展名（小写、去掉点）判断格式。
- 平台输入约束汇总：

| 平台 | 允许扩展名 | 大小上限 | 可上传长边 | 放大镜长边 | 推荐长边 | 比例要求 | 白底检查 | 主体阈值 |
|---|---|---|---|---|---|---|---|---|
| `amazon_us` | jpg/jpeg/png/tif/tiff/gif | 10 MB | 500 | 1000 | 1600 | 1:1 推荐（仅 WARN） | 边缘 2% 近白 ≥98% | 最长边占画面 ≥80% FAIL 区间 |
| `tiktok_us` | jpg/jpeg/png/webp | 5 MB | 800 | 800 | 1080 | 1:1 或 3:4 | 不检查 | 最长边占画面 ≥60% |

- 读取像素时统一转为 RGB：`RGBA/LA/P` 先合成到白色背景，其余直接 `convert("RGB")`。
- 动图检测：`Image.open(path).is_animated` 为真即 FAIL（GIF/WebP 动图）。
- 编码无关（二进制）；无文件头魔数校验。

### 3.2 视频规格 JSON

`utf-8-sig` 读取；顶层必须是对象。必填 8 字段，缺失/`null`/空串即 `INPUT_MISSING`（exit 2）：

| 字段 | 类型（转换） | 必填 | 说明 |
|---|---|---|---|
| `width` | int | 是 | 画面宽（像素） |
| `height` | int | 是 | 画面高（像素） |
| `duration_sec` | float | 是 | 时长（秒） |
| `fps` | float | 是 | 帧率 |
| `format` | string | 是 | 容器格式；转小写并去掉前导 `.` |
| `has_subtitles` | bool | 是 | 是否含字幕；按 `bool()` 强转 |
| `first_frame_product` | bool | 是 | 首帧是否出现产品；按 `bool()` 强转 |
| `aspect_ratio` | string | 是 | 声明的比例，去空格后比较（如 `9:16`、`9x16`、`0.5625`） |

- 额外字段忽略；数值字段用 `int()/float()`，非数字字符串会抛 `ValueError`（未捕获，退出码 1 + traceback，见 §6）。
- 布尔字段**不做字符串解析**：`"false"`、`"0"`、`"no"` 均为真值（实测 `"false"` 被判为已声明）。
- 缺失字段的错误消息按固定顺序列出：`height, duration_sec, fps, format, has_subtitles, first_frame_product, aspect_ratio`（`width` 缺失时会出现在列表首位）。

## 4. 输出契约

### 4.1 成功 JSON

```
{
  mode: "image" | "video",
  platform: "amazon_us" | "tiktok_us",
  file: <被检查文件：图片原路径 / --fix 输出路径 / spec 路径>,
  source_file: <图片原图路径> | null,   // 图片模式恒为 args.image；--fix 时仍指向原图，视频为 null
  verdict: "PASS" | "WARN" | "FAIL",
  counts: { "PASS": n, "WARN": n, "FAIL": n },   // findings 条数
  findings: [ { level, code, field, message } ],
  manual_checks: string[],               // 平台人工复核清单
  meta: {
    pillow: true|false,
    rules_basis: "编写时公开口径，发布前按卖家中心复核",
    image_limits: { upload_min_edge, zoom_min_edge, recommend_edge, max_mb, square, formats[] },
    fix_scope: "近白拉纯白 + 补正方形画布，不做抠图" | null
  }
}
```

- `mode=video` 时 `source_file=null`，`image_limits` 仍按平台输出，`fix_scope=null`。
- `manual_checks` 在图片模式由 `MANUAL_IMAGE[platform]` 追加；Pillow 缺失时只追加文本、仍输出该清单。视频模式追加 `MANUAL_VIDEO[platform]`。

人类可读（stdout）：

```
图片规格检查 · Amazon US
文件: <path>
[PASS] IMAGE_FILE_SIZE (image): 文件 0.12 MB，≤10 MB
[PASS] IMAGE_FORMAT (image): 格式 .png 允许
[FAIL] SUBJECT_TOO_SMALL (image): 主体最长边占画面 75.1%，低于 80%（官方要求约 85%）
[MANUAL] 主图不得出现文字、水印、边框、二维码、非售配件
总判定: FAIL (FAIL 1 / WARN 0 / PASS 5)
口径: 编写时公开口径，发布前按卖家中心复核。
```

- 首行按 `mode` 显示「图片/视频规格检查」；平台名固定 `Amazon US` / `TikTok Shop US`。
- Pillow 缺失且为图片模式时，会产出一条普通 finding `[WARN] PILLOW_MISSING (image): Pillow 未安装，跳过尺寸/比例/白底/主体占比等像素项；安装后重跑`，**计入 counts**（实测 `{PASS:2, WARN:1, FAIL:0}`，exit 0）。旧文档曾描述为「不计入 counts 的额外行」，实测为计数 finding，此处以实测为准。

### 4.2 失败契约

所有输入错误均为 stdout 上的 JSON（`--json` 时）或同文案纯文本；**stderr 为空**，且 JSON **没有 `missing` 键**：

```
{"status":"INPUT_MISSING", "message":"..."}
```

- **阶段 2.5 变更（#12）**：视频 spec 的全部解析异常统一 `{"status":"INPUT_ERROR", ...}` + exit 2：
  - JSON 语法错误 → `[INPUT_ERROR] JSON 解析失败: …`
  - 非 UTF-8 编码 → `[INPUT_ERROR] 文件编码不可读（需 UTF-8）: <path>`
  - 其他读取失败 → `[INPUT_ERROR] 文件无法读取: <path>`
  - 顶层非对象 → `[INPUT_ERROR] 顶层必须是 JSON 对象`
  - 数值字段非数字/bool → `[INPUT_ERROR] 视频数值字段非法：width='abc'（必须为数字）`
  - 仍为 `INPUT_MISSING` 的：文件不存在、缺字段（`缺少字段: …`）。
- 文件不存在 → `[INPUT_MISSING] 找不到文件: …`。
- **本批新增（#3）**：损坏/不可解码图片、0 尺寸图片、视频 0 宽或 0 高，统一输出 `{"status":"INPUT_ERROR", "message":"[INPUT_ERROR] …"}`，exit 2，不再抛 traceback。消息模板：
  - `[INPUT_ERROR] 图片无法解码（文件损坏或非图片）: <path>`
  - `[INPUT_ERROR] 图片尺寸非法（0 像素）: <path>（0x500）`
  - `[INPUT_ERROR] 视频尺寸非法：0×1920（宽高必须为正数）`
- `--fix` 指向原图 → `[INPUT_ERROR] --fix 输出路径不能与原图相同，请改用其他输出路径: <path>`，exit 2（#14）。

### 4.3 退出码矩阵

| 场景 | exit | 关键输出 |
|---|---|---|
| 图片：全部 PASS / 仅 WARN | 0 | `verdict=PASS/WARN` |
| 图片：任一 FAIL（不含缺图） | 1 | `verdict=FAIL` |
| 图片：缺图（无 `--fix`） | **2** | 仍为单条 `FILE_NOT_FOUND` FAIL（#2）；与「任一 FAIL → 1」分道 |
| 图片：损坏 / 不可解码 / 0 尺寸 | **2** | `status=INPUT_ERROR`（#3） |
| 视频：全部 PASS | 0 | `verdict=PASS`；TikTok 样例 7 条 PASS |
| 视频：任一 FAIL | 1 | `verdict=FAIL`；Amazon 9:16 样例 1 FAIL + 6 PASS |
| 视频：宽或高为 0 | **2** | `status=INPUT_ERROR`（#3） |
| 视频：数值字段非数字 / JSON 损坏 / 编码不可读 | **2** | `status=INPUT_ERROR`（#12） |
| 图片：`--fix` 指向原图 | **2** | `status=INPUT_ERROR`，拒绝覆盖（#14） |
| 缺 image 与 spec / 两者同给 / spec+fix / fix 缺 Pillow / fix 源图不存在 | 2 | `status=INPUT_MISSING` |
| spec 不存在 / 缺字段 | 2 | `status=INPUT_MISSING` |
| `--platform` 缺失或非法 | 2 | argparse usage 到 stderr；无 JSON |

## 5. 计算规则

### 5.1 图片

1. 文件大小：`size_mb = bytes / (1024 * 1024)`；`> max_mb` → FAIL `IMAGE_FILE_TOO_LARGE`，否则 PASS `IMAGE_FILE_SIZE`。消息保留 2 位小数。
2. 格式：扩展名不在允许集合 → FAIL `IMAGE_FORMAT`；否则 PASS。
3. Pillow 缺失：产出一条 WARN `PILLOW_MISSING`（计入 counts），仅完成大小与格式检查，追加人工清单，不再做像素项；`verdict=WARN`、exit 0。
4. 动图：`is_animated` 为真 → FAIL `IMAGE_ANIMATED`（不中断后续检查）。
5. 长边 `long_edge=max(width,height)`：
   - `< upload_min_edge` → FAIL `IMAGE_TOO_SMALL`
   - 否则 `< zoom_min_edge` → WARN `IMAGE_NO_ZOOM`
   - 否则 `< recommend_edge` → WARN `IMAGE_BELOW_RECOMMENDED`
   - 否则 PASS `IMAGE_SIZE`
   - 阈值：Amazon 500/1000/1600；TikTok 800/800/1080。
6. 比例 `ratio=width/height`：
   - Amazon：`|ratio-1|>0.01` → WARN `IMAGE_ASPECT`（推荐正方形，不硬性）；否则 PASS。
   - TikTok：`|ratio-1|≤0.01` PASS 1:1；否则 `|ratio-0.75|≤0.0075` PASS 3:4；否则 FAIL。
7. Amazon 边缘白底：取 `band=max(1, round(min(w,h)*0.02))` 的四条边带，统计三通道均 ≥240 的像素占比；`<0.98` → FAIL `MAIN_EDGE_NOT_WHITE`，否则 PASS。TikTok 不做该检查。
8. 主体包围盒：与纯白逐像素差、转灰度、阈值 `>15` 得 mask，取 bbox；无 bbox → FAIL `SUBJECT_NOT_FOUND`。`box_ratio=max(bbox_w,bbox_h)/max(w,h)`：
   - Amazon：`<0.80` FAIL；`<0.85` WARN；`>0.98` WARN；否则 PASS。
   - TikTok：`<0.60` FAIL；否则 PASS。
9. `--fix`：对每个通道 `≥240 → 255`；画布边长 `side=max(w,h)`，白底，居中粘贴；扩展名 `.jpg/.jpeg` 保存 JPEG（quality=92），其余一律保存 PNG。输出一条 PASS `FIX_SAVED`；随后对修正图重跑 1–8，`file` 指向修正图，`source_file` 保留原图。修正不改变主体包围盒比例，可能仍 FAIL。

容差与取整速查：

| 项 | 公式/阈值 | 取整与容差 |
|---|---|---|
| 文件大小 | `bytes/1048576` | 显示 2 位小数；等于上限算通过 |
| 长边档位 | `max(w,h)` 与 500/1000/1600 或 800/800/1080 比较 | 等于阈值算进入下一档 |
| 正方形 | `abs(w/h-1)` | 严格 `≤0.01`；Amazon 超出仅 WARN |
| 3:4 | `abs(w/h-0.75)` | `≤0.0075`，即约 0.7425–0.7575 |
| 白底边带 | `band=max(1, round(min(w,h)*0.02))` | Python 银行家舍入；四带并集可能重叠，按遍历像素重复计数 |
| 白底像素 | `R,G,B` 均 `≥240` | 占比严格 `<0.98` 才 FAIL |
| 主体 mask | 灰度差 `>15` | 差异恰为 15 不算主体 |
| 主体占比 | `max(bbox_w,bbox_h)/max(w,h)` | Amazon `<0.80` FAIL、`<0.85` WARN、`>0.98` WARN；TikTok `<0.60` FAIL |
| `--fix` 拉白 | 单通道 `≥240` 独立判断 | 不按亮度加权，只逐通道抬升 |
| 视频比例容差 | TikTok `0.5625*1%=0.005625`；Amazon 16:9 `±1%`、1:1 `±0.01` | 恰好等于边界算 PASS |

示例：1600×1600、主体 1200×1200 → `box_ratio=1200/1600=0.751` → Amazon `SUBJECT_TOO_SMALL`；800×800 → 长边 800 在 `[800,1080)` → `IMAGE_BELOW_RECOMMENDED`；1080×1920 → `ratio=0.5625`，TikTok 比例 PASS、Amazon 比例 FAIL。

### 5.2 视频

统一：`ratio=width/height`；`format` 已转小写去点；`fps` 为浮点。

| 检查 | Amazon US | TikTok Shop US |
|---|---|---|
| 比例 | 16:9（相对容差 1%）或 1:1（绝对容差 0.01）→ PASS，否则 FAIL `VIDEO_ASPECT` | 9:16=0.5625，`abs(ratio-0.5625) > 0.5625*1%` → FAIL |
| 分辨率 | `min(w,h)<720` → WARN `VIDEO_RESOLUTION`；否则 PASS | `w<720 或 h<1280` → FAIL；否则不等于 1080×1920 → WARN `VIDEO_RESOLUTION_RECOMMENDED`；否则 PASS |
| 时长 | `>60s` → FAIL；否则 PASS（无下限） | `<9s 或 >60s` → FAIL；否则 PASS |
| 首帧 | 未声明 → WARN | 未声明 → FAIL `VIDEO_FIRST_FRAME` |
| 字幕 | 未声明 → WARN | 未声明 → WARN；已声明 PASS |
| 声明比例字段 | 不检查 | 不在 `{"9:16","9x16","0.5625"}` → WARN `VIDEO_ASPECT_FIELD` |
| 格式 | 不在 `mp4/mov` → WARN；否则 PASS（两平台相同） | 同左 |
| 帧率 | `<24 或 >60` → WARN；否则 PASS（两平台相同） | 同左 |

- `check_video` 的返回值不被使用；最终结论只由 findings 汇总。
- 每条检查只产出一条 finding；通过项也计 PASS，因此 `counts.PASS` 是「通过检查条数」，不是检查项总数。

### 5.3 汇总

`verdict = FAIL if counts.FAIL>0 else (WARN if counts.WARN>0 else PASS)`；退出码 `1 if counts.FAIL>0 else 0`。WARN 不影响退出码。

常见组合的汇总结果（实测）：

| 场景 | findings 构成 | verdict → exit |
|---|---|---|
| Amazon 1600×1600、主体 75.1% | PASS 5 + FAIL 1（`SUBJECT_TOO_SMALL`） | FAIL → 1 |
| TikTok 800×800、主体 87.5% | PASS 4 + WARN 1（`IMAGE_BELOW_RECOMMENDED`） | WARN → 0 |
| Amazon 800×800 纯白 | PASS 4 + WARN 1（`IMAGE_NO_ZOOM`）+ FAIL 1（`SUBJECT_NOT_FOUND`） | FAIL → 1 |
| 图片不存在 | FAIL 1（`FILE_NOT_FOUND`） | FAIL → **2**（#2） |
| TikTok 规范样例视频 | PASS 7 | PASS → 0 |
| Amazon 用 9:16 视频 | PASS 6 + FAIL 1（`VIDEO_ASPECT`） | FAIL → 1 |

## 6. 已知行为与坑（现状）

| # | 现象 | 触发条件 | 现状行为（实测） | 建议 |
|---|---|---|---|---|
| 1 | ~~缺图片退出码与文档不符~~ | `image` 路径不存在、未给 `--fix` | **已实施 #2**：仍输出单条 `FILE_NOT_FOUND` FAIL、`verdict=FAIL`、`manual_checks=[]`，但退出码改为 **2** | 已解决（输出形态不变，只改退出码） |
| 2 | FAIL/WARN 判定导致 exit 1 | 任一 FAIL | 例：1600×1600 主体 75.1% → `SUBJECT_TOO_SMALL` FAIL，exit 1；视频 Amazon 9:16 → `VIDEO_ASPECT` FAIL，exit 1 | 保留 |
| 3 | 仅 WARN 也 exit 0 | 无 FAIL | 例：TikTok 800×800 → `IMAGE_BELOW_RECOMMENDED` WARN，exit 0 | 保留 |
| 4 | 缺入参 exit 2 | 无 image/spec、两者同给 | `status=INPUT_MISSING`，`message` 明确；无 `missing` 键 | 建议补 `missing` |
| 5 | `--fix` 与 `--spec` 互斥 | 同时给 | exit 2，message「--fix 仅用于图片…」 | 保留 |
| 6 | `--fix` 会重查修正图 | 任一图片 | `FIX_SAVED` PASS + 修正图全部检查；`source_file` 仍为原图；修正图可能仍 FAIL（实测 SUBJECT_TOO_SMALL 保留） | 保留，文档需写明 |
| 7 | `--fix` 无法修复主体占比/白底之外的问题 | 主体太小、图片过小 | 只拉白与补方，不改裁切/主体大小 | 保留 |
| 8 | `--fix` 输出扩展名与真实编码可能不符 | `--fix out.webp` | 非 jpg/jpeg 一律按 PNG 写盘，文件扩展名可能仍是 `.webp` | 建议按扩展名编码 |
| 9 | 视频布尔字段按真值强转 | `"has_subtitles":"false"` | `bool("false")=True` → PASS；`"first_frame_product":"false"` 同样 PASS | 必须修正（解析 true/false） |
| 10 | ~~视频坏 JSON 的状态名不一致~~ | spec 语法错误 | **已实施 #12**：`status=INPUT_ERROR`，message 前缀 `[INPUT_ERROR]`，exit 2 | 已解决 |
| 11 | 错误信息走 stdout | 全部输入错误 | 非 JSON 模式也是 stdout；stderr 为空 | 建议改 stderr |
| 12 | ~~数值字段非法会 traceback~~ | `width:"abc"` | **已实施 #12**：`status=INPUT_ERROR`「视频数值字段非法：width='abc'（必须为数字）」，exit 2 | 已解决 |
| 13 | Pillow 缺失只降级不失败 | 环境无 Pillow | WARN `PILLOW_MISSING`，跳过像素/比例/白底/主体项，exit 0 | 保留（但需提示复核） |
| 14 | 动图仅在图片模式检测 | GIF/WebP 动图 | `IMAGE_ANIMATED` FAIL；静态 GIF 可过格式 | 保留 |
| 15 | TikTok 允许 3:4 | 比例 0.75±0.0075 | PASS，但分辨率仍按 800 长边/1080 推荐判定 | 保留 |
| 16 | Amazon 正方形只是推荐 | 非 1:1 | 仅 WARN `IMAGE_ASPECT`，不 FAIL | 保留 |
| 17 | 边缘白底是近似判定 | 主图背景非纯白但有渐变 | 边带 2% 内三通道 ≥240 占比 <98% → FAIL；可能误伤/漏判 | 保留，需人工复核 |
| 18 | 主体检测对纯白图失效 | 整图接近白 | `SUBJECT_NOT_FOUND` FAIL；小图同时出现 `IMAGE_TOO_SMALL` 与 `SUBJECT_NOT_FOUND` | 保留 |
| 19 | `meta.image_limits.formats` 是数组 | JSON 输出 | 元组被序列化为数组（`["jpg",…]`） | 保留 |
| 20 | 视频模式也输出 `image_limits` | `mode=video` | 与平台对应的图片阈值仍在 meta 中；`fix_scope=null` | 保留 |
| 21 | `--platform` 无统一错误出口 | 缺失/非法 | argparse usage 到 stderr，exit 2，stdout 空 | 建议统一 |
| 22 | 视频最低时长缺省 | Amazon 短视频 | 只校验 `>60s`，0.1s 也 PASS | 产品确认是否补下限 |
| 23 | `--fix` 会自动创建输出目录 | 输出目录不存在 | `os.makedirs(..., exist_ok=True)` 后写文件，不报错 | 保留 |
| 24 | ~~损坏/伪装图片会 traceback~~ | 扩展名合法但内容不可解码 | **已实施 #3**：`status=INPUT_ERROR`、message「图片无法解码（文件损坏或非图片）」、exit 2，无 traceback | 已解决 |
| 25 | ~~数值 0 能过必填但会除零~~ | `height=0`（或宽高均为 0） | **已实施 #3**：视频宽高 ≤0 → `status=INPUT_ERROR`「视频尺寸非法」exit 2；图片解码后尺寸 ≤0 → `status=INPUT_ERROR`「图片尺寸非法（0 像素）」exit 2 | 已解决 |
| 26 | ~~`--fix` 输出可与输入同路径~~ | `--fix` 指向原图 | **已实施 #14**：`status=INPUT_ERROR`「--fix 输出路径不能与原图相同…」，exit 2，不覆盖原图 | 已解决 |

## 7. 对拍基准（必须可复现）

统一前缀：

```powershell
$env:PYTHONIOENCODING='utf-8'
```

### 7.1 视频

1. **TikTok 样例（PASS，exit 0）**

```powershell
python Agents/05_Creative_Agent/scripts/asset_check.py --spec Agents/05_Creative_Agent/examples/video_spec.json --platform tiktok_us --json
```

期望：exit 0；`mode=video`；`verdict=PASS`；`counts={PASS:7,WARN:0,FAIL:0}`；`file` 为 spec 路径；`source_file=null`；findings 依次为 `VIDEO_ASPECT`、`VIDEO_RESOLUTION`、`VIDEO_DURATION`、`VIDEO_FIRST_FRAME`、`VIDEO_SUBTITLES`、`VIDEO_FORMAT`、`VIDEO_FPS`；`manual_checks` 3 条 TikTok 视频项。

2. **同一样例按 Amazon（FAIL，exit 1）**

```powershell
python Agents/05_Creative_Agent/scripts/asset_check.py --spec Agents/05_Creative_Agent/examples/video_spec.json --platform amazon_us --json
```

期望：exit 1；`verdict=FAIL`；`counts={PASS:6,WARN:0,FAIL:1}`；唯一 FAIL 为 `VIDEO_ASPECT`（1080×1920 为 9:16，Amazon 只接受 16:9 或 1:1）。

3. **字符串布尔（现状 PASS，exit 0）**

```powershell
$s='{"width":1080,"height":1920,"duration_sec":30,"fps":30,"format":"mp4","has_subtitles":"false","first_frame_product":"false","aspect_ratio":"9:16"}'
[System.IO.File]::WriteAllText("$env:TEMP\strbool_spec.json",$s)
python Agents/05_Creative_Agent/scripts/asset_check.py --spec "$env:TEMP\strbool_spec.json" --platform tiktok_us --json
```

期望：exit 0；`verdict=PASS`；`VIDEO_SUBTITLES`、`VIDEO_FIRST_FRAME` 均为 PASS（暴露布尔强转缺陷）。

4. **spec 错误**

```powershell
python Agents/05_Creative_Agent/scripts/asset_check.py --spec no-such.json --platform tiktok_us --json
$bad='{"width":1080}'
[System.IO.File]::WriteAllText("$env:TEMP\bad_spec.json",$bad)
python Agents/05_Creative_Agent/scripts/asset_check.py --spec "$env:TEMP\bad_spec.json" --platform tiktok_us --json
python Agents/05_Creative_Agent/scripts/asset_check.py --spec Agents/05_Creative_Agent/examples/video_spec.json --platform tiktok_us --fix "$env:TEMP\x.png" --json
```

期望：三条均 exit 2；第一条 message「找不到文件」，第二条「缺少字段: height, duration_sec, fps, format, has_subtitles, first_frame_product, aspect_ratio」，第三条「--fix 仅用于图片…」。

### 7.2 图片（仓库无现成图片，用 Pillow 生成可复现样本）

```powershell
python -c "from PIL import Image, ImageDraw; bg=Image.new('RGB',(1600,1600),(255,255,255)); d=ImageDraw.Draw(bg); d.rectangle([200,200,1400,1400],fill=(200,200,200)); bg.save(r'$env:TEMP\img_amz.png')"
python -c "from PIL import Image, ImageDraw; bg=Image.new('RGB',(800,800),(255,255,255)); d=ImageDraw.Draw(bg); d.rectangle([50,50,750,750],fill=(180,180,180)); bg.save(r'$env:TEMP\img_tt.png')"
```

1. **Amazon 1600×1600，主体 75.1%（FAIL，exit 1）**

```powershell
python Agents/05_Creative_Agent/scripts/asset_check.py "$env:TEMP\img_amz.png" --platform amazon_us --json
```

期望：exit 1；`verdict=FAIL`；`counts={PASS:5,WARN:0,FAIL:1}`；FAIL 为 `SUBJECT_TOO_SMALL`（主体最长边 75.1% <80%）；`IMAGE_SIZE`、`IMAGE_ASPECT`、`MAIN_EDGE_WHITE` 均 PASS；`manual_checks` 4 条。

2. **TikTok 800×800，主体 87.5%（WARN，exit 0）**

```powershell
python Agents/05_Creative_Agent/scripts/asset_check.py "$env:TEMP\img_tt.png" --platform tiktok_us --json
```

期望：exit 0；`verdict=WARN`；`counts={PASS:4,WARN:1,FAIL:0}`；WARN 为 `IMAGE_BELOW_RECOMMENDED`（800 <1080）；`IMAGE_ASPECT` PASS 1:1；`SUBJECT_RATIO` PASS ≥60%。

3. **图片不存在（FAIL，exit 2）**

```powershell
python Agents/05_Creative_Agent/scripts/asset_check.py no-such.png --platform amazon_us --json
```

期望：exit 2（#2，旧实现为 1）；`verdict=FAIL`；`counts={PASS:0,WARN:0,FAIL:1}`；唯一 finding `FILE_NOT_FOUND`；`manual_checks=[]`；无 `missing` 键。

4. **`--fix` 重查（exit 1）**

```powershell
python Agents/05_Creative_Agent/scripts/asset_check.py "$env:TEMP\img_amz.png" --platform amazon_us --fix "$env:TEMP\fixed_amz.png" --json
```

期望：exit 1；`file` 指向修正图、`source_file` 指向原图；findings 首条 `FIX_SAVED` PASS；`SUBJECT_TOO_SMALL` 仍存在；`meta.fix_scope="近白拉纯白 + 补正方形画布，不做抠图"`。

5. **缺入参（exit 2）**

```powershell
python Agents/05_Creative_Agent/scripts/asset_check.py --platform amazon_us --json
python Agents/05_Creative_Agent/scripts/asset_check.py "$env:TEMP\img_amz.png" --spec Agents/05_Creative_Agent/examples/video_spec.json --platform amazon_us --json
python Agents/05_Creative_Agent/scripts/asset_check.py no-such.png --platform amazon_us --fix "$env:TEMP\fixed.png" --json
```

期望：前两条 exit 2（缺少入参 / 两者互斥）；第三条 exit 2、message「找不到图片」（`--fix` 分支在检查前直接返回，与不带 `--fix` 的 exit 2 同码但输出形态不同）。

## 8. 未完整刻画 / 待确认

- ~~视频数值字段（`width:"abc"`、`duration_sec:null`）的异常路径未逐项实测~~ → 已探测并实施 #12：`width:"abc"` 旧实现 `ValueError` traceback、exit 1；新实现 `INPUT_ERROR` + exit 2。
- ~~`--fix` 覆盖原图、损坏图片、零尺寸的异常路径仅按代码推导~~ → 已探测：损坏图 / 0 尺寸在 `--fix` 路径同样走 `INPUT_ERROR` + exit 2（#3）；`--fix` 指向原图已改为拒绝覆盖 + exit 2（#14）。
- `--fix` 对透明 PNG、渐进 JPEG、CMYK 输入的实际输出质量未验证。
- 动图检测对 WebP/APNG 的支持依赖 Pillow 版本，未单独构造样本。
- 边缘 2% 边带的实际取样边界（宽/高取整）未做像素级对拍。
- Amazon/TikTok 官方阈值均为「编写时公开口径」，未与卖家中心最新规则逐条核对。
- `manual_checks` 的文案被视为展示内容，重写时是否逐字保留需产品确认。
- `--platform` 缺失时的 argparse 输出不属于统一错误契约，未纳入 JSON 对拍。
- 静态 WebP 的实际解码与 `is_animated` 取值依赖 Pillow 编译选项，未验证。
- 0×0 图片无法用 Pillow 真实构造（`Image.save` 拒绝），0 尺寸分支由 `unittest.mock` 伪造 `Image.size` 覆盖，见 `tests/test_creative.py`。

### 8.1 探测记录（probe，2026-10-30）

旧实现 = `e:\SKILLS\supply-to-shelf-skills\Agents\05_Creative_Agent\scripts\asset_check.py`，全部命令均带 `$env:PYTHONIOENCODING='utf-8'`。

| # | 命令要点 | 旧实现观察 | 新实现结论 |
|---|---|---|---|
| 1 | `no-such.png --platform amazon_us --json` | exit 1、`FILE_NOT_FOUND` FAIL、`manual_checks=[]`、stderr 空 | #2：输出不变，exit 2 |
| 2 | `no-such.png --platform amazon_us --fix out.png --json` | exit 2、`status=INPUT_MISSING`、message「找不到图片」 | 保留 exit 2 |
| 3 | 文本文件改名 `.png`，`--platform amazon_us --json` | `UnidentifiedImageError` traceback，exit 1，stdout 空 | #3：`INPUT_ERROR`「图片无法解码…」exit 2 |
| 4 | `height=0` 视频 spec | `ZeroDivisionError` traceback，exit 1 | #3：`INPUT_ERROR`「视频尺寸非法」exit 2 |
| 5 | `width:"abc"` 视频 spec | `ValueError` traceback，exit 1 | #12：`INPUT_ERROR`「视频数值字段非法」exit 2 |
| 6 | 300×300 全白 PNG | FAIL `IMAGE_TOO_SMALL` + `SUBJECT_NOT_FOUND`，counts `{PASS:4,WARN:0,FAIL:2}`，exit 1 | SAME |
| 7 | 1600×1600、主体占 87.5% | PASS 6、exit 0；主体 75.1% → `SUBJECT_TOO_SMALL`、counts `{PASS:5,WARN:0,FAIL:1}` | SAME |
| 8 | TikTok 800×800 | `IMAGE_BELOW_RECOMMENDED` WARN、exit 0 | SAME |
| 9 | 无 Pillow（`importlib` 屏蔽） | WARN `PILLOW_MISSING`、counts `{PASS:2,WARN:1,FAIL:0}`、exit 0 | SAME |
| 10 | 比例 4:5 / 9:16 / 3:4 各平台 | 各条 finding 文案与顺序逐字复刻 | SAME |
| 11 | 视频 spec 缺字段 / 非对象 / 语法错误 | 缺字段按 `VIDEO_FIELDS` 顺序拼接；语法错误 `status=INPUT_MISSING` + `[INPUT_ERROR]` 前缀；非对象「顶层必须是 JSON 对象」 | 缺字段 SAME；语法错误/非对象 → #12 改 `INPUT_ERROR` |
| 12 | `--fix` 嵌套不存在的输出目录 | 自动 `makedirs`，`FIX_SAVED` PASS，重查原 finding | SAME |
| 13 | spec 文件非 UTF-8（尾部非法字节） | `UnicodeDecodeError` traceback，exit 1 | #12：`INPUT_ERROR`「文件编码不可读（需 UTF-8）」exit 2 |
| 14 | `--fix` 指向原图 | 覆盖原图后重查，exit 1，JSON 内 `FIX_SAVED` | #14：拒绝覆盖，`INPUT_ERROR` exit 2 |

对拍 harness 将这些场景与 01 的场景一起固化在 `tests/compare_oracle.py`（05 共 21 例，阶段 2.5 新增 4 例）。

