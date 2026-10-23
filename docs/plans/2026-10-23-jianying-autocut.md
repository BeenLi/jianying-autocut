# jianying-autocut Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 一个技能把 vlog 素材目录变成剪映 11.6 可打开、按故事排好的粗剪草稿（理解 → 故事 → 分镜 → 草稿）。

**Architecture:** 六个独立脚本，只通过 `--work` 目录里的文件通信、可断点重跑。理解阶段把所有素材拼成一条代理长片，调用一次上游 video-understanding，再按 proxy_map 拆回每段素材；故事阶段由 agent 写 recap_story_plan.json，转成唯一内部格式 story_plan.json；分镜与写草稿沿用今天 scratch 里已验证的 autocut 脚本。

**Tech Stack:** Python 3.10+，`uv run`（PEP 723 依赖），pyJianYingDraft==0.3.0，numpy，ffmpeg/ffprobe，pytest。

**Spec:** `~/.claude/skills/jianying-autocut/docs/specs/2026-10-23-jianying-autocut-design.md`

**移植来源（已验证代码）：** `<scratch>/jianying_autocut/{common.py,1_probe_materials.py,2_sample_frames.py,3_plan_shots.py,4_build_draft.py}`，
scratch = 本会话工作区。每个任务先 `cp` 对应文件再改。

## Global Constraints

- 根目录 `S=~/.claude/skills/jianying-autocut`；脚本在 `$S/scripts/`，测试在 `$S/tests/`，运行 `uv run --script $S/scripts/<x>.py`。
- 每个脚本顶部 PEP 723：`# /// script` / `requires-python = ">=3.10"` / `dependencies = ["numpy", "pyJianYingDraft==0.3.0"]`（只 build.py 需要 pyJianYingDraft；pyJianYingDraft 源：`pyJianYingDraft @ git+https://github.com/aoguai/pyJianYingDraft`）。
- 时间内部一律整数微秒，`US = 1_000_000`；CSV/JSON 对外写秒（3 位小数）时同时写 `_us` 字段。
- 上游 video-* 只按绝对路径调 CLI：`~/.claude/skills/video-understanding/scripts/understand.py`，不 import、不修改。
- MiMo 不可用（无 key / 402 / 文本含 余额|欠费|insufficient|balance|quota|credit）→ 打印充值提醒，退出码 3。
- 剪映主进程 `VideoFusion-macOS` 在运行时 build.py 拒绝写入；草稿版本号从 `root_meta_info.json` 读。
- 不复制素材进草稿；不调用 add_clip / inline_materials。
- `~/.claude/skills` 不是 git 仓库：各任务的 “Commit” 步骤省略，以测试通过为完成。

## Review Focus

1. 无音轨素材参与代理拼接 → concat 不能因流不一致失败；需补静音轨（Task 3 测试 `test_proxy_cmd_adds_silence_for_mute_clip`）。
2. 竖屏 / 4:3 / 方形素材 → 代理一律 1280x720 补黑边不裁（Task 3 测试 `test_proxy_cmd_pads_not_crops`）。
3. beat 时间超出代理末尾、或某章节零素材 → 不崩溃，并入相邻章节并警告（Task 4 测试 `test_beat_out_of_range_and_empty`）。
4. BGM 比成片短 / 比成片长 → 短则循环切段，长则截断，均不越界（Task 6 测试 `test_bgm_segments_loop_and_trim`）。
5. MiMo 理解中途报余额不足 → 同样提醒充值、退出码 3，而不是打印一堆 traceback（Task 3 测试 `test_classify_mimo_errors`）。

---

### Task 1: common.py + probe.py（盘点、clip_id、人声分、静音段）

**Files:** Create `$S/scripts/common.py`, `$S/scripts/probe.py`, `$S/tests/conftest.py`, `$S/tests/test_probe.py`

