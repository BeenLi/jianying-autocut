# 拍摄脚本页面（模式 A 写脚本，模式 B 对素材）

拍摄脚本放在一个 Claude Artifact 页面里：用户在页面上看、勾选、确认，你用 `ArtifactData` 读写页面的数据库。
剪辑流程本身只认本地文件：进入 4c 时把数据库导出成 `W/shoot_plan.json` 和 `W/matches.json`，再跑 `match.py`。

页面模板：`assets/shoot_plan_page.html`（相对本 skill 目录）。

## 写骨架（模式 A 的 A1，或把用户口述的故事整理成骨架）

借 `vendor/video-script-refs/creative-editing-playbook.md` 的导演方法，按出发前的视角收窄：

1. 先定一句导演意图（`meta.intent`）：看完这条片子，观众得到什么。
2. 分 4–7 章：一个 `hook`（最想让人看到的画面，拍摄时就要专门去拍），至少一个 `turn`，结尾落在 `payoff`。
3. 每章 3–8 个镜头。镜头写**看得见的画面**，让人在现场一眼知道拍什么：
   - `desc`：画面描述（"灯塔在雾里若隐若现"，不写"展现孤独感"）。
   - `size`：远景 / 全景 / 中景 / 近景 / 特写 / 空镜。
   - `duration`：成片里大概用几秒。拍摄时每个镜头至少多录 5–10 秒，给剪辑留余地，写进 `tips`。
   - `tips`：时间、光线、机位、设备提示（"日落前 30 分钟""开慢动作""稳定器跟拍"）。
4. **出镜口播**（`kind: "talk"`）：`talk` 写要点，不写逐字稿（照念会僵）。按约 4 字/秒估时长，
   要点估出来超过 `duration` 就拆成两个镜头或调长 `duration`。一条片子口播镜头别太多，一章最多一两个。
5. 用户说了天数和设备，就按真实条件写：两天行程不要排出三个日出镜头；没有无人机就不写航拍。

## 发布页面（A2）

1. 把模板复制到 scratchpad，把 `<title>拍摄脚本</title>` 换成这次的名字（如"枸杞岛两日"），发布：
   `capabilities: {db: {}, user: {}, assets: {}}`，`icon: "checklist"`。
2. 用 `ArtifactData batch` 写入骨架（一次最多 50 条，多了分批）：
   - `plan/meta`：`{title, intent, place, days, stage: "shooting"}`
   - `chapters/<ch1…>`：`{order, title, function, rhythm}`
   - `shots/<S01…>`：`{chapter, order, kind, desc, size, duration, talk, tips, done: false, note: "", edited_by_user: []}`
3. 把链接给用户：手机上登录 claude.ai 打开，拍完一个勾一个。
4. 模式 B 开始时把链接写进 `W/shoot_plan_url`（一行），之后重跑任何一步都从这里找。用户找不到链接时用
   `Artifact list` 帮他找。

## 数据库结构

| 路径 | 字段 | 你写 | 用户在页面上写 |
|---|---|---|---|
| `plan/meta` | `title`, `intent`, `place`, `days`, `stage`（`shooting` / `editing`） | ✓ | `title`, `intent` |
| `chapters/<id>` | `order`, `title`, `function`, `rhythm` | 初稿 | 改名、改顺序、增删 |
| `shots/<id>` | `chapter`, `order`, `kind`, `desc`, `size`, `duration`, `talk`, `tips`, `done`, `note`, `edited_by_user` | 初稿 | 勾选、备注、改描述、增删 |
| `clips/<clip_id>` | `thumbs: [{id, t}]`（asset id + 素材内秒数）, `desc`, `duration` | ✓ | 只读 |
| `matches/<shot_id>` | `clip_id`, `at`, `start`, `end`, `confidence`（high/mid/low）, `reason`, `confirmed`, `by` | 建议 | 确认、改素材或秒数 |
| `extras/<clip_id>` | `chapter`, `at`, `reason`, `accepted`（null / true / false） | 建议 | 采纳、拒绝 |
| `requests/<id>` | `text`, `status`（new / done / not_found）, `reply`, `created` | `status`, `reply` | `text` |
| `lines/<L01…>` | `chapter`, `order`, `kind`（`narr` 旁白 / `live` 这里放原声）, `text`, `shots: [shot_id]`, `est_s`, `edited_by_user` | 旁白稿初稿 | 增删改、关联镜头 |
| `nmatch/<id>` | `file`, `start`, `end`, `skip`, `skip_reason`, `visuals: [{clip_id, at}]`, `confidence`, `reason`, `confirmed`, `by`；稿外的转写句另有 `chapter`, `order`, `text`；`live` 句用 `clip_id` + `start/end`（素材内秒） | 剪辑时的建议 | 确认、换画面、改时间、跳过 / 恢复 |

旁白片（`plan/meta.kind: "narration"`）的写法和导出见 `narration.md`。`lines.est_s` 留空时页面按约 4 字/秒自己估；
用户改了 `text` 页面会把 `est_s` 清空。

### 不覆盖用户的改动

