# GPU 兼容矩阵

> 维护方式：CXY 维护 50 系主轨，LJQ 维护 40 系兼容轨；环境变化后更新。  
> 只填写命令或真实运行产生的结果。

## 当前矩阵

| 轨道 | 负责人 | GPU | Python / Torch | 当前证据 | 当前结论 |
|---|---|---|---|---|---|
| 50 系完整轨 | CXY | RTX 5060 Laptop 8 GB | 整合包 Python 3.9.13；Torch 2.7.0+cu128 | GPU 可用；切分/ASR/特征/训练权重已产生 | 环境和训练已通过；先补 Web UI 新 WAV，再验证项目 adapter 调用 |
| 40 系兼容轨 | LJQ | 待实测 | 待实测 | 待提交 `LJQ-40series-baseline.md` | 未验证 |

## 50 系已确认事实

- 参考运行时：`D:\Documents\GPT-SoVITS-v2pro-20250604-nvidia50`，只作为 CXY 本机外部依赖，不写进代码。
- `torch.cuda.is_available()` 为 `True`。
- GPU 为 `NVIDIA GeForce RTX 5060 Laptop GPU`。
- 整合包包含可用 FFmpeg、FunASR 模型和预训练模型。
- 已产生切片、ASR `.list`、特征目录、SoVITS `.pth` 和 GPT `.ckpt`。
- 尚需用选定的一对训练权重，通过项目拟采用的 adapter 路径生成一条全新 WAV。

## 40 系 Week 1 最小检查

LJQ 只需先完成：

1. `nvidia-smi`；
2. 实际 Python 路径和版本；
3. Torch、内置 CUDA、`torch.cuda.is_available()`；
4. FFmpeg；
5. GPT-SoVITS 目录和版本来源；
6. 适配器 `probe_environment`；
7. 条件允许时生成一条真实零样本 WAV。

40 系 Week 1 不要求完成训练。未出 WAV 时必须给出错误日志和下一步，仍可完成环境基线任务。

## 兼容验收

- 只有 50 系完整闭环通过，才能写“50 系完整支持”。
- 只有 40 系项目入口真实出声，才能写“40 系推理兼容”。
- 只有 40 系训练并加载新权重出声，才能写“40 系训练兼容”。
