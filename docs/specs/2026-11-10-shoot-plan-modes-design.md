# 拍摄脚本 + 按故事剪辑：两种模式设计

日期：2026-11-10
状态：待审阅

## 1. 目标

把 jianying-autocut 从"Claude 看完素材自己编故事再剪"扩展为两种模式，并把两者接成一条线：

- **模式 A：拍摄前**。用户给主题、地点、天数等，Claude 生成拍摄脚本（故事骨架 + 镜头清单 + 出镜口播稿），用户拍摄时在手机上看、勾选、备注。
- **模式 B：剪辑**。素材已拍好，用户有自己想讲的故事（来自模式 A 的脚本，或口述），Claude 把素材对到故事的每个镜头上，用户确认后生成剪映草稿。

人和 Claude 通过一个 **Claude Artifact 页面**交互（人看页面，Claude 通过 `ArtifactData` 读写页面数据库），不再要求人读 JSON。

### 用户已确认的决定

| 问题 | 决定 |
|---|---|
| 模式 A 与 B 是否接起来 | 接起来：脚本是结构化数据，剪辑时按它对素材，并报告漏拍 |
| 素材怎么对到镜头 | Claude 看画面描述（`scene_notes.json`）和语音转写自动对，用户确认 |
| 计划外的好素材 | 脚本是骨架；计划外素材由 Claude 建议放进某章，用户采纳或拒绝 |
| 剪辑时补故事 | 支持：用户在页面上写补充，Claude 去素材里找 |
| 交互方式 | Claude Artifact 页面（假设拍摄时有网），拍摄和剪辑两阶段共用一个页面 |
| 缩略图 | 上传到 Artifact（默认私有） |
| 口播 | 本次只做**出镜口播**；后期旁白另开 spec |
| 实现思路 | 一个 skill，第 0 步按模式分流 |

### 不做（本 spec 范围外）

- 后期旁白（另录音轨盖在画面上）：另开 spec。
- 离线使用页面。
- 自动接受 Claude 的匹配（如 `--accept-high`）：先只认用户确认过的。

## 2. 架构与数据流

```
模式 A（拍摄前）                         模式 B（剪辑）
───────────────                         ─────────────
A0 问需求                                0 提需求（含故事来源）
  ↓                                      1–3 不变：盘点、抽帧、转写、画面描述
A1 Claude 写故事骨架                        ↓
  ↓                                      4a Claude 匹配，写对照表、计划外建议、上传缩略图
A2 发布页面 ──────▶ 【拍摄脚本页面】 ◀───── 4b 用户在页面确认 / 修改 / 补故事
A3 来回修改          (Artifact + db)         ↓
拍摄中：手机勾选                          4c 导出 W/shoot_plan.json + W/matches.json
                                            → match.py → story_plan.json → story.py --check
                                          5 以后不变
```

原则：

- **本地文件仍是剪辑流程的唯一输入。** 页面只负责人机交互；进入 4c 时 Claude 把页面数据导出到 `W`，之后的 Python 脚本不联网、可单独重跑。
- **页面不可用时可降级**：Claude 直接在对话里写 / 改 `W/shoot_plan.json` 和 `W/matches.json`，流程照样能跑。
- **不改**：`probe.py`、`frames.py`、`transcribe.py`、`notes.py`、`orient.py`、`beatsync.py`、`build.py`。
- **小改**：`story.py`（跨章共享素材的校验，见 §5.3）；`plan.py` 仅在定长模式需要时（见 §5.3）。

### 模式 B 的三种故事来源

| 来源 | 做法 |
|---|---|
| 已有模式 A 的页面 | 用户给链接，或 Claude 用 `Artifact list` 帮用户找 |
| 用户口述故事 | Claude 整理成骨架，发布新页面（跳过勾选环节），从 4a 开始 |
| 没有故事 | 走现有流程：Claude 看完素材自己写 `story_plan.json`，不建页面 |

### 页面链接的保存

模式 A 时还没有素材目录，链接不落本地；模式 B 开始时写入 `W/shoot_plan_url`，之后重跑任何一步都能找回。

## 3. 页面数据库

页面声明 `capabilities: {db: {}, user: {}, assets: {}}`。页面默认只有用户本人能看，重点是**用户和 Claude 不互相覆盖**。

