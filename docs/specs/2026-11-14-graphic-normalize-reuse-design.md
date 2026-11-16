# 图形素材、旁白响度归一化、画面重复使用 / 消音 设计

日期：2026-11-14（2026-11-16 按 Fable 评审修订）
来源：枸杞岛真实素材端到端（PR #6）里发现的问题 12、15、16。当时是手工绕过去的，这次把它们做成工具本身的能力。

## 1. 目标与验收

用户的决定：

| 问题 | 用户的选择 |
|---|---|
| 15 旁白各文件响度不一致 | 接受剪映里引用归一化副本，原文件不动；副本用 **WAV** |
| 12 图形素材被当成相机素材判画质 | 看联系表时手动标：`orient.py --graphic` |
| 16 画面不能重复用、不能单独消音 | 只在旁白片里做：`narration_plan.json` 支持，页面上能勾选 |
| 评审 C1：地图动画差 31ms 盖不住三句旁白 | 一槽末尾剩下不到 0.1s 的零头时，挤给下一句（通用规则） |
| 评审 I10：reuse 放开哪些限制 | 只放开两项：素材已被占用、紧跟着同素材的原声段。仍然不和前一个镜头同素材相邻，同一句里也不重叠 |

验收：用枸杞岛数据重跑旁白版，以下几条都要满足。

- 不再需要 `视频/手机/副本/` 里的去音轨副本和链接副本，改用 `reuse` / `mute`；
- 不手改 `frames.csv`，地图动画标 `--graphic`；
- 地图动画用**原始 21.000 秒版本**（不补静止帧），一个镜头盖住「从上海出发」三句（槽长 21.031s）；
- 9 个旁白副本的积分响度都在 **-16 ±0.7 LUFS** 以内（实测两遍法的结果是 -16.05 到 -16.59），彼此相差不超过 1 dB（现在差 5.6 dB）；真峰值不超过 -1.5 dBTP；
- 现有测试全过，下面每一节都有新增测试覆盖。

不做：

- 按镜头剪的片子（story_plan）不支持 reuse / mute；
- 原声段（live）不做归一化副本；
- 不做降噪；
- `beatsync.py` 不改。它对旁白片会直接拒跑，所以图形素材在卡点里暂时用不上，记成 TODO。

## 2. 旁白响度归一化（问题 15）

### 现状

`build.py --narration` 在剪映里直接引用用户录的原文件，按实测响度设一个增益：最多 +12 dB，真峰值不超过 -1 dBTP。

手机录音的峰值和平均响度差得多。枸杞岛实测：响度 -26 到 -31 LUFS，峰值 -6 到 -12 dBTP。增益提几 dB 就碰到峰值上限，各文件最后停在 -17.4 到 -23.0 LUFS，彼此相差 5.6 dB。

### 做法：两遍 loudnorm，生成 WAV 副本

新模块 `scripts/normalize.py`，由 `build.py` 调用，不单独运行：

```
normalize(path, out_dir, cache) -> (out_path, info)
info = {"type": "dynamic" | "linear", "short": bool}
```

1. **第一遍**：`ffmpeg -i <src> -af loudnorm=I=-16:TP=-1.5:LRA=11:print_format=json -f null -`。从 stderr 的 JSON 里读出 `input_i / input_tp / input_lra / input_thresh / target_offset`。
2. **第二遍**：带上第一遍的测量值：

   ```
   loudnorm=I=-16:TP=-1.5:LRA=11:measured_I=…:measured_TP=…:measured_LRA=…:measured_thresh=…:offset=…:linear=true:print_format=json
   ```

   输出 `-ar 48000 -c:a pcm_s16le`，也就是 WAV。WAV 的时长和原文件逐样本一致，也不会有编码带来的峰值过冲。第二遍 JSON 里的 `normalization_type` 记进 `info["type"]`。

   实测说明：这批手机旁白全部是 `dynamic`，因为要提 10 到 15 dB，峰值不允许纯线性增益。`linear` 只会出现在峰值本来就很低的录音里，或者不到 3 秒的文件里（这时 ffmpeg 自己会退回线性）。
