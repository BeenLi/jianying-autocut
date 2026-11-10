# 拍摄脚本 + 按故事剪辑 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 给 jianying-autocut 加上模式 A（拍摄前生成拍摄脚本页面）和模式 B（按用户故事把素材对到镜头再剪），两者通过一个 Claude Artifact 页面衔接。

**Architecture:** 人在 Artifact 页面上看和改，Claude 用 `ArtifactData` 读写页面 db；进入剪辑时 Claude 把 db 导出成 `W/shoot_plan.json` + `W/matches.json`，新脚本 `match.py` 把它们转成现有的 `story_plan.json`，第 5 步以后不变。

**Tech Stack:** Python 3.10+ 标准库（脚本头 PEP 723，`uv run --script`），pytest（`./run_tests.sh`），单文件 HTML + Artifact runtime capabilities（`db`、`user`、`assets`）。

**Spec:** `docs/specs/2026-11-10-shoot-plan-modes-design.md`

## Global Constraints

- 剪辑流程的 Python 脚本不联网；页面只做人机交互，页面不可用时可直接写本地 JSON 降级。
- 不改 `probe.py`、`frames.py`、`transcribe.py`、`notes.py`、`orient.py`、`beatsync.py`、`build.py`。
- 新脚本 `match.py` 依赖为空（`# dependencies = []`），沿用 `common.read_csv`。
- `match.py` 只认 `confirmed: true` 的匹配；存在未确认匹配即报错、退出码 1、不写 `story_plan.json`。
- 跨章共享素材：同一素材可出现在多章，前提是它在每一章都有 pin。
- 口播：本次只做出镜口播（`kind: "talk"`）；口播时长按约 4 字/秒估算。后期旁白不做。
- 文案与报错用中文，风格同 `story.py`（`sys.exit("…有问题：\n  " + "\n  ".join(errs))`）。
- 页面外部脚本只允许来自 Artifact 规定的 CDN 白名单；页面模板不含用户数据，全部从 db 渲染。

## 数据格式（Task 2–5 共用）

`W/shoot_plan.json`：
```json
{"meta": {"title": "枸杞岛两日", "intent": "一座岛从雾里慢慢露出来", "place": "枸杞岛", "days": 2, "stage": "editing"},
 "chapters": [{"id": "ch1", "order": 1, "title": "雾里的灯塔", "function": "hook", "rhythm": "fast"}],
 "shots": [{"id": "S01", "chapter": "ch1", "order": 1, "kind": "visual", "desc": "灯塔在雾里若隐若现",
            "size": "远景", "duration": 5, "talk": "", "tips": "", "done": true, "note": ""}]}
```

`W/matches.json`：
```json
{"matches": {"S01": {"clip_id": "c012", "at": 15.0, "start": null, "end": null,
                     "confidence": "high", "reason": "…", "confirmed": true, "by": "user"}},
 "extras": {"c020": {"chapter": "ch2", "at": 8.0, "reason": "…", "accepted": true}}}
```

db 路径与上面一一对应：`plan/meta`、`chapters/<id>`、`shots/<id>`、`clips/<clip_id>`、`matches/<shot_id>`、`extras/<clip_id>`、`requests/<id>`（字段见 spec §3）。

## Review Focus

1. 两个已确认匹配指向同一素材且 `at` 相差 < 1s（一个瞬间对了两个镜头）→ plan.py 第二个 pin 会因"已占用"被跳过；期望 match.py 报警告并合并为一个 pin。
2. 一条匹配都没确认（或全部章节都没素材）→ 期望报错退出，而不是写出空的 `story_plan.json`。
3. 页面输入框把 `at` 存成字符串（如 `"15"`、`"1:05"`）→ 期望数字字符串被接受，非数字报出具体镜头。
4. extras 素材同时被另一章的已确认匹配用到 → 期望生成两章各自带 pin 的合法 story_plan（通过放宽后的 story.py 校验）。
5. `accepted: null`（用户还没决定）的 extras → 期望不进成片，并在报告里列出"待决定 N 段"提醒用户。

---

