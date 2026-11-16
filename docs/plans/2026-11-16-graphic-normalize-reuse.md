# 图形素材、旁白响度归一化、画面重复使用 / 消音 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把枸杞岛端到端里手工绕过的三件事做成工具能力：
- `orient.py --graphic` 标记图形素材；
- 旁白先生成两遍 loudnorm 的 WAV 副本；
- 旁白片画面支持 `reuse` / `mute`。

另外，一槽末尾剩下的微小零头挤给下一句。

**Architecture:** 改动集中在四处：
- `plan.Clip`：新增 `edge`、`graphic`、`reuse_used` 和 `unconstrained()`；
- `narrate.layout` 的放置函数：处理 reuse、mute 和零头；
- 新模块 `normalize.py`：两遍 ffmpeg，由 `build.py` 调用；
- `build.py`：原文件换成副本，按镜头设 mute 音量。

页面测试脚本收进 `tests/page/`，由 pytest 调用 node 运行。

**Tech Stack:** Python 3.10+（PEP 723，`uv run --script`）、ffmpeg（`loudnorm`、`ebur128`）、pyJianYingDraft、pytest（`./run_tests.sh`）、node（页面测试，没装就跳过）。

**Spec:** `docs/specs/2026-11-14-graphic-normalize-reuse-design.md`（2026-11-16 修订版）

## Global Constraints

- 所有内部时间都是整数微秒（`common.US`）。JSON 里给人看的字段用秒。
- `normalize.py` 不依赖第三方库（`# dependencies = []`），只调 ffmpeg。
- 归一化参数：`loudnorm=I=-16:TP=-1.5:LRA=11`。第二遍带 `measured_I / measured_TP / measured_LRA / measured_thresh / offset` 和 `linear=true`。输出 `-ar 48000 -c:a pcm_s16le`（WAV）。
- 副本放在 `W/旁白_归一化/<原文件名去掉扩展名>.wav`。去掉扩展名后同名的，按原路径排序，依次加 `_n2`、`_n3`。
- 响度验收：副本用 ebur128 测，积分响度在 -16 ±0.7 LUFS 以内，真峰值 ≤ -1.5 dBTP。短文件（不到 3s）只要求提示「太小声，还差 N dB」。
- 图形素材：`edge = 0`，`frames = []`。相机素材的 `edge = EDGE`（0.5s）。常量 `EDGE` 保留。
- 零头阈值：`NUDGE_MAX = int(0.1 * US)`。只在下一槽是旁白句时挤过去。
- reuse 放开的限制只有两项：已占用的区间（`used`）、紧跟的同素材原声段（`next_live`）。前一个镜头的同素材相邻回避保留，同一句里 reuse 区间不重叠（靠 `reuse_used`）。
- mute 镜头的音量是 0，优先于 `--volume`。
- 不改 `beatsync.py`、`story.py` 的行为，也不改按镜头剪的片子（story_plan）的数据格式。
- 旧数据兼容：
  - 没有 `mute` 列的 `shots.csv`；
  - `visuals` 里没有 `reuse` / `mute` 的 `narration_plan.json`；
  - 没有 `graphic` 的 `orientation.json`。
  
  这三种读进来时行为都和现在一样。
- 文案和报错用中文。每个任务先写失败测试、看着它失败，再实现。

## Review Focus

1. 旧的 `shots.csv`（没有 `mute` 列）直接给 `build.py --narration` 用：不报错，所有垫底音量照旧。测试放在 Task 5。
2. 零头的下一槽是原声段，或者本槽是最后一槽：不挤，照旧处理，`_rows_ok` 仍然通过。测试放在 Task 3。
3. 本机没有 ffmpeg 时跑 `build.py --narration`：退出，并说明是归一化失败，不能静默引用原文件。测试放在 Task 8。
4. 页面上旧的 `nmatch.visuals`（没有 `reuse` / `mute`）：照常渲染，勾选框都不勾，点「确认」不会写出 `reuse: undefined`。测试放在 Task 6。
5. reuse 画面所用的素材本身是图形素材（`edge = 0`）：能放到第 0 秒，而且不污染 `used`。测试放在 Task 4。

---

