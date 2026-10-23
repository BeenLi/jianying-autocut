# jianying-autocut 设计（2026-10-23）

## 目标

一个技能把「一堆旅行 vlog 素材」变成「剪映 11.6 能直接打开、按故事排好的粗剪草稿」。
合并三样东西：

- `jianying-draft`：BGM 轨（循环 / 音量 / 淡入淡出）、拍摄时间排序
- 今天的 autocut 四脚本：盘点、抽帧判糊、章节配额 + 节奏挑镜头、pyJianYingDraft@164 写草稿 + 自检
- video-recap 技能链的特色：先 **video-understanding** 理解，再按 **video-script** 写故事脚本

成功标准：庐山 62 段素材端到端跑通，草稿在剪映 11.6 打开时间线完整；总时长精确到微秒；
没有 MiMo 时能明确提醒充值并可降级完成。

## 不做（v1）

两套写入器切换；每段素材单独调 MiMo；AI 旁白 / TTS / 字幕（只留接口）；
`visual_audio_board.json`、`review.py` 评审；转场 / 变速 / 滤镜；读回剪映加密过的草稿。

## 目录

```
~/.claude/skills/jianying-autocut/
  SKILL.md
  scripts/
    common.py             路径、CSV、版本探测、MiMo 预检与报错归类
    probe.py              第 1 步 盘点 + 人声分 → inventory.csv
    frames.py             第 2 步 关键帧打分 + 缩略图 + 联系表 → frames.csv, contact/*.jpg
    understand.py         第 3 步 代理长片 + video-understanding + 拆回 → clip_understanding.json
    story.py              第 4 步 recap_story_plan.json → story_plan.json（或生成默认 story_plan）
    plan.py               第 5 步 分镜规划 → shots.csv
    build.py              第 6 步 写草稿 + 自检
  references/
    story_plan.md         story_plan.json 格式与写故事的指引
    pitfalls.md           剪映 11.6 实测坑（版本号、加密、判糊、抽帧提速…）
  docs/specs/            本文件
```

所有脚本顶部写 PEP 723 依赖，`uv run scripts/xxx.py` 运行；依赖锁定 `pyJianYingDraft==0.3.0`、`numpy`。
工作目录 `--work <dir>`（默认素材目录下 `_autocut/`），各步只通过这里的文件通信，可断点重跑。
上游 video-* 只按绝对路径调 CLI（`~/.claude/skills/video-understanding/scripts/understand.py`），不 import、不修改。

## 各步

### 1 probe.py
沿用 1_probe_materials.py：ffprobe 盘点（无 ffprobe 退 pymediainfo），按拍摄时间排序，竖屏按显示方向计宽高。
新增 `clip_id`（`c001`…，按排序）和 `speech_score`：
`highpass=300,lowpass=3000,astats(reset=1s)` 取逐秒 RMS，score = 高于 −35 dBFS 的秒数占比 × 变异系数。
无音轨 = 0。

### 2 frames.py
沿用 2_sample_frames.py：`-skip_frame nokey` 每 8 s 抽一帧；判糊 = 低于本段中位数 35% 或绝对值 < 15；
曝光惩罚；`score` = 全局清晰度百分位 × 曝光。新增联系表：每张 4×5 缩略图网格，标 `clip_id @ 秒`，
供降级模式下 agent 看图写故事。

### 3 understand.py（video-recap 特色 ①）
1. **MiMo 预检**：无 `MIMO_API_KEY` → 提示「未配置 MiMo key：请到 MiMo 控制台充值 / 获取 key 后 `export MIMO_API_KEY=…`；
   或加 `--no-understanding` 用联系表降级」并退出码 3。有 key → 发一次最小 chat 请求；
   401 → key 无效；402 或报错文本含 余额/欠费/insufficient/balance/quota/credit → **提醒充值**；均退出码 3。
2. **代理长片**：逐段转 1280x720、15 fps CFR、`scale=-2:720` + pad 黑边（不裁）、自动纠正旋转、
   保留音轨（无音轨补静音），`h264_videotoolbox`，4 路并行，按 路径+大小+mtime 缓存；
   concat demuxer 拼成 `proxy/reel.mp4`，写 `proxy_map.json [{clip_id, source_path, proxy_start, proxy_end}]`。
   素材之间不插黑场。
3. 调 `understand.py proxy/reel.mp4 --work-dir understanding/ --context <用户描述>`。
   运行中失败时按同一规则归类报错，余额类同样提醒充值。
