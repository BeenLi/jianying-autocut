<h1 align="center">jianying-autocut</h1>

<p align="center"><b>简体中文</b> | <a href="README.en.md">English</a></p>

<p align="center">
  <b>把一个装满旅行 / vlog 素材的文件夹，变成剪映专业版能直接打开、按故事排好的粗剪草稿。</b><br>
  先让 AI 看懂素材，再按故事挑镜头、生成带章节标题、字幕、旁白和 BGM 的剪映草稿。你只需要在剪映里精修和导出。<br>
  故事可以交给 Claude 写，也可以出发前先写拍摄脚本、拍完按脚本剪，或者先录旁白、让画面跟着旁白走。
</p>

<p align="center">
  <img alt="macOS" src="https://img.shields.io/badge/macOS-only-111111?style=flat-square&logo=apple&logoColor=white">
  <img alt="剪映专业版 11.6" src="https://img.shields.io/badge/%E5%89%AA%E6%98%A0%E4%B8%93%E4%B8%9A%E7%89%88-11.6-081431?style=flat-square">
  <a href="https://www.python.org/"><img alt="Python 3.10+" src="https://img.shields.io/badge/Python-3.10%2B-3776AB?style=flat-square&logo=python&logoColor=white"></a>
  <img alt="Claude Code skill" src="https://img.shields.io/badge/Claude%20Code-skill-bf4520?style=flat-square">
  <a href="https://github.com/BeenLi/jianying-autocut/actions/workflows/test.yml"><img alt="test" src="https://img.shields.io/github/actions/workflow/status/BeenLi/jianying-autocut/test.yml?branch=main&style=flat-square&label=test"></a>
  <a href="./LICENSE"><img alt="License MIT" src="https://img.shields.io/badge/License-MIT-1F6FEB?style=flat-square"></a>
</p>

https://github.com/user-attachments/assets/e7c27388-6343-4862-a71c-0ee0be00a2b0

<p align="center"><sub>60 秒演示：62 段原始素材 → 盘点打分 → Claude 看画面、Whisper 听语音 → 写故事 → 分镜 → 剪映草稿。演示素材来自一次真实的庐山徒步，人脸已打码。
⬇ <a href="https://github.com/BeenLi/jianying-autocut/raw/main/docs/promo/promo.mp4">下载 mp4</a></sub></p>

<details>
<summary>看不到播放器？点这里看 GIF 版</summary>
<img alt="宣传片 GIF 版" src="docs/promo/promo.gif" width="100%">
</details>

---

## 三种用法

| 你的情况 | 怎么用 | 故事从哪来 | 节奏由谁定 |
|:--|:--|:--|:--|
| 拍完了，没想好讲什么 | 把素材目录交给 Claude | Claude 看完素材写故事 | 长短镜头节奏（可选卡点） |
| 还没出发 / 拍完了，有自己的故事 | 先写**拍摄脚本**，或口述故事；拍完按脚本剪 | 你的脚本，Claude 把素材对到每个镜头 | 长短镜头节奏（可选卡点） |
| 想做解说 / 旁白 vlog | 先录**旁白**（可以先在脚本里写旁白稿） | 你的旁白，Claude 按每句话配画面 | 旁白 |

三种用法共用第 1–3 步（盘点、抽帧打分、看懂素材），也共用最后一步生成草稿；区别在中间怎么定故事和镜头。

## 工作流

<p align="center">
  <img alt="jianying-autocut 工作流：素材 → 盘点打分 → Claude 看联系表写画面描述、本地 Whisper 转写语音 → Claude 写故事 → 分镜规划与卡点 → 确认 → 生成带字幕的剪映草稿" src="docs/workflow.png" width="100%">
</p>