### Task 1: story.py 放宽跨章共享素材校验

**Files:**
- Modify: `skills/jianying-autocut/scripts/story.py:88-118`（`validate`）
- Modify: `skills/jianying-autocut/references/story_plan.md`（"一段素材只放进一章"一句改为新规则）
- Test: `tests/test_story.py`、`tests/test_plan.py`

**Interfaces:**
- Produces: `validate(plan: dict, inv_ids: set[str]) -> list[str]`（签名不变）。规则：同一素材出现在多章（`pool` 不为 `all`）时，若它在任一所在章没有 pin，报 `素材 {c} 出现在多个章节，每一章都要给它 pin`。

- [ ] **Step 1: 写失败测试**（`tests/test_story.py`）

```python
def test_validate_shared_clip_ok_when_pinned_in_every_chapter():
    from story import validate
    plan = {"chapters": [
        {"id": "a", "clip_ids": ["c001"], "pins": [{"clip_id": "c001", "at": 5}]},
        {"id": "b", "clip_ids": ["c001"], "pins": [{"clip_id": "c001", "at": 60}]}]}
    assert validate(plan, {"c001"}) == []


def test_validate_shared_clip_needs_pin_in_each_chapter():
    from story import validate
    plan = {"chapters": [
        {"id": "a", "clip_ids": ["c001"], "pins": [{"clip_id": "c001", "at": 5}]},
        {"id": "b", "clip_ids": ["c001"], "pins": []}]}
    assert any("c001" in e and "pin" in e for e in validate(plan, {"c001"}))
```

- [ ] **Step 2: 跑测试确认失败**

Run: `./run_tests.sh tests/test_story.py -v`
Expected: 第一个 FAIL（现有"出现在多个章节"报错），第二个 PASS 或 FAIL 均可（报错文案不含 pin）。

- [ ] **Step 3: 改 `validate`**：先收集每段素材出现在哪些章，再对出现 ≥2 次（且所在章 `pool != "all"`）的素材检查每章 pins 里都有它。

- [ ] **Step 4: 加 plan.py 定长模式行为测试**（`tests/test_plan.py`，用该文件已有的 `_work` 辅助函数）

```python
def test_fixed_mode_shared_clip_shots_do_not_overlap(tmp_path):
    _work(tmp_path, [("c001", 120, 0), ("c002", 60, 0)],
          [{"id": "a", "title": "a", "clip_ids": ["c001"], "pins": [{"clip_id": "c001", "at": 20}]},
           {"id": "b", "title": "b", "clip_ids": ["c001", "c002"], "pins": [{"clip_id": "c001", "at": 90}]}])
    rows, _, _ = plan(str(tmp_path), 60 * US)
    spans = sorted((r["in_us"], r["in_us"] + r["dur_us"]) for r in rows if r["name"] == "c001.mp4")
    assert all(a_end <= b_start for (_, a_end), (b_start, _) in zip(spans, spans[1:]))
```

如该测试需要 `frames.csv` 等文件，照 `tests/test_plan.py` 里已有的定长模式测试补齐。

- [ ] **Step 5: 跑全部测试**

Run: `./run_tests.sh`
Expected: 全部 PASS。

- [ ] **Step 6: 改 `references/story_plan.md`**：`clip_ids` 行的"一段素材只放进一章"改为"一段素材通常只放进一章；放进多章时每章都要给它 pin（match.py 生成的故事会这样）"。

- [ ] **Step 7: Commit**

```bash
git add skills/jianying-autocut/scripts/story.py skills/jianying-autocut/references/story_plan.md tests/test_story.py tests/test_plan.py
git commit -m "Allow a clip in several chapters when every chapter pins it"
```

---

### Task 2: match.py 校验

**Files:**
- Create: `skills/jianying-autocut/scripts/match.py`
- Test: `tests/test_match.py`

