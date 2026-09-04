# Web UI 整合包取证指南

> 适用 CXY（50 系主轨）和 LJQ（40 系兼容轨）。

先不要强行脱离 Web UI 重写命令。先用页面完成真实操作，同时记录页面字段、控制台日志和输出文件；再从整合包启动脚本、`webui.py`、`api.py`、`config.py` 反查调用链。这样得到的是可复核的事实，不是猜测。

## 每次实验必须留下的证据

1. 本机整合包根目录（只保存在本机，不提交仓库）。
2. GPU、显存、驱动、Python、Torch/CUDA、FFmpeg 版本。
3. 页面名称、操作时间、参考音频、参考文本、目标文本。
4. 页面中显示的 GPT 权重路径、SoVITS 权重路径、实验名和输出目录。
5. 新生成文件的完整路径、大小、修改时间。
6. 控制台日志或错误截图。
7. 结论：真实通过、执行失败但原因明确、尚未验证。

不要用旧 WAV 代替本次结果，也不要只截“按钮点击成功”的图。

## 命令和权重路径从哪里查

- `go-webui.bat` / `go-webui.ps1`：Web UI 启动入口。当前整合包使用 `runtime\\python.exe -I webui.py zh_CN`。
- `webui.py`：按钮背后的切分、ASR、特征、训练和推理调用。搜索 `subprocess`、`Popen`、`output_folder`、`GPT_weights`、`SoVITS_weights`。
- `api.py`：可选诊断入口。顶部示例说明 `-dr` 参考音频、`-dt` 参考文本、`-dl` 语言，`-g`/`-s` 可指定 GPT/SoVITS 权重。确认版本一致后再使用，不能默认替代 Web UI。
- `config.py`：默认模型、设备和端口配置来源。

推理页面的“批量推理”打开时会调用 `inference_webui_fast.py`，关闭时调用 `inference_webui.py`。本项目要求关闭该选项，并记录开关状态。

## 推荐取证流程

### 1. 页面取证

操作前截图保存所有路径输入框；操作后在 `GPT_weights`、`SoVITS_weights` 和 `output` 目录确认本次新增文件。

### 2. 保存控制台

不要关闭 Web UI 的控制台窗口。可从整合包根目录启动并保存输出：

```powershell
Set-Location '<整合包根目录>'
$log = "logs\\evidence-$(Get-Date -Format 'yyyyMMdd-HHmmss').txt"
& '.\\runtime\\python.exe' -I '.\\webui.py' zh_CN 2>&1 | Tee-Object -FilePath $log
```

### 3. 前后文件对比

```powershell
Get-ChildItem '.\\GPT_weights' -Recurse -File -Include *.ckpt | Select-Object FullName,Length,LastWriteTime
Get-ChildItem '.\\SoVITS_weights' -Recurse -File -Include *.pth | Select-Object FullName,Length,LastWriteTime
Get-ChildItem '.\\output' -Recurse -File -Include *.wav,*.list,*.txt | Select-Object FullName,Length,LastWriteTime
```

只把脱敏后的文件名模式、时间、大小、命令摘要和结论提交仓库；真实音频、权重和个人绝对路径留在本机。

## CXY 立即执行

用 50 系 Web UI，选择训练得到的一对 GPT `.ckpt` 和 SoVITS `.pth`，关闭批量/并行推理，生成一条全新 WAV。保存页面截图、控制台日志和输出目录前后列表，写入 `Documents/环境/CXY-50series-webui-evidence.md`。本周先完成 Web UI 链路取证，再让 LHY 根据证据接 adapter，不要求你立即改成项目直调。

## LJQ 立即执行

在自己的 40 系整合包中独立完成环境记录和一条零样本推理，关闭批量/并行推理。保存页面截图、控制台日志和输出目录前后列表，写入 `Documents/环境/LJQ-40series-webui-evidence.md`。Web UI 成功只能证明整合包在本机成功，不能直接写成“项目 adapter 已兼容”；adapter 复现需单独记录。

## 交给 LHY 的最低信息

整合包版本/来源、入口文件、页面动作对应的源码文件或函数、参数含义、输入输出类型、成功判定、脱敏权重文件名模式，以及一次真实成功或失败的日志摘要。无法确认的项目写“待实测”，不要猜 API。
