# 后期旁白模式 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 支持"先录旁白、画面跟着旁白剪"：转写旁白 → `narration_plan.json` → `narrate.py` 产出 `shots.csv` + `narration_track.json` → `build.py --narration` 生成带旁白轨、稳定 BGM、响度归一化的剪映草稿；拍摄脚本页面加旁白稿。

**Architecture:** `narrate.py` 是和 `plan.py` 并联的第二个 `shots.csv` 生产者，核心是无 I/O 的纯函数（`timeline`、`layout`）。响度测量独立成 `loudness.py`，由 `build.py` 调用。`plan.py` / `story.py` / `match.py` 不改。

**Tech Stack:** Python 3.10+ 标准库（PEP 723，`uv run --script`），ffmpeg（`ebur128`、`silencedetect`），faster-whisper，pyJianYingDraft（锁定版本见 `run_tests.sh`），pytest（`./run_tests.sh`），单文件 HTML + Artifact `db`。

**Spec:** `docs/specs/2026-11-11-narration-mode-design.md`

## Global Constraints

- 所有内部时间为整数微秒（`common.US`）；JSON 里给人看的字段用秒，`narration_track.json` 用 `*_us`。
- `narrate.py`、`loudness.py` 依赖为空（`# dependencies = []`）；`transcribe.py`、`build.py` 依赖不变。
- 不改 `plan.py`、`story.py`、`match.py` 的行为；只 `import` 复用 `load_clips`、`Clip`、`place_pin`、`pick_one`、`write_shots`、`FIELDS`、`MIN_SHOT`、`REUSE_DECAY`。
- 现有模式行为不变：`duck_keyframes`、`speech_from_segments`、`verify` 新增参数都带默认值，默认值下输出与现在逐字节一致（现有测试全部不改且通过）。
- 默认值（全部可通过 CLI 调）：`--lead 0.3`、`--head 1.0`、`--tail 1.5`、`--pause-ratio 0.6`、`--pause-min 0.3`、`--pause-max 1.2`、`--file-gap 1.2`；边界外扩上限 0.3s；旁白淡变 15ms；字幕每条 ≤16 字；对镜说话降权 ×0.5。
- 混音：人声目标 -16 LUFS，增益上限 +12 dB，真峰值 ≤ -1 dBTP；人声 − BGM 短时响度 ≥ 12 LU；`NARR_BED` 上限 0.15、目标比人声低 18 LU；BGM 压低 0.3s、升起 0.8s；无人声空隙 ≥ 4s 才升；`live` 人声比底噪 < 15 dB 不提升。
- 文案与报错用中文；校验错误列全后 `sys.exit("…有问题：\n  " + "\n  ".join(errs))`。
- Ruling（相对 spec 的细化）：spec §5.4 把 `gain` 写进 `narration_track.json`；本计划改为 `narrate.py` 不测响度（保持纯函数），`gain` 由 `build.py` 调 `loudness.py` 算出——cost if wrong：多一次字段搬运。

## 数据格式（Task 1–5 共用）

`W/narration_speech.json`（Task 1 产出）：
```json
{"files": {"n1": "/abs/01_开场.m4a"},
 "durations": {"n1": 63.2},
 "lines": {"n1": [{"start": 0.4, "end": 5.2, "text": "凌晨四点，我们从山脚出发。",
                   "words": [{"start": 0.4, "end": 0.7, "word": "凌晨"}]}]},
 "silences": {"n1": [[0.0, 0.38], [5.3, 5.9]]}}
```

`W/narration_plan.json`：见 spec §4（`files`、`chapters`、`items`，`line` / `live`，可选 `skip`、`skip_reason`、`bgm`、`pause_after`）。

