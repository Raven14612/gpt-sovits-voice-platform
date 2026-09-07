# CXY Week 2 任务单：50 系算法与验收

> 目标：冻结 50 系可复现训练链路，并把真实训练结果交给 LHY/WGX 接入。40 系不属于本周范围。

## CXY-W2-01：冻结 50 系数据与训练参数（P0）

- 输入：`Documents/环境/CXY-50series-command-io.md`、整合包源码、`logs/Columbina/config.json`、Week 1 证据。
- 工作：确认并记录切分、ASR、1A/1B/1C 特征、SoVITS、GPT、推理的版本、参数、GPU 和并行开关。
- 产物：`Documents/环境/CXY-50series-parameter-freeze.md`，包含脱敏配置快照和待实测项。
- 通过：同一输入和配置可重跑；参数没有依赖页面默认值的模糊描述；个人路径只用占位符。

**可直接交给 AI 的提示词**

```text
先阅读当前执行计划、engine-adapter 契约、Week 1 归档和 CXY Week 2 任务单。
请检查整合包源码、logs/Columbina/config.json 和已有真实日志，整理 50 系参数冻结表。
必须覆盖：切分、ASR、1A 文本、1B HuBERT/SV、1C semantic、SoVITS、GPT、推理。
每项写版本、参数、输入、输出、成功判定、证据路径和待实测字段。不要猜参数，不要写入个人绝对路径，不要修改整合包核心代码。
```

## CXY-W2-02：可复现 50 系训练闭环（P0）

- 输入：冻结参数、已校对 `slicer_opt.list`、12 个切片、RTX 5060 运行时。
- 工作：按固定配置重新执行一次数据格式化/特征/SoVITS/GPT 训练；GPU 全程串行。
- 产物：本机证据目录中的配置、完整日志、训练权重、文件清单；仓库提交脱敏摘要。
- 通过：GPT 与 SoVITS 权重均生成且可加载；日志包含退出结果和 epoch；不得用旧权重冒充本次结果。

**可直接交给 AI 的提示词**

```text
使用已冻结的 50 系参数，在本机 RTX 5060 上执行一次完整训练闭环。
先记录训练前权重目录，再执行特征和训练；所有命令使用参数数组或整合包已确认入口；GPU 任务串行。
保存 stdout/stderr、退出码、耗时、训练后权重文件大小和修改时间。成功必须以新权重文件和可加载检查为准，不得把旧文件或计划文字写成成功。
```

## CXY-W2-03：训练权重回归与音色档案审核（P0）

- 输入：W2-02 新权重、Week 1 参考切片和文本。
- 工作：使用项目 adapter 和整合包 API 各合成至少一条中性文本，检查 WAV；建立 Columbina 音色档案字段映射。
- 产物：真实 WAV、日志、权重配对记录、`VoiceProfile` 字段审核表。
- 通过：两条输出均可播放；GPT/SoVITS 配对明确；输出不是旧文件覆盖。

**可直接交给 AI 的提示词**

```text
请读取新训练权重和项目 adapter 接口，分别通过整合包 API 与项目 adapter 生成回归 WAV。
记录 GPT/SoVITS 文件名、输入文本、参考音频、退出码、WAV 参数和日志路径；比较两条结果是否都有效。
同时审核 VoiceProfile 所需 voice_id、display_name、dataset_id、权重路径、references、engine_profile、status 字段。没有真实文件就标未验证。
```

## CXY-W2-04：Week 2 验收（P0）

- 输入：W2-01 至 W2-03 证据、LHY/WGX 交付物。
- 产物：`Documents/环境/Week2-50series-acceptance.md`、`Decisions.md` 阶段记录。
- 通过：数据集、训练、权重、项目 adapter、UI 状态均有证据；Mock 单独标注。

**可直接交给 AI 的提示词**

```text
根据 Week 2 任务单、契约和所有真实文件，生成验收表：节点、操作、证据、结论、限制、下一步。
没有文件/日志/WAV 的项目标未验证；测试替身只能算工程测试；40 系不列为阻塞项。
```
