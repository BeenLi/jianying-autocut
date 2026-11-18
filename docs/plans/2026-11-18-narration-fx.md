# 旁白片的转场、画面特效、滤镜、片头片尾动画 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 旁白片的 `narration_plan.json` 可以写转场、画面特效、滤镜、片头 / 片尾动画。narrate 按最终镜头算出效果的位置，build 把效果写进剪映草稿并逐个自检。页面上可以逐个确认。

**Architecture:** 分四层，每层只靠文件衔接：

- `fx_catalog.py` 把 pyJianYingDraft 的五个枚举导出成 `assets/fx_catalog.json`（显示名 → 成员名）；
- 新模块 `fx.py`（不依赖第三方库）负责校验、计算 fx、算 `shots_sig`，由 narrate 调用；
- 新模块 `fx_draft.py`（依赖 pyJianYingDraft）负责预检、挂效果、读回自检，由 build 调用；
- 页面加效果卡片，`visuals` 的写入改成从本地待定副本出发。

`layout()` 只多记一样东西：每个镜头的来源（`item`、`vis`）。

**Tech Stack:** Python 3.10+（PEP 723，`uv run --script`）、pyJianYingDraft@69cee12、pytest（`./run_tests.sh`）、node（页面 harness，`tests/page/*.js`）。

**Spec:** `docs/specs/2026-11-18-narration-fx-design.md`（ecd8470）

## Global Constraints

- 所有内部时间是整数微秒（`common.US`）。fx 只用 `layout` 的最终整数微秒，不用 shots.csv 里的 `start_s` / `dur_s`。
- `narrate.py`、`fx.py` 保持 `# dependencies = []`，不导入 pyJianYingDraft。只有 `fx_catalog.py`、`fx_draft.py`、`build.py` 依赖它（版本 `69cee12ae3f7442416df16acdf368ae574764811`）。
- 目录键是**显示名**（转场 / 特效 / 滤镜用 `value.name`，入场 / 出场用 `value.title`）。取成员一律用 `getattr(枚举, member)`，**不用** `from_name()`。
- 目录里的 `dur` 用秒（`default_duration` 或 `duration` ÷ 1e6），只有转场、入场、出场有这个字段。
- 字段可写的键（多了就报错）：`transition` 是 `type / dur / reason`；`effect` 是 `type / reason`；`filter` 是 `type / intensity / reason`；`intro` / `outro` 是 `type / reason`。
- 数值：`dur` 是有限正数，不能是 bool，`round(dur*US) > 0`；`intensity` 是有限数，不能是 bool，在 0–100 之间，省略时为 100。
- 截短：转场 ≤ 两侧镜头中较短那个的一半；动画 ≤ 所在镜头的长度；只有一个镜头、又同时有片头和片尾时，各 ≤ 镜头长度的一半。截短后不到 `FX_MIN_US = 100_000` 的效果：警告并忽略。
- 上限提醒：转场 > 8 个、特效 > 3 个时给警告（`FX_MAX_TRANSITIONS = 8`，`FX_MAX_EFFECTS = 3`）。
- 特效轨的名字是 `"特效"`。草稿里滤镜强度存成 `intensity / 100`，比较时允许 1e-6 的误差。
- 没有 fx 时：`narration_track.json` 里不写 `fx` 键；build 的代码路径和现在一样（不建特效轨，不调用 `fx_draft`）。
- 文案和报错用中文。每个任务先写失败测试、看着它失败，再实现。

## Review Focus

1. **目录文件丢了或写坏了**（`assets/fx_catalog.json` 不存在或不是 JSON）：编排里没有 fx 字段时，narrate 照常运行；有 fx 字段时，报一行中文错误「效果目录 … 读不了：重跑 fx_catalog.py」，不能抛 traceback。测试放在 Task 2。
2. **原声段接原声段，后一段写了转场**：切点前后都是 `live` 镜头，转场照样生效，`shot` 指向前一个原声段。测试放在 Task 4。
3. **一句的第一个镜头来自回退**（`pick_one` 从本章素材借来的，`vis=None`）：这个镜头仍然属于这一句，转场照样挂在它前面；这句的滤镜不加在它上面。测试放在 Task 4。
4. **shots.csv 的 `idx` 不是从 1 连续编号**（被手改或被别的工具重写过）：build 预检时把 `idx` 和行号一起核对，对不上就报错，不能按位置挂到错的镜头上。测试放在 Task 5。
5. **页面待定副本永远清不掉**：服务器回来的 `visuals` 键的顺序和本地不同。比较时要用键排序后的 JSON，快照一致就清掉待定副本，之后的操作从快照出发。测试放在 Task 7。