`W/narration_track.json`（Task 3 产出，`build.py` 消费）：
```json
{"audio": [{"fid": "n1", "file": "/abs/01_开场.m4a", "src_us": 300000, "start_us": 700000, "dur_us": 4900000,
            "fade_in_us": 15000, "fade_out_us": 15000}],
 "subs": [{"start_us": 1000000, "dur_us": 4800000, "text": "凌晨四点，我们从山脚出发。"}],
 "speech": [[1000000, 4800000]],
 "live": [{"start_us": 21300000, "dur_us": 6200000, "clip_id": "c007", "src_us": 30600000}],
 "bgm": [{"start_us": 21300000, "dur_us": 6200000, "mode": "drop"}],
 "total_us": 98000000}
```
`speech` = 所有人声区间（旁白句的开口到收口 + `live` 里 `speech.json` 的句子，成片时间），给 BGM 压低和响度校验用。

## Review Focus

1. 重录句夹在两句保留句中间（`skip` 在块内）→ 期望重录那一截音频不进成片：两侧保留句之间的剪口落在停顿中间，不残留半句重录。
2. `items` 顺序和文件内时间顺序不一致（用户把后录的句子挪到前面）→ 期望在乱序处断块、按跨块处理，不出现负时长音频段。
3. `line` 紧跟 `live` 时 J-cut 的槽起点会早于 `live` 结束 → 期望槽起点夹到 `live` 结束，`live` 画面不被截短。
4. 旁白片里没给 `--bgm`、或一个 `live` 都没有 → 期望照常生成，只有旁白 + 画面，verify 不误报。
5. `loudness.json` 缓存的文件被重录覆盖（同路径、mtime 变了）→ 期望重新测量，不用旧值。

---

### Task 1: transcribe.py 旁白入口

**Files:**
- Modify: `skills/jianying-autocut/scripts/transcribe.py`
- Modify: `skills/jianying-autocut/scripts/common.py`（加 `AUDIO_EXTS`）
- Test: `tests/test_transcribe.py`

**Interfaces:**
- Produces:
  - `speech_from_segments(segments, duration=None, prompt="", dedupe=True, words=False) -> list[dict]`：`dedupe=False` 时不做 `MAX_REPEAT` 和提示词回声过滤；`words=True` 时每句带 `words`（取 `segment.words` 的 `start/end/word`）。
  - `narration_files(path: str) -> list[str]`：文件则 `[abs]`；目录则其中扩展名属于 `AUDIO_EXTS | VIDEO_EXTS`、不以 `._` 开头的文件，按文件名排序，绝对路径。
  - `assign_file_ids(paths: list[str], old: dict[str, str]) -> dict[str, str]`：返回 `{fid: path}`；`old` 里已有的路径沿用原 id，新路径从 `max(old)+1` 起编 `n<k>`。
  - CLI：`transcribe.py --work W --narration <文件或目录> [--context …] [--model …] [--force]` → `W/narration_speech.json`（格式见上，`durations` 用 ffprobe 读，`silences` 用 `probe.analyze_audio`）。
- `common.AUDIO_EXTS = {".m4a", ".mp3", ".wav", ".aac", ".flac"}`

- [ ] **Step 1: 写失败测试**
  - `test_dedupe_false_keeps_retakes`：同一句出现 3 次，`dedupe=False` 保留 3 句；`dedupe=True` 结果与现在相同（0 句）。
  - `test_dedupe_false_keeps_prompt_echo_like_line`：和 prompt 相同的句子在 `dedupe=False` 下保留。
  - `test_words_attached`：假 segment 带 `words=[SimpleNamespace(start=0.1,end=0.4,word="你好")]`，`words=True` 时输出 `words == [{"start":0.1,"end":0.4,"word":"你好"}]`；`words=False` 时没有 `words` 键。
  - `test_narration_files_sorted_and_filtered`：tmp 目录里 `02.m4a`、`01.wav`、`._01.wav`、`a.txt` → `[01.wav, 02.m4a]` 的绝对路径。
  - `test_assign_file_ids_stable`：`old={"n1": "/a", "n2": "/b"}`，`paths=["/b", "/c", "/a"]` → `{"n1": "/a", "n2": "/b", "n3": "/c"}`。
- [ ] **Step 2:** `./run_tests.sh tests/test_transcribe.py -k "dedupe or words or narration or assign"` → FAIL（参数 / 函数不存在）。
- [ ] **Step 3:** 实现上述函数；`main` 加 `--narration` 分支（与素材转写互斥），逐文件转写、每个文件完成即 `_save`，已有结果且非 `--force` 跳过。
- [ ] **Step 4:** `./run_tests.sh` → 全部 PASS（含原有 transcribe 测试）。
- [ ] **Step 5:** `git commit -m "transcribe: add --narration entry for voiceover files"`