### Task 1: 页面测试收进仓库

**Files:**
- Create: `tests/page/scroll_harness.js`、`tests/page/minor_harness.js`、`tests/page/narration_harness.js`、`tests/page/write_harness.js`，内容从 scratchpad 的 `pagetest/scroll_harness.js`、`minor_harness.js`、`narration_harness.js`、`harness.js` 原样复制，脚本里不写死路径。
- Create: `tests/test_page.py`

**Interfaces:**
- Produces：每个 harness 用法都是 `node <harness> <页面路径>`，退出码 0 表示通过，最后一行打印结果 JSON。`tests/test_page.py` 对 `tests/page/*.js` 逐个参数化运行。

- [ ] **Step 1:** 复制 4 个 harness。检查每个都是从 `process.argv[2]` 读页面、失败时 `process.exit(1)`。缺失败退出的，在末尾补上 `process.exit(Object.values(R).every(Boolean) ? 0 : 1)`。
- [ ] **Step 2:** 写 `tests/test_page.py`：

```python
PAGE = ROOT / "skills/jianying-autocut/assets/shoot_plan_page.html"
@pytest.mark.skipif(shutil.which("node") is None, reason="没有 node")
@pytest.mark.parametrize("h", sorted((ROOT / "tests/page").glob("*.js")), ids=lambda p: p.stem)
def test_page_harness(h):
    r = subprocess.run(["node", str(h), str(PAGE)], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stdout + r.stderr
```

- [ ] **Step 3:** 运行 `./run_tests.sh tests/test_page.py -v`。Expected：4 个都 PASS。然后临时把页面里的 `listTop` 恢复逻辑删掉，确认 `scroll_harness` FAIL，再改回来。
- [ ] **Step 4:** Commit `test: page harnesses live in tests/page and run under pytest`

### Task 2: 图形素材（`orient.py --graphic`、`Clip.edge`）

**Files:**
- Modify: `skills/jianying-autocut/scripts/orient.py`（`build_orientation`、`main`）
- Modify: `skills/jianying-autocut/scripts/plan.py`（`Clip`、`snap_to_silence`、`load_clips`、`place_pin`、`place_pins`）
- Modify: `skills/jianying-autocut/scripts/narrate.py`（`_extend`、`_place_in_free_segment`，以及所有用到 `EDGE` 的地方）
- Modify: `skills/jianying-autocut/SKILL.md`（第 3 步）
- Test: `tests/test_orient.py`（没有就新建）、`tests/test_plan.py`、`tests/test_narrate.py`

**Interfaces:**
- Produces：
  - `build_orientation(frames, flip=(), unusable=(), bad=(), graphic=())`，输出里 `clips[cid]["graphic"] = True`。
  - `Clip(row, frames, silences, graphic=False)`，带属性 `.graphic` 和 `.edge`（图形素材为 0，否则为 `EDGE`）。
  - `snap_to_silence(a, d, silences, dur, edge=EDGE)`。
  - `load_clips(work)` 返回的 `Clip` 会按 `orientation.json` 设好 `graphic`，图形素材的 `frames` 为 `[]`。

- [ ] **Step 1: 失败测试**

```python
# tests/test_orient.py
def test_graphic_merges_after_flip_and_unusable():
    o = build_orientation({"c1": [1.0], "c2": [1.0], "c3": [1.0]}, flip=["c1"], unusable=["c2"], graphic=["c1", "c2", "c3"])
    assert o["clips"]["c1"]["graphic"] and o["clips"]["c1"]["rotate"] == 180
    assert o["clips"]["c2"]["graphic"] and o["clips"]["c2"]["unusable"] and o["clips"]["c3"] == {"graphic": True}
def test_graphic_unknown_clip_raises():
    with pytest.raises(ValueError): build_orientation({"c1": [1.0]}, graphic=["c9"])
# tests/test_plan.py
def test_graphic_clip_uses_full_length_and_ignores_frame_scores(tmp_path):
    # frames.csv 里 c1 全是坏帧；orientation 标 graphic → load_clips 后 frames==[]、edge==0、
    # place_pin(c, 0, c.dur) == (0, c.dur)；同目录相机素材 c2 的 edge == EDGE、frames 非空
```

