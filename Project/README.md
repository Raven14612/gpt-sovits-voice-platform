# 轻量级语音克隆项目

这是项目重新整理后的 v3 工程骨架。GPT-SoVITS 和第三方整合包是外部依赖，本仓库只实现页面、业务逻辑、文件管理、任务状态和引擎适配。

当前状态：四页工程壳和基础契约已经建立，真实切分、训练、推理尚未接入，页面不会用假音频或假成功代替。

## 目录

```text
Project/
├─ app.py                    # 唯一启动入口
├─ adapters/                 # 外部 GPT-SoVITS 适配器
├─ config/                   # 配置样例；本机路径不提交
├─ models/                   # 数据结构和统一错误
├─ services/                 # 页面调用的业务函数
├─ ui/                       # 四页 Gradio 页面
├─ assets/                   # 样式和固定文案
├─ data/                     # 数据集、音色、结果与索引
├─ tests/                    # 不依赖 GPU 的基础测试
└─ Documents/                # 当前计划、任务单和历史废案
```

## 启动页面壳

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python app.py
```

默认只启动 UI。需要探测 GPT-SoVITS 时，复制 `config/engine.example.json` 为 `config/engine.local.json`，填写本机实际路径。不要把个人路径、整合包、模型权重或真实音频提交到仓库。

## 当前任务

从 [Documents/README.md](Documents/README.md) 进入，阅读自己的成员任务单。计划功能不能视为已实现。