### Task 2: narrate.py 校验、初稿与时间线

**Files:**
- Create: `skills/jianying-autocut/scripts/narrate.py`
- Test: `tests/test_narrate.py`

**Interfaces:**
- Consumes: Task 1 的 `narration_speech.json` 格式。
- Produces:
  - `@dataclass Opts: lead=0.3, head=1.0, tail=1.5, pause_ratio=0.6, pause_min=0.3, pause_max=1.2, file_gap=1.2, edge_max=0.3, fade=0.015`（秒；内部用时乘 `US`）。
  - `validate(plan, clip_durs: dict[str, float], file_durs: dict[str, float]) -> (errs: list[str], warns: list[str])`：spec §4 的每条错误；`bgm:"up"` 在 `line` 上进 `warns`。
  - `mark_retakes(lines: list[dict]) -> list[dict]`：同文件内，某句与其后 3 句之内的某句 `difflib.SequenceMatcher(None, a, b).ratio() >= 0.8`（比较去标点后的文本）就标 `skip: true, skip_reason: "重录，取后一遍"`；含"重来 / 不对 / 再来一遍"的句子标 `skip_reason: "口头重来"`。返回新列表，不改入参。
  - `align_to_script(lines, script: list[dict]) -> (lines, missing: list[str])`：`script = [{"id","text"}]`；每句转写取 ratio 最高的稿子句，≥ 0.6 记 `script_id`；多句对上同一稿子句时只留最后一句，其余 `skip_reason: "重录"`；对不上的 `skip_reason: "稿外：口误或闲聊"`；没被对上的稿子 id 进 `missing`。
  - `draft_plan(speech: dict, script: list[dict] | None = None) -> dict`：按文件 id 顺序把每句变成 `line` 项（`id` 为 `L01…`，`visuals: []`，无 `chapter` 时用 `"ch1"` 并建一个 `chapters` 项），有 `script` 用 `align_to_script`，否则用 `mark_retakes`。
  - `timeline(plan, silences: dict[str, list], file_durs: dict[str, float], opts) -> dict`：返回 `{"audio": [...], "marks": [{"item": id, "mouth_us", "close_us"} | {"item": id, "live": True, "start_us", "end_us"}], "total_us"}`。`audio` 项格式同 `narration_track.json.audio`（不含 `file`）。

  时间线算法（spec §5.1）：
  ```
  cursor = head；遍历未 skip 的 items：
    live：start_us=cursor，cursor += end-start；当前块结束
    line：与"上一保留 line"同文件、中间无 live、且 start >= 上一句 end → 同块：
            p = start - prev.end（中间若隔着被 skip 的句子，p = min(该句 start - prev.end, start - 该句 end)）
            p' = pause_after 或 min(p, clamp(p*ratio, pmin, pmax))
            p' == p 且中间无 skip：音频段连续延伸
            否则：当前段结束于 prev.end + p'/2（源时间），新段从 start - p'/2 开始；cursor 相应推进
          否则新块：若上一项是 line 则 cursor += file_gap；
            块起点源时间 = max(start - edge_max, 上一个结束于 start 之前的静音的终点)，不晚于 start，不早于 0
          块收尾（遇到 live / 新块 / 结束）：终点源时间 = min(end + edge_max, 下一个起始于 end 之后的静音的起点, 文件长)
    mouth_us = 该句在成片里的位置 = 段 start_us + (line.start - 段 src)
  total_us = cursor + tail
  每段 fade_in/out = fade
  ```