| 路径 | 字段 | Claude 写 | 用户写 |
|---|---|---|---|
| `plan/meta` | `title`, `intent`（导演意图）, `place`, `days`, `stage`（`shooting` / `editing`） | ✓ | `title`, `intent` |
| `chapters/<chId>` | `order`, `title`, `function`（hook/setup/turn/escalation/payoff）, `rhythm`（slow/normal/fast/montage） | 初稿 | 改名、改顺序、增删 |
| `shots/<S01…>` | `chapter`, `order`, `kind`（`visual` / `talk`）, `desc`, `size`（景别）, `duration`（秒）, `talk`（口播要点，仅 talk）, `tips`; `done`, `note`; `edited_by_user`（字段名列表） | 初稿 | `done`, `note`, 改描述、增删 |
| `clips/<c001…>` | `thumbs`（asset id + 秒数）, `desc`, `duration` | ✓（剪辑阶段） | 只读 |
| `matches/<S01…>` | `clip_id`, `at`（素材内秒）, `start`/`end`（仅口播：整句范围）, `confidence`（high/mid/low）, `reason`, `confirmed`, `by`（claude/user） | 建议 | 确认、改素材或秒数 |
| `extras/<c0xx>` | `chapter`, `at`, `reason`, `accepted`（null/true/false） | 建议 | 采纳 / 拒绝 |
| `requests/<id>` | `text`, `status`（new/done/not_found）, `reply` | `status`, `reply` | `text` |

### 不互相覆盖的规则

1. Claude 每次写前先读，只用 `update` 合并自己负责的字段，从不整条 `set` 覆盖已有文档。
2. 页面在用户改动 `desc` 等字段时把字段名记入 `edited_by_user`；Claude 不改这些字段。
3. `confirmed: true` 的匹配，Claude 重新匹配时跳过。
4. 缩略图来自 `frames.py` 已生成的 `W/thumbs/<clip>_<t>.jpg`，每段素材挑 2–4 张，Claude 用 Artifact 的 `asset: true` 上传，asset id 记入 `clips/`。

## 4. 两个模式的流程（SKILL.md 改法）

### 模式 A

| 步 | 内容 |
|---|---|
| A0 问需求 | 一次问完：去哪、几天、几个人、想讲什么、设备（手机/相机/无人机/稳定器）、大概多长 |
| A1 写骨架 | 按 `vendor/video-script-refs/` 的导演方法：一句导演意图，4–7 章，每章 3–8 个镜头。镜头写描述、景别、建议时长、拍摄小贴士。需要出镜口播的镜头 `kind: talk`，写口播要点（不逐字），按约 4 字/秒估时长，超出镜头时长就拆镜头或调长 |
| A2 发布 | 用 skill 内的页面模板发布 Artifact，用 `ArtifactData batch` 写入骨架，给用户链接 |
| A3 修改 | 用户在页面上改或在对话里提；Claude 改前先读 |
| 拍摄中 | 用户勾选、备注，不需要 Claude |

### 模式 B

| 步 | 内容 |
|---|---|
| 0 | 问素材目录、BGM、**故事来源**（§2） |
| 1–3 | 不变 |
| 4a 匹配 | 读页面数据；`visual` 镜头用 `scene_notes.json` 比画面描述；`talk` 镜头用 `speech.json` 比口播要点（文字比对优先于画面），`at` 取句子中点并记 `start/end`。写 `matches/`（含把握和理由）、`extras/`、上传缩略图，`plan/meta.stage = editing` |
| 4b 确认 | 用户在页面确认 / 修改匹配、采纳 / 拒绝 extras、写补充故事。Claude 处理 `requests/`（找素材 → 新增镜头和匹配建议，或回复找不到），直到用户说"好了" |
| 4c 落地 | 导出 `W/shoot_plan.json`、`W/matches.json`（含 extras）→ `match.py --work W` → `story_plan.json` → `story.py --check` |
| 5 以后 | 不变。5.8 字幕：`talk` 镜头的句子默认入选 `subtitles.json`，用口播要点校正 Whisper 的同音字（地名、人名） |

## 5. match.py

### 5.1 输入输出

- 输入：`W/shoot_plan.json`（meta、chapters、shots）、`W/matches.json`（matches、extras）、`W/inventory.csv`。
- 输出：`W/story_plan.json`；终端打印报告。
- 退出码：有错误为 1，不写 `story_plan.json`。

### 5.2 生成规则

- 章节顺序、`title`、`function`、`rhythm` 来自 `chapters`；`director_intent` 来自 `meta.intent`；`pool: own`。
- 每章 `clip_ids` = 本章**已确认**匹配的素材 ∪ 本章 `accepted: true` 的 extras 素材（去重，保持出现顺序）。
- 已确认匹配 → 本章 `pins`（`{clip_id, at}`）；采纳的 extras → 本章 `pins`。
- 整章没有任何素材 → 不输出该章，报告"章 X 整章漏拍，已删除"。
- 报告：漏拍镜头列表（按章）、整章删除、未采纳的 extras 数、未被任何章引用的素材数（这些不进成片，dry-run 时照常列出）。

