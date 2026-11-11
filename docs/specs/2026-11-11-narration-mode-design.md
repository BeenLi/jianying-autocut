# 后期旁白模式设计

日期：2026-11-11
状态：待审阅
前置：[拍摄脚本 + 按故事剪辑](2026-11-10-shoot-plan-modes-design.md)（PR #3）

## 1. 目标

支持"先录旁白，画面跟着旁白剪"的片子：旁白决定节奏和时长，Claude 按旁白每句话的内容配画面，
旁白的间隙里可以插入原声（出镜口播、现场声）。拍摄脚本（模式 A）里也写旁白稿，录音时当提词器，
录完后用稿子对齐转写结果，自动找出重录和口误。

### 用户已确认的决定

| 问题 | 决定 |
|---|---|
| 谁先谁后 | 先录旁白，画面跟着剪；旁白决定节奏 |
| 录音形式 | 一整段（含口误、重录）或按章节分文件，两种都支持；多文件按文件名排序 |
| 原声 | 旁白间隙可插入原声段（`live`），插入时旁白暂停、时间线顺延；旁白下的原声压低垫底 |
| 和模式 A | 打通：脚本里写旁白稿，以"句"为单位 |
| 实现思路 | 新增 `narrate.py`，绕开 `plan.py`，直接产出 `shots.csv`；`build.py` 加 `--narration` |
| BGM | 全片稳定：默认停在"压低"档，只在有意标注（`bgm: up/drop`）或长空隙处变化；人声按来源归一化，不逐句动 BGM |
| 剪切方式 | 画面领先旁白开口 0.3s（J-cut）；同一素材不相邻 |
| 阈值 | 都给参数，用户可调 |

### 不做（本 spec 范围外）

- 动画 / 特效 / 转场轨：pyJianYingDraft 支持，但依赖剪映在线资源，先单独做 spike 验证 11.6 兼容性，再另开 spec。
- AI 配音 / TTS。
- 自动降噪、自动压限（剪映里手动做）。
- 定长模式（`--target`）：旁白片时长由旁白决定。

## 2. 架构

```
旁白录音（1 个或多个文件）
  │ transcribe.py --narration <文件或目录>
  ▼
W/narration_speech.json     {文件名: [{start,end,text,words}]}  文件内秒，不做重复过滤
  │ Claude 读它 + 旁白稿（有模式 A 时）+ scene_notes + speech.json → 写初稿 / 发页面确认
  ▼
W/narration_plan.json
  │ narrate.py --work W [--dry-run]
  ▼
W/shots.csv（字段不变，kind 新增 narr / live） + W/narration_track.json（成片时间）
  │ build.py --narration W/narration_track.json [--bgm …] [--subs …] [--titles]
  ▼
剪映草稿：主轨 / 旁白 / 字幕 / 章节标题 / BGM
```

`plan.py`、`story.py`、`match.py` 不改。`beatsync.py` 检测到 `W/narration_track.json` 时拒绝运行
（它会按节拍伸缩镜头，和"旁白锁死时长"冲突），提示用 `--bgm`。

## 3. 转写旁白：`transcribe.py --narration`

- 输入一个文件或一个目录（目录里取音频/视频扩展名的文件，按文件名排序），不要求在 `inventory.csv` 里。
- 复用 Whisper 调用、`--context` 提示、`no_speech_prob` 过滤；**关掉**同句重复过滤（`MAX_REPEAT`）和提示词回声过滤——旁白里同一句出现多次是重录，不是幻听。
- 开 `word_timestamps=True`，每句带 `words: [{start,end,word}]`。
- 同时对每个旁白文件跑 `probe.analyze_audio` 的静音检测，存进 `narration_speech.json` 的 `silences` 字段。
- 输出 `W/narration_speech.json`：`{"files": {"n1": "/abs/01_开场.m4a"}, "lines": {"n1": [...]}, "silences": {"n1": [[a,b], …]}}`。文件 id 按排序后的顺序编 `n1, n2, …`，重跑时同路径保持同 id。

## 4. `narration_plan.json`

```json
{
  "files": {"n1": "/abs/旁白/01_开场.m4a"},
  "chapters": [{"id": "ch1", "title": "出发"}],
  "items": [
    {"id": "L01", "type": "line", "chapter": "ch1", "file": "n1", "start": 0.4, "end": 5.2,
     "text": "凌晨四点，我们从山脚出发。",
     "visuals": [{"clip_id": "c003", "at": 12.0}, {"clip_id": "c004"}]},
    {"id": "L02", "type": "line", "chapter": "ch1", "file": "n1", "start": 6.0, "end": 8.1,
     "text": "凌晨四点，我们……", "skip": true, "skip_reason": "重录，取下一遍"},
    {"id": "V01", "type": "live", "chapter": "ch1", "clip_id": "c007", "start": 30.6, "end": 36.8,
     "reason": "到顶时大家的欢呼", "bgm": "drop"}
  ]
}
```