- [ ] **Step 1: 写失败测试**（`tests/test_narrate.py`，用手造 `plan`/`silences`，无文件 I/O）
  - `test_validate_reports_all_errors`：一份同时含未知文件 id、`start>=end`、`end` 超文件长、未知 `clip_id`、`at` 越界、`live` 越界、未定义 `chapter`、非法 `bgm`、重复 `id` 的 plan → `errs` 恰好 9 条，各含对应 item id。
  - `test_validate_warns_bgm_up_on_line`。
  - `test_mark_retakes_keeps_last_take`：三句 "凌晨四点我们出发" / "凌晨四点，我们出发了" / "山很高" → 第 1 句 skip，第 2、3 句保留。
  - `test_mark_retakes_restart_keyword`。
  - `test_align_to_script_last_take_offscript_missing`：稿子 `[A,B,C]`，转写 `[A', A'', 闲聊, B']` → `A'` skip "重录"，`闲聊` skip "稿外…"，`missing == ["C"]`。
  - `test_timeline_continuous_block_keeps_short_pause`：两句间停顿 0.4s（×0.6=0.24 → 夹到 0.3 → min(0.4,0.3)=0.3）→ 两段音频，剪口在停顿中点两侧各 0.15s。
  - `test_timeline_pause_within_limits_stays_one_segment`：停顿 0.3s → 一段音频连续。
  - `test_timeline_skip_inside_block_cut_out`：A、retake(skip)、B → 两段音频，第一段源终点 < retake.start，第二段源起点 > retake.end。（Review Focus 1）
  - `test_timeline_out_of_order_breaks_block`：items 里 B（源 10–12s）在 A（源 20–22s）之后 → 两块、中间 `file_gap`、无负时长段。（Review Focus 2）
  - `test_timeline_edge_expand_to_silence_never_shrink`：句 start=1.0，静音 [0,0.85] → 块起点 0.85；静音 [0,0.5] → 0.7（上限 0.3）；句 start 处于静音内也不晚于 start。
  - `test_timeline_live_and_file_gap_and_head_tail`：`[line n1, live, line n2]` → live 前后无间隔，n2 块前无 file_gap（上一项是 live）；`total_us = 最后结束 + tail`；第一段 `start_us == head`。
  - `test_timeline_pause_after_override`。
- [ ] **Step 2:** `./run_tests.sh tests/test_narrate.py` → FAIL（模块不存在）。
- [ ] **Step 3:** 实现 `Opts`、`validate`、`mark_retakes`、`align_to_script`、`draft_plan`、`timeline`。
- [ ] **Step 4:** `./run_tests.sh tests/test_narrate.py` → PASS。
- [ ] **Step 5:** `git commit -m "narrate: validation, retake marking and voiceover timeline"`

### Task 3: narrate.py 铺画面、输出与 CLI

**Files:**
- Modify: `skills/jianying-autocut/scripts/narrate.py`
- Test: `tests/test_narrate.py`

**Interfaces:**
- Consumes: Task 2 的 `timeline`、`Opts`；`plan.Clip`、`plan.place_pin`、`plan.pick_one`、`plan.load_clips`、`plan.write_shots`、`plan.FIELDS`、`plan.MIN_SHOT`。
- Produces:
  - `slots(tl, plan, opts) -> list[dict]`：每个保留项一个 `{"item", "start_us", "end_us", "live": bool}`，首尾相接覆盖 `[0, total_us)`；`line` 槽起点 = `max(mouth - lead, 上一个 live 的结束)`，第一个槽从 0 开始。
  - `layout(plan, clips: dict[str, Clip], speech: dict, silences, file_durs, opts) -> (rows, track, report)`：`rows` 是 `plan.FIELDS` 格式的 shots 行；`track` 是 `narration_track.json` 的内容（含 `file`）；`report = {"fallback": [(item, clip_id)], "unpaired": [item], "skipped": [(item, reason)], "warns": [str]}`。
  - `split_sub(text, start_us, dur_us, max_chars=16) -> list[(start_us, dur_us, text)]`：按 `，。！？；、` 断句，超长再硬切；时长按字数比例分。
  - CLI：`narrate.py --work W [--draft [--script W/narration_script.json]] [--dry-run] [--lead …] …`。`--draft` 写 `W/narration_plan.json` 初稿（已存在则拒绝，需 `--force`）；否则读 plan、校验、`layout`、写 `shots.csv`（经 `write_shots`）和 `narration_track.json`，或 `--dry-run` 只打印。
