# 基于语音克隆及合成的音色共享平台

版本：v1.0；日期：2026-09-07；状态：草案，随真实证据与接口联调持续修订。

# 项目背景

本项目基于 GPT-SoVITS 的语音克隆与文本转语音能力，构建面向学生项目的本地音色共享平台。产品重点是形成一条可交付、可验证、可扩展的语音工作流，而不是复制第三方整合包。

# 项目概述

平台支持授权音频导入、切片、中文识别、人工校对、情绪标注、特征提取、音色训练、文本合成和历史结果管理。项目采用单入口 Project/app.py、Python services + models、Gradio 单体应用和本地 JSON 索引。

# 产品定位

这是一个面向授权音频处理、音色仓库管理和文本合成的语音克隆及合成平台。MVP 以真实流程可跑通为目标，第三方 GPT-SoVITS 仅作为外部运行时，不属于本项目自研成果。

# 范围

MVP 包含音频导入与安全路径校验、固定参数切片、中文 ASR、人工校对与情绪标注、特征提取、音色训练任务管理、文本合成、历史记录与结果管理、环境探测与配置切换。暂不纳入数字水印、高级敏感词体系、跨语言情感迁移完整验证、数据库、消息队列和云端部署。

# 用户角色

| 角色 | 说明 |
|---|---|
| 项目使用者 | 上传授权音频、校对文本、发起训练和合成、管理结果 |
| 开发者 | 调试接口、查看环境状态、排查任务和日志 |
| 观察者 | 查看环境状态、历史记录和任务进展 |

# 核心原则

- 单入口为 Project/app.py，使用 Gradio Blocks。
- 不引入 FastAPI、数据库、Redis、队列或云服务。
- UI、业务服务与 GPT-SoVITS 运行时分离，外部命令通过配置和参数数组调用。
- GPU 任务全局串行，禁止并行推理；第二个任务返回 GPU_BUSY。
- 测试替身、真实证据和生产结果严格区分，不用假音频或假成功替代真实结果。
- 本机绝对路径、权重和真实音频不得提交 Git。

# 功能需求

### F001 环境探测与配置

**描述**：读取本机引擎配置并返回 Python、Torch、CUDA、GPU、FFmpeg 和入口状态；配置错误、环境缺失和探测失败映射为统一错误。

**优先级**：MVP

| 子功能 | 描述 | 数据来源 |
|---|---|---|
| 配置读取 | 读取 engine.local.json；仓库只保留 engine.example.json | 本地配置文件 |
| 运行时探测 | 通过参数数组启动解释器并采集版本、CUDA 和 GPU 状态 | GPT-SoVITS 环境 |
| 错误映射 | 将缺失配置、引擎不可用和 GPU 不可用转换为统一错误 | 探测结果 |

### F002 音频导入与切片

**描述**：导入授权音频，完成安全路径校验和固定参数切片，生成可供识别和人工校对的数据集。

**优先级**：MVP

| 子功能 | 描述 | 数据来源 |
|---|---|---|
| 授权音频导入 | 接收音频文件并确认路径在允许目录内 | 用户上传 |
| 固定参数切片 | 使用 threshold=-34、min_length=4000、min_interval=300、hop_size=10、max_sil_kept=500 | 切片服务 |
| 数据集建档 | 保存 dataset_id、源路径、切片目录和状态 | JSON 索引 |

### F003 ASR与人工校对

**描述**：对切片目录执行中文识别，输出 .list 和逐条文本，并支持人工修改文本与标记情绪。

**优先级**：MVP

| 子功能 | 描述 | 数据来源 |
|---|---|---|
| 中文识别 | 对切片音频调用中文 ASR 并输出初稿 | ASR 引擎 |
| 文本校对 | 用户查看并修改每个片段文本 | 用户输入 |
| 情绪标注 | 为片段标记 neutral、happy 或 sad | 用户输入 |

### F004 特征提取

**描述**：对校对后的数据集执行特征提取，保存特征目录、日志和失败阶段。

**优先级**：MVP

| 子功能 | 描述 | 数据来源 |
|---|---|---|
| 特征任务创建 | 校验数据集状态并创建 GPU 任务 | 数据集索引 |
| 特征提取执行 | 调用外部引擎命令并记录 stdout、stderr、退出码和超时 | GPT-SoVITS 环境 |
| 输出校验 | 检查特征目录和必要文件是否存在 | 文件系统 |

### F005 音色训练与权重管理

**描述**：按数据集和音色 ID 组织训练任务，串行执行 GPU 任务，并保存 GPT/SoVITS 权重档案。

**优先级**：MVP

| 子功能 | 描述 | 数据来源 |
|---|---|---|
| 训练任务管理 | 支持 pending、running、succeeded、failed、cancelled 状态 | 任务状态机 |
| GPU 串行控制 | 已有任务运行时拒绝第二个任务并返回 GPU_BUSY | 全局锁 |
| 音色档案保存 | 保存 voice_id、数据集、权重路径、引擎配置和参考音频 | JSON 索引 |