- `items` 是扁平有序列表，就是成片顺序；`chapter` 只是标签（生成章节标题）。
- 旁白时间存"文件 + 文件内秒"，不存全局秒；全局时间每次由 `narrate.py` 重算。
- `line.visuals` 为空列表 = 延续上一个镜头（报告里列出"没配画面的句子"）。
- `live` 的 `start/end`：Claude 填值时在原声句子外前留 0.4s、后留 0.3s（钳在素材范围内、不跨进别的句子），让环境声先进来。
- 可选字段：`skip` / `skip_reason`（不进成片，保留以便恢复）、`bgm: "up" | "drop"`、`pause_after`（秒，覆盖自动算出的句后停顿）。
- 重录句：相似度（`difflib` ≥ 0.8）的相邻几遍默认取最后一遍，其余 `skip`；有旁白稿时以和稿子对齐的结果为准（§7.3）。

### 校验（`narrate.py` 开头，错误列全再退出）

文件 id 不存在 / 文件不存在；`start >= end`；`end` 超出文件长度；`clip_id` 不在 inventory；
`at` 不在素材范围；`live` 区间超出素材；`chapter` 未定义；`bgm` 取值非法；`id` 重复。
`bgm: "up"` 落在 `line` 上：⚠ 并忽略（人声会被盖住）。

## 5. `narrate.py`：排时间线、铺画面

核心是纯函数 `layout(plan, clips, opts) -> (rows, track, report)`：不读写文件、不用随机数；
`main` 负责读文件、调用、写输出或 `--dry-run` 打印。

### 5.1 旁白音频段（"连续块"）

- 同一文件里相邻、都不 `skip`、中间没有 `live` 的句子合成一个**连续块**，作为一段音频放进旁白轨——句间停顿保留真实的房间底噪，不出现数字静音。
- 块的边界：首句开头向前、末句结尾向后，各**扩到最近的静音**（`silences`），最多扩 0.3s；**永不内缩**（Whisper 边界误差 ±0.2–0.5s，内缩会吃字）。
- 块内停顿压缩：停顿 `p` 变成 `clamp(p × --pause-ratio, --pause-min, --pause-max)`（默认 0.6、0.3s、1.2s）；`pause_after` 覆盖。需要缩短时，从停顿**中间**剪掉一截，块在剪口处拆成两段音频，两侧各留至少 `--pause-min / 2` 的底噪，剪口两侧各 15ms 淡变。
- 块与块之间：同文件内被 `live` 隔开时间隔为 0；跨文件间隔 `--file-gap`（默认 1.2s）。
- 片头在第一段旁白前留 `--head`（默认 1.0s，只有画面），片尾在最后一项后留 `--tail`（默认 1.5s）。
- 每段音频首尾 15ms 淡入淡出（落在已扩出的余量里，不切字）。

### 5.2 画面槽

- 每个 `line` 的槽：从它在成片里"开口时刻 − `--lead`（默认 0.3s，J-cut）"到下一项槽的起点。第一项的槽从 0 开始（含 `--head`），最后一项的槽到成片结尾（含 `--tail`）。
- `live` 的槽就是它自己的 `[start, end]`，画面和声音同步；它前面那一项的槽到 `live` 起点为止。
- 所有槽首尾相接，主轨零缝隙。

### 5.3 放置顺序和规则

1. **先放全部 `live`**：画面严格取 `[start, end]`，不吸附、不挑窗口，直接占用素材的 `used`；范围内有坏帧 ⚠ 但不改。
2. **再放 `line` 的画面**（按成片顺序）：
   - 槽长按 `visuals` 个数平分；每个 visual 是一个**连续镜头**，不设硬上限。
   - 有 `at`：`place_pin(c, at, d)`，调用方把结果写进 `c.used`（`place_pin` 本身不写）。
   - 无 `at`：`c.best_window(d)`。
   - 放置时把素材的 `silences` 置空（narr 镜头原声只是垫底，静音吸附没意义，还会挪走最佳窗口）。
   - 放不下（太短 / 坏帧 / 已占用）：把时长交给下一个 visual；都放不下时依次回退到 **相邻句的 visuals** → **本章出现过的所有素材**（`pick_one`），回退的镜头在报告里 ⚠"这句没配到你指定的画面"，并打印所选素材的场景描述，方便发现语义错位。整章无可用素材：报错退出。
   - 素材选择对"对镜说话"的窗口降权（`speech.json` 里有句子的区间分数 × 0.5），避免画面里人在张嘴而声音是旁白。