先看一眼 `build_orientation` 现在怎么写 `rotate` 和 `unusable` 的字段，测试里的字段名按实际的来。

- [ ] **Step 2:** `./run_tests.sh tests/test_orient.py tests/test_plan.py -q`。Expected：新测试 FAIL（`unexpected keyword 'graphic'`）。
- [ ] **Step 3:** 实现。
  - `orient.py` 加 `--graphic` 参数（逗号分隔），在 flip / unusable / bad 之后用 `setdefault(cid, {})["graphic"] = True` 写入。
  - `Clip` 里 `EDGE` 的每一处都改成 `self.edge`。
  - `place_pin`、`place_pins` 的 cover 逻辑和提示文字都改成 `c.edge`。
  - `snap_to_silence` 用 `edge` 参数，`Clip.snap` 传 `self.edge`。
  - `narrate.py` 里用到 `EDGE` 的地方都改成 `c.edge`，`from plan import EDGE` 如果不再需要就删掉。
- [ ] **Step 4:** 全套 `./run_tests.sh`。Expected：全部 PASS，现有测试不改。
- [ ] **Step 5:** `SKILL.md` 第 3 步「方向」那一段加上 `--graphic`，写明适用场景：地图、片头卡片、录屏。Commit `orient/plan: --graphic clips skip quality judging and the 0.5s edge`

### Task 3: 零头挤给下一句（评审 C1）

**Files:**
- Modify: `skills/jianying-autocut/scripts/narrate.py`（`layout`）
- Test: `tests/test_narrate.py`

**Interfaces:**
- Consumes：Task 2 的 `Clip(..., graphic=True)`。
- Produces：常量 `NUDGE_MAX = int(0.1 * US)`。`layout` 可能把相邻两个旁白槽的分界提前不到 `NUDGE_MAX`，`report["items"]` 里的 `start_us` / `end_us` 反映提前之后的位置。

- [ ] **Step 1: 失败测试**

```python
def test_tiny_remainder_is_nudged_into_next_line():
    # 测试辅助 _clip 增加 graphic 参数（透传给 Clip）
    # 第一句的槽比 21.0s 的图形素材 g 长 31ms，后面紧跟一句旁白（画面 c2，60s）
    # 期望：第一句只有 g 一个镜头，长 21.0s；第二句的第一个镜头提前 31ms 开始；_rows_ok 通过；
    #      所有镜头 ≥ MIN_SHOT
def test_no_nudge_before_live_or_at_end():
    # 同样的 g，下一槽是 live，或者本槽是最后一槽：不挤（不提前），照旧处理（Review Focus 2）
```

句子的起止秒数要算到让槽长正好是 `21.0s + 31ms`：用 `_tl` 和 `slots` 先算出槽长，再反推参数，写死在测试里。

- [ ] **Step 2:** 运行上面两个测试。Expected：第一个 FAIL（第一句是 g 19.031s，再加一个借来的 2s 镜头），第二个 PASS。
- [ ] **Step 3:** 实现。处理零头的最后一个分支（入点往前挪、剪短之后）之前，先判断三个条件：
  - `0 < remaining < NUDGE_MAX`；
  - 本块是最后一块；
  - `k + 1 < len(sl)` 并且 `not sl[k + 1]["live"]`。

  三个都满足时：`s["end_us"] -= remaining`，`sl[k + 1]["start_us"] -= remaining`，`remaining = 0`。

  这一步必须放在 `_place_any(..., last=True)` 把这一块缩到「留 MIN_SHOT」**之前**：`_place_any` 的 last 分支在 `0 < remaining - d < NUDGE_MAX` 时不能缩短 d，要直接返回 d，把这段零头留给本步处理。
- [ ] **Step 4:** 全套测试 PASS。Commit `narrate: a sub-0.1s remainder at a slot's end moves into the next narration line`

### Task 4: reuse

**Files:**
- Modify: `skills/jianying-autocut/scripts/plan.py`（`Clip.reuse_used`、`Clip.unconstrained()`、`Clip.free`）
- Modify: `skills/jianying-autocut/scripts/narrate.py`（`validate`、`_try_place`、`_place_in_free_segment`、`_place_any`、`_extend`、`layout`）
- Test: `tests/test_narrate.py`

