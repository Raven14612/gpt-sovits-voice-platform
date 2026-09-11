# LHY Week 3 任务单：合成后端与历史生命周期

## LHY-W3-01：持久推理与合成任务（P0）

- 输入：`tts-history-v1` 契约、现有 adapter、GPU 全局锁。
- 工作：管理整合包 API 启动、健康检查、模型切换、超时和退出；每次合成写 `TaskRecord` 和日志。
- 产物：adapter/service 修改及测试。
- 通过：同一模型连续请求不重复冷启动；切换音色可验证；进程异常不写成功结果；GPU 仍全局串行。

**AI 节点提示词**

```text
阅读 tts-history-v1、adapter、tts_service、task_service 和整合包 API 源码。实现本地持久推理进程生命周期、健康检查、受控模型切换、超时终止与合成 TaskRecord。命令必须是参数数组，端口仅绑定 127.0.0.1，日志写入 data/logs/synthesis。用进程替身覆盖启动失败、超时、退出和模型切换，再做真实 50 系冒烟。
```

## LHY-W3-02：历史 CRUD 与文件一致性（P0）

- 输入：`GenerationRecord`、`history_service`、`data/outputs/`。
- 工作：实现原子 upsert、查询、删除和复用读取；限定输出目录并处理损坏索引。
- 产物：service、测试和字段说明。
- 通过：失败不进入成功列表；删除同时处理索引与对应 WAV；路径逃逸、重复 ID、并发写入和文件缺失有测试。

**AI 节点提示词**

```text
扩展 history_service 为原子 list/get/upsert/delete/reuse 接口。只允许管理 Project/data/outputs 内的文件；删除顺序要保证索引与 WAV 最终一致。覆盖 JSON 损坏、重复 ID、路径逃逸、缺失 WAV、并发写入和删除失败。不要创建假成功 WAV。
```

## LHY-W3-03：失败恢复与后端交付检查（P0）

- 输入：W3-01/W3-02 实现。
- 工作：恢复中断合成任务、清理孤立临时文件、验证日志和索引一致性。
- 产物：恢复逻辑、故障测试、后端验收记录。
- 通过：重启不保留伪 `running`；成功历史均有有效 WAV；测试、compileall 和导入检查通过。

**AI 节点提示词**

```text
对合成任务、推理进程和历史文件执行恢复审计。实现应用启动时将中断任务标失败、识别安全范围内的临时文件，并报告孤立成功记录。补充断电/进程退出/无效 WAV/索引损坏测试，运行完整 unittest、compileall 和核心导入检查，保存结果。
```
