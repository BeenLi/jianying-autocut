# 写故事脚本（第 4 步）

第 5 步只认 `story_plan.json`。它有两个来源：

| 来源 | 怎么做 | 何时用 |
|---|---|---|
| 手写（默认） | 读 `footage_brief.md`，写 `story_plan.json`，再 `story.py --check` | 默认流程 |
| 兜底 | `story.py --default --chapters N`，按拍摄时间间隔切章 | 用户只要「快速出一版」 |
| 拍摄脚本 | 用户在页面上确认对照后，`match.py --work W` 生成，见 `shoot_plan.md` | 模式 A 的脚本页面或用户口述的故事 |

## 写故事的思路

借 video-script 的导演方法，按 vlog 收窄。原文见 `vendor/video-script-refs/creative-editing-playbook.md`，只借其中的方法；文中的 `recap_story_plan.json`、`clip_plan.json` 等文件格式本技能不用。

1. 先定一句 `director_intent`：看完这条片子，观众得到什么。
2. 找最强的画面或瞬间做 `hook`，哪怕它在时间上发生在中间。
3. 其余按时间或路线走，中间至少有一个 `turn`（天气变了、迷路、累了），结尾落在 `payoff`。
4. 与主题无关的素材（日常、测试镜头）不放进任何章节，它们就不会被用到。

## story_plan.json

通常写 4–7 章。时间一律是**素材内秒数**。

```json
{
  "director_intent": "两天走完庐山东线：从雨雾里出发，到三叠泉和云海",
  "chapters": [
    {"id": "ch1", "title": "三叠泉", "function": "hook", "rhythm": "fast",
     "clip_ids": [], "pool": "all",
     "pins": [{"clip_id": "c050", "at": 20.0}]},
    {"id": "ch2", "title": "出发", "function": "setup", "clip_ids": ["c041", "c042", "c043"], "pool": "own", "pins": []},
    {"id": "ch3", "title": "飞瀑", "function": "payoff", "clip_ids": ["c050", "c051"], "pool": "own",
     "pins": [{"clip_id": "c050", "at": 62.5}, {"clip_id": "c051", "at": 8.0}]}
  ]
}
```

| 字段 | 含义 |
|---|---|
| `function` | `hook / setup / turn / escalation / payoff`。`hook` 章排到成片最前（冷开场），其余按章节顺序 |
| `clip_ids` | 本章可用的素材（clip_id 见 `inventory.csv`，联系表上也标了）。一段素材通常只放进一章；放进多章时每章都要给它 pin（match.py 生成的故事会这样） |
| `pool` | `own`（默认）只从本章素材取；`all` 可从全部素材取，适合开场钩子 |
| `rhythm` | 可选，`slow / normal / fast / montage`，本章镜头快慢，怎么选见 SKILL.md「精剪」；精简模式下不写就按 `function` 取默认值 |
| `pins` | 必须出现的瞬间：素材内秒数，可以写多个。精简模式下，本章有 pin 的素材只留 pin，所以这里决定了长素材留下什么。所有章节的 pins 会先于普通镜头放置，高光不会被别的章节占走。可选 `cover: [起, 止]`（素材内秒）：镜头至少盖住这一段，用于有人说话的瞬间（match.py 会给口播镜头自动带上整句范围） |
| `share` | 可选，只在定长模式（`--target`）有效：本章占成片的比例；不写就按可用素材量自动分 |

hook 精简模式下只留 pin（没有 pin 就取一个最好的镜头）；定长模式下没写 share 时默认只占 min(20s, 目标的 10%)。

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
- 找线索的办法：读 `footage_brief.md` 的画面和语音（比如语音里有人说「爸妈还在后面」、画面里有「白发老人坐在台阶上休息」），再看缩略图确认是同一批人。
- 交替章节不做「最多挪 2 位」的节奏调整（交替本身就是节奏），差额外溢也不会塞进这一章。

## 剔除无关素材

素材目录里常混着与本次主题无关的东西（日常、别的行程、测试镜头之类）。同一场景的多条素材可能是不同角度，不算无关，取舍由用户决定。写故事前从 `footage_brief.md` 把无关素材挑出来，用 `--exclude` 剔掉：

```bash
uv run --script story.py --work W --check --exclude c059-c062
uv run --script story.py --work W --default --chapters 5 --exclude c002-c040,c059-c062
```

兜底模式（`--default`）尤其要剔：它按拍摄时间把**所有**素材都分进章节。