**Interfaces:**
- Produces（common.py）：`US`, `DRAFTS_DIR`, `VIDEO_EXTS`, `write_csv(path, rows, fields)`, `read_csv(path)`, `jianying_running() -> bool`, `detect_versions(drafts_dir) -> dict`（同 scratch 版），`default_work(folder) -> str`（= `<folder>/_autocut`），`classify_mimo_error(text: str, status: int|None) -> str`（返回 `"recharge"|"bad_key"|"rate_limit"|"other"`），`RECHARGE_HINT: str`。
- Produces（probe.py）：`speech_score(rms_db: list[float]) -> float`，`parse_silences(stderr: str, dur: float) -> list[tuple[float,float]]`；输出 `inventory.csv` 字段 = scratch 版字段 + `clip_id, speech_score`，以及 `silences.json {clip_id: [[start,end],...]}`。

- [ ] **Step 1: 写失败测试**（`conftest.py` 把 `$S/scripts` 加入 `sys.path`）
```python
def test_speech_score_bursty_beats_steady():
    steady = [-30.0] * 20                     # 风声：一直很响但平稳
    bursty = [-60, -25, -28, -60, -22, -60] * 4
    assert speech_score(bursty) > speech_score(steady)
    assert speech_score([-80.0] * 10) == 0.0  # 全静音
def test_parse_silences():
    err = "silence_start: 1.5\nsilence_end: 3.0 | silence_duration: 1.5\nsilence_start: 9.2\n"
    assert parse_silences(err, 10.0) == [(1.5, 3.0), (9.2, 10.0)]
def test_classify_mimo_errors():
    assert classify_mimo_error("Insufficient balance", 402) == "recharge"
    assert classify_mimo_error("账户余额不足", 400) == "recharge"
    assert classify_mimo_error("API 认证失败 (401)", 401) == "bad_key"
    assert classify_mimo_error("Too Many Requests", 429) == "rate_limit"
```
- [ ] **Step 2:** `cd $S && uv run --with pytest --with numpy pytest tests/test_probe.py -q` → FAIL（模块不存在）
- [ ] **Step 3: 实现。** common.py 从 scratch 复制后加 `default_work`、`classify_mimo_error`（402 或文本命中关键词 → recharge；401 → bad_key；429 → rate_limit）、`RECHARGE_HINT`（中文：去 MiMo 控制台充值 / `export MIMO_API_KEY=…` / 或加 `--no-understanding`）。probe.py 从 1_probe_materials.py 复制，排序后按序赋 `clip_id=f"c{i:03d}"`；有音轨的素材跑一次
  `ffmpeg -i p -af highpass=f=300,lowpass=f=3000,asetnsamples=n=<sr>,astats=metadata=1:reset=1,ametadata=print:key=lavfi.astats.Overall.RMS_level,silencedetect=n=-35dB:d=0.4 -f null -`，
  从 stderr/输出解析逐秒 RMS 与静音段。`speech_score = (高于 -35dB 的秒占比) × min(1, 变异系数)`，变异系数按线性幅度 `10**(db/20)` 计算；全部低于 -35dB 返回 0。
- [ ] **Step 4:** 测试 PASS；`uv run --script $S/scripts/probe.py ~/Videos/my-trip` → 62 段、出现 `speech_score` 列与 `_autocut/silences.json`。

### Task 2: frames.py（关键帧打分 + 联系表）

**Files:** Create `$S/scripts/frames.py`, `$S/tests/test_frames.py`

**Interfaces:**
- Consumes：Task 1 `inventory.csv`（含 `clip_id`）。
- Produces：`frames.csv`（字段 `clip_id,path,t,sharpness,brightness,score,bad`），`thumbs/<clip_id>_<t>.jpg`，`contact/sheet_NN.jpg`；函数 `judge(rows) -> rows`（就地补 score/bad）。

