# LHY 任务单：后端、数据与引擎集成

> 角色定位：后端领域负责人。可以在没有 GPU 的情况下独立开工；不等待 CXY 完成全部模型任务。

## 当前任务队列

## 现在立刻做什么

先检查当前 `Project` 骨架和 Python 版本，完成 schemas、`AppError`、任务状态机和 adapter 的测试。不要等待 CXY 的 WAV，也不要直接把 GPT-SoVITS 代码复制进项目。

### LHY-W1-01：schemas 与错误模型（P0，可立即开始）

- **工作**：实现 `models/schemas.py`，包含 `DatasetRecord`、`VoiceProfile`、`EmotionReference`、`GenerationRecord`、`TaskRecord` 和 `AppError`。
- **产物**：代码、序列化/校验测试和字段说明。
- **通过**：模块可导入；非法情绪、路径、状态流转会被拒绝；不创建假成功数据。
- **下游**：LHY-W1-02、WGX-W1-02。

**可直接交给 AI 的提示词**

```text
你是本项目后端开发助手。请先阅读：
1. Project/Documents/当前执行计划 v3.md
2. Project/Documents/契约/engine-adapter-v0.1.md
3. Project/Documents/成员任务/LHY.md
4. Project/models/schemas.py（如果已有，先检查再修改）

任务：实现或修正 DatasetRecord、VoiceProfile、EmotionReference、GenerationRecord、TaskRecord、EngineConfig、EngineStatus 和 AppError。

要求：
- 兼容 Python 3.9；不要使用 3.10 以上专属类型写法；
- 情绪只允许 neutral/happy/sad；
- 任务状态必须能区分 pending/running/succeeded/failed/cancelled；
- 路径、文本长度、语速和情绪重复需要校验；
- 不创建假音频、假权重或假成功记录；
- 保持现有目录，不引入数据库和 Web API。

请输出：修改后的文件、字段说明、测试命令、测试结果和仍待确认的字段。先审查现有代码，再做最小修改。
```

### LHY-W1-02：Engine Adapter 骨架（P0）

- **输入**：`契约/engine-adapter-v0.1.md`；CXY 的真实命令可以后补。
- **工作**：建立 `adapters/base.py`、`adapters/gpt_sovits_adapter.py`、`config/engine.example.json`；实现配置读取和 `probe_environment`。
- **要求**：路径来自配置；使用参数数组启动子进程；捕获 stdout/stderr；关闭并行；一次只允许一个 GPU 任务。
- **产物**：代码、配置样例、探测测试、错误映射。
- **通过**：测试替身下通过；在 CXY/LJQ 配置间切换不需要修改源码。
- **下游**：CXY-W1-03、LJQ-W1-02、WGX-W1-02。

**可直接交给 AI 的提示词**

```text
请阅读当前执行计划、engine-adapter-v0.1.md、Project/adapters 和 Project/services。

任务：实现可配置的 GPTSoVITSAdapter，先完成 probe_environment，不要假装完成切分、训练或合成。

要求：
1. 配置从 config/engine.local.json 读取，仓库只保留 engine.example.json；
2. 不出现任何个人绝对路径；
3. 子进程使用参数数组，捕获 stdout/stderr、退出码和超时；
4. 统一返回 EngineStatus 或 AppError；
5. 强制 max_gpu_jobs=1、parallel_infer=false；
6. 能在 40 系和 50 系只换配置、不改业务源码；
7. 先写测试替身，再写真实探测。

请输出：修改文件、接口示例、测试命令、失败场景和未实现边界。不要复制上游源码，不要引入 FastAPI、数据库或并发队列。
```

### LHY-W1-03：services 与任务状态机（P0）

- **工作**：建立四个 service 骨架和 `task_service`；实现合法状态流转、日志路径、全局 GPU 锁和明确的未实现错误。
- **产物**：`audio_service.py`、`voice_service.py`、`tts_service.py`、`history_service.py`、`task_service.py` 及测试。
- **通过**：模块可导入；未完成动作返回 `AppError`，不返回固定成功；并发第二个 GPU 任务返回 `GPU_BUSY`。
- **下游**：WGX 页面事件、Week 2 业务实现。

**可直接交给 AI 的提示词**

```text
请根据契约实现 Project/services 的最小骨架和 task_service。

必须有：audio_service、voice_service、tts_service、history_service、task_service。
任务状态：pending → running → succeeded/failed；可安全取消时允许 cancelled。

要求：
- 尚未接入真实模型的函数必须抛出明确 AppError("NOT_IMPLEMENTED", ...)，不能返回成功；
- GPU 任务使用全局锁，第二个任务返回 GPU_BUSY；
- 日志路径可追踪，JSON 写入预留原子替换；
- 测试不得生成或提交假 WAV、假权重；
- 兼容 Python 3.9。

请先检查已有代码，再给出最小改动、测试和输出示例。
```

### LHY-W1-04：唯一入口集成

- **输入**：WGX-W1-01 四页模块。
- **工作**：将 UI 与 service 骨架接入 `app.py`，保留一个启动入口。
- **通过**：应用可启动，环境探测显示真实/未配置状态；不存在第二个 Web 服务。

**可直接交给 AI 的提示词**

```text
请检查 Project/app.py 和 Project/ui，完成唯一入口集成。

目标：一个 app.py 启动 Gradio；四页能显示；侧栏底部显示 probe_environment 的真实状态；业务未接入时显示“尚未接入”，不返回假成功。

请先运行静态导入/构建检查，再最小修改代码。兼容 Python 3.9 和项目 requirements.txt；不要把整合包路径写进源码，不要增加第二个 Web 服务。
输出修改文件、启动命令、浏览器检查清单和已知限制。
```

## Week 2–4 领导任务

- Week 2：数据集管理、切分/ASR/训练编排、原子索引、权重归档和恢复。
- Week 3：TTS 串行服务、历史、复用、删除、失败隔离和重启恢复。
- Week 4：测试、错误加固、日志、安装与配置说明。

## 可使用测试替身的范围

可以模拟退出码、日志、超时和输出文件校验；不能把模拟 WAV、模拟权重或模拟 GPU 状态作为验收证据。
