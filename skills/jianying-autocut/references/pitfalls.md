# 剪映 11.6（macOS）草稿生成：实测坑

| 坑 | 结论 | 代码位置 |
|---|---|---|
| 实测通过 | 2026-10-23：164 直写的 5 分钟草稿（42 镜头 + 章节标题轨 + BGM 3 段）在剪映 11.6.13345 打开正常、时间线完整 | — |
| 实测通过（11.7） | 2026-11-10：枸杞岛 21 段手机素材生成的草稿（21 镜头 + 章节标题 + 人声字幕 5 条 + 卡点 BGM，BGM 带音量关键帧避让人声）在剪映 11.7.0 打开正常，字幕和避让效果经用户确认 | — |
| 版本号 | 写本机真实 `new_version`（11.6 = 164.0.0），每次从草稿根目录 `root_meta_info.json` 读（单个草稿的 `draft_meta_info.json` 被剪映打开后会加密，读不了）；`app_version` 读 `/Applications/VideoFusion-macOS.app` 的 Info.plist。剪映会自动更新，别硬编码 | `common.detect_versions`、`build.stamp_versions` |
| 加密 | pyJianYingDraft 的加解密只支持 Windows。Mac 上写明文 `draft_info.json`，剪映首次打开时自己加密；之后读不回来 | — |
| 清场 | 剪映运行中写草稿不会被发现，退出时还会覆盖；重新生成要整目录删掉，不能在旧目录上覆盖 | `build.main` |
| 文字悬空引用 | TextSegment 的 `extra_material_refs` 若指向不存在的变速素材，剪映报「草稿内容已损坏」；构造后清空并在保存后全量检查 | `build.verify` |
| 时间 | 一律整数微秒；`Timerange(起点, 时长)` 第二个参数是时长；下一段起点 = 上一段终点，避免取整漂移 | `plan.py`、`build.py` |
| 素材零复制 | 只用 VideoMaterial + VideoSegment 引用绝对路径，不用 add_clip / inline_materials；几百 GB 素材复制会爆盘 | `build.injected_material` |
| 库版本 | aoguai/pyJianYingDraft 锁定提交 69cee12（0.3.0）。`injected_material` 依赖库内部字段，升级前先跑一遍 build 自检 | `build.py` 头部 |
| 抽帧速度 | 4K 10-bit HEVC 软解 seek 单帧 ~20s；`-skip_frame nokey` 只解关键帧 ~0.4s（取到 t 之前最近的关键帧，打分够用） | `frames.grab` |
| 判糊 | 拉普拉斯方差要和本段素材自己的中位数比：室内 / 雾天清晰帧也只有晴天外景的 1/10，按全局排名会整段误杀 | `frames.judge` |
| 理解素材 | Claude 能看图但听不到声音，所以画面由 Claude 看联系表写 `scene_notes.json`（写成文件，换会话不丢），语音用本地 Whisper。联系表的秒数是四舍五入的，`orient.py` 换回 `frames.csv` 的精确时间，否则 `plan.py` 匹配不到坏帧 | `notes.py`、`transcribe.py`、`orient.py` |
| 抽帧时间 | `-skip_frame nokey -ss t` 取到的是 t 之后的下一个关键帧，不是之前的（实测）。抽帧点要先对齐到真实关键帧，并从略早处 seek，否则联系表标注和画面对不上，pin 和坏帧的时间都会偏 | `frames.snap_to_keyframes`、`frames.grab` |
| 场景切换抽帧 | 固定间隔会漏掉短场景，所以在相邻关键帧差异超过 0.4 的地方补帧；只解关键帧，4K 也快。手持晃动可能误报，所以补的帧最多翻一倍，优先留差异最大的。关键帧间隔长的素材（实测 libx264 默认约 8 秒）只能看到关键帧上的画面，可能漏掉很短的场景 | `frames.merge_times` |
| 切点 | `speech.json` 有句子时间，但 `plan.py` 目前只吸附 ffmpeg 测的静音段，还没用上句子时间 | `plan.snap_to_silence` |
| 画面方向 | 运动相机倒挂、相机挂在胸前晃着拍时，文件里没有旋转元数据，要看画面判断：整段倒装的在草稿里转 180°；大半歪倒的整段不用（晃着拍的素材转 180° 也救不回来）；个别歪帧当坏帧避开 | `orient.py`、`build.py` |
| 字幕 | `--subs` 的字幕只显示落在镜头里的部分；不到 0.5s 不显示，不到整句 80% 时警告「被剪断了」。底色用 TextBackground（黑、55%、圆角 0.3），放在 `transform_y=-0.85`，章节标题在 -0.75，两者同时出现时会挨得很近。说话时 BGM 用音量关键帧压到 25%，相隔不到 0.6s 的两句合并成一段，不在中间把音乐拉起来 | `build.place_subs`、`build.duck_keyframes` |
| Whisper 幻听 | 安静画面上会把 `--context` 提示词原样念出来（实测日落、渔港两段都转出「舟山枸杞岛旅行，带着小狗格桑。」），也会反复输出同一个词、给出超出素材长度的时间。置信度 `avg_logprob` 分不开真假（幻听 -0.25 比真话还高），只有 `no_speech_prob` 能分（真话 ≤0.20，幻听 0.60），阈值定 0.5。另外丢掉与提示词相似度 ≥0.8 的句子、超出素材长度的句子、同一素材重复 ≥3 次的句子 | `transcribe.speech_from_segments` |
| 卡点切话 | 有 `speech.json` 时，切点若落在一句话中间（句尾 0.2s 内不算），改用 2s 内不切话的拍点；找不到就照旧。章节交界只能落在小节线上，所以常常避不开 | `beatsync.snap_cuts` |
| 卡点备份 | `beatsync.py` 总从 `shots.prebeat.csv` 读（重复卡点不会叠加）；`plan.py` 写新分镜时必须删掉它，否则卡点悄悄用回旧分镜（实测） | `plan.write_shots` |
| 人声分（已取消） | 「人声频段响度起伏」「4Hz 音节调制」「WebRTC VAD」对照 MiMo 转写 AUC 都只有 0.43–0.64；MiMo 的 15s 转写窗口跨多段短素材，本身也不能当标准答案。改为所有有音轨的素材都把入点吸附到 1.5s 内的静音段 | `plan.Clip.snap` |
| 时钟 | 多设备时钟不齐会打乱拍摄时间排序，本技能不自动校时，交给用户 | SKILL.md |
| BGM | `.ncm` 是网易云加密格式不能用；歌短于成片就循环，循环剩下 <1s 的尾巴从上一段借时间 | `build.bgm_segments` |