- [ ] **Step 1: 测试**
```python
def test_judge_relative_blur():
    rows = [{"path":"a","sharpness":s,"brightness":120} for s in (100,110,120,20)] + \
           [{"path":"b","sharpness":s,"brightness":120} for s in (2000,2100,2200)]
    out = judge(rows)
    assert [r["bad"] for r in out] == [0,0,0,1, 0,0,0]   # 低纹理段不误杀，突降被抓
def test_judge_exposure():
    assert judge([{"path":"a","sharpness":500,"brightness":5}])[0]["bad"] == 1
```
- [ ] **Step 2:** 运行 → FAIL
- [ ] **Step 3:** 从 2_sample_frames.py 复制；把打分段抽成 `judge(rows)`；缩略图始终生成（`-skip_frame nokey` 那条命令）；联系表用 ffmpeg 把每张缩略图加 `drawtext=<clip_id> @<t>s` 后 `tile=4x5` 拼成 `contact/sheet_NN.jpg`（无 drawtext 滤镜时不加字，文件名仍按顺序）。
- [ ] **Step 4:** 测试 PASS；在庐山素材上跑，坏帧数 ≈ 15，`contact/` 里有 ≈10 张图。

### Task 3: understand.py（MiMo 预检 + 代理长片 + 调上游 + 拆回）

**Files:** Create `$S/scripts/understand.py`, `$S/tests/test_understand.py`

**Interfaces:**
- Consumes：`inventory.csv`；common 的 `classify_mimo_error`, `RECHARGE_HINT`。
- Produces：`proxy/reel.mp4`，`proxy_map.json [{clip_id, source_path, proxy_start, proxy_end}]`（秒），`understanding/`（上游输出），`clip_understanding.json {clip_id: {"scenes":[{start,end,description,frame_facts}], "speech":[{start,end,text}]}}`（素材内秒）；函数
  `proxy_cmd(row: dict, out: str) -> list[str]`，`build_map(rows, durations) -> list[dict]`，
  `split_to_clips(proxy_map, vlm: list, asr: list) -> dict`，`mimo_preflight() -> None`（失败时 `sys.exit(3)`）。

- [ ] **Step 1: 测试**
```python
def test_proxy_cmd_pads_not_crops():
    c = " ".join(proxy_cmd({"path":"x.mp4","has_audio":"True"}, "o.mp4"))
    assert "scale=-2:720" in c and "pad=1280:720" in c and "crop" not in c and "fps=15" in c
def test_proxy_cmd_adds_silence_for_mute_clip():
    c = " ".join(proxy_cmd({"path":"x.mp4","has_audio":"False"}, "o.mp4"))
    assert "anullsrc" in c and "-shortest" in c
def test_split_to_clips():
    pm = [{"clip_id":"c001","proxy_start":0,"proxy_end":10},{"clip_id":"c002","proxy_start":10,"proxy_end":30}]
    vlm = [{"start":2,"end":12,"description":"山路","frame_facts":{}},   # 8s 在 c001 → 归 c001
           {"start":12,"end":30,"description":"瀑布","frame_facts":{}}]
    asr = [{"start":8,"end":13,"text":"到了"}]                           # 中点 10.5 → c002
    out = split_to_clips(pm, vlm, asr)
    assert out["c001"]["scenes"][0]["description"] == "山路"
    assert out["c002"]["scenes"][0] == {"start":2.0,"end":20.0,"description":"瀑布","frame_facts":{}}
    assert out["c002"]["speech"][0]["text"] == "到了" and out["c002"]["speech"][0]["start"] == 0.0
```
- [ ] **Step 2:** 运行 → FAIL
- [ ] **Step 3: 实现。**
  - `proxy_cmd`：`ffmpeg -y -i <path> [-f lavfi -i anullsrc=r=48000:cl=stereo] -vf scale=-2:720,pad=1280:720:(ow-iw)/2:(oh-ih)/2,fps=15,format=yuv420p -c:v h264_videotoolbox -b:v 2M -c:a aac -ar 48000 -ac 2 [-shortest] <out>`；无音轨时 map `0:v` + `1:a`。
  - 缓存：`proxy/parts/<clip_id>_<sha1(path+size+mtime)[:8]>.mp4` 已存在则跳过；`ThreadPoolExecutor(4)`；拼接用 concat demuxer `-c copy`；`build_map` 用 ffprobe 测得的各 part 真实时长累加。
  - `mimo_preflight`：无 `MIMO_API_KEY` → 打印 `RECHARGE_HINT` 并 exit 3；否则 POST 一次 `{"model":"mimo-v2.5","messages":[{"role":"user","content":"ping"}],"max_tokens":1}` 到 `MIMO_API_URL`（默认取上游 lib 的同一默认值，读 `~/.claude/skills/video-understanding/scripts/lib.py` 里的默认 URL 常量），按 `classify_mimo_error` 处理，`recharge`/`bad_key` → exit 3。
  - 调上游：`subprocess.run([sys.executable? 否 → "python3", UPSTREAM, reel, "--work-dir", wd, "--context", ctx], capture_output=False)` 并 tee stderr 到 `understanding/run.log`；非零退出时读 log 末 4KB 用 `classify_mimo_error`，recharge → 提醒 + exit 3。
  - `split_to_clips`：场景与每个 clip 区间求交，交集最长的 clip 得该描述（时间裁到该 clip 内）；ASR 按中点归属；输出素材内秒（减 `proxy_start`），保留 3 位小数。
  - CLI：`understand.py --work W [--context "..."] [--no-understanding]`；`--no-understanding` 直接打印「降级：请看 contact/ 写 story_plan.json」并退出 0。