---

### Task 1: 效果目录 `fx_catalog.py` → `assets/fx_catalog.json`

**Files:**
- Create: `skills/jianying-autocut/scripts/fx_catalog.py`（PEP 723 头部的依赖和 `build.py` 相同，只要 pyJianYingDraft）
- Create: `skills/jianying-autocut/assets/fx_catalog.json`（生成后提交）
- Test: `tests/test_fx_catalog.py`

**Interfaces:**
- Produces:
  - `SOURCES: dict[str, tuple[type[Enum], str]]` = `{"transition": (TransitionType, "name"), "effect": (VideoSceneEffectType, "name"), "filter": (FilterType, "name"), "intro": (IntroType, "title"), "outro": (OutroType, "title")}`
  - `build_catalog(sources=SOURCES) -> dict`：结构见 spec §4，顶层有 `"lib": "pyJianYingDraft@69cee12"`。显示名重名时 `raise ValueError`，消息里列出 `类/显示名: 成员1, 成员2`。
  - `CATALOG_PATH`：`assets/fx_catalog.json` 的绝对路径（按脚本所在目录算）。
  - `main()`：写 `CATALOG_PATH`（`ensure_ascii=False, indent=0, sort_keys=True`），打印五类条数和其中免费的条数。

- [ ] **Step 1: 写失败测试** `tests/test_fx_catalog.py`：
  - `test_catalog_file_matches_library`：读提交的 JSON，`== build_catalog()`；五类条数依次是 453、1097、1160、155、124。
  - `test_member_roundtrip`：每一类随便取 20 条（加上全部会员项里的前 5 条），`getattr(enum, e["member"]).value` 的显示名等于键，`resource_id` 和 `is_vip` 一致。
  - `test_special_names`：`catalog["effect"]["X-Signal"]["member"] == "X_Signal"`；`catalog["transition"]["叠化"]["dur"] == 0.5`。
  - `test_duplicate_display_name_fails`：用 `Enum("Fake", {"a": M("同名"), "b": M("同名")})`（`M` 是有 `name / is_vip / resource_id` 的简单对象）调用 `build_catalog({"effect": (Fake, "name")})`，`pytest.raises(ValueError, match="同名")`。
- [ ] **Step 2:** 运行 `./run_tests.sh tests/test_fx_catalog.py -v`。Expected：ImportError（`fx_catalog` 不存在）。
- [ ] **Step 3:** 实现 `fx_catalog.py`，运行 `uv run --script skills/jianying-autocut/scripts/fx_catalog.py` 生成 JSON。
- [ ] **Step 4:** 运行 `./run_tests.sh tests/test_fx_catalog.py -v`。Expected：4 passed。
- [ ] **Step 5:** Commit `feat(fx): 效果目录 fx_catalog.py → assets/fx_catalog.json`

### Task 2: 校验（`fx.validate_fx`，接进 `narrate.validate`）

**Files:**
- Create: `skills/jianying-autocut/scripts/fx.py`（`# dependencies = []`）
- Modify: `skills/jianying-autocut/scripts/narrate.py`：`validate()`（第 73 行起）、`main()`
- Test: `tests/test_fx.py`（新建）

**Interfaces:**
- Consumes: `assets/fx_catalog.json`（Task 1）
- Produces:
  - `fx.CATALOG_PATH`；`fx.load_catalog(path=CATALOG_PATH) -> dict`，读不了时 `raise ValueError(f"效果目录 {path} 读不了：重跑 fx_catalog.py（{e}）")`。
  - `fx.KEYS = {"transition": {"type","dur","reason"}, "effect": {"type","reason"}, "filter": {"type","intensity","reason"}, "intro": {"type","reason"}, "outro": {"type","reason"}}`
  - `fx.has_fx(plan) -> bool`：plan 里有没有任何 fx 字段。
  - `fx.validate_fx(plan, catalog) -> (errs: list[str], warns: list[str])`
  - `narrate.validate(plan, clip_durs, file_durs, catalog=None)`：只有 `fx.has_fx(plan)` 时才加载目录（`catalog` 为 None 就调用 `fx.load_catalog()`），把 `ValueError` 变成一条错误。

