# LHY Week 2 任务单：数据档案与训练编排

> 目标：在不运行整合包 GPU 训练的前提下，完成可测试的数据、任务、日志和权重归档后端。

## LHY-W2-01：数据集 JSON 档案与原子索引（P0）

- 输入：`DatasetRecord`、`data/index/datasets.json`、Week 1 输出路径约定。
- 产物：索引读写 service、原子替换、损坏文件处理、测试。
- 通过：写入中断不破坏旧索引；路径序列化稳定；不存在记录时返回空集合或明确错误。

**AI 提示词**

```text
先阅读当前计划、契约、LHY Week 2 任务单、models/schemas.py 和现有 history_service。
实现 DatasetRecord JSON 索引：list/get/upsert/delete，使用临时文件加替换保证原子写入。
路径使用 Pydantic 序列化；处理不存在、JSON 损坏和并发写入错误；不得写入个人路径或假数据。
补充 unittest，运行全部测试并报告文件和结果。
```

## LHY-W2-02：数据处理阶段编排（P0）

- 输入：CXY-W2-01 冻结命令、GPTSoVITSAdapter、TaskRecord。
- 工作：建立 validating/slicing/asr/feature_text/feature_hubert/feature_semantic 阶段编排；每阶段记录命令、日志、退出码和输出校验。
- 通过：参数数组、超时、失败阶段明确；第二个 GPU 任务返回 GPU_BUSY；不返回假成功。

**AI 提示词**

```text
请在现有 adapter 和 task_service 上实现数据处理编排器，不复制 GPT-SoVITS 源码。
每个阶段接收配置路径和输入输出路径，使用 subprocess 参数数组，捕获 stdout/stderr、退出码和超时，更新 TaskRecord stage/status/log_path。
先用测试替身覆盖成功、非零退出、超时、输出缺失和 GPU_BUSY；真实命令只读取配置，不写死路径。
```

## LHY-W2-03：训练任务、权重归档和恢复（P0）

- 输入：数据集记录、冻结训练配置、adapter 命令边界。
- 产物：训练编排、权重文件校验、VoiceProfile 写入、失败隔离和重启恢复测试。
- 通过：只有真实存在且可识别的 `.ckpt/.pth` 才能归档；失败不能创建 succeeded 记录。

**AI 提示词**

```text
实现 train_voice 任务编排和权重归档接口。SoVITS/GPT 子进程必须串行、可超时、可记录日志；训练结束后检查权重路径、文件大小和修改时间，再写 VoiceProfile。
测试替身只能生成临时文本或状态，不得提交假 WAV/假权重；覆盖训练失败、权重缺失、恢复已有任务和重复 GPU 任务。
```

## LHY-W2-04：Week 2 后端交付检查（P0）

- 运行导入、unittest、compileall；输出字段说明和未实现边界。
- 通过：所有服务可导入；真实动作未接入时返回 NOT_IMPLEMENTED；索引和任务日志可追踪。
