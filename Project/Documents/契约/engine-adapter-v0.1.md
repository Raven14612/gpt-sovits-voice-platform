# Engine Adapter 契约 v0.1

> 目的：让前端、业务代码和 GPU 运行环境可以独立开发。  
> Week 1 首条项目内真实 WAV 产生前冻结为 v1.0。

## 1. 配置边界

仓库只提交 `engine.example.json`，本机配置文件加入 `.gitignore`。

```json
{
  "profile": "local-gpt-sovits",
  "engine_root": "<absolute-path>",
  "python_path": "<absolute-path-to-python>",
  "max_gpu_jobs": 1,
  "parallel_infer": false
}
```

不得在 Python 源码中出现 CXY 或 LJQ 的实际磁盘路径。

## 2. 统一状态

```text
PENDING → RUNNING → SUCCEEDED
                  ↘ FAILED
PENDING/RUNNING → CANCELLED（仅在子进程可安全终止时）
```

训练任务的 `stage`：

```text
validating / slicing / asr / feature_text / feature_hubert /
feature_semantic / train_sovits / train_gpt / packaging
```

UI 可展示阶段和日志，但没有真实总工作量时不得虚构完成百分比。

## 3. 接口

| 接口 | 主要输入 | 主要输出 |
|---|---|---|
| `probe_environment(config)` | 引擎配置 | Python、Torch、CUDA、GPU、FFmpeg、模型与入口状态 |
| `slice_audio(source, output_dir, params)` | 音频、输出目录、固定参数 | 切片列表与日志 |
| `run_asr(slice_dir, output_dir, language)` | 切片目录、`zh` | `.list` 路径与逐条文本 |
| `extract_features(dataset, work_dir)` | 校对后的数据集 | 特征目录、日志、失败阶段 |
| `train_voice(dataset, voice_id, params)` | 数据集、音色 ID、固定参数 | GPT/SoVITS 权重路径与训练日志 |
| `synthesize(voice, request, output_path)` | 权重、参考音频/文本、目标文本 | WAV 路径、采样率、时长与日志 |

所有路径必须先解析为绝对路径，并验证处于已配置的引擎目录、项目数据目录或显式授权输入目录内。

## 4. 固定切分参数

第一轮保持用户已验证的参数，不开放给普通用户：

```json
{
  "threshold": -34,
  "min_length": 4000,
  "min_interval": 300,
  "hop_size": 10,
  "max_sil_kept": 500
}
```

## 5. 统一错误

```python
AppError(
    code: str,
    message: str,
    detail: dict | None = None,
    stage: str | None = None,
)
```

首批错误码：

- `ENGINE_CONFIG_MISSING`
- `ENGINE_UNAVAILABLE`
- `GPU_UNAVAILABLE`
- `GPU_BUSY`
- `INVALID_AUDIO`
- `ASR_FAILED`
- `FEATURE_EXTRACTION_FAILED`
- `TRAINING_FAILED`
- `VOICE_WEIGHTS_MISSING`
- `REFERENCE_MISSING`
- `SYNTHESIS_FAILED`
- `OUTPUT_INVALID`

## 6. 数据模型最小字段

### DatasetRecord

`dataset_id`、`display_name`、`source_path`、`slice_dir`、`list_path`、`emotions_path`、`status`、`created_at`。

### VoiceProfile

`voice_id`、`display_name`、`feature_name`、`dataset_id`、`gpt_weight`、`sovits_weight`、`references`、`engine_profile`、`status`、`created_at`。

### EmotionReference

`emotion`、`audio_path`、`prompt_text`、`language`。`emotion` 当前只允许 `neutral/happy/sad`。

### GenerationRecord

`result_id`、`voice_id`、`text`、`emotion`、`speed_factor`、`fragment_interval`、`output_path`、`status`、`created_at`。

## 7. 测试与真实证据

- LHY 可用测试替身验证命令、状态、错误和 JSON，但不得把替身结果写成 GPU 成功。
- CXY/LJQ 提供的真实日志和 WAV 进入验收证据目录，不直接提交未经授权音频。
- 同一 adapter 接口必须能读取不同的 40/50 系配置，而不修改 services 与 UI。