- 放置（spec §5.3）：先把所有 `live` 写进对应素材 `used`；再按成片顺序处理 `line` 槽；放置前临时清空该素材 `silences`；`place_pin` 的结果由调用方 `c.used.append`；`pick_one` 返回的 `kind` 覆盖为 `narr`；对镜说话降权在调用 `best_window` 前通过临时把 `speech.json` 区间内帧的分数 ×0.5 实现（用后恢复）；回退顺序：本句其余 visuals → 前一句、后一句的 visuals → 本章所有出现过的素材（`pick_one`）；同素材相邻时换下一候选；`< MIN_SHOT` 的槽并进前一镜头。

- [ ] **Step 1: 写失败测试**
  - `test_slots_cover_timeline_without_gaps`：任意 plan 的槽首尾相接，首 0 尾 `total_us`。
  - `test_slot_jcut_start_is_mouth_minus_lead`。
  - `test_slot_after_live_clamped_to_live_end`。（Review Focus 3）
  - `test_live_shot_exact_range`：`live` 行 `in_us == start`、`dur_us == end-start`、`kind == "live"`。
  - `test_line_visual_respects_at_and_marks_used`：有 `at` 的 visual 窗口包含 `at`，且该区间出现在 `clip.used`。
  - `test_live_reserved_before_lines`：同一素材既做 `live` 又被 line 引用 → line 的窗口与 live 区间不重叠。
  - `test_fallback_order_and_report`：指定素材全是坏帧 → 用前一句的 visual，`report["fallback"]` 记一条。
  - `test_same_clip_never_adjacent`。
  - `test_short_slot_merged_into_previous`：1.2s 的槽不单独成镜头。
  - `test_kind_is_narr_after_pick_one`。
  - `test_talking_window_deprioritized`：素材前半段有 speech、两半帧分数相同 → 选后半段。
  - `test_chapter_without_clips_errors`。
  - `test_track_subs_split_long_line`：22 字的句子拆成 2 条，每条 ≤16 字，时长和等于句长。
  - `test_track_speech_and_bgm_marks`：`bgm:"drop"` 的 live 进 `track["bgm"]`；`speech` 含旁白句和 live 的 speech.json 句子（成片时间）。
  - `test_main_dry_run_writes_nothing` 与 `test_main_writes_shots_and_track`：tmp 工作目录造 `inventory.csv`、`narration_speech.json`、`narration_plan.json`，`main([...])` 返回 0；dry-run 下不产生文件；正式运行产生两个文件且删掉 `shots.prebeat.csv`。
  - `test_main_draft_refuses_overwrite`。
- [ ] **Step 2:** `./run_tests.sh tests/test_narrate.py` → 新测试 FAIL。
- [ ] **Step 3:** 实现 `slots`、`layout`、`split_sub`、`main`。
- [ ] **Step 4:** `./run_tests.sh` → 全部 PASS。
- [ ] **Step 5:** `git commit -m "narrate: lay picture under voiceover, write shots and track"`

### Task 4: loudness.py

**Files:**
- Create: `skills/jianying-autocut/scripts/loudness.py`
- Test: `tests/test_loudness.py`

**Interfaces:**
- Produces:
  - `parse_ebur128(stderr: str) -> {"i": float, "tp": float, "short": list[(t_s, S)]}`：解析 `ffmpeg -af ebur128=peak=true:framelog=verbose` 的逐帧行（`t: … S: …`）和 Summary 的 `I:`、`Peak:`。
  - `measure(path, start=None, end=None) -> dict`（调 ffmpeg，`-ss/-to`）。
  - `class Cache(work)`：`get(path, key_extra="")` / `put(...)`，存 `W/loudness.json`，键 = `f"{path}|{mtime}|{size}|{key_extra}"`。
  - `voice_gain(i, tp, target=-16.0, max_db=12.0, tp_max=-1.0) -> (gain_linear, short_db)`：`db = min(target - i, max_db, tp_max - tp)`；`short_db = max(0, target - i - db)`（>0 表示达不到目标）。
  - `bed_gain(clip_i, voice_target=-16.0, below=18.0, cap=0.15) -> float`。
  - `bgm_duck(levels: list[(song_base_db, s_max_under_speech)], voice=-16.0, margin=12.0, default=0.25) -> float`：返回全片统一的压低比例 `min(default, min_k 10^((voice - margin - (s_max + base_db))/20))`。
  - `margin_warnings(speech_spans, bgm_short_at, voice_levels, margin=12.0) -> list[str]`：`bgm_short_at(t_us) -> 该时刻 BGM 实际短时响度（已含增益与压低）`。