3. **不到 3 秒的文件**：ffmpeg 会退回 linear，可能被真峰值卡住，到不了目标响度（实测有一个 2.5s 的样本停在 -25.7 LUFS）。这时 `info["short"] = True`。`build.py` 拿副本的实测响度和 -16 比，差 0.7 以上就沿用现有的提示「太小声，还差 N dB」。
4. **副本位置**：`W/旁白_归一化/<原文件名去掉扩展名>.wav`。几个原文件去掉扩展名后同名时，按原路径排序，依次加 `_n2`、`_n3`。序号记在缓存里，再次运行时保持不变。
5. **缓存**：存在 `loudness.Cache` 里，用 `get` / `put`，不走 `measure()`（`measure()` 会把没有 `short` 字段的条目当成失效）。键是原文件的「路径 + mtime + 大小」，额外标记为 `norm`。值是 `{out, out_mtime, type, short}`。下面几种情况会重新生成：
   - 原文件改动过（重录覆盖），键对不上；
   - 副本被删了；
   - 副本的 mtime 和记录的对不上。
6. **失败**：ffmpeg 返回非零就抛 `CalledProcessError`。`build.py` 捕获后退出，并说明是哪个文件。旁白片的音量全靠这一步，不能悄悄退回原文件。

### build.py 的改动

原文件到副本的映射一共有 4 处：

| 位置 | 改法 |
|---|---|
| `missing_vo` 的存在性检查 | 不变，仍然检查原文件 |
| `narration_mix` 里测旁白 | 先 `normalize`，再对**副本**跑 `cache.measure`。增益固定为 1.0。`level` 的键**保持原文件路径**，这样 `voice_of` 和 `audio_at`（键是 `narr["audio"][i]["file"]`）都不用改 |
| 剪映旁白片段 | `injected_audio(副本路径, vo_durs[原路径])`，时长沿用转写时记下的原时长（WAV 和原文件一致），`volume=1.0` |
| 报告 | 每个文件一行：`<文件名> -29.1 → -16.2 LUFS（限幅）`，前后两个数都用 ebur128（`cache.measure`）测，不用 loudnorm 自己报的数值（两者差 0.4 到 0.7 LU，混用会让人以为前后差值就是增益）。另外写明副本放在哪个目录 |

- 「音量放大（>100%）待真机验证」这条提示：旁白不会再触发它。原声段的 `live_gain` 仍可能大于 1，那部分照旧提示。
- `narration_track.json` 里的路径仍然是原文件。换成副本只发生在 build 这一步：转写和时间线用的都是原文件的时间，换副本只改音量，不改时间。
- 要改的现有测试：`tests/test_build_main.py` 里断言旁白音量是 `10**(6/20)` 的那一条，改成断言音量是 1.0、引用的是副本路径。

### 测试

- **合成音频**：用 ffmpeg 生成 10 秒、约 -28 LUFS 的正弦波，叠加几处 20ms、-6 dBFS 的尖峰。跑 `normalize` 后用 ebur128 复测副本：积分响度在 -16 ±0.7 以内，真峰值不超过 -1.5，`type == "dynamic"`。
- **短文件**：2.5 秒的同类音频，`info["short"]` 为真，`type == "linear"`。
- **缓存**：第二次调用不跑 ffmpeg（用 monkeypatch 计数）；改了原文件的 mtime 会重跑；删掉副本会重跑；同名原文件分别得到 `_n2` 这样的序号，而且两次运行序号一样。
- **没有 ffmpeg 的环境**：上面几条跳过，和现有 loudness 测试的做法一致。
- **build 层**：mock 掉 `normalize`，检查剪映里旁白片段引用的是副本路径、音量是 1.0、时长等于原时长，报告里有「→ -16」那一行。

## 3. 图形素材（问题 12）

### 怎么标

`orient.py --work W --graphic c023[,c024]`，写进 `orientation.json`：`{"clips": {"c023": {"graphic": true}}}`。

- 可以和 `--flip` / `--unusable` / `--bad` 同时用。`--flip` 和 `--unusable` 是整体赋值（`clips[cid] = {...}`），所以 `--graphic` 必须**在它们之后**用 `setdefault(cid, {})["graphic"] = True` 合并，否则会被覆盖。
- 素材编号在 frames.csv 里找不到时报错，和 `--flip` 的做法一样。
- `orient.py` 每次运行都会重写整个文件（这个行为不变），所以要把所有标记一起带上。
- `SKILL.md` 第 3 步加一句：地图、片头卡片、录屏这类不是相机拍的素材，要标 `--graphic`。

### 标上以后