- [ ] **Step 1: 写失败测试**（`tests/test_fx.py`，目录用一个手写的小字典 `CAT`，包含 `叠化`（dur 0.5）、`闪白`、`冲击波`、`夏日风吟`、`渐显`、`渐隐`）：
  - `test_unknown_name_suggests`：`transition.type = "叠画"` 报错，消息里有「叠化」。
  - `test_unknown_key`：`{"type": "叠化", "durr": 1}` 报错，消息里有「durr」。
  - `test_not_object_or_missing_type`：值是 `"叠化"`、`{}` 时都报错。
  - `test_dur_bad`：参数化 `"1"`、`True`、`nan`、`inf`、`0`、`-1`、`1e-7`（换算后是 0 微秒），都报错。
  - `test_intensity_bad`：参数化 `True`、`"60"`、`nan`、`-1`、`101`，都报错；`0`、`100`、`60.5` 不报错。
  - `test_transition_on_first_kept_item`：第一项写转场报错；第一项 `skip`、第二项写转场，也报错。
  - `test_skipped_item_fx_warns`：被跳过的项写 `transition` / `effect` / `visuals[0].filter`，是警告，不是错误。
  - `test_limits_warn`：9 个转场、4 个特效，各给一条警告。
  - `test_old_plan_no_new_messages`：`tests/test_narrate.py` 里 `_work()` 生成的编排，`validate` 的结果和不传目录时完全相同。在 `test_narrate.py` 里加 `test_validate_without_fx_needs_no_catalog`：把 `fx.CATALOG_PATH` monkeypatch 成不存在的路径，旧编排的 `validate` 不报错。
  - `test_catalog_missing_only_matters_with_fx`（Review Focus 1）：同样 monkeypatch，带 `intro` 的编排调用 `narrate.main(["--work", w, "--dry-run"])` 返回 1，stderr 里有「重跑 fx_catalog.py」。
- [ ] **Step 2:** 运行 `./run_tests.sh tests/test_fx.py tests/test_narrate.py -v`。Expected：新测试 FAIL（ImportError / 断言），旧测试仍然 PASS。
- [ ] **Step 3:** 实现 `fx.py` 里的校验部分，并改 `narrate.validate`。候选名用 `difflib.get_close_matches(name, catalog[kind], n=3)`；「第一个没被跳过的项」按 `items` 的顺序找。错误消息以 `"{iid}："` 开头，和现有消息风格一致。
- [ ] **Step 4:** 运行同一条命令。Expected：全部 PASS。
- [ ] **Step 5:** Commit `feat(fx): narration_plan 的效果字段校验`

### Task 3: `layout()` 记录每个镜头的来源

**Files:**
- Modify: `skills/jianying-autocut/scripts/narrate.py`：`_place_any()`（第 499 行起）、`layout()`（第 576 行起）
- Test: `tests/test_narrate.py`

**Interfaces:**
- Produces（`layout` 的返回值不变，只给 `report` 加两个键）：
  - `report["srcs"]: list[{"item": str, "vis": int | None}]`，和 `rows` 一一对应。
  - `report["slots"]: list[{"item", "start_us", "end_us", "live"}]`，是最终的槽（零头挤给下一句之后的边界）。
  - `_place_any` 返回的 shot dict 多一个键 `"v"`：选中的那个候选 dict 本身。layout 用 `vis` 列表里的**同一个对象**（`is` 比较）反查原始下标，查不到（借来的、`pick_one` 的）就是 `None`。
  - 原声段镜头：`{"item": it["id"], "vis": None}`。被 `_extend` 延长的镜头不改来源。

- [ ] **Step 1: 写失败测试**：
  - `test_srcs_record_item_and_vis`：一句配 `c1`、`c2`，槽够长、能分两块。`srcs` 是 `[{"item": "L1", "vis": 0}, {"item": "L1", "vis": 1}]`。
  - `test_srcs_actual_visual_when_first_is_taken`：`c1` 已经被前一句占满。本句 `visuals = [c1, c2]`，两块都落在 `c2` 上，`vis` 都是 1。
  - `test_srcs_borrowed_is_none`：本句的画面全被占用，从相邻句借了画面。`vis is None`，`item` 是本句。
  - `test_srcs_extended_keeps_source`：第二句 `visuals=[]`，延续第一句的镜头。只有一行，`srcs == [{"item": "L1", "vis": 0}]`。
  - `test_srcs_live`：原声段那一行是 `{"item": "V1", "vis": None}`。
  - `test_report_slots_after_nudge`：沿用现有零头测试的场景，`report["slots"]` 的边界和 `rows` 的切点一致。
  - `test_rows_unchanged_by_tracking`：`rows` 里没有 `v`、`item`、`vis` 列（`write_shots` 的列不变）。