| 步骤 | 做什么 | 产出（`_autocut/` 下） |
|:--|:--|:--|
| **0&nbsp;提需求**<br><sub>你</sub> | 素材目录、一句话背景、要不要 BGM | — |
| **1&nbsp;盘点**<br><sub>`probe.py`</sub> | 时长、分辨率、拍摄时间、静音段；编号随文件稳定 | `inventory.csv` |
| **2&nbsp;抽帧打分**<br><sub>`frames.py`</sub> | 每 8 秒抽关键帧，判糊、判曝光，拼联系表 | `frames.csv` `contact/` |
| **3&nbsp;看懂素材**<br><sub>Claude · `transcribe.py` · `notes.py` · `orient.py`</sub> | Claude 看联系表写场景描述、判方向；本地 Whisper 转写语音，不额外收费 | `footage_brief.md`、`orientation.json` |
| **4&nbsp;写故事**<br><sub>Claude · `match.py`</sub> | 钩子 / 铺垫 / 转折 / 高潮 / 收尾；剔除无关素材；可选平行蒙太奇。有拍摄脚本时改为把素材对到镜头、你在页面上确认 | `story_plan.json` |
| **5&nbsp;分镜**<br><sub>`plan.py`</sub> | 只留关键片段并列出删除清单，按长短节奏挑镜头，避坏帧、吸附静音；先 dry-run | `shots.csv` |
| **5.5&nbsp;卡点**<br><sub>`beatsync.py`</sub> | 可选：切点吸附拍点，章节交界落在小节线，可把高潮对到音乐高能段 | `shots.csv`、`bgm_plan.json` |
| **6&nbsp;生成草稿**<br><sub>`build.py`</sub> | 主视频轨 + 章节标题 + 字幕 + 旁白 + BGM，写完读回自检 | 剪映草稿 |
| **7&nbsp;精修导出**<br><sub>你</sub> | 剪映里调色、转场、字幕、导出成片 | 成片 |


### 拍摄脚本：出发前写，拍完按它剪

1. **拍摄前**：告诉 Claude 去哪、几天、想讲什么，它写一份拍摄脚本：章节、镜头清单（景别、时长、拍摄小贴士）、出镜口播要点，
   要做旁白片时每章再写旁白稿。脚本发布成一个只有你能看的 Claude Artifact 页面。
2. **拍摄时**：手机上打开页面，拍完一个勾一个，随手写备注；镜头可以现场增删改。
3. **拍完以后**：素材照第 1–3 步处理，第 4 步不由 Claude 编故事，而是把素材对到每个镜头上。同一个页面切到「剪辑」，
   列出每个镜头的对照（带缩略图）、漏拍的镜头和计划外的好素材；你确认、换素材、采纳或拒绝，还可以写"再补一段迷路的故事"让 Claude 去找。
   确认完 `match.py` 生成 `story_plan.json`，后面照常。

没有拍摄脚本、只是口述了一个故事，Claude 也会把它整理成同样的页面让你确认。

### 旁白片：先录旁白，画面跟着走

1. **录旁白**：一口气录一整段（口误、重录都没关系），或一章录一个文件。拍摄脚本里写了旁白稿时，页面的「录音稿」视图可以当提词器。
2. **转写和初稿**：`transcribe.py --narration` 逐句转写（带逐字时间），`narrate.py --draft` 生成初稿：重录的句子只留最后一遍，
   有旁白稿时和稿子逐句对齐，口误、闲聊默认跳过。
3. **配画面**：Claude 按每句话的内容挑素材，需要现场声的地方（出镜口播、欢呼、浪声）插一段原声，旁白在这里停下。
   有页面时在「剪辑」视图逐句确认、换画面、改时间、标跳过。
4. **排时间线**：`narrate.py` 按旁白定每个镜头的长短，画面比开口早 0.3 秒切（J-cut）；句间停顿按比例压缩，从停顿中间剪，保留真实底噪；
   同一素材的镜头不相邻。先 `--dry-run` 看一遍。
5. **混音**：`build.py --narration` 加一条旁白轨。人声按录音来源统一到 -16 LUFS，旁白下的原声垫底，BGM 全片稳定在压低档，
   只在长空隙或你标了 `up` 的地方升起、标了 `drop` 的地方留白；逐句检查人声比 BGM 高至少 12 LU。

详细规则见 [`references/narration.md`](skills/jianying-autocut/references/narration.md)。

## 支持的功能

