# 旁白片：先录旁白，画面跟着剪

用户先录好旁白（一个文件或一章一个文件），你按每句话的内容配画面，旁白的间隙里可以插原声（出镜口播、现场声）。
节奏和时长由旁白决定，不走 `story_plan.json` / `plan.py`，也不卡点。

## 流程

| 步 | 做什么 | 产出 |
|---|---|---|
| 0–3 | 素材照常盘点、抽帧、转写、写 `scene_notes.json` | `inventory.csv`、`frames.csv`、`speech.json`、`scene_notes.json` |
| N1 | `transcribe.py --work W --narration <旁白文件或目录> --context "<背景>"` | `narration_speech.json`（逐句、逐字时间、静音段；**不过滤重复句**，重复的是重录） |
| N2 | `narrate.py --work W --draft [--script W/narration_script.json]` | `narration_plan.json` 初稿：每句一个 `line`，重录 / 口误默认 `skip` |
| N3 | **你来配画面**：按句子内容和 `scene_notes` 给每个 `line` 写 `visuals`，需要原声的地方插 `live`，按故事需要标 `bgm` | 改好的 `narration_plan.json`（或页面上的 `nmatch`） |
| N4 | 有页面时发给用户确认（见下），确认后导出成 `narration_plan.json` | — |
| N5 | `narrate.py --work W --dry-run` 给用户看 → 去掉 `--dry-run` | `shots.csv`、`narration_track.json` |
| N6 | 确认剪映已 ⌘Q 退出 → `build.py --work W --name <草稿名> --narration W/narration_track.json [--bgm 歌.mp3] [--titles] [--subs W/subtitles.json]` | 剪映草稿 + 自检 + 响度报告 |

`--script`：有旁白稿时（模式 A 页面的 `lines`），导出成 `[{"id": "L01", "text": "…"}]` 给它。转写会和稿子逐句对齐：
同一句录了几遍取最后一遍，对不上稿子的句子（口误、闲聊）默认跳过，稿子里没录到的句子在初稿的 `missing_script` 里列出。
没有稿子时按相似度找重录（后面 3 句之内相似度 ≥ 0.8 的，前一遍跳过），含"重来 / 不对 / 再来一遍"的短句也跳过。

## `narration_plan.json`

```json
{"files": {"n1": "/abs/旁白/01_开场.m4a"},
 "chapters": [{"id": "ch1", "title": "出发"}],
 "items": [
  {"id": "L01", "type": "line", "chapter": "ch1", "file": "n1", "start": 0.4, "end": 5.2,
   "text": "凌晨四点，我们从山脚出发。", "visuals": [{"clip_id": "c003", "at": 12.0}, {"clip_id": "c004"}]},
  {"id": "L02", "type": "line", "chapter": "ch1", "file": "n1", "start": 6.0, "end": 8.1,
   "text": "凌晨四点，我们……", "skip": true, "skip_reason": "重录，取后一遍"},
  {"id": "V01", "type": "live", "chapter": "ch1", "clip_id": "c007", "start": 30.6, "end": 36.8,
   "reason": "到顶时大家的欢呼", "bgm": "drop"}]}
```

| 字段 | 说明 |
|---|---|
| `items` 顺序 | 就是成片顺序；`chapter` 只是标签（章节标题用） |
| `line.start/end` | 旁白文件内秒，来自转写；句头句尾被切时手动放宽 |
| `line.visuals` | 按顺序平分这句的画面时长。`at` = 素材里必须出现的那一刻；不写 `at` 就取得分最高的窗口。空列表 = 延续上一个镜头 |
| `live` | 画面和声音都来自这段素材，旁白在这里暂停。`start` 比原声句子早 0.4s、`end` 晚 0.3s，让环境声先进来 |
| `skip` | 不进成片，但留着，用户可以恢复 |
| `bgm` | `"drop"`：这一项期间 BGM 淡出（揭晓前的留白、让现场声呼吸）；`"up"`：这一项期间 BGM 不压低（只对没有人声的 `live` 有效，比如纯画面的高潮）。**只在故事确实需要的地方建议，写明理由，让用户确认** |
| `pause_after` | 这句后面的停顿秒数，覆盖自动压缩 |

### 配画面怎么想