**Interfaces:**
- Consumes：Task 2 的 `c.edge`。
- Produces：
  - `Clip.reuse_used: list[(in_us, out_us)]`。
  - `Clip.unconstrained()`：上下文管理器。在里面 `free(a, d)` 只检查 `reuse_used`，不检查 `used`。
  - `_try_place(c, at, d, speech, reuse=False)` 和 `_place_in_free_segment(c, d, reuse=False)`：占用写进 `c.reuse_used if reuse else c.used`。
  - 镜头字典可以带 `"reuse": True`。`_extend(shot, extra, head=False)` 遇到它时增删的是 `reuse_used`。
  - `validate`：`reuse` 不是布尔值时报 `"{id}：visuals 的 reuse 要写 true / false"`。

- [ ] **Step 1: 失败测试**

```python
def test_reuse_visual_ignores_live_occupancy():
    # c022 整段被原声段 V 占用；前一句 L 的 visuals=[{"clip_id": "c022", "reuse": True}]，L 紧跟在 V 之前
    # 期望：L 用了 c022（不回退）；V 的 used 区间不变；c022.used 里没有 L 的区间
def test_reuse_does_not_allow_adjacent_with_previous_shot():
    # 前一句以 c1 结尾，本句 visuals=[{"clip_id": "c1", "reuse": True}, {"clip_id": "c2"}]
    # 期望：本句第一个镜头不是 c1（前一个镜头的同素材回避仍然生效）
def test_two_reuse_visuals_of_same_clip_do_not_overlap():
def test_remainder_merges_into_reuse_shot_without_error():   # _extend 处理 reuse 镜头
def test_reuse_visual_on_graphic_clip_starts_at_zero():      # Review Focus 5
def test_validate_rejects_non_bool_reuse_and_mute():         # Task 5 共用：mute 同理
```

- [ ] **Step 2:** 运行。Expected：全部 FAIL（第一个回退到别的素材，`_extend` 抛 `list.remove` 错误，等等）。
- [ ] **Step 3:** 实现。
  - `_place_any` 遇到 `v.get("reuse")` 时：在 `with c.unconstrained():` 里面再计算 `longest_free`，再放置，放置时传 `reuse=True`；avoid 只去掉 `next_live`。
  - 镜头字典加上 `"reuse": True`。
  - 借用路径生成的是新的 `{"clip_id": …}`，本来就不会带上 reuse。
- [ ] **Step 4:** 全套测试 PASS。Commit `narrate: visuals.reuse lets a line reuse a clip already used by a live item`

### Task 5: mute（`shots.csv` 一列，`build` 按镜头设音量，dry-run 标注）

**Files:**
- Modify: `skills/jianying-autocut/scripts/plan.py`（`FIELDS` 末尾加 `"mute"`）
- Modify: `skills/jianying-autocut/scripts/narrate.py`（`layout` 产出镜头带 `mute`、`rows` 写入 `mute`、`report["items"][*]["shots"]` 加一个 flags 字段、`_print_report`）
- Modify: `skills/jianying-autocut/scripts/build.py`（`narration_mix` 里垫底响度的测量范围、`main` 镜头循环里的 `vol`）
- Test: `tests/test_narrate.py`、`tests/test_build_main.py`

**Interfaces:**
- Produces：
  - `shots.csv` 多一列 `mute`，值是 `""` 或 `"1"`。
  - `report["items"][*]["shots"]` 的元素从三元组变成 `(cid, in_us, dur_us, flags)`，`flags` 是 `{"reuse"?, "mute"?}` 里的布尔值。
  - `--dry-run` 在这类镜头行尾标「（重复用）」「（消音）」。

- [ ] **Step 1: 失败测试**

```python
# test_narrate
def test_mute_flag_reaches_shot_rows_and_dry_run():
    # visuals=[{"clip_id": "c1", "mute": True}] → rows[0]["mute"] == "1"；同素材其它镜头 ""；dry-run 输出含「（消音）」
# test_build_main（沿用现有的 narration build 夹具）
def test_muted_narr_shot_volume_zero_even_with_volume_flag():
    # shots.csv 里一个 narr 镜头 mute=1、一个不是；带上 --volume 0.3 → 前者音量 0，后者 0.3
def test_old_shots_csv_without_mute_column_builds():          # Review Focus 1
```

