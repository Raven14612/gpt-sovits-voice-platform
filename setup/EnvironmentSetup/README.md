# 环境诊断与配置

MVP 版本，仅提供给经过验证的 NVIDIA RTX 50 系 Windows 电脑使用。

从项目根双击 `setup/EnvironmentSetup/start.bat`，或在终端执行它。入口固定使用 `runtimes/ui/python.exe`，无需 PATH 中已有 Python。源码包缺运行时时按 [PREPARE.md](PREPARE.md) 组装。

```powershell
.\setup\EnvironmentSetup\start.bat
# 修改诊断端口、保存指定报告；不会修改应用的默认端口。
.\setup\EnvironmentSetup\start.bat --port 9988 --ui-port 17860 --report-path data\environment.json
# 跳过 GPU 或大文件哈希时，对应项标为 NOT_VERIFIED。
.\setup\EnvironmentSetup\start.bat --no-gpu --skip-hashes
# 显式提出路径候选，先预览。所有相对路径均以项目根为准。
.\setup\EnvironmentSetup\start.bat --engine-root engines/verified-v2pro --engine-python engines/verified-v2pro/runtime/python.exe
# 核对预览后，以同样参数追加 --write-project-config 写入。
.\setup\EnvironmentSetup\start.bat --write-project-config
# 使用写入报告中的事务目录回滚；文件有后续修改时拒绝覆盖。
.\setup\EnvironmentSetup\start.bat --rollback data/migrations/事务ID
```

默认报告为 `setup/EnvironmentSetup/reports/environment-report.json`，同目录自动生成 `environment-report-sanitized.json`。本地报告含实际路径、命令、导入来源与配置候选；分享时只选择 sanitized 文件。公开报告采用字段白名单，移除所有原始子进程输出、配置内容和路径。

| 层级 | READY 的含义 |
|---|---|
| basic | Windows、项目、双解释器路径、UI 依赖及 Gradio 构建、写权限和 UI 端口可用 |
| inference | 基础条件、模型推理依赖、CUDA 小张量、显存提示、工具/资源哈希、可用音色权重和参考输入、推理端口检查通过 |
| training | 基础条件、训练依赖、CUDA 小张量、特征/训练入口和 ASR/预训练资源哈希检查通过 |
| actual_validation | 此诊断不训练、不合成，始终 NOT_VERIFIED；真实结果单独验收 |

READY 是本次准备检查通过，不代表任意输入/参数均可运行。显存使用 4 GiB 可用量作为提醒线，不作为训练成功保证。资源清单 `config/environment-resources.json` 固定了本机已验证 v2Pro 组合的相对目标、来源、大小和 SHA-256；哈希是本地基线，不是分发许可证明。

向导不执行真实训练或合成。交付验收步骤见[开发与交付](../../Documents/开发与交付.md)。

普通 `start.bat` 在启动 UI 前生成 `data/logs/startup-environment.json`：检查依赖及文件存在性，不执行 CUDA 运算和全量哈希。UI 基础依赖失败会阻止启动；模型缺项在报告中提示，可进入 UI 准备数据。`start.bat --diagnose` 执行完整诊断但不启动 UI，`start.bat --check` 仅作路径/解释器检查。

测试入口：`runtimes\ui\python.exe -m unittest tests.test_s5_environment -v`。基础诊断器只依赖标准库及两个标准库路径/事务模块；Gradio、Pydantic、Torch 均由相应子进程导入。

独立真实合成冒烟（会生成新 WAV，与诊断不同）：

```powershell
runtimes\ui\python.exe scripts\environment_smoke.py --voice "你的音色ID" --port 9988 --report data\environment-synthesis.json
```

该命令使用项目 service、真实权重、新结果 ID 和历史索引；报告记录 WAV 校验与任务证据。诊断报告仍不自动变成实际验证通过，新音频听测需单独确认。