- [ ] **Step 4:** 测试 PASS；庐山素材上实际跑（后台），确认 `clip_understanding.json` 有 62 个键左右。

### Task 4: story.py（recap_story_plan → story_plan；默认章节）

**Files:** Create `$S/scripts/story.py`, `$S/references/story_plan.md`, `$S/tests/test_story.py`

**Interfaces:**
- Consumes：`proxy_map.json`，`inventory.csv`，`<work>/recap_story_plan.json`（video-script 格式：`beats[{beat_id, source_start, source_end, function, event, must_keep_moment?, evidence?}]`，可有 `director_intent`）。
- Produces：`story_plan.json`（spec 中的格式：`director_intent`, `chapters[{id,title,function,share?,clip_ids,pool,pins[{clip_id,at}]}]`）；函数
  `beats_to_chapters(beats, proxy_map, usable: dict[str,float]) -> tuple[list[dict], list[str]]`（返回章节与警告），
  `default_chapters(inv_rows, n) -> list[dict]`（按拍摄时间间隔切，逻辑同 scratch `split_chapters`）。

- [ ] **Step 1: 测试**
```python
PM = [{"clip_id":f"c{i:03d}","proxy_start":i*10.0,"proxy_end":i*10.0+10} for i in range(6)]
USE = {f"c{i:03d}":9.0 for i in range(6)}
def test_majority_membership_and_pins():
    beats=[{"beat_id":"b1","source_start":0,"source_end":24,"function":"hook","event":"出发","must_keep_moment":"12.5"},
           {"beat_id":"b2","source_start":24,"source_end":60,"function":"payoff","event":"登顶"}]
    ch, warn = beats_to_chapters(beats, PM, USE)
    assert ch[0]["clip_ids"] == ["c000","c001"] and "c002" in ch[1]["clip_ids"]   # c002 被 b2 占 6s>4s
    assert ch[0]["pins"] == [{"clip_id":"c001","at":2.5}] and ch[0]["function"] == "hook"
def test_beat_out_of_range_and_empty():
    beats=[{"beat_id":"b1","source_start":0,"source_end":59,"function":"setup","event":"a"},
           {"beat_id":"b2","source_start":59,"source_end":70,"function":"payoff","event":"b"}]  # 只碰到 1s、超出末尾
    ch, warn = beats_to_chapters(beats, PM, USE)
    assert len(ch) == 1 and warn
```
- [ ] **Step 2:** 运行 → FAIL
- [ ] **Step 3:** 实现。`must_keep_moment` 可能是数字字符串或含时间的文字：用正则取第一个数字作代理秒，映射到所在 clip 的素材内秒；取不到就忽略。可用素材 < 20 s 的章节并入前一章（第一章则并入后一章），加警告；无素材的章节丢弃加警告。`title` = `event` 前 12 字。CLI：`story.py --work W --from-recap` | `--default --chapters N`；写 `story_plan.json` 并打印章节表。`references/story_plan.md` 写格式说明 + 给 agent 的写故事指引（读 brief、按 hook/setup/turn/escalation/payoff 组织、pin 高光、`pool: all` 用于开场）。
- [ ] **Step 4:** 测试 PASS。