### F006 文本合成

**描述**：选择音色、输入文本和情绪参数，调用 GPT-SoVITS 适配器生成 WAV，并校验输出有效性。

**优先级**：MVP

| 子功能 | 描述 | 数据来源 |
|---|---|---|
| 合成参数输入 | 输入音色、文本、情绪、语速和片段间隔 | 用户输入 |
| 外部引擎调用 | 使用配置后的 Python 解释器、权重和参考音频调用 API | GPT-SoVITS 适配器 |
| WAV 输出校验 | 检查输出路径和 WAV 文件有效性，失败时隔离结果 | 文件系统 |

### F007 历史记录与结果管理

**描述**：记录成功任务和结果，支持播放、下载、复用与删除；失败任务不能伪装成成功记录。

**优先级**：MVP

| 子功能 | 描述 | 数据来源 |
|---|---|---|
| 历史查询 | 查询生成结果和任务记录 | history.json、tasks.json |
| 结果复用 | 复用既有音色和合成参数发起新任务 | 历史记录 |
| 结果删除 | 删除结果文件和对应索引记录 | 用户操作 |

### F008 统一状态与错误处理

**描述**：统一管理任务状态、错误代码、日志和阶段信息，保证失败、取消、超时和重启恢复可观察。

**优先级**：MVP

| 子功能 | 描述 | 数据来源 |
|---|---|---|
| 状态转换 | 限制任务只能按合法状态迁移 | TaskStatus |
| 统一错误 | 使用 ENGINE_CONFIG_MISSING、GPU_BUSY、ASR_FAILED 等错误码 | AppError |
| 日志与恢复 | 保存阶段日志，检查输出并支持 JSON 索引恢复 | data/logs、data/index |

# 用户流程

1. 上传授权音频。
2. 自动切片并生成可校对片段。
3. 通过 ASR 生成初稿文本。
4. 人工校对文本并标记情绪。
5. 提取特征并进入训练任务。
6. 完成音色保存与权重管理。
7. 输入文本和情绪参数，生成语音。
8. 在历史页查看播放、下载和复用。

# 数据需求

| 实体 | 字段 |
|---|---|
| DatasetRecord | dataset_id、display_name、source_path、slice_dir、list_path、emotions_path、status、created_at |
| VoiceProfile | voice_id、display_name、feature_name、dataset_id、gpt_weight、sovits_weight、references、engine_profile、status、created_at |
| EmotionReference | emotion、audio_path、prompt_text、language；emotion 取 neutral/happy/sad |
| GenerationRecord | result_id、voice_id、text、emotion、speed_factor、fragment_interval、output_path、status、created_at |
| TaskRecord | task_id、kind、status、stage、message、log_path、created_at、updated_at |
| EngineStatus | configured、available、python_version、torch_version、cuda_version、gpu_name、message |

# 状态与错误

统一状态为 PENDING、RUNNING、SUCCEEDED、FAILED、CANCELLED。统一错误包括 ENGINE_CONFIG_MISSING、ENGINE_UNAVAILABLE、GPU_UNAVAILABLE、GPU_BUSY、INVALID_AUDIO、ASR_FAILED、FEATURE_EXTRACTION_FAILED、TRAINING_FAILED、VOICE_WEIGHTS_MISSING、REFERENCE_MISSING、SYNTHESIS_FAILED、OUTPUT_INVALID。

# 非功能需求

- Python 版本兼容 3.9。
- 不使用个人绝对路径，不提交权重、真实音频和本机运行时环境。
- 页面与业务逻辑分离，测试替身、真实证据和生产结果严格区分。
- GPU 任务串行，子进程必须使用参数数组，并捕获输出、退出码和超时。
- 40 系仅作兼容观察，不作为 MVP 阻断条件；50 系完整训练和推理闭环是 MVP 目标。

# 接口需求

系统通过 Python 服务函数和 GPTSoVITSAdapter 与外部运行时交互。适配器负责环境探测、构造 api.py 参数数组、启动子进程、轮询本地服务并保存 WAV；当前真实切分、训练和合成命令仍需由真实环境证据补齐。

# 总体设计约束

- 唯一入口为 Project/app.py，使用 Gradio Blocks。
- 不引入 Vue、React、FastAPI、数据库、Redis、Celery 或云服务。
- GPT-SoVITS 是外部依赖，业务源码不写死其安装目录。
- 只有真实日志、音频、权重和截图证据才能支持“已完成”结论。

# 需求分级

| 等级 | 内容 |
|---|---|
| MVP | F001-F008 的本地可验证流程、状态、错误、索引和 UI 骨架 |
| 后续 | 数字水印、高级敏感词、跨语言情感迁移完整验证、云端部署 |

