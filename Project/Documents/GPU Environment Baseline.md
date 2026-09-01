# GPU 环境基线：40 系 / 50 系双轨道说明

> 适用对象：全组四人（LJQ 主责维护，CXY 验收对照，LHY/WGX 只读引用）  
> 用途：说明 RTX 40 系与 50 系混用时的协作规则，并提供每人可填写的环境基线模板。  
> 关联节点：Week 1 `LJQ-N1`；Week 2 及以后 GPU 冒烟前对照本表。

---

## 1. 结论（先看这个）

| 层面 | 40 系 / 50 系混用是否有影响 |
|---|---|
| Gradio 页面、Python services、JSON、文件存储 | **基本无影响** |
| GPT-SoVITS 推理、ASR、GPU 切分 | **有影响**，每人本机 PyTorch/CUDA 组合可能不同 |
| 最终 Demo / 阶段验收 | **各人在本机分别通过即可** |
| 团队协同 | **统一模型版本与业务代码**，**不统一整台 conda 环境** |

**驱动版本不同本身通常不是致命问题。** 真正要管理的是：PyTorch 自带的 CUDA 运行时（`cu124` / `cu128` 等）是否与各自显卡匹配。

参考包说明：仓库中存在 `Reference-Project/GPT-SoVITS-v2pro-20250604-nvidia50.7z`，表明 50 系可能需要单独整合包；40 系同学不要强行共用该包。

---

## 2. 统一什么、不统一什么

### 必须统一（项目真值）

- GPT-SoVITS 参考目录 / 提交版本 / 预训练权重来源
- `contract-v1.0` 字段与 services 接口
- 固定试听文本、回归文本、授权素材清单
- `Project/` 业务代码（Gradio + Python services）

### 不要统一（本机环境）

- NVIDIA 驱动具体版本号
- PyTorch 是 `cu124` 还是 `cu128`
- 整合包是通用版还是 `nvidia50` 专用版
- 显存大小与推理耗时

### 禁止事项

- 四人共用一个 venv 或整包拷贝到另一台机器后直接跑
- 用 A 同学的 40 系环境替 B 同学证明 50 系 OK
- CPU 回退跑通后当作“GPU 验收通过”
- 口头猜测版本，不运行命令就写进基线表

---

## 3. 推荐双轨道

| 轨道 | 适用硬件 | 建议组合 | 参考来源 |
|---|---|---|---|
| **Track A** | RTX 40 系（Ada） | Python 3.10 或 3.11 + PyTorch 2.5.1 + CUDA 12.4（`cu124`） | GPT-SoVITS README 主推荐组合 |
| **Track B** | RTX 50 系（Blackwell） | Python 3.11 + PyTorch 2.7 + CUDA 12.8（`cu128`）；优先 `nvidia50` 参考包 | GPT-SoVITS README / 本仓库 `nvidia50` 包 |

官方 GPT-SoVITS 测试组合示例：

- `Python 3.10/3.11 + PyTorch 2.5.1 + CUDA 12.4`
- `Python 3.11 + PyTorch 2.7.0 + CUDA 12.8`

LJQ 负责在两条轨道上各跑通一次，并更新下文「全组环境矩阵」。LHY 的 `tts_service` 只依赖稳定 Python 接口，**不得写死某一张卡的 CUDA 版本**。

---

## 4. 只读检查命令

在各自环境中运行，把输出粘贴到个人基线表（不要猜）：

```powershell
# 系统与驱动
nvidia-smi

# Python 环境
python --version
python -c "import torch; print('torch', torch.__version__); print('cuda', torch.version.cuda); print('available', torch.cuda.is_available()); print('device', torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'N/A')"

# FFmpeg（音频链路需要）
ffmpeg -version
```

可选补充：

```powershell
# 确认 GPT-SoVITS 目录（按本机实际路径修改）
python -c "import os; print(os.path.exists(r'<你的GPT-SoVITS目录>'))"
```

---

## 5. 个人环境基线表（每人填写一份）

复制本节到 `Project/Documents/env/<姓名缩写>-baseline.md`（例如 `env/LJQ-baseline.md`），或由 LJQ 汇总到全组矩阵。

### 5.1 基本信息

| 字段 | 填写内容 |
|---|---|
| 填写人 | |
| 填写日期 | |
| 机器标识 | （如：实验室 PC-01 / 自带笔记本） |
| 主责角色 | CXY / LJQ / LHY / WGX |

### 5.2 硬件与驱动

| 字段 | 填写内容 | 来源命令/文件 |
|---|---|---|
| GPU 型号 | 如 RTX 4080 / RTX 5090 | `nvidia-smi` |
| 显存 | 如 16 GB | `nvidia-smi` |
| NVIDIA 驱动版本 | | `nvidia-smi` |
| 环境轨道 | Track A（40 系）/ Track B（50 系） | 按上表选择 |

### 5.3 Python 与 PyTorch