- **`Clip` 怎么知道自己是图形素材**：`Clip.__init__(row, frames, silences, graphic=False)` 加一个可选参数。`plan.load_clips` 读 `orientation.json`，在构造时传进去。测试里那 7 处直接构造 `Clip` 的地方不用改。
- **画质判断**：图形素材的 `frames` 直接设成 `[]`。这样 `window_score` 本来就会返回 0.5，`good_usable` 等于 `usable`，所有帧都算好帧。图形素材不会有「歪帧」，所以 `--bad` 对它不再单独处理。
  - 精简模式按得分删素材时，图形素材的得分是 0.5，不会因为「得分低」被删。
  - 已知的限制：frames.csv 的 `score` 是在整个工作目录所有帧里排的百分位。图形素材的帧会压低别的素材的百分位，而 `frames.py` 是在 `orient.py` 之前跑的，所以没法在排名时把它剔除。这个影响可以接受，记进 pitfalls。
- **首尾**：`Clip` 增加属性 `edge`。相机素材是 `EDGE`（0.5s），图形素材是 0。凡是用到 `EDGE` 的地方都改成按素材取值：
  - `plan.py`：`Clip.usable / feasible / best_window / longest_free / snap`、`place_pin`、`place_pins` 的 cover 逻辑。模块级函数 `snap_to_silence` 加参数 `edge=EDGE`（保留默认值，`tests/test_plan.py` 直接调用它）。`place_pins` 提示里写死的「首尾 0.5s 不取」改成按 `c.edge` 生成。
  - `narrate.py`：`_extend`、`_place_in_free_segment`，以及 `from plan import EDGE` 的用法。常量 `EDGE` 本身保留，测试里有 import。
  - `story.py` 的 `usable_seconds`（`--check` 的信息输出）不改。图形素材在那里会少算 1 秒，只影响显示。
  - `beatsync.py` 不改（见第 1 节「不做」）。

### 测试

- **`orient.py`**：`--graphic` 写对了字段；和 `--flip`、`--unusable` 一起用时三个字段都在；素材编号不存在时报错。
- **`load_clips`**：图形素材的 `frames` 为空、`edge` 为 0；相机素材不受影响。
- **`place_pin` / 旁白 `layout`**：图形素材能从第 0 秒取到最后一秒。21.000s 的图形素材加 31ms 零头能盖住 21.031s 的槽，靠的是第 4 节的「零头挤给下一句」，这一条在第 4 节测。

## 4. 旁白片铺画面：零头、重复使用、消音（问题 16 + 评审 C1）

### 零头挤给下一句（评审 C1）

`layout` 里，一槽最后一块处理完后，如果还剩 `0 < remaining < 0.1s`，而且并不进本槽的任何镜头（往后延长、入点往前挪都不行），就把这段时间挤给**下一句**：本槽的结束点和下一槽的开始点一起提前 `remaining`，下一句的第一个镜头相应地早这么一点出现。

- 前提：下一槽是旁白句。如果下一槽是原声段，或者本槽是最后一槽，就照旧处理。
- 阈值 `NUDGE_MAX = 0.1s`，约 3 帧，肉眼看不出。
- 测试：21.000s 的图形素材是本槽唯一的画面，后面紧跟一句旁白，槽长 21.031s。结果是图形素材一个镜头 21.000s，下一句的槽提前 31ms 开始，`_rows_ok` 检查成片时间仍然没有缝隙。

### 数据格式

`narration_plan.json` 的 `line.visuals[]` 里，每一项可以多两个可选字段：

```json
{"clip_id": "c022", "at": 4.0, "reuse": true, "mute": true}
```

`narrate.validate` 在 visuals 循环里检查：`reuse` 和 `mute` 要么不写，要么是布尔值，否则报中文错误。

### reuse

用户的选择：只放开两项限制，**已占用的区间**和**紧跟着同素材的原声段**。其它规则照旧：

- 不和前一个镜头同素材相邻；
- 同一句里两个 reuse 画面不重叠。

实现方式：

- 镜头字典带 `"reuse": True`。
- `Clip` 增加两个字段：`reuse_used`（reuse 镜头自己的占用，只用来防止同一句里互相重叠）和一个上下文管理器 `with c.unconstrained():`。在这个上下文里，`free()` 只检查 `reuse_used`，不检查 `used`。
- `_place_any` 遇到 `v.get("reuse")`：
  - 在 `unconstrained()` 里放置。`longest_free` 要在**进入上下文之后**再计算。
  - 放好的区间记进 `reuse_used`，不记进 `used`。
  - avoid 里只去掉 `next_live`，仍然避开前一个镜头的素材。
- `_extend` 遇到 `shot["reuse"]`：增删的是 `reuse_used`，不是 `used`；边界按 `c.edge` 检查。
- `_try_place` / `_place_in_free_segment` 接收一个 `reuse` 参数，决定把占用 `append` 到哪个列表。不要用「先登记、事后恢复」的写法，否则可能把原声段的占用一起弄丢。
- 只有用户写在本句 `visuals` 里的画面才算 reuse。借来的画面（相邻句的、本章池里的）不继承这个标记：借用路径会生成新的 `{"clip_id": …}` 字典，本来就不会带上 `reuse`。