### Task 5: plan.py（按 story_plan 分镜）

**Files:** Create `$S/scripts/plan.py`, `$S/tests/test_plan.py`

**Interfaces:**
- Consumes：`inventory.csv`，`frames.csv`（可缺），`silences.json`（可缺），`story_plan.json`。
- Produces：`shots.csv`（scratch 字段 + `chapter_function`）；函数 `allocate_quota(chapters, target_us)`（scratch 版不变，增加：有 `share` 的章节先拿 `round(share*target)`，上限 good_us，剩余给其他章节按原算法），`snap_to_silence(a, d, silences_us, dur) -> int`（返回平移后的起点，平移不超过 1.5 s，不越界）。

- [ ] **Step 1: 测试**
```python
def test_quota_share_exact():
    chs=[{"good_us":600*US,"share":0.5},{"good_us":300*US},{"good_us":300*US}]
    q=allocate_quota(chs, 600*US); assert sum(q)==600*US and q[0]==300*US
def test_pins_included(tmp_path):   # 用小型合成 inventory/story_plan 运行 plan()，pin 时刻必须落在某个镜头内
    ...  # 构造 2 段 60s 素材，pin c002@30.0，target 40s；断言存在 shot: source==c002 且 in<=30<in+dur
def test_snap_to_silence():
    assert snap_to_silence(10*US, 5*US, [(9.2*US, 9.8*US)], 60*US) == int(9.5*US)
def test_hook_first_and_total_exact(tmp_path):
    ...  # story_plan 中 hook 章写在第 2 位，断言 shots.csv 第一行 chapter_function=="hook"，dur_us 之和==target
```
- [ ] **Step 2:** 运行 → FAIL
- [ ] **Step 3:** 从 3_plan_shots.py 复制。章节来自 story_plan（`pool: all` 时候选素材 = 全部）；pins 先放：窗口长度取当前节奏档、尽量以 `at` 居中、避开坏帧（向两侧每 0.5 s 平移找第一个可行位置）；`speech_score >= 0.15` 的素材窗口两端调用 `snap_to_silence`（取窗口中心不变的前提下，端点各自吸附到最近静音段中点，再重算 d）；最终精确总长逻辑不变（缺额外溢）。章节输出顺序：function=="hook" 的章节最前，其余按 story_plan 顺序。CLI 同 scratch：`--work W --target 10:00 [--seed] [--dry-run]`。把 `main()` 拆出 `plan(work, target_us, seed) -> rows` 便于测试。
- [ ] **Step 4:** 测试 PASS；`--dry-run` 在庐山素材 + 默认 story_plan 上总长 10:00.0。

### Task 6: build.py（写草稿 + BGM + 自检）

**Files:** Create `$S/scripts/build.py`, `$S/tests/test_build.py`