| 字段 | 填写内容 | 来源命令/文件 |
|---|---|---|
| Python 版本 | | `python --version` |
| PyTorch 版本 | | `torch.__version__` |
| PyTorch 内置 CUDA | | `torch.version.cuda` |
| `torch.cuda.is_available()` | True / False | 见 §4 命令 |
| 虚拟环境名称/路径 | | 本机记录 |

### 5.4 GPT-SoVITS 与依赖

| 字段 | 填写内容 | 来源命令/文件 |
|---|---|---|
| GPT-SoVITS 目录 | 绝对路径 | 本机记录 |
| 版本/包来源 | 如 git commit、整合包文件名 | 本机记录 |
| 预训练权重是否齐全 | 是 / 否，缺什么 | 本机检查 |
| FFmpeg 版本 | | `ffmpeg -version` |
| ASR 方案 | FunASR / FasterWhisper 等 | Week 1 实际使用 |

### 5.5 启动与入口

| 字段 | 填写内容 |
|---|---|
| 官方 WebUI 启动方式 | 如 `go-webui.bat` 或具体命令 |
| 项目内 TTS 导入入口 | 如 `GPT_SoVITS/TTS_infer_pack/TTS.py` |
| 已知路径/权限问题 | |

### 5.6 GPU 冒烟证据（Week 1 必填，之后有变更时重跑）

| 检查项 | 结果 | 证据路径 |
|---|---|---|
| 零样本 TTS 出 1 条 WAV | 通过 / 失败 | |
| 切分跑通 1 次 | 通过 / 失败 / 未测 | |
| ASR 跑通 1 次 | 通过 / 失败 / 未测 | |
| 典型错误与处理 | | 日志摘要或截图路径 |

### 5.7 风险与备注

| 字段 | 填写内容 |
|---|---|
| 当前阻塞 | 如 OOM、CUDA 不可用、权重缺失 |
| 是否可参与 GPU 串行任务 | 是 / 否 |
| 备注 | |

---

## 6. 全组环境矩阵（LJQ 汇总，CXY 验收对照）

| 成员 | GPU | 轨道 | 驱动 | Python | PyTorch | CUDA(cu) | GPT-SoVITS 包 | TTS 冒烟 | 最后更新 |
|---|---|---|---|---|---|---|---|---|---|
| CXY | | | | | | | | | |
| LJQ | | | | | | | | | |
| LHY | | | | | | | | | |
| WGX | | | | | | | | | |

**验收口径：**

- Week 1：每人至少 **Track 对应轨道** 上 TTS 出 1 条真实 WAV；矩阵四行都有记录。
- Week 2+：环境变更（换包、换 PyTorch、换机器）后 **24 小时内** 更新个人表与矩阵。
- **不要求** 四人 PyTorch 版本完全一致；**要求** 业务代码 + 模型版本一致，且每人本机 GPU 链路可证明。

---

## 7. 常见问题与处理

| 现象 | 可能原因 | 处理 |
|---|---|---|
| `CUDA unavailable` | 50 系装了 `cu124` 老环境，或驱动过旧 | 换 Track B：`PyTorch 2.7 + cu128`，或使用 `nvidia50` 包 |
| 依赖冲突 / 启动失败 | 40 系误用 50 系专用整合包 | 回到 Track A：README 推荐的 12.4 组合 |
| OOM | 显存不足或同时占用 GPU 的程序过多 | 单任务串行、缩短文本、关闭其他占 GPU 进程 |
| “我这边能跑你那边不行” | 环境未记录，口头猜版本 | 对照 §5、§6，逐条核对命令输出 |
| 官方 WebUI 能跑、`app.py` 不能 | 项目入口或路径未对齐 | LHY 对照 LJQ 的环境记录修导入路径，不是换驱动 |

---

## 8. 与阶段 Demo 的关系

- **答辩主 Demo**：优先选矩阵中 **最稳定的一台** 机器现场演示。
- **其余成员**：提供本机 WAV + 日志，证明“同版本业务代码在本机也可运行”。
- **降级**：若现场 OOM，可播放同版本预跑 WAV，但必须说明降级；资源允许时再现场生成一条短句。

Week 1 若只有官方 WebUI 在本机出声而项目未接入，仍记 **「部分通过」**——这与 40/50 差异无关，是集成进度问题。

---

## 9. 维护责任

| 角色 | 责任 |
|---|---|
| **LJQ** | 维护双轨道说明、汇总全组矩阵、环境变更时通知 LHY |
| **CXY** | 验收时检查矩阵是否完整、证据是否本机真实产出 |
| **LHY** | 读模型路径与入口，不在代码里写死 CUDA 版本 |
| **WGX** | 环境状态 UI 展示 LHY 提供的检测结果，不伪造 GPU 状态 |

---

## 依据

- 统一范围：`Project/Documents/newplan.md`
- Week 1 节点：`Project/Documents/Week1/LJQ Nodes.md`（LJQ-N1）
- GPT-SoVITS：<https://github.com/RVC-Boss/GPT-SoVITS>
- 本仓库 50 系参考包：`Reference-Project/GPT-SoVITS-v2pro-20250604-nvidia50.7z`