- [ ] **Step 2:** 运行 `./run_tests.sh tests/test_narrate.py -v`。Expected：新测试 FAIL（`KeyError: 'srcs'`）。
- [ ] **Step 3:** 实现。新建镜头的位置有三处：原声段、`placed = place(...)`、`nxt = place(...)`。都在这里设 `item` 和 `vis`；输出 rows 时弹出 `v`，生成 `srcs`。
- [ ] **Step 4:** 运行 `./run_tests.sh -v`。Expected：全部 PASS（旧测试的 rows 不变）。
- [ ] **Step 5:** Commit `feat(narrate): 镜头记录来源（item、实际选中的画面下标）`

### Task 4: 计算 fx、`shots_sig`，写进 `narration_track.json`

**Files:**
- Modify: `skills/jianying-autocut/scripts/fx.py`
- Modify: `skills/jianying-autocut/scripts/narrate.py`：`main()`、`_print_report()`
- Test: `tests/test_fx.py`、`tests/test_narrate.py`

**Interfaces:**
- Consumes: `report["srcs"]`、`report["slots"]`（Task 3）、`fx.load_catalog`（Task 2）
- Produces:
  - `fx.shots_sig(rows) -> str`：`"sha1:" + sha1("\n".join(f"{int(idx)}|{kind}|{source}|{int(in_us)}|{int(start_us)}|{int(dur_us)}"))`。rows 可以是 narrate 的 int 字典，也可以是 `read_csv` 读出来的字符串字典，两种算出来要一样。
  - `fx.compute_fx(plan, rows, srcs, slots, catalog) -> (fx: dict | None, warns: list[str], notes: dict[str, list[str]])`：
    - `fx` 的结构见 spec §5.3，有 `shots_sig`；一个生效的效果都没有时返回 `None`。
    - `notes` 是 `item_id → ["转场 叠化 0.6s", …]`，给 dry-run 用；片头 / 片尾的 note 挂在第一个 / 最后一个镜头所属的 item 上。
  - narrate 写出的 `track["fx"]`：只在 `fx is not None` 时写。dry-run 在每一项后面打印 `⤷ …`，`warns` 并进 ⚠，会员项打印成一行「会员：星光叠化（L11）、…」。

规则见 spec §5.2。这些决定 spec 没写，这里定死：
- 转场：在 rows 里找第一个 `srcs[r]["item"] == k` 的行 r。r 是第 0 行，或者找不到时，警告「{k}：没有自己的镜头（被上一句延长吞掉），转场忽略」。否则 `shot = r`（1 起，也就是切点前那一行的 idx），`at_us = rows[r]["start_us"]`。
- 时长：`dur_us = round(dur*US)`，省略时用目录 `dur`。截到 `min(rows[r-1].dur_us, rows[r].dur_us) // 2`，截短时警告。
- 特效：`[slot.start_us, slot.end_us)`。
- 滤镜：`srcs[r] == {"item": k, "vis": i}` 的每一行一条记录，`intensity` 省略时为 100。一行都没有时警告。如果这句的第 i 块用了别的画面，警告里写出用了哪个素材。

- [ ] **Step 1: 写失败测试**（`tests/test_fx.py`。用 `test_narrate.py` 的 `_lay` 风格真实跑 `layout`，再调用 `compute_fx`。辅助函数 `_fx(items, clips, plan_extra=None, **opts)`）：
  - `test_transition_at_cut_plain`：两句，第二句写 `叠化 0.6`。`at_us == rows[1].start_us`，`shot == 1`，`dur_us == 600000`。
  - `test_transition_before_and_after_live`：`L1, V1(live, 带转场), L2(带转场)`。两个切点都对上。
  - `test_transition_live_to_live`（Review Focus 2）：`V1, V2(带转场)`，`shot == 1`。
  - `test_transition_multi_visual_item`：第二句配了两个画面。切点是它的第一个镜头。
  - `test_transition_continuation_borrowed_new_shot`：延续项紧跟原声段，切出了新镜头。转场生效。
  - `test_transition_swallowed_warns`：槽太短，被上一句延长吞掉。`fx is None`，警告里有「吞掉」。
  - `test_transition_after_nudge`：零头挤给下一句，`at_us` 等于挪动后的切点。
  - `test_transition_on_fallback_shot`（Review Focus 3）：一句的第一个镜头来自 `pick_one`。转场生效；这句 `visuals[0]` 的滤镜不加在这一行。
  - `test_transition_truncated_and_dropped`：`dur 5` 截到较短镜头的一半，并给警告；两侧镜头都是 0.15s 时，截出来 < 0.1s，忽略并警告。
  - `test_effect_covers_final_slot`
  - `test_filter_follows_all_shots_of_visual`：一个画面拆成两块，两行都有滤镜，强度省略时是 100。
  - `test_filter_not_on_borrowed`
  - `test_filter_visual_swallowed_warns`
  - `test_filter_extended_shot`：延续项延长了上一句的镜头，滤镜记录只有一条，覆盖整个延长后的行。
  - `test_intro_outro_truncated_and_single_shot_halves`：只有一个 0.6s 的镜头、默认时长 0.5s 时，片头和片尾各 300000。
  - `test_no_fx_returns_none`
  - `test_vip_flag_from_catalog`
  - `test_shots_sig_sensitive`：参数化六个字段，各改一个，指纹都会变；`int` 字典和对应的 `str` 字典算出来的指纹相同。
  - 在 `test_narrate.py` 里：`test_main_writes_fx_only_when_present`（旧编排不写 `fx` 键；带 `intro` 的编排写了，并且 `shots_sig == fx.shots_sig(read_csv(shots.csv))`）、`test_dry_run_prints_fx_lines`（输出里有「⤷ 转场 叠化 0.6s」）。