- [ ] **Step 2:** 运行。Expected：FAIL。
- [ ] **Step 3:** 实现。
  - `main` 镜头循环里：`kind == "narr"` 并且 `s.get("mute") in ("1", 1, True)` 时音量为 0，否则保持原来的表达式。
  - `narration_mix` 里，只出现在 mute 镜头里的素材不测垫底响度。
- [ ] **Step 4:** 全套测试 PASS。Commit `narrate/build: visuals.mute silences a shot's bed sound`

### Task 6: 页面勾选框

**Files:**
- Modify: `skills/jianying-autocut/assets/shoot_plan_page.html`（旁白编辑视图的画面卡片、新动作 `vflag-n`、`reassign-n`）
- Modify: `tests/page/narration_harness.js`（新增断言）

**Interfaces:**
- Produces：画面卡片里有两个勾选框，元素 id 是 `vr-<line>-<i>` 和 `vm-<line>-<i>`，点击触发动作 `vflag-n`，携带 `data-id`、`data-i`、`data-f`（`reuse` 或 `mute`）。动作把整个 `visuals` 写回 `nmatch/<id>`，带上 `by: "user"`；值为 false 时直接删掉这个字段，不写 `false`，也不写 `undefined`。

- [ ] **Step 1:** 在 harness 里加断言：
  - `vflagWrites`：点一下「消音」，写入 `visuals[0].mute === true`；
  - `oldVisualsRender`：没有这两个字段的旧 visuals 照常渲染，勾选框都不勾，点「确认」也不写出这两个字段（Review Focus 4）；
  - `reassignKeepsFlags`：同一素材只改 `at` 时保留这两个字段；
  - `reassignClearsFlags`：换了素材就清空。
- [ ] **Step 2:** `./run_tests.sh tests/test_page.py`。Expected：narration_harness FAIL。
- [ ] **Step 3:** 实现。`reassign-n` 判断 `clip === v0.clip_id`，相同就保留 `v0` 的 `reuse` 和 `mute`。
- [ ] **Step 4:** 页面测试全过。Commit `page: per-visual reuse / mute checkboxes in the narration editor`

### Task 7: `normalize.py`

**Files:**
- Create: `skills/jianying-autocut/scripts/normalize.py`
- Test: `tests/test_normalize.py`

**Interfaces:**
- Consumes：`loudness.Cache` 的 `get(path, key_extra)`、`put(path, value, key_extra)`、`measure(path)`。
- Produces：
  - `normalize(path, out_dir, cache, short_s=3.0) -> (out_path, info)`，`info = {"type": "dynamic" | "linear", "short": bool}`。
  - `copy_names(paths) -> {path: out_basename}`：去掉扩展名后同名的，按路径排序，依次加 `_n2`、`_n3`。

- [ ] **Step 1: 失败测试**

用 `pytest.mark.skipif(shutil.which("ffmpeg") is None)` 包住需要 ffmpeg 的用例。夹具用 ffmpeg 生成 10s 的音频：`sine=f=220` 衰减到约 -28 LUFS，再用 `aevalsrc` 在 2s、5s、8s 叠加 20ms、-6 dBFS 的尖峰。

```python
def test_normalize_hits_target_with_peaks(tmp_path):
    out, info = normalize(src, tmp_path / "n", Cache(str(tmp_path)))
    m = loudness.measure(out)
    assert abs(m["i"] + 16) <= 0.7 and m["tp"] <= -1.5 and info["type"] == "dynamic" and out.endswith(".wav")
def test_short_file_flagged(tmp_path):        # 2.5s → info["short"] and info["type"] == "linear"
def test_cache_skips_second_run_and_reruns_on_change(tmp_path, monkeypatch):
    # 计数 subprocess.run：第二次是 0 次；改原文件 mtime → 2 次；删掉副本 → 2 次
def test_copy_names_dedupes_stably():
    assert copy_names(["/a/x.m4a", "/b/x.wav"]) == {"/a/x.m4a": "x", "/b/x.wav": "x_n2"}
def test_ffmpeg_failure_raises(monkeypatch):  # 返回码非零 → CalledProcessError
```

