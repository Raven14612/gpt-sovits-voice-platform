# CXY 50 系 WebUI 证据评估（基于 2026-09-06 终端记录）

## 结论

当前记录证明 50 系整合包完成了切分、中文 ASR、特征准备、SoVITS 训练（8 epoch）、GPT 训练（15 epoch）以及推理 WebUI 启动，并加载了 `Columbina-e15.ckpt` 与 `Columbina_e8_s192.pth`。这部分为“部分通过”。

随后已在同一 50 系运行时通过 `api.py` 使用训练权重完成一次新的真实合成，WAV 文件证据已补齐。用户已确认整合包 9872 页面合成结果听感正常，并提供了 5 张页面截图，已归档到 `Documents/环境/evidence/`。

## 已确认事实

| 节点 | 证据摘要 | 判定 |
| --- | --- | --- |
| 0b 切分 | `tools/slice_audio.py` 执行完成，输出 `output\\slicer_opt` | 通过（终端记录） |
| 0c ASR | FunASR 模型加载完成，12 段音频处理完成 | 通过（终端记录） |
| 特征/数据准备 | `phoneme_data_len: 12`、`wav_data_len: 96`、`skipped_phone: 0` | 通过（终端记录） |
| SoVITS 微调 | epoch 1–8，`Columbina_e8_s192.pth` 后续被加载 | 部分通过 |
| GPT 微调 | `max_epochs=15`，推理加载 `Columbina-e15.ckpt` | 部分通过 |
| 推理服务 | `http://0.0.0.0:9872` 启动，CUDA Graph 检查通过 | 服务启动通过 |
| 新 WAV 文件 | `output/evidence_cxy_20260906.wav`，684844 字节，2026-09-06 12:23:57；32 kHz/单声道/16-bit/10.7 秒，HTTP 200；用户确认听感正常 | 通过（API真实推理+人工听感） |

## 可立即开始的下游节点

- LHY-W1-02：可依据已有真实入口和日志继续完善配置化探测；真实合成命令仍标记待实测。
- LHY-W1-03、LHY-W1-04：不依赖 GPU，可直接开发和测试。
- WGX-W1-01、WGX-W1-02、WGX-W1-03：不依赖模型结果，可直接开发/做 UI 结构验证。
- CXY-W1-02：可整理已确认的切分、ASR、训练入口；`synthesize` 的输出路径和参数仍待一条新 WAV 证据补齐。
- LJQ-W1-01：必须在真实 40 系机器独立取证，当前记录不能替代。

## 补证动作

剩余补证：将 API 控制台原始输出保存为本机日志；项目 adapter 直调仍需在源码/日志反查后单独接线验证。
