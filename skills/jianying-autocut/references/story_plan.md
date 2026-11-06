# 写故事脚本（第 4 步）

第 5 步只认 `story_plan.json`。它有三个来源，任选其一：

| 来源 | 怎么做 | 何时用 |
|---|---|---|
| 手写（默认） | 看 `contact/sheet_*.jpg` 联系表和 `speech.json`，直接写 `story_plan.json`，再 `story.py --check` | 默认流程 |
| 理解模式 | 读 `understanding/agent_narration_brief.md` 和 `clip_understanding.json`，按 video-script 格式写 `recap_story_plan.json`，再 `story.py --from-recap` | 用户选了 MiMo，跑过 `understand.py` |
| 兜底 | `story.py --default --chapters N`，按拍摄时间间隔切章 | 用户只要「快速出一版」 |

## recap_story_plan.json（理解模式，video-script 格式的子集）

时间一律是**代理长片上的秒**（brief 和 `vlm_analysis.json` 里的时间就是这个时间轴）。

```json
{
  "schema_version": 1,
  "director_intent": {"viewer_promise": "两天走完庐山东线：从雨雾里出发，到三叠泉和云海", "pov": "第一人称徒步者"},
  "beats": [
    {"beat_id": "b1", "function": "hook",   "source_start": 1210.0, "source_end": 1260.0,
     "event": "三叠泉飞瀑", "must_keep_moment": "1234.5", "key_moments": [1241.0, 1252.5], "rhythm": "fast"},
    {"beat_id": "b2", "function": "setup",  "source_start": 0,      "source_end": 420.0,  "event": "出发与上山"},
    {"beat_id": "b3", "function": "escalation", "source_start": 420.0, "source_end": 1210.0, "event": "石阶与雾"},
    {"beat_id": "b4", "function": "payoff", "source_start": 1260.0, "source_end": 1600.0, "event": "云海风车"}
  ]
}
```

- `function` 取 `hook | setup | turn | escalation | payoff`。`hook` 章会被排到成片最前（冷开场），其余按 beats 顺序。
  hook 可以只框一小段（几秒到几十秒）并给 `must_keep_moment`：它不受「不足 20s 合并」限制，可从故事里任意素材取镜头，
  精简模式下只留 pin（没有 pin 就取一个最好的镜头）；定长模式下没写 share 时默认只占 min(20s, 目标的 10%)。所有章节的 pins 会先于普通镜头放置，高光不会被别的章节占走。
- 一段素材只归一个 beat（重叠多的那个），所以 beats 之间可以粗略相接，不必精确到素材边界。
- `must_keep_moment` 写代理时间的秒数（可以带文字，取第一个数字）：那一刻一定会出现在成片里。
- `key_moments` 可选，是关键瞬间的列表，每项取第一个数字，规则同 `must_keep_moment`。精简模式下，本章有 pin 的素材只留 pin，所以这里决定了长素材留下什么。
- `rhythm` 可选，取 `slow | normal | fast | montage`，决定这一章的镜头快慢；怎么选见 SKILL.md「精剪」。
- 通常写 4–7 个 beats；可用素材不足 20s 的 beat 会被并入相邻 beat。

写故事的思路（借 video-script 的导演方法，按 vlog 收窄；原文见 `vendor/video-script-refs/creative-editing-playbook.md`）：
1. 先定一句 `viewer_promise`：看完这条片子，观众得到什么。
2. 找最强的画面或瞬间做 `hook`，哪怕它在时间上发生在中间。
3. 其余按时间或路线走，中间至少有一个 `turn`（天气变了、迷路、累了），结尾落在 `payoff`。
4. 与主题无关的素材（日常、测试镜头）不放进任何 beat，它们就不会被用到。

## story_plan.json（默认手写，或由转换生成）

```json
{
  "director_intent": "一句话",
  "chapters": [
    {"id": "ch1", "title": "三叠泉", "function": "hook", "share": 0.12,
     "clip_ids": ["c050", "c051"], "pool": "own",
     "pins": [{"clip_id": "c050", "at": 20.0}]},
    {"id": "ch2", "title": "出发", "function": "setup", "clip_ids": ["c041", "c042", "c043"], "pool": "own", "pins": []}
  ]
}
```

| 字段 | 含义 |
|---|---|
| `clip_ids` | 本章可用的素材（clip_id 见 `inventory.csv`，联系表上也标了） |
| `share` | 可选，只在定长模式（`--target`）有效：本章占成片的比例；不写就按可用素材量自动分 |
| `pool` | `own`（默认）只从本章素材取；`all` 可从全部素材取——适合开场钩子 |
| `rhythm` | 可选，`slow / normal / fast / montage`，本章镜头快慢；精简模式下不写就按 `function` 取默认值 |
| `pins` | 必须出现的瞬间：素材内秒数。精简模式下，本章有 pin 的素材只留 pin |

不放进任何章节的素材不会被使用。

## 平行蒙太奇（intercut）

一章里有两条同时进行的线（两代人各自爬山、出发路上 × 目的地、你和朋友兵分两路），可以交替剪：

```json
{"id": "b2", "title": "两代人上山", "function": "escalation",
 "clip_ids": ["c014", "c015", "c016", "c017", "c018", "c020", "c026"],
 "intercut": {"a": ["c014", "c015", "c016"], "b": ["c017", "c018", "c020", "c026"], "end_on": "b"},
 "pool": "own", "pins": []}
```

- `a` / `b` 必须都是本章 `clip_ids` 里的素材；两条线轮流各出一个镜头，各线内按拍摄时间排；最后一个镜头落在 `end_on`。
- 一条线挑不出镜头时由另一条补，所以两条线素材量别差太多。
- 找线索的办法：读语音转写和画面（比如语音里有人说「爸妈还在后面」、画面描述里有「白发老人坐在台阶上休息」），再看缩略图确认是同一批人。
- 用 MiMo 时先 `--from-recap` 转换，再在 `story_plan.json` 里给对应章节加 `intercut`，最后 `story.py --check` 校验。
- 交替章节不做「最多挪 2 位」的节奏调整（交替本身就是节奏），差额外溢也不会塞进这一章。

## 剔除无关素材（三种模式都适用）

素材目录里常混着与本次主题无关的东西（日常、别的行程、测试镜头之类）。同一场景的多条素材可能是不同角度，不算无关，取舍由用户决定。写故事前先看联系表和
`speech.json` 把它们挑出来，转换时用 `--exclude` 剔掉：

```bash
uv run --script story.py --work W --from-recap --exclude c059-c062
uv run --script story.py --work W --default --chapters 5 --exclude c002-c040,c059-c062
```

兜底模式（`--default`）尤其要剔：它按拍摄时间把**所有**素材都分进章节。
