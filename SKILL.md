---
name: jianying-autocut
description: >
  把一堆 vlog / 旅行素材自动粗剪成剪映专业版（11.6，macOS）能直接打开的草稿：先用 video-understanding（MiMo）
  理解全部素材，再按 video-script 的导演方法（见 vendor/video-script-refs/）写故事脚本（钩子/铺垫/转折/高潮/收尾），然后按章节配额和长短镜头
  节奏自动挑镜头、判糊避坏帧、总时长精确，最后生成带章节标题和 BGM 的剪映草稿。
  触发词：自动粗剪、vlog 粗剪、按故事剪、素材太多帮我剪、旅行素材剪一版、剪映自动化、autocut、
  帮我把这个文件夹剪成 N 分钟。
---

# jianying-autocut：素材文件夹 → 讲故事的剪映粗剪草稿

`S=~/.claude/skills/jianying-autocut/scripts`，一律 `uv run --script $S/<x>.py` 调用（依赖写在脚本头里，首次运行自动装）。
工作目录 `W` 默认是 `<素材目录>/_autocut`；各步只通过 W 里的文件衔接，任何一步都能单独重跑。

## 多台设备混拍：先让用户自己校正时间

章节内镜头大体按拍摄时间排序。几台相机 / 手机的时钟没对齐时，顺序会乱、甚至被误判成不同行程
（实测：一台手机日期慢了近一个月）。本技能不自动校时：发现拍摄日期与内容对不上时，提醒用户先用
相机自带功能或 `exiftool` 修正拍摄时间再跑；也可以只靠故事脚本的章节顺序来讲时间线。

## 开工前先问用户（一次问完）

素材目录的绝对路径、目标成片时长、一句话背景（去了哪、几天、想讲什么）、要不要 BGM（给歌或让你从
`~/Music/网易云音乐/` 挑本地 mp3/flac/m4a，`.ncm` 不能用）。

## 流程

| 步 | 命令 | 产出 |
|---|---|---|
| 1 盘点 | `probe.py <素材目录>` | `inventory.csv`（clip_id、时长、分辨率）、`silences.json` |
| 2 抽帧 | `frames.py --work W` | `frames.csv`（判糊 / 曝光）、`contact/sheet_*.jpg` 联系表 |
| 3 理解 | `understand.py --work W --context "<背景>"`（耗时长，后台跑；已有结果自动跳过，`--force` 重跑） | `understanding/`（MiMo 场景描述 + 语音转写 + brief）、`clip_understanding.json`、`orientation.json`（画面方向） |
| 4 故事 | **你来写**，见下 | `story_plan.json` |
| 5 分镜 | `plan.py --work W --target 10:00 --dry-run` → 给用户看 → 去掉 `--dry-run` | `shots.csv` |
| 6 草稿 | 确认剪映已 ⌘Q 退出 → `build.py --work W --name <草稿名> --titles [--bgm 歌.mp3]` | 剪映草稿 + 自检结果 |

每步把关键输出（表格、警告）转述给用户；第 5 步 dry-run 的章节表必须给用户确认后再落地。

## 第 3 步：MiMo 不可用时必须提醒用户充值

`understand.py` 退出码 3 = 没有 `MIMO_API_KEY`、key 无效或**余额不足 / 欠费**。这时要原话告诉用户：
「MiMo 不可用，请到小米 MiMo 开放平台充值（或配置 MIMO_API_KEY）」，并给出降级选项——
`understand.py --no-understanding`，由你看 `contact/` 联系表写故事。不要静默降级。

## 第 4 步：写故事（你的活，按 references/story_plan.md）

1. **先剔除无关素材**：看联系表和 `clip_understanding.json`，把与主题无关的（日常、别的行程、测试镜头）
   列出来告诉用户，转换时 `--exclude c059-c062,...`。拿不准就问用户。
2. 理解模式：读 `W/understanding/agent_narration_brief.md`，写 `W/recap_story_plan.json`（video-script 的
   director_intent + beats，时间用代理长片秒），然后 `story.py --work W --from-recap --exclude ...`。
3. 降级模式：看联系表直接写 `W/story_plan.json`，然后 `story.py --work W --check --exclude ...`。
4. 用户只要「快速出一版」：`story.py --work W --default --chapters N --exclude ...`。

## 第 6 步注意

- 剪映主进程在跑会被拒绝（它退出时会覆盖打开过的草稿）。请用户 ⌘Q，或经用户同意后代为退出。
- 同名草稿默认拒绝；要重建加 `--replace`（整目录删除后重建）。
- 自检失败（退出码 1）不要交付，按列出的问题修。
- 告诉用户：素材不要移动或改名（草稿里是绝对路径）；字幕、转场、调色在剪映里做。

## 不做

自动导出成片（剪映 7+ 隐藏了导出控件）；读回剪映加密过的草稿；AI 旁白 / TTS（v2，`build.py --extra` 预留）。

坑与实测值见 `references/pitfalls.md`。