- [ ] **Step 2:** 运行 `./run_tests.sh tests/test_fx.py tests/test_narrate.py -v`。Expected：新测试 FAIL。
- [ ] **Step 3:** 实现 `shots_sig`、`compute_fx`，接进 `main` 和 `_print_report`（`_print_report` 多接一个 `fx_notes` 参数，默认为 `{}`）。
- [ ] **Step 4:** 运行 `./run_tests.sh -v`。Expected：全部 PASS。
- [ ] **Step 5:** Commit `feat(fx): narrate 按最终镜头计算效果，输出 fx 段和 shots 指纹`

### Task 5: build：预检、挂效果、特效轨

**Files:**
- Create: `skills/jianying-autocut/scripts/fx_draft.py`（依赖 pyJianYingDraft，从 `fx_catalog.SOURCES` 拿枚举）
- Modify: `skills/jianying-autocut/scripts/build.py`：`main()`。预检放在读完 `narr` 之后、`rmtree` 之前；挂效果放在主轨循环里的 `script.add_segment(seg, main_track)` 之前
- Test: `tests/test_build_main.py`

**Interfaces:**
- Consumes: `fx.shots_sig`、`fx.load_catalog`、`fx_catalog.SOURCES`
- Produces:
  - `fx_draft.member(kind, name, catalog)`：返回枚举成员；查不到时 `raise KeyError(f"{kind} {name} 不在效果目录里")`。
  - `fx_draft.preflight(fx, shots, catalog) -> list[str]`：检查 `shots_sig`；每个 `shot` 行号在范围内，并且 `int(shots[shot-1]["idx"]) == shot`；转场 `at_us == start_us + dur_us`；滤镜 / 片头 / 片尾的 `start_us`（如果有）等于这一行的 `start_us`；每个名字都能取到成员。错误消息末尾统一加「（重跑 narrate.py）」。
  - `fx_draft.by_shot(fx) -> dict[int, list[tuple[str, dict]]]`：键是行号，值是 `("transition"|"filter"|"intro"|"outro", 条目)` 的列表。
  - `fx_draft.attach(seg, entries, catalog) -> None`：转场用 `add_transition(m, duration=dur_us)`，滤镜用 `add_filter(m, intensity)`，动画用 `add_animation(m, dur_us)`。
  - `fx_draft.add_effects(script, fx, catalog) -> int`：有特效时 `append_track(TrackSpec(TrackType.effect, "特效"))`，逐条调用 `add_effect`，返回条数。
  - `fx_draft.summary(fx) -> str`：比如「转场 6 个、特效 2 个、滤镜 1 个、片头片尾动画 2 个；会员：星光叠化（L11）」。

- [ ] **Step 1: 写失败测试**（在 `test_build_main.py` 加辅助函数 `_with_fx(work, fx_patch)`：往 `_narration()` 写出的 track 里加 `fx`，`shots_sig` 用真实的 shots.csv 算）：
  - `test_fx_attached_before_add_segment`：转场挂在第 1 行、滤镜 60 挂在第 2 行、片头挂在第 1 行、片尾挂在第 2 行、特效 `[1s, 2s)`。build 成功；`materials.transitions` 1 条，挂在第 1 段的 `extra_material_refs` 里；滤镜材料的 `value == 0.6`；`material_animations` 有 in 和 out；特效轨有 1 段，`target_timerange == {"start": 1000000, "duration": 1000000}`；没有悬空引用（现有自检通过）。
  - `test_preflight_sig_mismatch_keeps_old_draft`：`shots_sig` 改掉一位，带 `--replace` 重建「旧草稿」。`SystemExit`，提示里有「重跑 narrate.py」，`old/keep.txt` 还在。
  - 同样的结构参数化：行号越界、`at_us` 对不上、名字查不到。
  - `test_preflight_idx_not_position`（Review Focus 4）：shots.csv 两行的 `idx` 写成 `1, 3`，`shots_sig` 按改过的 idx 重算。预检失败。
  - `test_no_fx_no_effect_track`：没有 `fx` 键时，草稿里没有 `"特效"` 轨，`transitions`、`video_effects`、`material_animations` 都是空的，滤镜材料为 0 条。