### mute

- `layout` 产出的镜头带上 `mute: True`。
- `shots.csv` 的 `FIELDS` 在末尾增加一列 `mute`，值是空字符串或 `1`。`write_csv` 用的是 `DictWriter`（缺字段时写空），`beatsync` 原样透传各列，`build` 用 `s.get("mute")` 读取，所以旧文件不受影响。
- 按镜头算音量的地方在 `build.main` 的镜头循环里（不是 `narration_mix`）：`kind == "narr"` 并且带 `mute` 的镜头，音量设为 0，**优先于 `--volume`**。
- `narration_mix` 只为没有被 mute 的旁白镜头测垫底响度。只出现在 mute 镜头里的素材不用测。
- `--dry-run` 报告：`report["items"][*]["shots"]` 从 `(cid, in, dur)` 改成 `(cid, in, dur, flags)`，`_print_report` 在这类镜头行尾标「（重复用）」「（消音）」。

### 页面

- 旁白编辑视图（`nmatch` 详情）里，每个已选画面下面加两个勾选框：「允许重复用」「消音」。改动时把整个 `visuals` 写回 `nmatch/<id>`，带上 `by: "user"`。
- 「换画面」（`reassign-n`）现在会把 `visuals` 整体替换成只有一项。新的规则：
  - 新素材和原来第一个画面是同一个素材（`clip === v0.clip_id`），只改了 `at`：保留 `reuse` 和 `mute`；
  - 换了素材：这两项清空。
- `narration.md` 的导出说明：`line.visuals` 原样带上 `reuse` 和 `mute`。

### 测试

- **reuse**：
  - 素材整段被原声段占用时，reuse 画面仍然能放进去，原声段的 `used` 不变；
  - 紧跟原声段的那一句用同一素材的 reuse 画面，不会被回避；
  - 同一句里两个同素材的 reuse 画面不重叠；
  - reuse 镜头后面的零头可以并进它（`_extend` 不报错）；
  - 不写 reuse 时，行为和现在一样（回归）。
- **mute**：带 mute 的镜头在 `shots.csv` 里 `mute=1`；build 层 mock 混音后，这个镜头的音量是 0，即使给了 `--volume 0.3` 也是 0；同一素材的其它镜头不受影响。
- **validate**：`reuse: "yes"` 会报错。
- **页面**：勾选框会写进 `nmatch.visuals[i].reuse / mute`；只改 `at` 时保留，换素材时清空。

### 页面测试进仓库（评审 I11）

现在的页面测试脚本放在 scratchpad 里，每个 PR 都要重建一遍。这次把它们收进仓库，放在 `tests/page/*.js`：

- 加一个 pytest 用例 `tests/test_page.py`，用 `node` 逐个跑这些脚本，脚本退出码为 0 才算通过；
- 本机没有 `node` 时 skip；
- `./run_tests.sh` 和 CI 都会跑到它们。

## 5. 文档

- **`SKILL.md` 第 3 步**：加上 `--graphic`。
- **`references/narration.md`**：
  - visuals 字段表加上 `reuse` / `mute`；「配画面怎么想」一节加上呼应和闪回的写法；
  - 混音表里旁白那一行改成：先生成归一化 WAV 副本（-16 LUFS、-1.5 dBTP），剪映里引用副本；
  - 报告提示表：旁白去掉「音量放大待真机验证」，加上「归一化失败」和「太小声，还差 N dB」（不到 3 秒的文件）。
- **`references/pitfalls.md`** 加三条：
  - 手机旁白的峰值和平均响度差得多，光调增益到不了 -16 LUFS；
  - 图形素材会被判成坏帧，还会压低其它素材的画质百分位；
  - 单声道旁白在剪映里按双声道播放，听感会比测量值响约 3 LU。

## 6. 风险

- loudnorm 的动态模式会压缩旁白的动态。这批 -26 到 -31 LUFS 的手机录音，听感上会更平、更近。用户想保留原来的动态，可以在剪映里把素材替换回原文件，报告里写明了副本的位置。
- 剪映引用 WAV 副本，需要在真机上确认能正常播放。`common.AUDIO_EXTS` 已经包含 `.wav`，pyJianYingDraft 注入的音频素材不依赖格式。这条列进真机验证。
- 「零头挤给下一句」会让下一句的画面比 J-cut 规则早不到 0.1 秒出现，听感上没有影响。
