# Week 2 50 系阶段验收（开发推进中）

| 节点 | 产物 | 结论 | 下一步 |
|---|---|---|---|
| CXY-W2-01 | `CXY-50series-parameter-freeze.md`、Citlali 配置 | 通过 | 以 Citlali 为正式音色 |
| CXY-W2-02 | `logs/Citlali`、Citlali GPT/SoVITS 权重 | 通过（用户真实训练） | 保留训练日志和文件清单 |
| CXY-W2-03 | `citlali_adapter_w2.wav/.log`、正式 VoiceProfile、用户听感确认 | 通过 | 进入后端/UI 档案接线 |
| LHY-W2-01 | `services/dataset_service.py`、测试 | 通过 | 接 UI 数据集选择 |
| LHY-W2-02 | `services/pipeline_service.py`、测试 | 通过（骨架） | 接冻结命令与真实输出校验 |
| LHY-W2-03 | 训练编排、权重归档、VoiceProfile 写入及风险修复 | 工程测试通过 | 接入冻结的真实 stage command |
| LHY-W2-04 | 任务持久化、重启恢复、GPU 串行锁及回归测试 | 工程测试通过 | 接 UI 任务状态 |
| WGX-W2-01 | 音频导入、数据集、校对表、标签保存、service 提交 | 通过（UI 与数据保存） | 后端接入切分/ASR |
| WGX-W2-02 | 训练提交、任务/阶段日志、GPU_BUSY、Citlali 档案 | 通过（UI 边界） | 后端提供真实训练配置 |
| WGX-W2-03 | 五个共享 State、四页导航、桌面/窄窗口/键盘/刷新截图 | 通过 | 真实模型接通后业务回归 |
| WGX-W2-04 | 构建/导入/编译、服务边界审计和回归测试 | 通过 | 进入主线后端联调 |
| LJQ-W2-PAUSE | 暂停，无 40 系操作 | 通过 | 无 |

2026-09-08 更新：配置 Citlali 真实权重路径后，unittest 36/36 通过，无跳过；compileall 和核心模块导入通过。详见 `LHY-week2-risk-fixes.md`。测试使用临时副本验证编排与归档，不代表重新执行了模型训练；用户已确认整合包真实训练、生成和听感正常。

同日 WGX 代执行后新增 UI/数据保存/结果路径测试，最新验证见 `WGX-week2-browser-smoke.md`。真实数据处理与训练尚不能从项目页面一键跑通，Week 2 整体业务闭环仍待后端接线；这不影响 WGX 按明确未接入提示的节点验收通过。
