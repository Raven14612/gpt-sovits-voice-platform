# Week 2 50 系阶段验收（开发推进中）

| 节点 | 产物 | 结论 | 下一步 |
|---|---|---|---|
| CXY-W2-01 | `CXY-50series-parameter-freeze.md` | 通过 | 可复现训练闭环 |
| CXY-W2-02 | 已有 Week 1 训练权重，未重跑新实验 | 待执行 | 单独执行新训练并保存日志 |
| CXY-W2-03 | Week 1 adapter 真实 WAV/日志 | 部分通过 | 使用 W2 新权重再回归 |
| LHY-W2-01 | `services/dataset_service.py`、测试 | 通过 | 接 UI 数据集选择 |
| LHY-W2-02 | `services/pipeline_service.py`、测试 | 通过（骨架） | 接冻结命令与真实输出校验 |
| LHY-W2-03 | 训练/权重归档 service 尚未接入 | 待执行 | 实现训练编排和 VoiceProfile 写入 |
| WGX-W2-01/02 | 音频页/训练页状态文案和阶段说明 | 部分通过 | 接真实 DatasetRecord/TaskRecord |
| WGX-W2-03 | `WGX-week2-browser-smoke.md` | 部分通过 | 窄窗口/键盘/刷新截图 |
| LJQ-W2-PAUSE | 暂停，无 40 系操作 | 通过 | 无 |

测试：unittest 9 项通过；compileall 通过。真实训练和模型验收不得由测试替身代替。
