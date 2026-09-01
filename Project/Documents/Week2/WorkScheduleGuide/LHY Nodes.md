# LHY Week 2 节点：Python 业务与集成

## LHY-N1：实现 audio_service

**目标**  
实现上传、校验、裁剪、标准化、切分、ASR 和数据集导出。

**输入**

- Week 1 services、schemas 与错误结构。
- CXY-N1 契约。
- LJQ-N1/N2 的参考规则与算法参数。

**工作**

- 实现上传、校验、裁剪和标准化。
- 封装官方静音切分与 ASR。
- 支持人工修正转写。
- 导出 `dataset.list` 与 `dataset.json`。
- 写路径、授权、格式和时长校验及相关测试。

**输出**

- 可调用的 `audio_service.py`。
- 一份真实数据集样例。
- 非 GPU 单测和 GPU 集成记录。

**三个指标**

- **哪些人的工作会影响我？** Week 1 服务骨架是硬依赖；CXY-N1、LJQ-N1/N2 是软依赖，收到后对齐字段和参数。
- **我需要交付什么内容？** 完整音频服务、真实数据集样例、测试与函数说明。
- **谁需要等待我完成该工作？** WGX-N1 等真实返回结构；LHY-N2/LHY-N4 等参考片段；CXY-N3 等样例抽检。

**完成判定**

- `.list` 四字段正确且 `dataset.json` 可追溯。
- ASR 失败时允许人工文本，不返回假转写。

**AI 参考提示词**

```text
请根据以下contract-v1.0和算法参数实现audio_service：
<粘贴契约>
<粘贴LJQ参数>

功能：上传、校验、裁剪、标准化、官方切分、ASR、人工修正、导出dataset.list/json。
要求：AppError、路径限制、授权字段、切片duration、非GPU单测、GPU测试独立标记。
ASR失败可以空文本等待人工修正，但不能生成假转写。
禁止HTTP API、数据库和自研VAD宣称。
```

---

## LHY-N2：实现真实试听与音色保存

**目标**  
分离“生成试听”和“保存音色”，确保保存前已有真实试听。

**输入**

- 一条合法、已授权的 3–10 秒短参考及准确参考文本，可由 CXY 资产直接提供。
- LHY-N1 的合法参考片段仅用于接入完整音频页主流程，不是开始本节点的硬依赖。
- CXY-N1 音色契约。
- LJQ-N1/N2 的参考规则和试听参数。
- Week 1 `tts_service` 骨架。

**工作**

- 实现 `generate_preview`，只写临时 `preview.wav`。
- 实现 `save_voice`，保存 `reference.wav`、`preview.wav` 和 `voice.json`。
- 校验 3–10 秒、授权、参考文本和试听成功状态。
- 使用 `tts_service` 进程内调用官方 `TTS.py`。

**输出**

- `voice_service` 试听与保存功能。
- 至少一条真实 `preview.wav`。
- 给 WGX/LJQ 的函数说明。

**三个指标**

- **哪些人的工作会影响我？** 合法短参考与 Week 1 `tts_service` 骨架是启动依赖；契约 v1.0 在首次正式保存前是硬依赖；LHY-N1 只影响完整跨页接入，LJQ 参数是软依赖。
- **我需要交付什么内容？** `generate_preview`、`save_voice`、真实试听和接口说明。
- **谁需要等待我完成该工作？** LHY-N3 等保存目录；WGX-N2 等事件返回；LJQ-N3 等项目内试听入口。LHY-N1 不等待本节点，可并行推进音频处理。

**完成判定**

- 试听 WAV 来自本机本次推理。
- 未调用 `save_voice` 前不会生成正式音色目录。

**AI 参考提示词**

```text
请实现voice_service的generate_preview与save_voice。

输入：<contract-v1.0 voice部分>、<LJQ试听参数>。

规则：
- generate_preview只生成临时preview.wav；
- save_voice才复制reference/preview并写voice.json；
- 参考时长3至10秒、authorized=true、文本非空；
- 试听成功后才允许保存；
- 进程内调用tts_service/TTS.py，GPU串行；
- AppError包装OOM、路径、语言和模型错误。

禁止保存前建档、Mock WAV和修改模型核心。
```

---

## LHY-N3：原子索引与重启恢复

**目标**  
安全维护 `voices.json`，并在应用重启后恢复音色。

**输入**

- LHY-N2 单音色目录。
- CXY-N1 的 `voice.json`/`voices.json` schema。

**工作**

- 实现 `list_voices`、`get_voice`、索引更新和重建。
- 临时文件写入后原子替换 `voices.json`。
- 启动时校验索引，损坏时从 `data/voices/` 重建。
- 文件缺失或校验失败的音色不进入可用列表。

**输出**

- 原子索引实现。
- 真实 `voices.json` 样例。
- 重启恢复测试和日志。

**三个指标**

- **哪些人的工作会影响我？** LHY-N2 是硬依赖；CXY-N1 是软依赖，保存前必须完成 schema 对齐。
- **我需要交付什么内容？** 索引、重建、样例和重启验证。
- **谁需要等待我完成该工作？** LHY-N4 等列表能力；CXY-N3/N4 等档案与恢复证据。

**完成判定**

- 索引与目录一致。
- 重启后音色数量与内容保持一致。
- 损坏恢复不清空用户数据。

**AI 参考提示词**

```text
请实现音色索引与重启恢复。

Schema：<粘贴voice.json和voices.json>

要求：
- list_voices/get_voice/update/rebuild；
- 临时文件写入后原子替换；
- 启动校验，损坏从data/voices重建；
- 无效音色跳过并记录日志；
- pytest覆盖写入、损坏和重建。

禁止删除整个数据目录或实现history.json。
```

---

## LHY-N4：页面事件集成

**目标**  
将音频页和音色页接入真实 services，形成可演示应用。

**输入**

- LHY-N1/N2/N3。
- WGX-N3 的页面、事件和 State。

**工作**

- 绑定音频与音色页面事件。
- GPU重任务使用 Gradio queue，并禁止重复提交。
- 环境状态显示真实音色数量。
- 合成页和结果页保持空壳。
- 输出启动说明、绑定表和日志。

**输出**

- Week 2 集成版 `app.py`。
- UI事件到 service 函数的绑定表。
- 联调入口和启动日志。

**三个指标**

- **哪些人的工作会影响我？** LHY-N1/N2/N3 和 WGX-N3 都是硬依赖。
- **我需要交付什么内容？** 一键启动集成版、绑定表、启动说明和日志。
- **谁需要等待我完成该工作？** WGX-N4 等浏览器联调；CXY-N4 等阶段预演。

**完成判定**

- 一个命令启动，音频和音色主流程能运行。
- 不启动第二个服务，不绑定假音频。

**AI 参考提示词**

```text
请集成Week 2单体Gradio，将audio_page和voice_page绑定到services。

输入：<ui模块>、<services>、<当前app.py>。

要求：
- 绑定上传、裁剪、切分、ASR、选片、试听、保存和列表；
- queue与GPU串行；
- gr.State跨页；
- 环境状态显示真实音色数；
- 合成页/结果页保持空壳；
- 展示真实AppError。

输出修改步骤、事件绑定表、启动和冒烟清单。
```