**Interfaces:**
- Consumes: `common.read_csv(path) -> list[dict]`
- Produces:
  - `load_inputs(work: str) -> tuple[dict, dict, dict[str, float]]`：返回 `(shoot_plan, matches, durations)`，`durations` 来自 `inventory.csv` 的 `clip_id → float(duration_s)`。
  - `to_seconds(v) -> float | None`：接受数字、数字字符串、`"m:ss"`；无法解析返回 `None`。
  - `validate(shoot_plan: dict, matches: dict, durations: dict[str, float]) -> list[str]`

报错规则（每条指明镜头或素材 id）：
- 匹配的镜头 id 不在 `shots` → `匹配 {sid}：没有这个镜头`
- 镜头的 `chapter` 不在 `chapters` → `镜头 {sid}：所属章 {ch} 不存在`
- `clip_id` 不在 `durations` → `匹配 {sid}：素材 {cid} 不在 inventory.csv`
- `at` 解析失败或不在 `[0, 时长]` → `匹配 {sid}：秒数 {at} 无效（素材 {cid} 时长 {d}s）`
- 口播匹配的 `start`/`end` 有值时不满足 `start < at < end` → `匹配 {sid}：口播范围 start/end 不包住 at`
- `confirmed` 不为 `true` → `匹配 {sid}：还没确认，请先在页面上确认或删除`
- extras 的 `chapter` 不存在、`clip_id` 不在 inventory、`at` 无效 → 同上格式，前缀 `计划外素材 {cid}`
- 章节 `function` 不在 `hook/setup/turn/escalation/payoff`、`rhythm` 不在 `slow/normal/fast/montage`（允许空）→ `章 {id}：…`

- [ ] **Step 1: 写失败测试**（`tests/test_match.py`）。写一个 `_inputs()` 辅助函数返回合法的 `(shoot_plan, matches, durations)`：两章（ch1 hook / ch2 setup）、三个镜头 S01–S03（S03 为 `talk`）、`durations = {"c001": 30.0, "c002": 120.0, "c003": 20.0}`，S01→c001@10、S02→c002@15、S03→c002@80（start 78、end 83），全部 confirmed。测试：

