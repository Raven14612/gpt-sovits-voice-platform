# WGX Week 2 任务单：音频页与训练页

> 目标：把四页 UI 从静态壳推进到真实 TaskRecord/DatasetRecord 状态展示，不直接调用模型命令。

## 2026-09-08 代执行结果

| 节点 | 状态 | 交付 |
|---|---|---|
| WGX-W2-01 | 通过（UI 与数据保存） | PCM WAV 导入/试听/路径、数据集选择、切分/ASR 提交及未接入提示、识别文本导入、逐片校对和三种人工标签保存 |
| WGX-W2-02 | 通过（UI 边界） | 训练提交、数据校对检查、真实任务状态/阶段日志、GPU_BUSY 禁用、Citlali 正式档案展示 |
| WGX-W2-03 | 通过 | 五个共享 State 接线、四页导航、桌面/390px 窄窗口、长中文、键盘、刷新和失败日志浏览器验证 |
| WGX-W2-04 | 通过 | 全量测试、编译/构建/导入、UI 服务边界审计、截图及交付记录 |

验收记录：`../环境/WGX-week2-browser-smoke.md`。

节点完成不表示项目模型服务已全部接通：音频切分/ASR 仍返回 `NOT_IMPLEMENTED`；训练缺少配置好的 stage command，页面明确提示未接入；合成页模型接线属于 Week 3。整合包已有成功训练、生成和听感结论继续保留。

## WGX-W2-01：音频数据页接入（P0）

- 输入：audio_service、DatasetRecord、TaskRecord、CXY 冻结参数。
- 工作：实现上传/路径显示、切分与 ASR 提交入口、阶段状态、文本校对表和 neutral/happy/sad 人工标签。
- 通过：未接入动作明确显示 NOT_IMPLEMENTED；真实任务显示阶段和日志，不虚构百分比。

**AI 提示词**

```text
先阅读当前计划、契约、WGX Week 2 任务单、ui 现有页面和 models/schemas.py。
完善 audio_page.py：输入音频、显示当前数据集、提交 service 任务、展示 TaskRecord 阶段/消息/日志，并提供文本校对和 neutral/happy/sad 标签字段。
页面不得启动 GPT-SoVITS 命令、读取整合包内部目录或创建假音频；service 未接入时明确提示尚未接入。
```

## WGX-W2-02：训练页与音色档案展示（P0）

- 输入：DatasetRecord、VoiceProfile、训练任务返回结构。
- 工作：数据集选择、训练提交、真实阶段流水、日志摘要、已保存音色列表。
- 通过：训练未完成不显示成功音色；GPU_BUSY 时禁用提交并说明原因；没有总量不显示百分比。

**AI 提示词**

```text
完善 voice_page.py，接收 DatasetRecord/TaskRecord/VoiceProfile。
实现数据集选择、训练按钮、阶段显示、日志摘要和音色档案列表；按钮状态由任务状态决定。
失败显示失败，GPU_BUSY 显示“已有任务正在运行”，不得生成假权重、假进度或假音色卡。
```

## WGX-W2-03：跨页状态与浏览器冒烟（P0）

- 输入：四页 layout、任务状态组件、Gradio 5.50.0。
- 工作：共享 selected_dataset/selected_slice/selected_voice/active_task/current_result；检查窄窗口、长中文、刷新、键盘。
- 产物：`Documents/环境/WGX-week2-browser-smoke.md` 和截图。
- 通过：无白屏、重叠、错误页同时显示；刷新后的空状态准确，不伪造恢复成功。

**AI 提示词**

```text
启动 Project/app.py，逐项检查四页切换、默认页、窄窗口、长中文路径和文本、按钮禁用、等待/失败状态、刷新和键盘操作。
记录操作、预期、实际、截图路径和结论。后端未接入的项目标 UI 结构验证，不写成业务通过，不使用假音频。
```

## WGX-W2-04：前端交付检查（P0）

- 运行导入/构建检查，确认页面只调用 services，不含外部整合包路径和命令。
- 通过：四页可启动，状态组件可复用，空状态清晰。