4. **拆回素材**：scenes / vlm_analysis / timeline_fusion 每条在素材边界处切开；跨素材的场景描述归占比大的素材并记日志；
   ASR 句子按中点归属。输出 `clip_understanding.json {clip_id: {scenes:[{start,end,description,frame_facts}], speech:[{start,end,text}]}}`
   （时间为素材内时间）。

### 4 story.py（video-recap 特色 ②）——agent 停顿点
- 理解模式：agent 读 `understanding/agent_narration_brief.md`，按 video-script 的
  `recap_story_plan.json` 格式（director_intent + beats，function ∈ hook/setup/turn/escalation/payoff，
  `source_start/end` 在代理时间轴上）写到 work 目录，然后 `story.py --from-recap` 转换：
  - 素材归属 = 与 beat 时间重叠；同时碰到两个 beat 的素材归重叠多的那个
  - 不足 20 s 可用素材的 beat 并入相邻 beat，打警告
  - pins = `must_keep_moment` / 证据时间点经 proxy_map 映射成 (clip_id, 素材内秒)
- 降级模式（`--no-understanding`）：agent 看联系表直接写 `story_plan.json`。
- 都不写：`story.py --default` 按拍摄时间间隔切 N 章生成默认 story_plan（等价于今天的行为）。

`story_plan.json`（唯一内部格式，见 references/story_plan.md）：
```json
{"director_intent": "一句话", "chapters": [
  {"id": "ch1", "title": "雨中上山", "function": "hook", "share": 0.15,
   "clip_ids": ["c041", "c042"], "pool": "own",
   "pins": [{"clip_id": "c047", "at": 12.5}]}]}
```
`share` 可省（省略则按配额算法分）；`pool: all` 允许该章（如开场钩子）从任意素材取镜头。

### 5 plan.py
沿用 3_plan_shots.py，改为读 story_plan.json：
- 配额：有 `share` 的按 share 分，其余用现有算法（20 s 保底 + √可用时长注水），总和精确 == 目标
- pins：先放一个以 `at` 为中心、按节奏取长度的窗口（避开坏帧则就近平移），再填其余
- 人声保护：`speech_score` 高且有 ASR 句子的素材，窗口端点吸附到句子边界（无 ASR 时吸附到静音段）
- 保留：长 12–18 / 短 3–6 / 中 6–9 循环、复用降权、不重叠、缺额外溢、整数微秒、`--dry-run`
- 章内按拍摄时间排序；hook 章（function=hook）放最前，其余按 story_plan 顺序
- `shots.csv` 增加 `chapter_function`

### 6 build.py
沿用 4_build_draft.py（版本号从 root_meta_info.json 读、素材元数据注入、剪映运行中拒绝、
同名需 `--replace`、自检），新增：
- `--bgm path[:gain[:fade]]` 可多次：AudioSegment，音量、淡入淡出；歌短于成片时按歌长循环切段（最后一段截断）
- `--volume` 原声音量；有 BGM 且未指定时默认原声 0.6、BGM 0.3
- 预留 `audio_tracks[]` / `subtitles[]` 输入（`--extra tracks.json`），v2 接旁白用；v1 不暴露在 SKILL.md
- 自检增加：BGM 段落不重叠、BGM 不超出成片

## 报错与提醒

| 情况 | 行为 |
|---|---|
| 无 MiMo key / 余额不足 / 欠费 | 明确提醒去充值，退出码 3；提示可 `--no-understanding` 降级 |
| key 无效 (401) | 提示检查 key 与 URL |
| 429 限流 | 交给上游重试，不提醒 |
| 剪映在运行 | 拒绝写草稿，提示 ⌘Q |
| 素材不够目标时长 | plan 退出并给出缺口 |
| 自检失败 | build 退出码 1，列出每条问题 |

## 测试

- 单元：proxy_map 拆回（跨边界场景、ASR 中点归属）；beats→chapters 映射（多数归属、<20 s 合并、pins 映射）；
  BGM 循环切段；配额 share 与精确总和；MiMo 报错归类（401 / 402 / 含「余额」文本 / 429）。
- 端到端：庐山 62 段 → 理解（MiMo）→ agent 写 recap_story_plan → 10 分钟草稿 + 一首 BGM → 剪映打开。
- 降级：`--no-understanding` 跑通一遍。

## 迁移

旧 `jianying-draft` 保留不动，作为回退；新技能 SKILL.md 描述限定「vlog 素材自动粗剪 / 按故事排草稿」，
旧技能描述不改。新技能完成一个带 BGM 的真实项目后，再删除旧技能。
