# 首次准备与故障定位

完整目录包：直接运行项目内 `setup/EnvironmentSetup/start.bat`。无需安装全局 Python，不修改系统 PATH，不自动升级模型运行时。

源码包：先安装官方 Windows x64 Python 3.13（含 pip），从项目根运行 `python scripts/assemble_ui_runtime.py`，联网按 `config/ui-runtime.lock.json`、`config/ui-requirements.lock` 下载并校验，生成 `runtimes/ui`。网络中断后可重新运行组装脚本；已完整存在的 UI 目录不会被覆盖。模型解释器保持为单独的 `engines/verified-v2pro/runtime/python.exe`。

| 失败项 | 准备动作 |
|---|---|
| ui_runtime/ui_imports | 按锁定清单组装 UI Python；检查对应报告错误和 import 来源 |
| engine_python/model_* | 恢复固定 v2Pro nvidia50 组合的独立模型运行时，不使用 UI Python 安装/运行模型 |
| cuda_tensor/gpu_scope | 从 https://www.nvidia.com/Download/index.aspx 安装对应 50 系 Windows 驱动并重启；先核对运行时 Torch CUDA 版本，无须无条件安装 CUDA Toolkit |
| gpu_memory | 关闭自己不需要的 GPU 应用后重试；不结束未知进程，不把卡名或显存数量当作成功保证 |
| resource:* | 在本地报告 actual 中查目标路径、source、bytes、sha256；按源仓库/模型站准备，执行 `Get-FileHash -Algorithm SHA256 "文件"` 与清单比较 |
| resources | 恢复项目 `config/environment-resources.json`；缺清单不能宣布完整 |
| ffmpeg/ffprobe | 恢复本机验证的模型 runtime 内工具，来源 https://ffmpeg.org/download.html；不接受 PATH 中其他工具代替随包完整性 |
| voice_inputs | 在 UI 中训练或注册带有效权重、PCM 参考 WAV 和文本的音色；未配置音色只影响推理准备 |
| permission_* | 将项目放到当前用户可写目录；检查输出、日志、缓存、临时目录或配置目录是否为越界链接 |
| ui_port/port | 检查占用者，关闭自己拥有的实例或选择其他端口；诊断不杀进程 |
| timeout | 查看本地报告 command、exit_code=-2 和耗时；处理导入/磁盘问题后重试，可用 --timeout 调整导入与 GPU 探测上限 |

预览默认不写配置，只生成诊断报告和必要目录及短生命周期写权限探针。`--write-project-config` 先验证候选、保留原 profile/未知字段，再以 data/migrations 唯一事务备份和原子替换；故障恢复原文件。备份校验或并发编辑冲突会阻止回滚覆盖。

资源源码参考 https://github.com/RVC-Boss/GPT-SoVITS ，模型参考 https://huggingface.co/lj1995/GPT-SoVITS 与 https://modelscope.cn/models/iic 。不同版本下载内容可能变化，必须与本项目清单匹配；不匹配时保留 FAIL 并核对固定版本来源，不直接改哈希放行。许可与完整包组装、第二台机器验收属于 S7。
