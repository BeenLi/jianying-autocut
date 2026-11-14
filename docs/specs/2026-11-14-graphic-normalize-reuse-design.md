# 图形素材、旁白响度归一化、画面重复使用 / 消音 设计

日期：2026-11-14
来源：枸杞岛真实素材端到端（PR #6）发现的问题 12、15、16。那次靠手工绕过去了，这次把它们变成工具本身的能力。

## 1. 目标与验收

用户的决定：

| 问题 | 用户选择 |
|---|---|
| 15 旁白各文件响度不一致 | 接受「剪映里引用归一化副本」，原文件不动 |
| 12 图形素材被当成相机素材判画质 | 看联系表时手动标，用 `orient.py --graphic` |
| 16 画面不能重复用、不能单独消音 | 只做旁白片：`narration_plan.json` 支持，页面上也能勾选 |

验收（用枸杞岛数据重跑旁白版）：

- 不需要 `视频/手机/副本/` 里的去音轨副本和链接副本，改用 `reuse` / `mute`；
- 不需要手改 `frames.csv`，地图动画标 `--graphic`；
- 地图动画用原始的 21 秒版本、不补静止帧，就能盖住「从上海出发」三句；
- 9 个旁白文件进剪映后的积分响度都在 -16 ±0.5 LUFS，彼此相差不超过 1 dB（现在相差 5.6 dB）；
- 现有测试全过，新增测试覆盖下面每一节。

不做：按镜头剪的片子（story_plan）不支持 reuse / mute；原声段（live）不做归一化副本；不做降噪。

## 2. 旁白响度归一化（问题 15）

### 现状

`build.py --narration` 在剪映里直接引用用户录的原文件，按实测设一个增益：最多 +12 dB，真峰值不超过 -1 dBTP。

手机录音的峰值和平均响度差得多（枸杞岛实测：响度 -26 到 -31 LUFS，峰值 -6 到 -12 dBTP），增益提几 dB 就碰到峰值上限。结果各文件停在 -17.4 到 -23.0 LUFS，彼此相差 5.6 dB。

### 做法：两遍 loudnorm 生成副本

新模块 `scripts/normalize.py`，由 `build.py` 调用，不单独跑：

```
normalize(path, out_dir, cache) -> (out_path, info)
```

1. **第一遍**：`ffmpeg -i <src> -af loudnorm=I=-16:TP=-1.5:LRA=11:print_format=json -f null -`，读出 `input_i / input_tp / input_lra / input_thresh / target_offset`。
2. **第二遍**：带上第一遍的测量值：

   ```
   loudnorm=I=-16:TP=-1.5:LRA=11:measured_I=…:measured_TP=…:measured_LRA=…:measured_thresh=…:offset=…:linear=true
   ```

   输出 `-ar 48000 -c:a aac -b:a 192k`。峰值允许时，ffmpeg 自己用纯线性增益；不允许时，自动退到带限幅的动态模式。第二遍的 JSON 输出里 `normalization_type` 会写明用了哪种，记进 `info`。
3. **副本位置**：`W/旁白_归一化/<原文件名去扩展名>.m4a`。同名冲突时，在文件名后加 `_n<序号>`。
4. **缓存**：复用 `loudness.Cache` 的键，即「路径 + mtime + 大小」，再加上额外标记 `norm`。值记 `{out, out_mtime, type, before_i, before_tp}`。
   - 原文件改动（重录覆盖）后，键就对不上了，会重新生成；
   - 副本被删，或副本的 mtime 和记录的对不上，也重新生成。
5. **失败**：ffmpeg 返回非零就抛出异常。`build.py` 收到后退出，并说明是哪个文件出的错。旁白片的音量全靠这一步，不能静默退回原文件。

### build.py 的改动

- `narration_mix`：旁白文件先过 `normalize`，再对副本实测响度（走 `loudness.Cache`）。副本的增益固定为 1.0，记下的人声电平就是副本的实测值。BGM 压低比例和音量差检查都用这个值（PR #6 已经改成按实际人声算）。
- 剪映里引用副本路径。`injected_audio` 的时长取自副本（用 ffprobe，或继续沿用转写时记下的时长，两者差异小于 1 帧）。
- 报告：每个文件一行，「`<文件名>` -29.1 → -16.0 LUFS（线性 / 限幅）」。增益不再超过 1.0，「音量放大待真机验证」这条提示随之去掉。
- `narration_track.json` 里的路径仍是原文件，换成副本只发生在 build 这一步：转写和时间线用的是原文件的时间，副本长度相同，时间不变。

### 测试

- 用 ffmpeg 生成测试音频：-30 LUFS 的正弦波，叠加几个 -6 dBFS 的尖峰。跑 `normalize` 以后，输出的积分响度在 -16 ±0.5 LUFS，真峰值不超过 -1.5 dBTP，`type` 是 dynamic。
- 缓存：第二次调用不跑 ffmpeg（用 monkeypatch 计数）；改动原文件的 mtime 后会重跑。
- 测试环境没有 ffmpeg 时跳过这两条，和现有 loudness 测试的处理一致。
- `build` 层：mock 掉 `normalize`，检查剪映里旁白片段引用的是副本路径、音量是 1.0。

## 3. 图形素材（问题 12）

### 怎么标

`orient.py --work W --graphic c023[,c024]`，写进 `orientation.json`：`{"clips": {"c023": {"graphic": true}}}`。

