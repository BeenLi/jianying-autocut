# 待办

素材理解已全面改为「Claude 看联系表 + 本地 Whisper」，MiMo 已移除。下面这些内容还停留在 MiMo 流程：

- [ ] README（中英文）：演示视频说明、工作流图的替代文字（要和新图、新视频一起改）
- [ ] `docs/workflow.png` 和 `docs/workflow.html`：工作流图
- [ ] `docs/promo/`：宣传视频（`promo.mp4`、`promo.gif`）、页面和素材脚本（`face_scan.py`、`prepare.py` 还在用 MiMo）

真实素材（枸杞岛，21 段手机素材）跑出来的问题：

- [ ] `transcribe.py`：Whisper 在没人说话的日落素材上幻听出 7 句「江湖」「北京」，有一句的时间超出素材长度（16–28s，素材只有 11s）。要丢掉超出素材时长的句子和短时间内重复的同一个词
- [ ] 卡点不避开说话：切点会落在一句话中间（`speech.json` 已有句子时间，`beatsync.py` 还没用）