### 5.3 跨章共享素材

一段长素材可能对上不同章的镜头。规则：**同一素材可出现在多章，前提是它在每一章都有 pin。**

- `story.py validate`：把"素材出现在多个章节"放宽为：出现在多章的素材，必须在每一章都有 pin；否则仍报错。
- 精简模式下 `plan.py` 已有"被 pin 过的素材只留 pin"（全局 `pinned` 集合），不会重复自动取镜头。
- 定长模式：实施时核实 `plan.py` 对同一素材在多章 pool 中的行为，需要时补同样的保护。

### 5.4 校验（逐条报错，指明是哪个镜头 / 素材）

- 匹配的镜头编号不在 `shots` 里；镜头所属章不在 `chapters` 里。
- `clip_id` 不在 `inventory.csv`。
- `at` 不在 `[0, 素材时长]`；口播的 `start < at < end` 不成立。
- 存在 `confirmed` 不为 true 的匹配 → 报错并列出，要求用户先在页面确认（或删除该匹配）。
- `rhythm`、`function` 取值非法。

## 6. 页面

### 布局

- **手机 · 拍摄阶段**：顶部标题、导演意图、已拍进度；章节可折叠；镜头卡片含大勾选框、描述、景别 / 时长标签、口播要点（`talk` 镜头单独标出）、备注；每章"＋加镜头"；用"上移 / 下移"调顺序，不做拖动。
- **Mac · 剪辑阶段**：左栏章节和镜头，状态色（🟢 已确认 / 🟡 待确认 / 🔴 漏拍）；右栏当前镜头的匹配：缩略图、素材和秒数、把握、理由，"确认" / "换素材" / 改秒数；底部计划外素材列表和"补充故事"输入框。窄屏时上下排列。
- 按 `meta.stage` 决定默认视图，可手动切换。

### 实现

- 一个 HTML 模板放在 `skills/jianying-autocut/assets/shoot_plan_page.html`，外部脚本只允许来自 Artifact 规定的 CDN 白名单；发布前读 `artifact-design` 与 `artifact-capabilities` 的约束。
- 页面所有内容从 db 渲染，模板本身不含用户数据。

### 出错处理

| 情况 | 处理 |
|---|---|
| `use("db")` 为 null（未登录等） | 显示只读提示，不假装保存 |
| 10 秒未加载到数据 | 显示"加载失败，刷新重试" |
| 写入失败 | 该项标"未保存"，用户下次操作时重试 |
| 页面整体不可用 | 降级为在对话里改本地 JSON（§2） |

## 7. 文件改动清单

| 文件 | 改动 |
|---|---|
| `skills/jianying-autocut/SKILL.md` | description 和触发词加入拍摄脚本；第 0 步按模式分流；新增模式 A 章节；第 4 步按故事来源分支；5.8 字幕加口播规则；"不做"保留 AI 旁白 / TTS |
| `skills/jianying-autocut/references/shoot_plan.md` | 新增：骨架怎么写（导演方法、镜头字段、口播要点和时长估算）、db 结构、`shoot_plan.json` / `matches.json` 格式、匹配方法 |
| `skills/jianying-autocut/references/story_plan.md` | 来源表加"由 match.py 生成"；说明跨章共享素材规则 |
| `skills/jianying-autocut/scripts/match.py` | 新增 |
| `skills/jianying-autocut/scripts/story.py` | 放宽跨章校验（§5.3） |
| `skills/jianying-autocut/assets/shoot_plan_page.html` | 新增页面模板 |
| `tests/test_match.py` | 新增 |
| `tests/test_story.py` | 补跨章共享素材用例 |
| `README.md` / `README.en.md` | 工作流加两种模式 |

## 8. 测试

- `tests/test_match.py`：正常生成；漏拍镜头；整章无素材被删除；extras 采纳 / 拒绝；未确认匹配拒绝生成；跨章共享素材生成多章 pin；各类格式错误（未知镜头、未知素材、秒数越界、口播 start/end 不合法）。用 `run_tests.sh` 跑。
- `tests/test_story.py`：跨章素材每章都有 pin 时通过，缺 pin 时报错。
- 页面：用示例数据发布一次，`ArtifactData list` 各集合确认读写；手机和 Mac 布局由用户实际打开确认。
- 端到端：一小批真实素材从模式 A 走到草稿生成。