1. 改之前先读（`list` / `get`），写的时候带上读到的 `version` 作 `if_version`；用户在这之间改过，写入会被拒，重读再写。
2. 只用 `update` 改你负责的字段，不整条 `set` 已有文档。
3. `shots.edited_by_user` 里列出的字段是用户改过的，不要再改，以用户的版本为准去找素材。
4. `confirmed: true` 的匹配不要动；重新匹配时跳过。
5. 用户在页面上可能删章、删镜头、改顺序，每次都以数据库里的当前状态为准。

章的顺序决定成片里章节的顺序（钩子章总在最前）；同一章内的镜头在成片里按拍摄时间排，页面上调镜头顺序只改脚本本身。

## 匹配（模式 B 的 4a）

前提：第 1–3 步跑完，有 `scene_notes.json`、`speech.json`、`thumbs/`。

1. 读 `shots`、`matches`、`chapters`，把 `plan/meta.stage` 改成 `editing`。
2. 对每个还没确认的镜头找素材：
   - `visual` 镜头：拿 `desc` 比 `scene_notes.json` 的画面描述，`at` 取最贴合的那一段的中间。
   - `talk` 镜头：拿 `talk` 要点比 `speech.json` 的转写文字（文字比对比看画面准），`at` 取那句话的中点，
     `start` / `end` 记整句范围。同一句话说了好几遍，挑说得最完整的那遍。
   - 写 `confidence`：画面和描述几乎一致为 `high`，大致对得上为 `mid`，只是勉强沾边为 `low`；`reason` 一句话说依据。
   - 找不到就不写匹配，页面上会显示漏拍。
   - 用户勾了 `done` 但找不到素材，在回复里专门说一声（可能素材没拷进来）。
3. 计划外素材：没对上任何镜头、但画面好或有意义的片段，写 `extras/<clip_id>`：建议放进哪章、哪一秒、为什么。
   宁缺毋滥，一章建议不超过三四段。**有漏拍的章优先**：漏拍的镜头不会被自动补上（精简模式下 match.py 生成的章只留 pin），
   想补就得靠用户采纳的计划外素材，所以给这些章找一两段能顶上的片段。
4. 缩略图：给出现在 `matches` 和 `extras` 里的每段素材，从 `W/thumbs/<clip>_<t>.jpg` 挑 2–4 张（含 `at` 附近那张），
   用 Artifact 的 `asset: true` + `file_paths` 上传（一次最多 25 张），把返回的 asset id 和秒数写进 `clips/<clip_id>.thumbs`，
   同时写 `desc`（来自 `scene_notes.json`）和 `duration`（来自 `inventory.csv`）。
5. 告诉用户：在 Mac 上打开页面，切到"剪辑"，逐个确认 🟡、看 🔴 漏拍、决定计划外素材、需要的话写补充故事。

## 用户确认与补充故事（4b）

用户说"好了"之前，按需处理 `requests` 里 `status: "new"` 的条目：去 `footage_brief.md` 里找相关素材，
找到了就新增镜头（`shots`，`edited_by_user: []`）和匹配建议，把请求标 `done` 并在 `reply` 说加了什么；
找不到标 `not_found` 并说明。然后请用户再看一遍。

## 导出并生成故事（4c）

1. `ArtifactData list` 读出全部 `plan`、`chapters`、`shots`、`matches`、`extras`。`list` 是分页返回的：
   结果里有 `next` 就带上它继续读下一页，直到没有 `next`，每个集合都读完再写 JSON（只读第一页会悄悄丢镜头）。
2. 写 `W/shoot_plan.json`：`{"meta": {...}, "chapters": [{"id": ..., ...}], "shots": [{"id": ..., ...}]}`（文档 id 放进 `id` 字段）。
3. 写 `W/matches.json`：`{"matches": {"S01": {...}}, "extras": {"c020": {...}}}`。
4. `uv run --script $S/match.py --work W`：
   - 有未确认的匹配会报错：请用户回页面确认（或把那个镜头标成漏拍），重新导出。
   - 报告里的漏拍、整章删除、待决定的计划外素材，都转述给用户。
   - `⚠ cXXX @a 和 @b 离得太近`：两章用了同一素材里挨得很近的两个瞬间，前一章的镜头会先拿走这段，后一章的 pin 会被跳过。
     请用户给其中一个换素材，或在页面上把秒数挪开。
   - `⚠ 计划外素材 … accepted 不是 true / false / null`：数据被写坏了，按待决定处理；在页面上重新点一次采纳或不要。
   - 秒数可以写 `15`、`1:05` 或 `1:05:00`；空白不等于 0。
   - `⚠ 口播 … 会被剪断`：镜头长度由章节节奏决定，整句比本章最长镜头还长。把这章 `rhythm` 改成 `slow`（页面上改章）后重新导出，
     或请用户换一遍说得更短的。
5. 接着 `story.py --work W --check`，再进第 5 步。

## 页面不可用时

claude.ai 打不开或用户不想用页面：直接在对话里把骨架和对照表写成 `W/shoot_plan.json` 和 `W/matches.json`（格式同上），
把对照表念给用户确认后把 `confirmed` 改成 `true`，照样跑 `match.py`。