3. **约束**：同一素材的两个镜头不能在成片里相邻（相邻时把后一个换成同槽或回退里的别的素材）；镜头短于 `MIN_SHOT`（2s）就并进前一个镜头；`kind` 一律写 `narr` / `live`（`pick_one` 会改成 short/mid，要覆盖）。
4. 复用 `plan.py` 的 `load_clips`、`Clip`、`place_pin`、`pick_one`、`GAP`、`REUSE_DECAY`、`MIN_SHOT`，以及 `write_shots`（会删掉旧的 `shots.prebeat.csv`）。

### 5.4 输出

- `W/shots.csv`：字段同 `plan.FIELDS`，`chapter_title` 取 `chapters[].title`，`chapter_function` 留空。
- `W/narration_track.json`（成片时间，整数微秒）：
  ```json
  {"audio": [{"file": "/abs/01_开场.m4a", "src_us": 300000, "start_us": 700000, "dur_us": 4900000,
              "fade_in_us": 15000, "fade_out_us": 15000, "gain": 1.6}],
   "subs":  [{"start_us": 1000000, "dur_us": 4800000, "text": "凌晨四点，我们从山脚出发。"}],
   "live":  [{"start_us": 21300000, "dur_us": 6200000, "clip_id": "c007", "gain": 1.0}],
   "bgm":   [{"start_us": 21300000, "dur_us": 6200000, "mode": "drop"}],
   "total_us": 98000000}
  ```
  字幕时间用句子本身的 `start/end`（不含扩出的余量），长句按标点拆成不超过 16 字一条。
- `--dry-run`：打印每项的成片时间、配了哪些镜头（含场景描述）、跳过的句子和原因、⚠ 列表、总时长，不写文件。

## 6. 混音

### 6.1 `build.py --narration`

| 声音 | 轨道 | 规则 |
|---|---|---|
| 旁白 | 新增音频轨"旁白"，按 `audio` 逐段 | 音量 = 归一化增益（§6.2），段首尾淡变 |
| 原声 · `narr` 镜头 | 主轨 | 垫底音量 `NARR_BED`：按该素材实测响度折算到比人声目标低 18 LU，上限 0.15；`--volume` 覆盖 |
| 原声 · `live` 镜头 | 主轨 | 归一化增益（§6.2）；在切点上直接跳变，不加关键帧 |
| BGM | 原 BGM 轨，只支持 `--bgm` | 见下 |

- **BGM 默认停在压低档**：基础电平就是"压低后"的电平，全片一致。只在两种地方升起：项标了 `bgm: "up"`，或没有人声的空隙 ≥ 4s（片头、片尾、长 `live` 无人声段）。`bgm: "drop"` 期间淡到 0。升降都是关键帧：压低 0.3s，升起 0.8s。
- 压低档的具体电平由实测反推：让每一处人声比同时段 BGM 短时响度高至少 12 LU（§6.3），取全片最保守的那个值，**整片一个值**；各首歌先按实测增益拉到同一响度。
- `duck_keyframes` 加参数 `merge_gap` 和 `ramp_up`（默认值保持现状），旁白模式另写一个"基础压低 + 例外升起"的关键帧生成函数，不改现有口播模式的行为。
- **原声音量只由 `kind` 决定**：`--narration` 下不再用 `talks`（字幕重叠）判断；`--subs` 仍可给 `live` 段加字幕，与旁白字幕放在同一条字幕轨。
- **verify**：按轨道名核对——旁白段数 == `audio` 条数、BGM 段数照旧；新增"每段旁白都在成片范围内"、"每个 `line` 的槽起点 == 其开口时刻 − lead"。

### 6.2 人声归一化（按来源，不逐句）

- 来源 = 每个旁白文件、每个 `live` 素材。用 ffmpeg `ebur128` 测积分响度（`live` 只测 `speech.json` 里有句子的区间）和真峰值。
- 增益 = `-16 LUFS − 实测`，上限 +12 dB，且使真峰值 ≤ −1 dBTP。同一来源内所有段同一个增益。
- 达不到 -16 LUFS 时不动 BGM，报告"这个文件 / 这段原声太小，建议重录或在剪映里处理"。
- `live` 段人声比底噪高不到 15 dB：不提升，报告"现场太吵"。
- 结果缓存在 `W/loudness.json`，键为 `路径 + mtime + size`。

### 6.3 逐句校验（只报告）

每句人声（旁白句、`live` 里的句子）对比同时段 BGM 的 3s 短时响度（取最大值），差值 < 12 LU 的列出来：
成片第几秒、差多少、在哪首歌的哪一段；建议把这首歌的 `--bgm` 音量整体调低。现有口播模式（`--subs`）也接上这个校验。

### 6.4 需要真机验证

- 剪映 11.6 是否接受 `volume > 1`（+12 dB ≈ 4 倍）。验证前，增益 > 1 的情况在报告里标"待验证"；如果不接受，改为上限 1.0、其余全部报告。
- 旁白轨音频段的 `add_fade`、主轨视频段的音量关键帧在剪映里是否正常。