- [ ] **Step 2:** 运行 `./run_tests.sh tests/test_build_main.py -v`。Expected：新测试 FAIL。
- [ ] **Step 3:** 实现 `fx_draft.py`，接进 `build.main`：`fxd = narr.get("fx") if narr else None`；有 fx 时先 `preflight`，有错就 `sys.exit`；主轨循环里用 `by_shot(fxd).get(int(s["idx"]), [])` 先调用 `attach`，再 `add_segment`；主轨之后调用 `add_effects`。
- [ ] **Step 4:** 运行 `./run_tests.sh -v`。Expected：全部 PASS。
- [ ] **Step 5:** Commit `feat(fx): build 预检并在入轨前挂上转场、滤镜、动画，特效轨`

### Task 6: build 自检：效果逐个对上

**Files:**
- Modify: `skills/jianying-autocut/scripts/fx_draft.py`、`skills/jianying-autocut/scripts/build.py`：`verify()`（第 378 行起），以及报告输出
- Test: `tests/test_build_main.py`、`tests/test_fx_draft.py`（新建，纯函数测试）

**Interfaces:**
- Produces:
  - `fx_draft.verify_fx(d, fx, catalog) -> list[str]`：`d` 是读回的 `draft_info.json`。读回路径和比对内容见 spec §7 的表格。两个方向都要比：预期有、草稿里没有，算失败；草稿里多出来的也算失败。按主轨片段的位置（1 起）对应 `shot`。
  - `build.verify` 补一项：所有 `effect` 类型轨道的片段，`material_id` 要在 `materials` 的 id 集合里。
  - build 报告：有 fx 时在 ✓ 行加「✓ 效果逐个对上」，下一行打印 `summary(fx)`。

- [ ] **Step 1: 写失败测试**（`tests/test_fx_draft.py`：`from test_build_main import _setup, _narration, _with_fx`，先用 Task 5 的辅助函数真实 build 一份带全部五类效果的草稿，读回 `d`，再在 `d` 上动手脚）：
  - `test_verify_clean`：没改过的 `d`，`verify_fx == []`。
  - `test_verify_transition_on_wrong_segment`：把转场的 ref 从第 1 段挪到第 2 段，报错。
  - `test_verify_wrong_duration`、`test_verify_wrong_name`（改 `resource_id`）、`test_verify_wrong_intensity`（`value = 0.61`）、`test_verify_animation_out_of_range`（out 动画的 start 改成负数）。
  - `test_verify_extra_effect`：特效轨多加一段，报错。
  - `test_verify_missing_effect`：删掉特效轨，报错。
  - `test_verify_intensity_tolerance`：`value = 0.6 + 5e-7`，不报错。
  - 在 `test_build_main.py` 里：`test_effect_segment_dangling_material_id`：读回后把特效段的 `material_id` 改成 `"nope"`，调用 `build.verify`，报「悬空」。
- [ ] **Step 2:** 运行 `./run_tests.sh tests/test_fx_draft.py tests/test_build_main.py -v`。Expected：新测试 FAIL。
- [ ] **Step 3:** 实现。先用一次真实 build 打印出读回的 JSON 结构，确认字段名后再写比对；字段名以实际读回为准，写进函数的 docstring。
- [ ] **Step 4:** 运行 `./run_tests.sh -v`。Expected：全部 PASS。
- [ ] **Step 5:** Commit `feat(fx): build 读回草稿逐个核对效果，特效轨补悬空检查`

### Task 7: 页面：`visuals` 的待定副本

**Files:**
- Modify: `skills/jianying-autocut/assets/shoot_plan_page.html`：`write()` 附近、`reassign-n`、`vflag-n`、nmatch 快照回调
- Test: `tests/page/fx_harness.js`（新建，风格和 `narration_harness.js` 一样，用假 db；`ref().update` 可以配置成失败）