- [ ] **Step 1: 写失败测试**：用固定的 ffmpeg stderr 样例测 `parse_ebur128`；`voice_gain` 三种封顶（目标、+12、真峰值）各一例并检查 `short_db`；`bed_gain` 上限；`bgm_duck` 取最保守值且不超过 0.25；`margin_warnings` 阈值边界（11.9 报、12.0 不报）；`test_cache_invalidates_on_mtime`（写缓存后 `os.utime` 改 mtime → miss）。（Review Focus 5）
- [ ] **Step 2:** `./run_tests.sh tests/test_loudness.py` → FAIL。
- [ ] **Step 3:** 实现。
- [ ] **Step 4:** `./run_tests.sh tests/test_loudness.py` → PASS。
- [ ] **Step 5:** `git commit -m "loudness: ebur128 measurement, cache and gain rules"`

### Task 5: build.py --narration、BGM 稳定曲线、verify、beatsync 拒跑

**Files:**
- Modify: `skills/jianying-autocut/scripts/build.py`
- Modify: `skills/jianying-autocut/scripts/beatsync.py`（`main` 开头）
- Test: `tests/test_build.py`、`tests/test_build_main.py`、`tests/test_beatsync.py`

**Interfaces:**
- Consumes: Task 3 的 `narration_track.json`；Task 4 的全部函数。
- Produces:
  - `bgm_curve(speech, ups, drops, seg_start, seg_dur, base, duck, ramp_down=0.3s, ramp_up=0.8s, min_gap=4s) -> list[(off_us, vol)]`：基础电平 = `base*duck`；`ups` 区间及无人声空隙 ≥ `min_gap` 处升到 `base`；`drops` 区间降到 0；关键帧裁到片段内。
  - `duck_keyframes(..., merge_gap=None)`：`None` 时等价于现在的 `2*ramp`。
  - `verify(draft_dir, shots, versions, bgm_expected, narr_expected=0)`：按轨道名 `"BGM"` / `"旁白"` 分别计数。
  - CLI：`--narration W/narration_track.json`；与 `--bgm-plan` 互斥（报错"旁白片不卡点"）。
- 行为：旁白轨每段 `AudioSegment(volume=gain)` + `add_fade`；主轨 `narr` 镜头音量 `bed_gain`，`live` 镜头音量为该素材 `voice_gain`；`--narration` 下不使用 `talks` 判断；旁白字幕和 `--subs` 字幕同一条字幕轨；BGM 每首先按积分响度归一（只衰减，不提升）再乘 `--bgm` 音量；`bgm_duck` 定全片压低比例；最后打印 `margin_warnings` 和 `voice_gain` 的 `short_db` 报告；增益 > 1 的段在报告里标"待真机验证"。口播模式（`--subs`，无 `--narration`）也打印 `margin_warnings`。
- `beatsync.py`：`W/narration_track.json` 存在时 `sys.exit("这是旁白片：镜头时长由旁白决定，不能卡点。用 build.py --bgm 铺 BGM。")`。