```python
def test_valid_inputs_have_no_errors():
    assert validate(*_inputs()) == []

def test_unconfirmed_match_is_an_error():
    sp, m, d = _inputs(); m["matches"]["S02"]["confirmed"] = False
    assert any("S02" in e and "确认" in e for e in validate(sp, m, d))

def test_unknown_shot_and_clip_and_out_of_range():
    sp, m, d = _inputs()
    m["matches"]["S99"] = dict(m["matches"]["S01"])
    m["matches"]["S01"]["clip_id"] = "c404"
    m["matches"]["S02"]["at"] = 999
    errs = validate(sp, m, d)
    assert any("S99" in e for e in errs) and any("c404" in e for e in errs) and any("999" in e for e in errs)

def test_talk_range_must_contain_at():
    sp, m, d = _inputs(); m["matches"]["S03"]["end"] = 79
    assert any("S03" in e and "口播" in e for e in validate(sp, m, d))

def test_at_accepts_numeric_strings_and_mmss():          # Review Focus 3
    assert to_seconds("15") == 15.0 and to_seconds("1:05") == 65.0 and to_seconds("abc") is None
    sp, m, d = _inputs(); m["matches"]["S02"]["at"] = "15"
    assert validate(sp, m, d) == []

def test_bad_rhythm_and_function():
    sp, m, d = _inputs(); sp["chapters"][0]["rhythm"] = "turbo"; sp["chapters"][1]["function"] = "x"
    errs = validate(sp, m, d)
    assert any("ch1" in e for e in errs) and any("ch2" in e for e in errs)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `./run_tests.sh tests/test_match.py -v`
Expected: FAIL（`ModuleNotFoundError: match`）。

- [ ] **Step 3: 实现 `match.py` 头部（PEP 723，`dependencies = []`，docstring 写用法 `uv run --script match.py --work W`）和 `load_inputs`、`to_seconds`、`validate`。**

- [ ] **Step 4: 跑测试确认通过**

Run: `./run_tests.sh tests/test_match.py -v`
Expected: PASS。

- [ ] **Step 5: Commit**

```bash
git add skills/jianying-autocut/scripts/match.py tests/test_match.py
git commit -m "Add match.py input validation"
```

---

### Task 3: match.py 生成 story_plan 和 CLI

**Files:**
- Modify: `skills/jianying-autocut/scripts/match.py`
- Test: `tests/test_match.py`

**Interfaces:**
- Consumes: Task 2 的 `load_inputs`、`to_seconds`、`validate`；`story.validate(plan, inv_ids)`（Task 1）。
- Produces:
  - `build_story_plan(shoot_plan: dict, matches: dict) -> tuple[dict, dict]`：返回 `(story_plan, report)`。
    `report = {"missing": {ch_id: [shot_id, …]}, "dropped_chapters": [ch_id, …], "pending_extras": [clip_id, …], "rejected_extras": int, "merged_pins": [(clip_id, at_kept, at_dropped), …]}`
  - `main(argv: list[str] | None = None) -> int`：读 `--work`，校验 → 生成 → 再用 `story.validate` 校验 → 写 `W/story_plan.json` → 打印报告；有错返回 1 且不写文件。

生成规则（spec §5.2）：
- 章按 `order` 排序；输出章 `{"id", "title", "function", "rhythm"(有才写), "clip_ids", "pool": "own", "pins"}`；`director_intent = meta.intent`。
- 本章 pins：已确认匹配按镜头 `order` 排，再接 `accepted: true` 的 extras；`at` 用 `to_seconds` 转成 float。
- `clip_ids`：pins 里的素材按出现顺序去重。
- 同章同素材两个 pin 的 `at` 相差 < 1.0s：只留第一个，记入 `merged_pins`（Review Focus 1）。
- 没有 pin 的章不输出，记入 `dropped_chapters`；镜头没有已确认匹配记入 `missing`。
- `accepted` 为 `None` 的 extras 记入 `pending_extras`；`False` 计入 `rejected_extras`。
- 所有章都被删掉时，`main` 报 `没有任何已确认的匹配，没法生成故事` 并返回 1（Review Focus 2）。
- 报告还打印"未被任何章引用的素材 N 段（不进成片）"，由 `main` 用 `durations` 计算。

- [ ] **Step 1: 写失败测试**

```python
def test_build_maps_confirmed_matches_to_pins():
    sp, m, _ = _inputs()
    story, rep = build_story_plan(sp, m)
    ch1, ch2 = story["chapters"]
    assert ch1["pins"] == [{"clip_id": "c001", "at": 10.0}]
    assert ch2["clip_ids"] == ["c002"] and [p["at"] for p in ch2["pins"]] == [15.0, 80.0]
    assert story["director_intent"] == sp["meta"]["intent"] and rep["missing"] == {}

def test_missing_shot_and_dropped_chapter():
    sp, m, _ = _inputs(); del m["matches"]["S01"]
    story, rep = build_story_plan(sp, m)
    assert [c["id"] for c in story["chapters"]] == ["ch2"]
    assert rep["dropped_chapters"] == ["ch1"] and rep["missing"] == {"ch1": ["S01"]}

def test_extras_accepted_pending_rejected():                 # Review Focus 5
    sp, m, _ = _inputs()
    m["extras"] = {"c003": {"chapter": "ch2", "at": 5, "accepted": True},
                   "c004": {"chapter": "ch2", "at": 1, "accepted": None},
                   "c005": {"chapter": "ch1", "at": 1, "accepted": False}}
    story, rep = build_story_plan(sp, m)
    assert "c003" in story["chapters"][1]["clip_ids"]
    assert rep["pending_extras"] == ["c004"] and rep["rejected_extras"] == 1

def test_extra_shared_with_other_chapter_passes_story_validate():   # Review Focus 4
    from story import validate as story_validate
    sp, m, d = _inputs()
    m["extras"] = {"c001": {"chapter": "ch2", "at": 25, "accepted": True}}
    story, _ = build_story_plan(sp, m)
    assert story_validate(story, set(d)) == []