- 一句话配 1–2 个画面就够，长句（> 8s）配 2–3 个。画面说的是同一件事，不是字面图解（说"很累"不用找人喘气，找陡坡）。
- 素材里有人对镜说话的段落会被降权（画面张嘴、声音是旁白很怪），真要用就写 `at`。
- 同一素材的两个镜头不会相邻；指定的素材放不下时，脚本按"本句其它画面 → 相邻句的画面 → 本章出现过的素材"回退，并在 `--dry-run` 里报 ⚠ 和所选画面的描述，你看一眼是否语义错位。

## 时间线规则（`narrate.py`）

- 同一文件里相邻的保留句连成一段音频，停顿里留着真实底噪；停顿按 ×0.6 压缩、夹在 0.3–1.2s，要缩短时从停顿中间剪。
- 块首尾向外扩到最近的静音（最多 0.3s），永不内缩，免得吃字。
- 画面比开口早 0.3s 切（J-cut）；`live` 之后的第一句不提前（不切进原声）。
- 跨文件留 1.2s；片头 1s、片尾 1.5s 只有画面。

都可以调：`--lead`、`--head`、`--tail`、`--pause-ratio`、`--pause-min`、`--pause-max`、`--file-gap`。
用户觉得节奏太赶就加大 `--pause-ratio`（0.8）；太拖就减小（0.4）。

## 混音（`build.py --narration`）

| 声音 | 规则 |
|---|---|
| 旁白 | 每个文件按实测归一化到 -16 LUFS，最多 +12 dB，真峰值 ≤ -1 dBTP；一个文件一个增益，不逐句拉平 |
| 旁白下的原声 | 垫底：比人声低 18 LU，最多 15% |
| 原声段（`live`） | 按人声归一化；现场太吵（人声比底噪高不到 15 dB）就不提升 |
| BGM | 每首歌先按实测拉到同一响度；默认停在压低档，**全片一个压低比例**（保证人声比 BGM 高 ≥ 12 LU）；只在 ≥ 4s 没有人声的空隙或 `bgm: up` 处升起（升 0.8s、压 0.3s），`bgm: drop` 处淡出 |

报告里的提示：

| 提示 | 怎么办 |
|---|---|
| `xx 太小声，提到 +12 dB 还差 N dB` | 建议用户重录（离麦近一点），或在剪映里降噪后再提音量 |
| `原声段 cxxx 现场太吵` | 换一段，或接受原音量 |
| `mm:ss 人声只比 BGM 高 N LU` | 这首歌那一段太响：`--bgm 歌.mp3:0.15` 整首调低，不要逐句调 |
| `音量放大（>100%）待真机验证` | 剪映 11.6 是否接受 >100% 的音量还没实测；打开草稿听一下，旁白音量不对就在剪映里手动调，并记进 pitfalls.md |

响度结果缓存在 `W/loudness.json`，旁白重录覆盖后会自动重测。`beatsync.py` 遇到旁白片会拒跑：旁白锁死了时长，不能按节拍伸缩镜头。

## 和拍摄脚本页面打通

页面的 db 结构见 `shoot_plan.md` 的 `lines` / `nmatch`。

- **拍摄前（模式 A）**：每章写 `lines`（旁白稿，完整句子，约 4 字/秒），`kind: "live"` 的句子表示"这里放原声"并关联口播镜头。页面上有"录音稿"视图当提词器，用户一章录一个文件最省事。
- **剪辑时**：`plan/meta.kind` 改成 `"narration"`，`stage` 改成 `"editing"`；转写、`--draft` 之后，把每句写进 `nmatch/<line_id>`（稿外的转写句用新 id，自带 `chapter`、`order`、`text`），给出 `visuals` 建议。用户在页面上确认、换画面、改时间、标跳过 / 恢复。
- **导出**：`ArtifactData list` 读出 `chapters`、`lines`、`nmatch`，按章节 `order`、句子 `order` 排成 `items`：`line` 取 `nmatch` 的 `file/start/end/skip/visuals`，文字用稿子（`lines.text`）；`kind: "live"` 的句子展开成 `live` 项（素材和区间取自它的 `nmatch`）。写 `W/narration_plan.json`，再跑 N5。
- 没有页面时直接改 `narration_plan.json`，把 `--dry-run` 的输出给用户看。