## 7. 和模式 A 打通：旁白稿

### 7.1 数据（页面 db）

- 新集合 `lines/<L01…>`：`{chapter, order, kind: "narr" | "live", text, shots: [shot_id], est_s, edited_by_user: []}`
  - `narr`：旁白稿，写完整句子（旁白可以照念，不同于口播只写要点）。
  - `live`：这里要让原声说话，`shots` 指向对应的 `talk` 或现场声镜头。
  - `est_s` 按 4 字/秒估算。
- 现有 `shots` 不变；`talk` 镜头是 `live` 的候选。
- 剪辑阶段新集合 `nmatch/<line_id>`：`{file, start, end, skip, skip_reason, visuals: [{clip_id, at}], confidence, reason, confirmed, by}`。

### 7.2 页面

- 拍摄视图：每章下多一栏"旁白稿"，可增删改句子、关联镜头；旁白估算时长和所关联镜头的计划时长差距大时提示（例如 20s 旁白只配了一个 6s 镜头）。
- 新"录音稿"视图：按章分组、大字号、每句后标估算秒数，录音时当提词器。
- 剪辑视图：旁白片显示每句的 🟢 已确认 / 🟡 待确认 / 🔴 没配到画面，点开看候选缩略图，确认 / 换素材 / 改秒数 / 标跳过。
- 不覆盖规则沿用 `shoot_plan.md`：`if_version`、只 `update`、`edited_by_user`、已确认的不改。

### 7.3 用稿子对齐转写

有旁白稿时，把 `narration_speech.json` 的句子按文字和稿子逐句对齐（字符级 `difflib`）：

- 对上同一句稿子的多遍录音：取最后一遍，其余 `skip`（`skip_reason: "重录"`）。
- 对不上任何稿子的转写句：默认 `skip`（`skip_reason: "稿外：口误或闲聊"`），用户可在页面上恢复。
- 稿子里没被录到的句子：报告"漏录"。
- 没有旁白稿时（用户直接录）：按 §4 的相似度规则处理重录，另把含"重来 / 不对 / 再来一遍"的句子标 `skip`。

### 7.4 导出

`ArtifactData list` 读出 `lines`、`nmatch`、`chapters` → 写 `W/narration_plan.json`（`items` 按章节 order、句子 order 排序，`live` 句展开为 `live` 项）→ 跑 `narrate.py --dry-run` 给用户看。

## 8. 文件清单

| 文件 | 变更 |
|---|---|
| `scripts/transcribe.py` | 加 `--narration` 入口 |
| `scripts/narrate.py` | 新增 |
| `scripts/loudness.py` | 新增：ebur128 测量、缓存、增益计算（`build.py` 调用） |
| `scripts/build.py` | `--narration`、关键帧生成、按 kind 定原声音量、verify 改造、响度校验 |
| `scripts/beatsync.py` | 检测到旁白模式拒跑 |
| `assets/shoot_plan_page.html` | 旁白稿、录音稿视图、旁白片剪辑视图 |
| `references/narration.md` | 新增：旁白模式完整指南 |
| `references/shoot_plan.md` | 加 `lines` / `nmatch` 集合 |
| `SKILL.md`、`README*.md` | 模式表加"旁白片"；"不做"里删掉后期旁白，加特效轨 |
| `tests/test_narrate.py`、`tests/test_loudness.py`、`tests/test_build.py`、`tests/test_transcribe.py` | 新增 / 扩充 |

## 9. 测试

`layout` 用手造的 `Clip(row, frames, silences)` 单测，不依赖真实素材：

- 时间线：单文件连续块、块内停顿按比例压缩、从停顿中间剪、跨文件间隔、`live` 打断、head/tail、`pause_after` 覆盖。
- 边界：只向外扩到静音、不内缩、扩展不超过 0.3s。
- 画面：槽首尾相接覆盖全片；J-cut 槽起点 = 开口 − lead；`live` 原样；先 live 后 line 不重叠；`place_pin` 结果写进 `used`；放不下时的回退顺序；同素材不相邻；短于 2s 并入；`kind` 覆盖；对镜说话降权；整章无素材报错。
- 校验：§4 每一条错误。
- 转写：`--narration` 下重复句不被过滤；稿子对齐的取最后一遍、稿外句、漏录。
- 响度：增益计算（上限、真峰值封顶）、缓存命中、逐句校验阈值；BGM 关键帧"基础压低 + 例外升起"、`drop`、不对称 ramp。
- build：旁白轨段数、原声音量按 kind、verify 新规则；`beatsync` 拒跑。
- 页面 JS：沿用 PR #3 的 node harness，测 `lines` / `nmatch` 的写入和草稿保留。

端到端（真实素材、剪映 11.6 打开）放进备忘里的端到端验证清单，和模式 A/B 一起跑。