- [ ] **Step 1: 写失败测试**
  - `test_bgm_curve_stays_ducked_through_short_gaps`：两句间 2s 空隙 → 无升起关键帧。
  - `test_bgm_curve_rises_on_long_gap_with_asymmetric_ramps`：6s 空隙 → 升起用 0.8s、压回用 0.3s。
  - `test_bgm_curve_drop_and_up`。
  - `test_duck_keyframes_default_unchanged`：现有两个 duck 测试不改仍 PASS，另加 `merge_gap=2*US` 合并 1.5s 间隔的用例。
  - `test_build_main_narration`（`test_build_main.py` 风格，monkeypatch `loudness.measure` 返回固定值）：草稿里有"旁白"轨且段数 == `audio` 条数；`narr` 镜头音量 == `bed_gain`；`live` 镜头音量 == 对应 `voice_gain`；字幕轨含旁白字幕；verify 通过。
  - `test_build_main_narration_without_bgm_or_live`。（Review Focus 4）
  - `test_build_rejects_narration_with_bgm_plan`。
  - `test_beatsync_refuses_narration_work`。
- [ ] **Step 2:** `./run_tests.sh tests/test_build.py tests/test_build_main.py tests/test_beatsync.py` → 新测试 FAIL。
- [ ] **Step 3:** 实现。
- [ ] **Step 4:** `./run_tests.sh` → 全部 PASS。
- [ ] **Step 5:** `git commit -m "build: voiceover track, steady BGM curve, loudness normalisation"`

### Task 6: 页面旁白稿与旁白片剪辑视图

**Files:**
- Modify: `skills/jianying-autocut/assets/shoot_plan_page.html`
- Test: node harness（`scratchpad/page_harness.js`，沿用 PR #3 的桩：`document`、`claude.use("db")` 内存实现）

**Interfaces:**
- db：`lines/<id>`、`nmatch/<id>`，字段见 spec §7.1。写入沿用页面现有的每路径队列、失败合并、`S.drafts`、`edited_by_user`。
- 视图：拍摄视图每章"旁白稿"栏（增删改、关联镜头、时长失衡提示：旁白估算 > 关联镜头计划时长 × 1.5 时提示）；新"录音稿"视图（按章、大字号、句后标秒数）；`plan/meta.kind == "narration"` 时剪辑视图按 `nmatch` 列句子（🟢/🟡/🔴，确认 / 换素材 / 改秒数 / 标跳过 / 恢复）。
- [ ] **Step 1:** harness 用例：新增句子写 `lines/<id>`；编辑中重渲染草稿不丢；失衡提示出现；`nmatch` 确认写 `confirmed:true, by:"user"`；标跳过写 `skip:true`；没有 `lines` 集合的旧页面数据照常渲染。先对旧页面跑 → FAIL。
- [ ] **Step 2:** 实现。
- [ ] **Step 3:** harness 全 PASS；发布一份示例数据的 Artifact 给用户在手机和 Mac 上看。
- [ ] **Step 4:** `git commit -m "page: narration script, teleprompter view and voiceover matching"`

### Task 7: 文档

**Files:**
- Create: `skills/jianying-autocut/references/narration.md`
- Modify: `skills/jianying-autocut/SKILL.md`、`references/shoot_plan.md`、`README.md`、`README.en.md`

内容：
- `narration.md`：完整流程（转写 → `--draft` → Claude 配 visuals 并发页面确认 → 导出 → `narrate.py --dry-run` → `build.py --narration`）、`narration_plan.json` 字段、各参数默认值及何时调、报告里每类 ⚠ 的含义和处理、`bgm: up/drop` 只在故事需要处建议并写明理由、"待真机验证"说明。
- `SKILL.md`：模式表加"旁白片"行和第 0 步问"有没有旁白录音"；"不做"删掉后期旁白，加"动画 / 特效 / 转场轨"。
- `shoot_plan.md`：`lines` / `nmatch` 集合、旁白稿写法（完整句子、4 字/秒）、导出步骤。
- README 两份：布局块加 `narrate.py`、`loudness.py`、`narration.md`。
- [ ] **Step 1:** 写文档。
- [ ] **Step 2:** `./run_tests.sh` → PASS；`grep -n "后期旁白" skills/jianying-autocut/SKILL.md` 不再出现在"不做"里。
- [ ] **Step 3:** `git commit -m "Document narration mode"`

### 端到端（不在本计划内执行）

真实旁白 + 素材跑通 A → 录音 → 剪辑 → 剪映 11.6 打开，验证 spec §6.4 两项；记入备忘 `shoot-plan-e2e-pending`，问题另开 PR。
