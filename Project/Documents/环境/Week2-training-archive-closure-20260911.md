# Week 2 真实训练与权重归档闭环

日期：2026-09-11。执行环境：CXY RTX 5060 Laptop GPU，GPT-SoVITS v2Pro。

## 输入与任务

- 数据集：`609062526508461a89b9b3bf826e3fa5`（Buer_test01）。
- 已校对切片：17 个，BERT、HuBERT、SV、语义特征完整。
- 项目音色 ID：`buer-w2-project`。
- 项目任务：`train-e0e8f45522034e7189cfc2fbf58ff1ba`。
- 训练准备目录：`data/training/buer-w2-project-b8f1768f07be4deca31572d846a524ae/`。

## 真实执行结果

| 阶段 | 配置 | 结果 | 证据 |
|---|---|---|---|
| GPT | 15 epoch、batch 4、fp16、DPO=false | 通过 | 日志退出码 0，达到 `max_epochs=15` |
| SoVITS | 8 epoch、batch 4、fp16、GPU 0 | 通过 | 日志退出码 0，e4/e8 checkpoint 保存成功，`training done` |
| 新权重检测 | SHA-256 内容变化 + 受控输出路径/glob | 通过 | 未复用旧 checkpoint |
| 项目归档 | `data/voices/buer-w2-project/` | 通过 | 两份权重和参考音频均写入相对路径档案 |
| 归档后合成 | 项目 `tts_service` 调用整合包 API | 通过 | `data/outputs/tts-5701909348ae48ec86aba29be7df133f.wav` |

归档权重：

- `buer-w2-project-e15.ckpt`：155,314,554 bytes；295 个 GPT 权重项；`info=GPT-e15`。
- `buer-w2-project_e8_s176.pth`：134,946,867 bytes；678 个 SoVITS 权重项；`info=8epoch_176iteration`。

合成 WAV 校验：167,724 bytes，单声道，32,000 Hz，83,840 frames。

## 工程回归

- 配置真实音频、真实特征数据集和本次归档权重后，`python -m unittest discover -v`：70/70 通过，无跳过。
- `python -m compileall -q .`：通过。
- `git diff --check`：通过。

## 结论

项目已经形成“已校对数据集 → 特征复核 → 隔离训练配置 → GPT/SoVITS 真实训练 → 本次新权重检测 → 项目内归档 → VoiceProfile → 项目服务真实合成”的 Week 2 技术闭环。用户于 2026-09-11 确认本次 Buer 合成 WAV 听感完全正常，Week 2 最终验收通过。