| 功能 | 状态 | 说明 |
|---|---|---|
| 素材盘点、按拍摄时间排序 | ✅ | ffprobe；没有 ffprobe 时退回 pymediainfo |
| 糊片 / 过暗 / 过曝识别 | ✅ | 拉普拉斯方差与本段中位数比较，室内、雾天不会被整段误杀 |
| 画面方向检测 | ✅ | Claude 看联系表判断：整段倒装的转 180°；挂着晃拍、大半歪倒的整段弃用；个别歪帧避开 |
| 理解素材 | ✅ | 按固定间隔和画面切换抽帧，Claude 写场景描述，本地 Whisper 转写语音 |
| 梳理故事线 | ✅ | 钩子冷开场、铺垫、转折、高潮、收尾；必须出现的瞬间（pin）一定入选 |
| 拍摄脚本页面 | ✅ | Claude Artifact 页面，手机可用：章节、镜头清单、口播要点、旁白稿；勾选、备注、增删改，Claude 不覆盖你的改动 |
| 按你的故事剪 | ✅ | 素材自动对到镜头（看画面描述和语音），页面上确认；报告漏拍，建议计划外的好素材 |
| 剔除无关素材 | ✅ | `story.py --exclude c001-c010,…` |
| 平行蒙太奇 | ✅ | 章节里两条线（如「我们俩」×「爸妈」）交替剪，落在指定的那条线 |
| 长短镜头节奏 | ✅ | 章内大体按时间，局部调整避免连续长镜头 / 三连短镜头 |
| 精简素材，时长不设限 | ✅ | 默认只留关键片段，时长由留下的片段决定；也可用 `--target` 指定，精确到微秒 |
| 章节标题 | ✅ | 每章开头 3 秒文字 |
| BGM | ✅ | 多首可选；短于成片自动循环、长于成片截断、首尾淡入淡出 |
| 人声字幕 | ✅ | Claude 挑出有意义的人声配底部字幕（带底色），说话时 BGM 自动压低；全片逐句字幕仍用剪映「智能字幕」 |
| 自录旁白 | ✅ | 按句配画面、间隙插原声、J-cut；重录和口误自动跳过；旁白自带字幕 |
| 人声 / BGM 响度平衡 | ✅ | ffmpeg 实测响度：人声统一到 -16 LUFS，BGM 全片一个压低值；人声被 BGM 盖住的句子会列出来 |
| AI 配音（TTS） | ❌ | 未做 |
| 转场、调色、变速、滤镜 | ❌ | 交给剪映 |
| 自动导出成片 | ❌ | 剪映 7+ 隐藏了导出控件，只能手动导出 |

## 输入与输出

**输入**

- 素材目录：`.mp4` `.mov` `.m4v` `.mkv` `.avi` `.mts` `.m2ts` `.mxf`（子目录会递归扫描）
- 一句话背景（帮助理解素材，也减少转写的同音字错误）；想要固定时长时再给目标时长（如 `5:00`）
- BGM（可选）：本地 `.mp3` / `.flac` / `.m4a`（网易云 `.ncm` 是加密格式，不能用）
- 旁白录音（旁白片）：`.m4a` `.mp3` `.wav` `.aac` `.flac`，一个文件或一个目录（按文件名排序）
- 拍摄脚本（可选）：出发前让 Claude 写，链接留着，剪辑时交给它

**输出**：剪映专业版草稿，位于剪映「全局设置 → 草稿位置」（默认 `~/Movies/JianyingPro/User Data/Projects/com.lveditor.draft/<草稿名>/`）

| 文件 | 内容 |
|---|---|
| `draft_info.json` | 草稿正文（明文 JSON，版本号与本机剪映一致，11.6 为 `164.0.0`）：主视频轨、章节标题文字轨、字幕轨（可选）、旁白音频轨（旁白片）、BGM 音频轨 |
| `draft_meta_info.json` | 草稿元数据 |

素材**不复制**进草稿，只记录绝对路径：生成后不要移动或改名素材。剪映首次打开时会自行加密这些文件。

中间产物全部在 `<素材目录>/_autocut/`，任何一步都能单独重跑。

## 环境依赖