**Interfaces:**
- Produces（页面内部函数，Task 8 要用）：
  - `S.pendingVis: Map<id, visuals[]>`
  - `curVis(id) -> visuals[]`：有待定副本就返回它，否则返回 `S.nmatch[id].visuals || []`。
  - `writeVis(id, visuals, extra = {})`：设置待定副本，然后 `write("nmatch/" + id, { visuals, ...extra })`。
  - 快照回调：`canon(S.nmatch[id].visuals) === canon(pending)` 时清掉待定副本。`canon` 是递归按键排序后的 `JSON.stringify`。
  - `reassign-n`：同一素材时保留 `filter`、`reuse`、`mute`；换素材时三个都不带。`vflag-n`：从 `curVis(id)` 出发改。

- [ ] **Step 1: 写失败测试** `tests/page/fx_harness.js`：
  - `reassignSameClipKeepsFilter`：`visuals[0]` 带 `filter`，改成同一素材、不同秒数，写出的 `visuals[0].filter` 还在。
  - `reassignOtherClipClears`：换成别的素材，写出的数组里没有 `filter`、`reuse`、`mute`。
  - `muteKeepsFilter`：勾选「消音」，写出的 `visuals[0].filter` 还在。
  - `noResurrection`：在快照还带着滤镜的情况下，删除滤镜（直接调用 `writeVis(id, 去掉 filter 的数组)`，让写入失败），马上勾选「消音」，再重试。所有写出的数组都不再带 `filter`。
  - `chainedOpsWithStaleSnapshot`：快照不更新，连续两次 `vflag-n`（先勾 reuse，再勾 mute）。第二次写出的数组同时有 `reuse` 和 `mute`。
  - `pendingClearedOnReorderedSnapshot`（Review Focus 5）：推送一个和待定副本内容相同、但键顺序不同的快照，`S.pendingVis` 被清空。
- [ ] **Step 2:** 运行 `./run_tests.sh tests/test_page.py -v`。Expected：`fx_harness` FAIL，其他 harness PASS。
- [ ] **Step 3:** 实现。harness 要能拿到 `S`、`writeVis`：沿用现有 harness 的做法（`eval` 页面脚本后，变量就在作用域里）。
- [ ] **Step 4:** 运行 `./run_tests.sh tests/test_page.py -v`。Expected：全部 PASS。
- [ ] **Step 5:** Commit `fix(page): visuals 的写入从本地待定副本出发，滤镜等字段不会被旧快照覆盖`

### Task 8: 页面：效果卡片、确认 / 改 / 去掉、清单标记、片头片尾

**Files:**
- Modify: `skills/jianying-autocut/assets/shoot_plan_page.html`：`narrPanel()`、`narrEditView()`、click 处理表、CSS
- Test: `tests/page/fx_harness.js`（接着 Task 7 写）

**Interfaces:**
- Consumes: `curVis`、`writeVis`（Task 7）
- Produces:
  - `fxCard(kind, obj, ctx) -> html`：`kind` 是 `transition|effect|filter|intro|outro` 之一。`ctx` 是 `{id}`（句子）、`{id, i}`（滤镜）或 `{meta: true}`（片头 / 片尾）。卡片显示中文类别（转场 / 画面特效 / 滤镜 / 片头 / 片尾）、名字、时长或强度、理由；状态显示「待确认」或「已确认」；`vip === true` 时显示「会员」，`vip === null` 时显示「会员？」。
  - 按钮的 `data-act`：`fx-confirm`、`fx-edit`、`fx-save`、`fx-remove`。`data-kind`、`data-id`、`data-i`、`data-meta` 指定目标。输入框 id 是 `fx-type-…`、`fx-dur-…`、`fx-int-…`。
  - 写入：
    - 句子上的转场 / 特效：`write("nmatch/"+id, {[kind]: obj})`；
    - 滤镜：`writeVis(id, …)`；
    - 片头 / 片尾：`write("plan/meta", {[kind]: obj})`。
    - 确认时写 `{...obj, confirmed: true, by: "user"}`。保存时，改过的值写进去，同时 `confirmed: true, by: "user"`；名字改了的话再加 `vip: null`。去掉时整个字段写成 `null`（滤镜从那个画面对象里删掉 `filter` 键）。
  - 清单：这一句（包括它的画面滤镜）有任何非 null 的效果时，在文字前显示 `✦`；其中有 `confirmed !== true` 的，加 class `fx-todo`（黄色）。
  - 剪辑视图顶部：`S.meta.intro`、`S.meta.outro` 两张卡片，没有时不显示。