可以和 `--flip` / `--unusable` / `--bad` 同时用。`orient.py` 每次运行都重写整个文件，这个行为不变，所以每次都要带上全部标记。`SKILL.md` 第 3 步加一句：地图、片头卡片、录屏这类不是相机拍的素材，标 `--graphic`。

### 标上以后

- **画质判断**：`plan.load_clips` 读到 `graphic`，就把这段素材所有帧的 `bad` 当 0、`score` 当 0.5（中性）。`--bad` 手动标的歪帧仍然算坏帧，因为那是人判断的。
- **首尾**：`Clip` 增加属性 `edge`，相机素材是 `EDGE`（0.5 s），图形素材是 0。`plan.py` 里 `Clip.usable / feasible / best_window / longest_free / snap`、`place_pin`、`place_pins` 的 cover 逻辑，以及 `narrate.py` 的 `_extend`、`_place_in_free_segment`，凡是用到 `EDGE` 的地方都改成读 `c.edge`。`beatsync.py` 的 `TAIL` 也改成按素材取：它读 `orientation.json`，图形素材取 0。
- **精简模式**：`plan_condense` 按得分百分位删素材，图形素材得分是 0.5，不会因为「得分低」被删。

### 测试

- `orient.py`：`--graphic` 写对字段，可以和 `--flip` 并存，素材编号不存在时报错。
- `load_clips`：图形素材的帧都不是坏帧，得分 0.5，`edge` 为 0；`--bad` 标的帧仍然是坏帧。
- `place_pin` / 旁白 `layout`：图形素材能从第 0 秒开始取、能取到最后一秒。用 21 秒的素材盖住 21 秒的槽，现在会失败，改完要成功。

## 4. 画面重复使用 / 消音（问题 16）

### 数据格式

`narration_plan.json` 的 `line.visuals[]` 每项可以多两个可选字段：

```json
{"clip_id": "c022", "at": 4.0, "reuse": true, "mute": true}
```

`narrate.validate` 检查：`reuse` / `mute` 要么不写，要么是布尔值，否则报中文错误。

### reuse

`layout` 放 `reuse: true` 的画面时：

- 不受已占用区间的限制：在一个临时状态下放置，`used` 视为空。
- 不受同素材不相邻的限制：跳过 `avoid`，包括前一个镜头和紧跟的原声段。
- 自己占用的区间不登记到 `c.used`，不影响别的句子使用这段素材。
- 只对用户写在本句 `visuals` 里的画面生效。借来的画面（相邻句、本章池）不继承 `reuse`。

实现方式：在 `_place_any` 里，`v.get("reuse")` 为真时，临时把 `c.used` 换成空列表，调用 `_try_place` / `_place_in_free_segment`，然后把 `c.used` 恢复原样（不记下这次的占用），并且跳过 `avoid` 检查。

### mute

- `layout` 产出的镜头带上 `mute: True`。
- `shots.csv` 的 `FIELDS` 增加末列 `mute`（空字符串或 `1`）。`write_shots` / `read_csv` 对没有这一列的旧文件保持兼容。
- `build.narration_mix` 垫底音量按镜头算：`kind == "narr"` 且 `mute` 的镜头音量为 0，其余照旧按素材取 `bed_gain`。
- `--dry-run` 报告里，这类镜头行尾标「（重复用）」「（消音）」。

### 页面

- 旁白编辑视图（`nmatch` 详情）里，每个已选画面下面有两个勾选框：「允许重复用」「消音」。改动时把整个 `visuals` 写回 `nmatch/<id>`，带 `by: "user"`。
- 「换画面」表单保留已有的 `reuse` / `mute`：换素材时这两项清空，只改 `at` 时保留。
- `narration.md` 的导出说明：`line.visuals` 原样带上 `reuse` / `mute`。

### 测试

- `layout`：素材整段被原声段占用时，`reuse` 画面仍然能放进去，原声段的占用不变；紧跟原声段的那句用同一素材的 `reuse` 画面时，不会被回避；不写 `reuse` 时行为和现在一致（回归）。
- `mute`：带 `mute` 的镜头在 `shots.csv` 里 `mute=1`；`build` 层 mock 混音后，这个镜头的音量为 0，同素材的其它镜头不受影响。
- `validate`：`reuse: "yes"` 报错。
- 页面 harness：勾选框写入 `nmatch.visuals[i].reuse / mute`；换素材时这两项清空。

## 5. 文档

- `SKILL.md` 第 3 步：加 `--graphic`。
- `references/narration.md`：
  - visuals 字段表加 `reuse` / `mute`，「配画面怎么想」里加呼应、闪回的写法；
  - 混音表里旁白一行改成「先生成归一化副本（-16 LUFS / -1.5 dBTP），剪映里引用副本」；
  - 报告提示表去掉「音量放大待真机验证」，加「归一化失败」。
- `references/pitfalls.md`：记下手机旁白峰值和平均响度差得多，以及图形素材被判成坏帧这两条实测经验。

## 6. 风险

- loudnorm 的动态模式对很短的文件（不到 3 秒）效果不稳定。补录单句（比如枸杞岛的比熊那句，约 6 秒）问题不大；不到 3 秒的文件改用一遍、线性模式，并在报告里注明。
- 副本占磁盘：AAC 192k，约 1.4 MB / 分钟，可以忽略。
- 剪映引用副本以后，用户在剪映里想换回原文件，得手动替换素材。报告里会写明副本的位置。