| 依赖 | 说明 |
|---|---|
| macOS | 草稿加解密库只支持 Windows，本项目写明文草稿，由 macOS 版剪映首次打开时加密 |
| 剪映专业版 11.6（VideoFusion-macOS） | 版本号每次从本机读取，剪映升级后无需改代码，但建议升级后重跑一次自检 |
| Python ≥ 3.10 + [uv](https://docs.astral.sh/uv/) | 每个脚本头部写了依赖（PEP 723），`uv run --script` 首次运行自动安装：numpy、pillow、pymediainfo、pyJianYingDraft（锁定提交 `69cee12`） |
| ffmpeg / ffprobe | 推荐 `brew install ffmpeg`（需要 `h264_videotoolbox`、`silencedetect`；旁白片的响度测量用 `ebur128`） |
| 磁盘空间约 500MB | 本地 Whisper small 模型，首次转写时自动下载 |
| Claude Code（或其他能读 Agent Skills 的编程 Agent） | 负责编排各步、写故事脚本 |
| claude.ai 账号（可选） | 拍摄脚本页面是 Claude Artifact，手机上登录 claude.ai 打开；不用页面也能直接改 JSON |

## 安装与使用

三种方式任选其一：

```bash
# 1. skills CLI：把技能复制到 ~/.claude/skills/jianying-autocut；以后用 `npx skills update -g` 更新
npx skills add BeenLi/jianying-autocut -g -a claude-code
```

```text
# 2. Claude Code 插件：在 Claude Code 里运行；技能名会带插件前缀（jianying-autocut:jianying-autocut）
/plugin marketplace add BeenLi/jianying-autocut
/plugin install jianying-autocut@jianying-autocut
```

```bash
# 3. git clone + 软链，适合开发：改了仓库立即生效
git clone https://github.com/BeenLi/jianying-autocut.git && cd jianying-autocut
mkdir -p ~/.claude/skills
ln -sfn "$PWD/skills/jianying-autocut" ~/.claude/skills/jianying-autocut
```

skills CLI 只复制 `skills/jianying-autocut/` 这一个文件夹（技能说明、脚本、收录的 vendor 模块），不带 `docs/` 里的宣传片和设计文档；插件会克隆整个仓库，再从这个文件夹读取技能。

然后在 Claude Code 里说：

```text
把 ~/Videos/my-trip 这个文件夹剪成旅行 vlog，只留关键片段，背景是两天徒步，配 ~/Music/xxx.mp3。
下周去枸杞岛玩两天，帮我写一份拍摄脚本。
我拍完回来了，素材在 ~/Videos/gouqi，按拍摄脚本剪。
旁白录好了在 ~/Voice/gouqi/，素材在 ~/Videos/gouqi，按旁白剪一版，配 ~/Music/xxx.mp3。
```

也可以手动逐步运行（`S=~/.claude/skills/jianying-autocut/scripts`，`W=<素材目录>/_autocut`）：

```bash
uv run --script $S/probe.py ~/Videos/my-trip
uv run --script $S/frames.py --work $W
uv run --script $S/transcribe.py --work $W --context "两天徒步"
# Claude 看 $W/contact/ 联系表，写 $W/scene_notes.json，判断方向
uv run --script $S/notes.py --work $W
uv run --script $S/orient.py --work $W --flip c012 --bad c005@12
# Claude 写 $W/story_plan.json（格式见 skills/jianying-autocut/references/story_plan.md）
uv run --script $S/story.py --work $W --check --exclude c001-c010
uv run --script $S/plan.py --work $W --dry-run     # 要固定时长就加 --target 5:00
uv run --script $S/plan.py --work $W
# ⌘Q 完全退出剪映
uv run --script $S/build.py --work $W --name 我的旅行粗剪 --titles --bgm ~/Music/xxx.mp3
```

旁白片在第 3 步之后换成：

```bash
uv run --script $S/transcribe.py --work $W --narration ~/Voice/my-trip/ --context "两天徒步"
uv run --script $S/narrate.py --work $W --draft          # 有旁白稿时加 --script $W/narration_script.json
# Claude 给 $W/narration_plan.json 的每句配画面（格式见 skills/jianying-autocut/references/narration.md）
uv run --script $S/narrate.py --work $W --dry-run        # 节奏太赶就加 --pause-ratio 0.8
uv run --script $S/narrate.py --work $W
# ⌘Q 完全退出剪映
uv run --script $S/build.py --work $W --name 我的旁白片 --titles --narration $W/narration_track.json --bgm ~/Music/xxx.mp3
```

跑测试：`./run_tests.sh`

## 当前限制

- **剪映打开后草稿会被加密，本项目读不回来。** 你在剪映里做的修改，脚本看不到也接不上；重新生成会整目录覆盖同名草稿，想保留手工修改要先在剪映里另存副本。要基于剪好的版本继续处理，只能等你从剪映导出成片，再把成片当素材交给流程。
- **写草稿时剪映必须完全退出**（⌘Q），否则剪映退出时会覆盖草稿。
- 只支持 macOS + 剪映专业版；CapCut 未测试。
- Claude 看的是联系表（默认每 8 秒一帧），两帧之间的动作看不到；可以用 `frames.py --every 4` 抽得更密。
- Claude 听不到声音：语音靠 Whisper 转写，环境声和音乐的情绪都听不出来；旁白片的响度是 ffmpeg 测的数值，不是"听感"。
- 切点只吸附到静音处，对着镜头说话的片段偶尔会切在半句。
- 画面方向按 8 秒一帧抽样判断，抽样之间的画面可能漏判。
- 多台设备混拍时，若设备时钟没对齐，按拍摄时间的排序会乱；请先自行校正拍摄时间。
- 章节素材很碎时（全是短镜头），节奏调整也避免不了三连短镜头。
- 旁白片里，人声需要放大（> 100%）时，剪映 11.6 是否按草稿里的音量播放还没实测；报告会标出这些地方，打开草稿听一下。
- 旁白的句子边界来自 Whisper，误差约 0.2–0.5 秒；脚本只往外扩、不往里缩，偶尔仍需在页面上改一下秒数。
- 旁白片不卡点：时长由旁白决定，`beatsync.py` 会拒绝运行。
- 拍摄脚本页面要联网、登录 claude.ai；页面上的镜头顺序只影响脚本，成片里同一章的镜头仍按拍摄时间排。
- 草稿只含视频 / 文字（章节标题、字幕）/ 旁白 / BGM 几类轨道；转场、调色、特效都在剪映里完成。

## 目录结构

```text
skills/jianying-autocut/                技能本体（npx skills / 插件安装的就是这个文件夹）
  SKILL.md                              给 Agent 的使用说明（技能入口）
  scripts/                              probe · frames · transcribe · notes · orient · story · match · plan · narrate · beatsync · loudness · build · common
  references/                           写故事指引（story_plan.md）、拍摄脚本页面（shoot_plan.md）、旁白片（narration.md）、实测踩坑（pitfalls.md）
  assets/                               拍摄脚本页面模板（shoot_plan_page.html）
  vendor/video-script-refs/             收录的 video-script 导演方法文档（MIT，见下方鸣谢）
.claude-plugin/marketplace.json         Claude Code 插件清单
tests/                                  pytest（./run_tests.sh）
docs/                                   设计规格、实现计划、工作流图、宣传片
```

## 鸣谢

- **[GuanYixuan/pyJianYingDraft](https://github.com/GuanYixuan/pyJianYingDraft)**（Apache-2.0）：Python 剪映草稿生成库，本项目写草稿的基础。
- **[aoguai/pyJianYingDraft](https://github.com/aoguai/pyJianYingDraft)**（Apache-2.0）：维护版，支持剪映 7+ / 11.6 的新草稿格式；本项目锁定使用其提交 `69cee12`。
- **[zenstory-ai/video-recap-skills](https://github.com/zenstory-ai/video-recap-skills)**（MIT, © 2026 PiteChen）：本项目收录了 `video-script` 的导演方法文档。许可证原文见 [`vendor/LICENSE-video-recap-skills`](skills/jianying-autocut/vendor/LICENSE-video-recap-skills)。
- **[cathrynlavery/diagram-design](https://github.com/cathrynlavery/diagram-design)**（MIT）：工作流图用它的设计系统绘制。
- **[faster-whisper](https://github.com/SYSTRAN/faster-whisper)**（MIT）：本地语音转写。
- **[FFmpeg](https://ffmpeg.org/)**（LGPL/GPL，系统安装，不随本项目分发）：盘点、静音检测、EBU R128 响度测量。
- 网络教程《剪映自动化粗剪 · 即抄提示词（适配剪映 11.6）》：版本号对齐、素材零复制等踩坑经验的来源。

## 许可证

本项目代码以 [MIT](LICENSE) 发布；`vendor/` 下的收录代码保留其原始 MIT 许可证。