**Interfaces:**
- Consumes：`shots.csv`，`inventory.csv`，common 的 `detect_versions`, `jianying_running`。
- Produces：剪映草稿目录；函数 `bgm_segments(song_us: int, start_us: int, end_us: int) -> list[tuple[int,int,int]]`（返回 `(target_start, source_start, duration)` 列表），`parse_bgm(arg: str) -> dict`（`path[:gain[:fade]]`，默认 gain 0.3、fade 1.5），`verify(draft_dir, shots, versions, bgm_expected) -> list[str]`。

- [ ] **Step 1: 测试**
```python
def test_bgm_segments_loop_and_trim():
    assert bgm_segments(100*US, 0, 250*US) == [(0,0,100*US),(100*US,0,100*US),(200*US,0,50*US)]
    assert bgm_segments(400*US, 0, 250*US) == [(0,0,250*US)]
def test_parse_bgm():
    assert parse_bgm("/a/b.mp3") == {"path":"/a/b.mp3","gain":0.3,"fade":1.5}
    assert parse_bgm("/a/b.mp3:0.5:2") == {"path":"/a/b.mp3","gain":0.5,"fade":2.0}
```
- [ ] **Step 2:** 运行 → FAIL
- [ ] **Step 3:** 从 4_build_draft.py 复制（画布按时长加权的版本）。BGM：`AudioMaterial(path)`，每段 `AudioSegment(mat, Timerange(t0, d), source_timerange=Timerange(s0, d), volume=gain)`，首段 `add_fade(fade_us, 0)`、末段 `add_fade(0, fade_us)`（先查 pyJianYingDraft 0.3.0 中 AudioSegment 的淡入淡出 API 名并按实际调用）；轨道 `TrackSpec(TrackType.audio, "BGM")`。`--volume` 未给且有 BGM 时原声 0.6。`--extra tracks.json` 预留：读到则 `raise NotImplementedError("v2")`。verify 增加 BGM 段不重叠、末段终点 == 成片时长。
- [ ] **Step 4:** 测试 PASS。

### Task 7: SKILL.md + references/pitfalls.md

**Files:** Create `$S/SKILL.md`, `$S/references/pitfalls.md`

- [ ] **Step 1:** SKILL.md frontmatter：`name: jianying-autocut`；description（中文为主）：把一堆 vlog/旅行素材自动粗剪成剪映草稿——先用 video-understanding 理解（MiMo），再按 video-script 风格写故事脚本，自动按章节/节奏挑镜头，生成剪映 11.6 草稿（BGM、章节标题）；触发词：自动粗剪、vlog 粗剪、按故事剪、素材太多帮我剪、剪映自动化、autocut。正文：工作流 6 步命令、agent 停顿点（第 4 步写 recap_story_plan.json 的要求，链接 references/story_plan.md）、MiMo 余额/无 key 时必须提醒用户充值并给降级选项、剪映需 ⌘Q、素材勿移动、与 jianying-draft 的分工（后者：已知入出点的手工剪）。
- [ ] **Step 2:** pitfalls.md：从 scratch README 的「和 PDF 的出入」整理，加入代理长片注意事项。
- [ ] **Step 3:** 全部测试 `cd $S && uv run --with pytest --with numpy pytest -q` PASS。

### Task 8: 端到端（庐山 62 段）

- [ ] **Step 1:** probe → frames → understand（MiMo，后台运行）→ 读 `understanding/agent_narration_brief.md` 写 `recap_story_plan.json` → `story.py --from-recap` → `plan.py --target 10:00 --dry-run` → 落地 → 选一首 `~/Music/网易云音乐/` 下的 mp3 → ⌘Q 剪映 → `build.py --name 庐山_故事粗剪 --titles --bgm <mp3>`；自检全绿。
- [ ] **Step 2:** 降级路径：`understand.py --no-understanding` + `story.py --default --chapters 5` + plan + build 到临时草稿目录，自检全绿。
- [ ] **Step 3:** 打开剪映确认草稿出现在首页、时长 10:00。
