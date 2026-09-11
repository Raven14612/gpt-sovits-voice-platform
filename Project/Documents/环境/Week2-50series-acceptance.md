# Week 2 50 系阶段验收（当前状态）

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

## 2026-09-11 复核

- `python -m unittest discover -v`：64 项通过，11 项因真实音频/权重 fixture 不在当前测试环境而跳过；无失败。
- 项目代码可编译，训练准备、任务持久化、GPU 串行锁、音频处理和 UI 边界均已具备。
- Week 2 尚未整体完成：`services/voice_service.py` 仍要求显式 GPT/SoVITS stage command，`services/tts_service.py` 仍返回 `NOT_IMPLEMENTED`。因此项目页面尚不能完成“训练 → 权重归档 → 项目内合成 → WAV 校验”的真实闭环。
- 外部 50 系整合包的真实训练、生成和听感确认已有记录，但不能替代项目内端到端验证。

### 剩余阻塞项

1. 在 `config/engine.local.json` 中登记经验证的训练 stage command 和输出路径规则，并由项目任务编排真实调用。
2. 实现项目级合成 service/adapter 调用整合包 API，生成并校验全新 WAV。
3. 以新生成 WAV 完成 VoiceProfile 归档、历史记录写入和页面回归。
4. 完成上述闭环后再将本文件结论改为“Week 2 完成”，并开始 Week 3 计划。

## 2026-09-11 真实闭环更新

训练命令、动态 checkpoint 检测、项目权重归档和归档后真实合成均已通过。真实回归为 70/70 通过、无跳过；详细证据见 `Week2-training-archive-closure-20260911.md`。

当前技术阻塞项已经清零。用户于 2026-09-11 确认 `data/outputs/tts-5701909348ae48ec86aba29be7df133f.wav` 听感完全正常。

## 最终结论

**Week 2 全部完成，通过验收。** 数据、真实训练、新 checkpoint 检测、项目权重归档、音色档案、项目合成、WAV 校验和人工听感均已闭环。后续工作按 `Documents/Week3安排.md` 执行。