- [ ] **Step 1: 写失败测试**（接着写在 `fx_harness.js`）：
  - `cardsRender`：转场卡片里有「叠化」「0.6s」、理由、「待确认」；会员项有「会员」；`vip:null` 显示「会员？」。
  - `confirmWrites`：点确认后写入 `{transition: {..., confirmed: true, by: "user"}}`。推送带 confirmed 的快照后，卡片显示「已确认」。
  - `editWrites`：把名字改成「闪白」、时长改成 0.8，写入的对象里 `type`、`dur` 是新值，`confirmed` 是 true，`vip` 是 null。
  - `removeWritesNull`：去掉转场写入 `{transition: null}`；去掉滤镜后，写出的 `visuals[0]` 里没有 `filter` 键。
  - `introOutroSeparate`：确认片头只写 `plan/meta` 的 `{intro: …}`，没有 `outro` 键。
  - `listMarker`：有待确认效果的句子显示 `✦` 和 `fx-todo`；全部确认后去掉 `fx-todo`。
  - `oldDataRenders`：没有任何 fx 字段的 nmatch 和 meta 照常渲染，没有 `✦`，也没有效果卡片。
- [ ] **Step 2:** 运行 `./run_tests.sh tests/test_page.py -v`。Expected：新断言 FAIL。
- [ ] **Step 3:** 实现。滤镜卡片放在对应画面的 `.card` 里，和 `.checks` 放在一起；转场 / 特效卡片放在 `dl.kv` 之后。
- [ ] **Step 4:** 运行 `./run_tests.sh -v`。Expected：全部 PASS。用浏览器打开页面，跑一次 harness 的假数据看样式。这一步可选；做了的话，截图给用户。
- [ ] **Step 5:** Commit `feat(page): 旁白片剪辑视图的效果卡片，逐个确认 / 改 / 去掉`

### Task 9: 文档

**Files:**
- Modify: `skills/jianying-autocut/references/narration.md`：新增「转场与特效」一节（spec §6 的建议原则，加上 §3 字段表的精简版）；「导出」一条补上读 `plan/meta`、白名单、只导出已确认的效果、把被排除的项列给用户、写建议时不覆盖值为 `null` 的字段。
- Modify: `skills/jianying-autocut/references/shoot_plan.md`：db 结构里补 `nmatch.transition/effect`、`visuals[i].filter`、`plan/meta.intro/outro` 和效果对象的结构。
- Modify: `skills/jianying-autocut/SKILL.md`：「不做」里删掉「动画 / 特效 / 转场轨」，改成「镜头片的转场特效（旁白片已支持，见 references/narration.md）」；第 7 步的说明改成「调色、改字幕、导出」；第 6 步注意事项加一句「目录升级：升级 pyJianYingDraft 后重跑 `fx_catalog.py`」。
- Modify: `README.md`：如果有功能列表，补一行。

- [ ] **Step 1:** 改文档。导出白名单写成一张表，内容照抄 spec §8。
- [ ] **Step 2:** 运行 `./run_tests.sh`。Expected：全部 PASS（文档不影响测试，这一步只是确认工作区干净）。
- [ ] **Step 3:** Commit `docs(fx): 旁白片效果的建议原则、页面数据结构和导出规则`

### Task 10: 真机验收：枸杞岛 v7（spec §2）

只在 Task 1–9 合并之后做。需要用户在剪映里检查，不写代码。

- [ ] **Step 1:** 读 `W/narration_plan.json` 和 `scene_notes.json`，按 spec §6 写建议：转场 ≤ 8 个、特效 ≤ 3 个、片头「渐显」、片尾「渐隐」，每条都有 `reason`。写进 live 页面的 nmatch / `plan/meta`，`confirmed: false, by: "claude"`，`vip` 按目录填。先把页面模板更新到这一版（重新发布到同一个 URL）。
- [ ] **Step 2:** 请用户在页面上逐个确认。确认后导出到 `W/narration_plan.json`，同步到 `W/_build_lut/`，然后跑 `narrate.py --work W/_build_lut --dry-run`。把 `⤷` 行、⚠ 和会员项给用户看。
- [ ] **Step 3:** 用户同意后去掉 `--dry-run`，然后 `build.py --work W/_build_lut --name 枸杞岛-车坏了以后-旁白版-v7 --narration … --bgm …`（参数和 v6 相同）。自检必须全部 ✓。
- [ ] **Step 4:** 请用户在剪映里检查：效果都在、位置都对、旁白和画面同步；另外看一下转场借画面时，素材首尾会不会出问题（spec §2「不做」的最后一条）。把发现写进 memory。
