# 剪映 11.6（macOS）草稿生成：实测坑

| 坑 | 结论 | 代码位置 |
|---|---|---|
| 实测通过 | 2026-10-23：164 直写的 5 分钟草稿（42 镜头 + 章节标题轨 + BGM 3 段）在剪映 11.6.13345 打开正常、时间线完整 | — |
| 版本号 | 写本机真实 `new_version`（11.6 = 164.0.0），每次从草稿根目录 `root_meta_info.json` 读（单个草稿的 `draft_meta_info.json` 被剪映打开后会加密，读不了）；`app_version` 读 `/Applications/VideoFusion-macOS.app` 的 Info.plist。剪映会自动更新，别硬编码 | `common.detect_versions`、`build.stamp_versions` |
| 加密 | pyJianYingDraft 的加解密只支持 Windows。Mac 上写明文 `draft_info.json`，剪映首次打开时自己加密；之后读不回来 | — |
| 清场 | 剪映运行中写草稿不会被发现，退出时还会覆盖；重新生成要整目录删掉，不能在旧目录上覆盖 | `build.main` |
| 文字悬空引用 | TextSegment 的 `extra_material_refs` 若指向不存在的变速素材，剪映报「草稿内容已损坏」；构造后清空并在保存后全量检查 | `build.verify` |
| 时间 | 一律整数微秒；`Timerange(起点, 时长)` 第二个参数是时长；下一段起点 = 上一段终点，避免取整漂移 | `plan.py`、`build.py` |
| 素材零复制 | 只用 VideoMaterial + VideoSegment 引用绝对路径，不用 add_clip / inline_materials；几百 GB 素材复制会爆盘 | `build.injected_material` |
| 库版本 | aoguai/pyJianYingDraft 锁定提交 69cee12（0.3.0）。`injected_material` 依赖库内部字段，升级前先跑一遍 build 自检 | `build.py` 头部 |
| 抽帧速度 | 4K 10-bit HEVC 软解 seek 单帧 ~20s；`-skip_frame nokey` 只解关键帧 ~0.4s（取到 t 之前最近的关键帧，打分够用） | `frames.grab` |
| 判糊 | 拉普拉斯方差要和本段素材自己的中位数比：室内 / 雾天清晰帧也只有晴天外景的 1/10，按全局排名会整段误杀 | `frames.judge` |
| 代理长片 | video-understanding 一次只吃一个视频。逐段转 1280x720/15fps，等比缩进再补黑边（不裁），无音轨补静音，统一 `-shortest` 防止偏移累积；不能用 `-skip_frame nokey`（时间戳不规则会毁掉场景检测）；不插黑场（会被当垃圾场景过滤） | `understand.proxy_cmd` |
| 场景归属 | 跨两段素材的场景描述归重叠多的那段；语音按中点归属。ASR 是 15s 粗窗口，没有句子边界，所以镜头切点吸附的是 ffmpeg 测的静音段 | `understand.split_to_clips`、`plan.snap_to_silence` |
| MiMo 报错 | 402 或文本含 余额/欠费/insufficient/balance/quota → 提醒充值（退出码 3）；401 → key 无效；「Unsupported model」→ 模型下线（退出码 3）；429 交给上游重试 | `common.classify_mimo_error` |
| MiMo 模型下线 | 2026-10 实测：video-understanding 写死的 `mimo-v2.5` 已不可用（可用 `mimo-v2.6-flash/pro`），ASR 的 `mimo-v2.5-asr` 仍在。预检先查 `/models`，自动选看图模型并通过 `MIMO_MODEL` 传给上游 | `understand.pick_vision_model` |
| 画面方向 | 运动相机倒挂、相机挂在胸前晃着拍时，文件里没有旋转元数据。用 MiMo 逐帧问方向：≥70% 帧上下颠倒 → 整段倒装，草稿里片段转 180°；否则歪倒帧当坏帧避开（晃着拍的素材转 180° 也救不回来） | `understand.decide_orientation`、`build.py` |
| 人声分（已取消） | 「人声频段响度起伏」「4Hz 音节调制」「WebRTC VAD」对照 MiMo 转写 AUC 都只有 0.43–0.64；MiMo 的 15s 转写窗口跨多段短素材，本身也不能当标准答案。改为所有有音轨的素材都把入点吸附到 1.5s 内的静音段 | `plan.Clip.snap` |
| 时钟 | 多设备时钟不齐会打乱拍摄时间排序，本技能不自动校时，交给用户 | SKILL.md |
| BGM | `.ncm` 是网易云加密格式不能用；歌短于成片就循环，循环剩下 <1s 的尾巴从上一段借时间 | `build.bgm_segments` |