- [ ] **Step 2:** 运行。Expected：FAIL（`no module normalize`）。
- [ ] **Step 3:** 实现：两遍 ffmpeg，JSON 从 stderr 最后一个 `{…}` 块里解析，参数见 Global Constraints。缓存键是 `key_extra="norm"`，值是 `{out, out_mtime, type, short}`。命中的条件是副本还在、mtime 和记录一致。
- [ ] **Step 4:** 测试 PASS。Commit `normalize: two-pass loudnorm WAV copies for narration files`

### Task 8: `build.py` 改用副本

**Files:**
- Modify: `skills/jianying-autocut/scripts/build.py`（`narration_mix`、`main` 旁白片段、报告）
- Test: `tests/test_build_main.py`（改掉那条 `10**(6/20)` 断言，并新增测试）

**Interfaces:**
- Consumes：Task 7 的 `normalize`、`copy_names`。
- Produces：
  - `narration_mix` 返回值不变：`vo_gain` 全部是 1.0，`level[原路径]` 是副本的实测响度。另外多返回一个 `{原路径: 副本路径}` 映射，作为第六个返回值，调用处要同步改。
  - 报告每个文件一行：`<文件名> <前> → <后> LUFS（限幅|线性）`，最后一行写明副本目录。

- [ ] **Step 1: 失败测试**（mock `normalize`，返回 tmp 里的假 WAV 路径，mock `cache.measure`）
  - 剪映旁白片段的素材路径是副本，`volume == 1.0`，时长等于 `vo_durs[原路径]`；
  - 报告里有「→ -16」那一行；
  - 副本没到目标的短文件，报告里有「太小声」；
  - `normalize` 抛 `CalledProcessError` 时，`main` 用 SystemExit 退出，退出信息里有「归一化失败」和文件名（Review Focus 3）。
- [ ] **Step 2:** 运行。Expected：FAIL。
- [ ] **Step 3:** 实现。
  - `missing_vo` 仍然检查原文件。
  - 「音量放大待真机验证」不再列旁白文件，只列 `live_gain > 1` 的原声段。
- [ ] **Step 4:** 全套测试 PASS。Commit `build: narration uses normalized WAV copies at unity gain`

### Task 9: 文档、枸杞岛验收

**Files:**
- Modify: `skills/jianying-autocut/references/narration.md`（visuals 字段表、配画面怎么想、混音表、报告提示表、导出说明）
- Modify: `skills/jianying-autocut/references/pitfalls.md`（三条：手机旁白的峰均比、图形素材判帧和百分位、单声道听感约 +3 LU）

- [ ] **Step 1:** 按 spec §5 改文档。
- [ ] **Step 2: 枸杞岛验收**。在 scratchpad 里复制一份工作目录，不动用户的原目录：
  - 把盘点和素材描述里的 c024–c027（副本素材）去掉；
  - `orient.py --graphic c023`，c023 改成指向原始的 21.000s `动画/route_map.mp4`（重新 probe）；
  - 在 `narration_plan.json` 里，把 L03、L08、L19 改成原片加 `"mute": true`，L05 改成原片加 `"reuse": true`，L28 用 c023、L29 和 L30 留空延续；
  - 跑 `narrate.py --head 0.4 --dry-run`，再用临时草稿名 `build.py --narration`。剪映正在运行时，用 smoke wrapper 绕过检测（见旁白模式那一轮的做法）。

  检查以下几条：
  - c023 一个镜头 21.000s，三句之间没有切换；
  - 没有用到 c024–c027；
  - 9 个副本的 ebur128 积分响度都在 -16 ±0.7 LUFS，彼此相差 ≤ 1 dB，真峰值 ≤ -1.5；
  - 自检全部通过。

  把这些数字记进 PR 描述。
- [ ] **Step 3:** 全套 `./run_tests.sh` PASS。Commit `docs: graphic clips, normalized narration, visual reuse/mute`
