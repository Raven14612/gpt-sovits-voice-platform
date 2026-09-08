# Citlali Week 2 正式音色档案

## 权重

- GPT：`GPT_weights_v2Pro/Citlali-e15.ckpt`
- SoVITS：`SoVITS_weights_v2Pro/Citlali_e8_s208.pth`
- 版本：v2Pro
- GPU：RTX 5060 Laptop GPU，GPU 0
- 训练配置：SoVITS 8 epoch、GPT 15 epoch、batch size 4、fp16、DPO 关闭

## 参考音频

- 文件：`output/slicer_opt/Citlali.wav_0000000000_0000182720.wav`
- 文本：`没错，我在人前的状态是装出来的，这才是我本来的性格。`
- 语种：zh
- 情绪：neutral

## 项目 adapter 回归

- 输出：`Project/data/outputs/citlali_adapter_w2.wav`
- 日志：`Project/data/outputs/citlali_adapter_w2.log`
- 输出大小：247084 bytes
- 结果：真实 API 子进程由项目 adapter 启动并清理，WAV 文件已生成。

## 人工确认

用户已确认本轮整合包训练结果和项目 adapter 新回归 WAV 听感正常。Citlali 正式音色档案的训练、权重加载和项目 adapter 合成均通过。