def test_near_duplicate_pins_are_merged():                  # Review Focus 1
    sp, m, _ = _inputs(); m["matches"]["S03"].update(at=15.4, start=None, end=None)
    story, rep = build_story_plan(sp, m)
    assert [p["at"] for p in story["chapters"][1]["pins"]] == [15.0]
    assert rep["merged_pins"] == [("c002", 15.0, 15.4)]

def test_main_writes_story_plan_and_refuses_when_nothing_confirmed(tmp_path):   # Review Focus 2
    # 用 _write_work(tmp_path, sp, m, d) 写出 shoot_plan.json / matches.json / inventory.csv
    sp, m, d = _inputs(); _write_work(tmp_path, sp, m, d)
    assert main(["--work", str(tmp_path)]) == 0 and (tmp_path / "story_plan.json").exists()
    (tmp_path / "story_plan.json").unlink()
    m["matches"] = {}; _write_work(tmp_path, sp, m, d)
    assert main(["--work", str(tmp_path)]) == 1 and not (tmp_path / "story_plan.json").exists()
```

`_write_work` 写 `inventory.csv` 时字段沿用 `tests/test_plan.py` 的 `INV_FIELDS`。

- [ ] **Step 2: 跑测试确认失败**

Run: `./run_tests.sh tests/test_match.py -v`
Expected: 新测试 FAIL（`build_story_plan` / `main` 未定义）。

- [ ] **Step 3: 实现 `build_story_plan` 和 `main`**（`argparse`，`--work` 必填；`if __name__ == "__main__": sys.exit(main())`）。报告格式：

```
漏拍：ch1 雾里的灯塔：S01
整章没有素材，已删除：ch1 雾里的灯塔
计划外素材待决定 1 段：c004（请在页面上采纳或拒绝）
合并了相差不到 1 秒的 pin：c002 @15.0 / 15.4
未被任何章引用的素材 12 段（不进成片）
→ W/story_plan.json
```

- [ ] **Step 4: 跑全部测试**

Run: `./run_tests.sh`
Expected: 全部 PASS。

- [ ] **Step 5: Commit**

```bash
git add skills/jianying-autocut/scripts/match.py tests/test_match.py
git commit -m "Generate story_plan.json from confirmed shot matches"
```

---

### Task 4: 拍摄脚本页面模板

**Files:**
- Create: `skills/jianying-autocut/assets/shoot_plan_page.html`

**Interfaces:**
- Consumes: db 结构（见"数据格式"与 spec §3）。
- Produces: 一个可直接用 Artifact 工具发布的单文件 HTML；发布时 `capabilities: {db: {}, user: {}, assets: {}}`。

- [ ] **Step 1: 先加载 `artifact-design` 和 `artifact-capabilities` 两个 skill**，读 `0.2.96/db.d.ts`、`assets.d.ts`、`claude.d.ts` 的类型定义。

- [ ] **Step 2: 写模板。** 必须满足：
  - 所有内容从 db 渲染，`onSnapshot` 每个集合只订阅一次；10 秒未加载到数据显示"加载失败，刷新重试"；`use("db")` 为 `null` 显示只读提示。
  - 用户可写字段：`plan/meta` 的 `title`/`intent`；`chapters` 改名、调顺序、增删；`shots` 的 `done`、`note`、`desc` 等（改 `desc`/`size`/`duration`/`talk`/`tips` 时把字段名追加进 `edited_by_user`）、增删、上移 / 下移；`matches` 的 `confirmed`、`clip_id`、`at`（改动时 `by: "user"`）；`extras` 的 `accepted`；`requests` 新建 `{text, status: "new"}`。一律 `update`，不整条 `set` 已有文档。
  - 写入失败把该项标"未保存"，下次操作重试。
  - 视图：`meta.stage` 决定默认视图，可手动切换。拍摄视图（手机优先）：进度"已拍 x/y"、可折叠章节、大勾选框、`talk` 镜头标"口播"并显示要点。剪辑视图（≥720px 左右两栏，窄屏上下）：镜头状态色 🟢 已确认 / 🟡 待确认 / 🔴 漏拍；当前镜头显示 `clips/<id>.thumbs` 缩略图（asset url）、素材与秒数、把握、理由、确认 / 换素材 / 改秒数；计划外素材列表（采纳 / 拒绝）；"补充故事"输入框和 `requests` 列表（含 `reply`）。

- [ ] **Step 3: 冒烟验证。** 发布一次（`icon: "checklist"`），用 `ArtifactData batch` 写入一份示例数据（2 章、4 镜头、1 匹配、1 extra），再 `ArtifactData list` 每个集合确认读回一致。把链接给用户，请用户分别在手机和 Mac 上打开确认两种布局和勾选、确认操作能保存。

- [ ] **Step 4: Commit**

```bash
git add skills/jianying-autocut/assets/shoot_plan_page.html
git commit -m "Add shoot plan Artifact page template"
```

---

### Task 5: SKILL.md、references、README

**Files:**
- Create: `skills/jianying-autocut/references/shoot_plan.md`
- Modify: `skills/jianying-autocut/SKILL.md`
- Modify: `README.md`、`README.en.md`

**Interfaces:**
- Consumes: Task 3 的 `match.py --work W`；Task 4 的模板路径 `assets/shoot_plan_page.html`。

- [ ] **Step 1: 写 `references/shoot_plan.md`**，包含：写骨架的方法（导演意图、4–7 章、每章 3–8 镜头、镜头字段含义、`talk` 口播要点按约 4 字/秒估时长、超出就拆镜头或调长）；发布页面的步骤（模板路径、capabilities、`ArtifactData batch` 初始化、链接写入 `W/shoot_plan_url`）；db 结构表与不互相覆盖的 4 条规则（spec §3）；匹配方法（visual 用 `scene_notes.json`，talk 用 `speech.json` 文字比对、`at` 取句子中点并记 start/end，写把握和理由，跳过已确认）；缩略图上传（`W/thumbs/<clip>_<t>.jpg`，每段 2–4 张，Artifact `asset: true`）；导出 `shoot_plan.json` / `matches.json` 的格式；页面不可用时的降级做法。

- [ ] **Step 2: 改 `SKILL.md`**：
  - frontmatter description 加入"拍摄前生成拍摄脚本（Artifact 页面，手机看、勾选）"和触发词：拍摄脚本、分镜脚本、拍摄清单、shot list、出发前帮我写脚本、按我的故事剪。
  - 第 0 步改为模式分流（模式 A / 模式 B 三种故事来源，spec §2）。
  - 新增"模式 A：拍摄前"小节（A0–A3，指向 `references/shoot_plan.md`）。
  - 流程表第 4 步拆为 4a / 4b / 4c（有页面时），无故事时保持现有写法。
  - "字幕与人声"加：`talk` 镜头的句子默认入选，用口播要点校正同音字。
  - "不做"保留 AI 旁白 / TTS，补"后期旁白（另录音轨）暂不支持"。

- [ ] **Step 3: 改 README**：工作流部分加两种模式的一段说明（中英各一），不改其他段落。

- [ ] **Step 4: 自检**：`grep -n "match.py\|shoot_plan" skills/jianying-autocut/SKILL.md` 确认引用的脚本和文件都存在；`./run_tests.sh` 全部 PASS。

- [ ] **Step 5: Commit**

```bash
git add skills/jianying-autocut/SKILL.md skills/jianying-autocut/references/shoot_plan.md README.md README.en.md
git commit -m "Document shoot-plan and story-driven edit modes"
```

---

### Task 6: 端到端验证

- [ ] **Step 1:** 用户提供一小批真实素材（或用已有的枸杞岛 `_autocut`）。按模式 A 生成一份 3 章脚本页面，用户在手机上勾选几个镜头。
- [ ] **Step 2:** 按模式 B 跑 1–3 步、4a 匹配、用户在 Mac 上确认、4c `match.py`，接着 `plan.py --dry-run`。
- [ ] **Step 3:** 把章节表、漏拍报告、删除清单给用户看；用户确认后跑完 `build.py`，自检通过。
- [ ] **Step 4:** 把实测中发现的坑记进 `references/pitfalls.md` 并 commit。
