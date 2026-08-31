# Task3. 第一周开发计划（基线闭环与数据质量）

本文是 Task1 第 1 周与 Task2 角色分工的落地计划。文档按四人分章，每人本周工作拆成独立节点；每个节点附一条可直接复制给 AI 的提示词。

必读上游：

- `Project/Documents/Task1. DevelopmentSketch.md`
- `Project/Documents/Task2. DivisionOfLabor(Theoretical).md`
- `Project/Documents/基于语音克隆及合成的音色共享平台.md`
- 官方真值：`Reference-Project/GPT-SoVITS-main/api_v2.py`、`webui.py`、`GPT_SoVITS/configs/tts_infer.yaml`

---

## 0. 共用约定

### 0.1 本周目标

第一周只做「基线闭环与数据质量」，让团队在真实 GPU 环境上证明：官方模型能说话、授权数据能入库、业务 API 能代理零样本、页面能走通上传到试听。

必须完成：

1. 锁定 GPU、CUDA、Python、PyTorch、GPT-SoVITS 提交和 `v2Pro` 基线。
2. 启动官方 WebUI / `api_v2.py`，跑通数据准备到推理。
3. 完成上传校验、授权确认、路径白名单和零样本代理。
4. 建立情感标签、敏感词库、水印选型和固定回归文本。

本周验收：

| 验收项 | 证据 |
|---|---|
| 零样本链路连续 3 次生成可播放 WAV | 3 个真实 WAV + 日志 + 耗时/显存记录 |
| 一套 8–15 分钟授权测试语音 | 授权确认、有效分钟数、质量抽检表 |
| 基线音色 / 韵律对照样音 | 固定音色下至少 2 组参数对照 + 听测表 |

### 0.2 本周明确不做

- 不跑 `s1_train.py` / `s2_train.py` 正式少样本训练（第 2 周）。
- 不接入完整文本情感分类器、不嵌入/检测水印、不做 Vue 全流程闭环（第 3 周）。
- 不把 Mock 音频当作里程碑或演示证据。Mock 只允许出现在隔离外部进程的接口测试里。
- 不把「90% 音色相似度」「情感识别准确率 80%」「不可攻破水印」写成已实现。

### 0.3 本周目录与路径

按 Task1 第 4 节落地最小骨架，未用到的模块可以建空目录，不要写假实现。

```text
Project/
├─ backend/
│  ├─ api/
│  ├─ services/
│  ├─ adapters/gpt_sovits/
│  ├─ modules/emotion/      # 本周只放标签枚举，不接分类器
│  ├─ modules/prosody/      # 本周只放参数范围草稿
│  ├─ modules/safety/       # 本周只放敏感词库与策略草稿
│  └─ db/
├─ frontend/
├─ data/{uploads,datasets,voices,outputs,watermarks}/
├─ tests/
├─ Documents/
│  ├─ Week1/
│  │  ├─ version-baseline.md
│  │  ├─ requirement-evidence-matrix.md
│  │  ├─ api-contract-v0.1.md
│  │  ├─ emotion-and-regression-texts.md
│  │  ├─ safety-policy-draft.md
│  │  ├─ audio-quality-report.md
│  │  ├─ zeroshot-run-log.md
│  │  ├─ prosody-ab-listen.md
│  │  ├─ algorithm-handoff.md
│  │  └─ week1-acceptance.md
│  └─ Task3. Week1DevelopmentPlan.md
└─ deploy/
```

`data/`、权重、授权音频、`.env` 不得提交代码仓库。业务层只记录官方日志和真实绝对路径，不改造训练产物格式。

### 0.4 本周接口与字段（暂定，CXY-N3 冻结后生效）

本周业务 API 只实现闭环所需最小集，其余路径可返回 `501` 或暂不注册。

| 方法 | 路径 | 本周是否必须 |
|---|---|---|
| POST | `/api/audio/upload` | 必须 |
| GET | `/api/tasks/{task_id}` | 必须 |
| POST | `/api/tts` | 必须（零样本代理） |
| GET | `/api/outputs/{output_id}` | 必须 |
| GET | `/api/health` | 必须 |
| GET | `/api/voices` | 建议（零样本占位音色） |
| POST | `/api/datasets` `/api/voices` | 本周不做训练，可留空 |
| POST | `/api/safety/check-text` | 本周可只读词库，不强制接入合成 |
| POST | `/api/safety/detect-watermark` | 本周不做 |

任务状态本周最小集：`queued → processing → succeeded/failed`。`cancelled` 可预留枚举，本周不要求实现取消。

音色状态本周只使用零样本占位：`ready` 表示已有授权参考音频；不要把未训练权重标成少样本音色。

官方推理真值（`api_v2.py`，默认 `127.0.0.1:9880`）：

- `POST /tts`：`text`、`text_lang`、`ref_audio_path`、`prompt_text`、`prompt_lang`、`speed_factor`
- `GET /set_gpt_weights`、`GET /set_sovits_weights`：本周可探活，不接训练产物

### 0.5 提示词使用规则

1. 一次只发送一个节点。做完并留下交付物后，再开下一个节点。
2. 把下方对应提示词整段复制给 AI，并附上本机已存在的相关文件路径。
3. 不向公共 AI 上传密钥、`.env`、未脱敏源码、个人信息或未经授权的声音数据。
4. 不直接执行 AI 建议的未知安装命令或破坏性命令；依赖版本以官方 README 和本机实测为准。
5. AI 草稿必须由人工对照官方源码、真实日志和真实 WAV 复核。数字和结论要能回溯到原始证据。
6. 队长提示词只允许起草规范与审查清单，不允许代替算法、后端、前端写实现代码。

### 0.6 节点依赖

```text
CXY-N1 版本冻结 ──► LJQ-N1 官方环境
                 └─► LHY-N1 后端骨架
CXY-N3 接口契约 ──► LHY-N3 上传与代理
                 └─► WGX-N3 上传授权页
LJQ-N2 授权音频 ──► LJQ-N3 数据准备 ──► LJQ-N4 零样本 3 次 ──► LJQ-N5 韵律对照
LHY-N4 零样本代理 ──► WGX-N6 联调试听
LJQ-N4 + LHY-N4 + WGX-N6 ──► CXY-N6 本周验收
```

建议节奏：前半周冻结规范与环境，后半周打通零样本代理和页面试听，周五对照证据矩阵验收。

---

## 1. CXY 队长

### 1.1 本周角色目标

负责把 Task1 第 1 周从原则变成可执行边界：版本、需求分级、接口字段、情感标签、安全策略和验收证据。不替代 LJQ / LHY / WGX 的具体编码或训练。本周结束时，四人的输入输出和接口必须有书面记录，未完成项必须标成增强或预研。

### 1.2 节点总览

| 节点 | 依赖 | 产出 | 交给谁 |
|---|---|---|---|
| CXY-N1 环境与版本冻结 | 无 | `Documents/Week1/version-baseline.md` | 全员 |
| CXY-N2 需求与证据矩阵 | CXY-N1 | `Documents/Week1/requirement-evidence-matrix.md` | 全员 |
| CXY-N3 接口契约 v0.1 | CXY-N2 | `Documents/Week1/api-contract-v0.1.md` | LHY、WGX、LJQ |
| CXY-N4 情感标签与回归文本 | CXY-N2 | `Documents/Week1/emotion-and-regression-texts.md` | LJQ、WGX、LHY |
| CXY-N5 安全策略初稿 | CXY-N3 | `Documents/Week1/safety-policy-draft.md` | LHY、WGX、LJQ |
| CXY-N6 联调主持与本周验收 | LJQ-N4、LHY-N4、WGX-N6 | `Documents/Week1/week1-acceptance.md` | 全员 |

### 1.3 逐节点工作与提示词

#### CXY-N1 环境与版本冻结

组织全员确认本机 GPU、驱动、CUDA、Python、PyTorch，以及本地 `Reference-Project/GPT-SoVITS-main/` 的提交、预训练模型是否为 `v2Pro`、相关许可证。输出一张基线表，作为后续排错和答辩的版本依据。缺项标「待确认」，不要填猜测值。

```text
# 角色
你是本项目的项目经理助手，协助队长 CXY 冻结第一周技术基线。你只起草文档和核对清单，不写业务代码，不修改官方仓库。

# 背景与必读文件
先阅读并仅依据以下材料：
- Project/Documents/Task1. DevelopmentSketch.md（第 7 节第 1 周、第 11 节开工前确认、第 12 节参考依据）
- Project/Documents/Task2. DivisionOfLabor(Theoretical).md（CXY 队长章节）
- Project/Documents/Task3. Week1DevelopmentPlan.md（CXY-N1）
- Reference-Project/GPT-SoVITS-main/docs/cn/README.md（测试通过的环境表、安装说明）
- Reference-Project/GPT-SoVITS-main/requirements.txt
如需核对许可证，只引用仓库内 LICENSE 与官方 GitHub 页面，并写明访问日期。

# 本节点唯一目标
起草一份可人工填写的版本基线表，锁定 GPU/CUDA/Python/PyTorch、GPT-SoVITS 提交、v2Pro 预训练权重和许可证。

# 必须完成的工作
1. 列出必须采集的字段：操作系统、GPU 型号、显存、NVIDIA 驱动、CUDA、cuDNN（如有）、Python、PyTorch、torch.cuda.is_available()、GPT-SoVITS 本地路径、git commit（或说明“无 git 时的目录日期”）、预训练模型文件名与是否为 v2Pro、api_v2.py 默认地址端口、FastAPI/Vue 计划版本、各组件许可证。
2. 为每个字段给出“如何在本机核验”的命令或查看位置，优先使用官方 README 已验证组合：Python 3.10/3.11 + PyTorch 2.5.1 + CUDA 12.4。
3. 单独列出风险：版本不一致、CPU 回退、预训练权重缺失、许可证不明。
4. 所有未知值写成“待确认”，不要编造版本号。

# 硬约束 / 禁止事项
- 禁止给出未在官方文档出现的安装脚本并要求直接执行。
- 禁止建议上传权重、密钥或授权音频到公共网盘/公共 AI。
- 禁止把案例文档里的 90% 相似度等研究目标写进基线表。
- 不要创建或修改 Python/Vue 源码。

# 交付物与存放路径
- Project/Documents/Week1/version-baseline.md
- 内容必须包含：已确认表、待确认表、核验命令、风险、填写责任人（CXY 汇总，LJQ 填算法环境，LHY 填后端运行时）。

# 验收标准
- 全员能按该表在 30 分钟内填完本机环境。
- 表中每一行都能指向官方文档或本机命令，而不是模型记忆。
- 明确写出本周推理基线是官方 api_v2.py + v2Pro，而不是自训权重。

# 完成后交给谁
交给 LJQ 填写算法环境实测值，交给 LHY 填写后端运行时，CXY 人工签字后分发给全员。
```

#### CXY-N2 需求与证据矩阵

把 Task1 的「必须实现 / 增强 / 预研」映射到第 1 周：哪些本周验收，哪些只建规范或占位。输出责任矩阵和证据矩阵，避免把第 2、3 周工作误报为本周完成。

```text
# 角色
你是需求与验收分析助手，协助队长 CXY 把 Task1 拆成第一周可验收清单。只产出表格和说明，不写实现代码。

# 背景与必读文件
- Project/Documents/Task1. DevelopmentSketch.md（第 2 节范围分级、第 7 节四周计划、第 8 节测试验收）
- Project/Documents/Task2. DivisionOfLabor(Theoretical).md（四个角色的输入输出）
- Project/Documents/Task3. Week1DevelopmentPlan.md（第 0 节本周必须完成/明确不做）
- Project/Documents/基于语音克隆及合成的音色共享平台.md（仅用于标出“案例指标 vs 本期不验收”）

# 本节点唯一目标
生成第一周需求清单、RACI 责任矩阵和验收证据矩阵，明确必须实现、本周占位、增强目标、预研功能四类。

# 必须完成的工作
1. 从 Task1 第 2.1 节逐条判断：本周验收 / 本周只做规范或占位 / 推迟到第 2–4 周。
2. 为每条本周验收项写清：负责人、协作人、证据文件、失败时的回退（例如零样本回退）。
3. 把案例文档中的 90% 相似度、解耦 RMSE、情感准确率 80%、不可听水印等全部列入“研究目标，本周不验收”。
4. 列出本周会议节奏建议：规范冻结、环境冒烟、零样本联调、周五验收。

# 硬约束 / 禁止事项
- 不得把第 2 周少样本训练或第 3 周水印/情感分类写成“本周必须完成”。
- 不得使用 Mock 音频、架构图或示意代码作为验收证据。
- 不得新增 Task1 未出现的产品范围。

# 交付物与存放路径
- Project/Documents/Week1/requirement-evidence-matrix.md
- 至少包含：范围分级表、RACI 表、证据矩阵、本周不做清单。

# 验收标准
- Task1 第 1 周三段话中的每一项都能在矩阵里找到对应行。
- 每个本周验收项都有“谁做、交给谁、什么文件算过”。
- 增强/预研项都有“不得对外称为已实现”的标注。

# 完成后交给谁
CXY 审核后发给全员，作为 CXY-N6 周五对照表。
```

#### CXY-N3 接口契约 v0.1

冻结本周前后端与算法之间的字段：`voice_id`、任务状态、上传与授权、TTS 请求/响应、错误码和日志字段。契约必须对齐 Task1 第 6 节，并写明与官方 `api_v2.py` 的映射，而不是改官方接口。

```text
# 角色
你是接口契约起草助手，协助队长 CXY 冻结 Week1 API 契约 v0.1。只写契约文档，不实现 FastAPI 或 Vue。

# 背景与必读文件
- Project/Documents/Task1. DevelopmentSketch.md（第 6 节数据模型与 API 草案）
- Project/Documents/Task3. Week1DevelopmentPlan.md（第 0.4 节本周必须接口）
- Reference-Project/GPT-SoVITS-main/api_v2.py 文件头注释（/tts、/set_gpt_weights、/set_sovits_weights 的真实字段）
- Project/Documents/Task2. DivisionOfLabor(Theoretical).md（LHY 与 WGX 的交接物）

# 本节点唯一目标
输出一份前后端可同时开发的契约 v0.1：本周必须实现的业务 API、字段、状态机、错误码，以及它们如何映射到官方 api_v2.py。

# 必须完成的工作
1. 为 POST /api/audio/upload、GET /api/tasks/{task_id}、POST /api/tts、GET /api/outputs/{output_id}、GET /api/health 写出请求/响应 JSON 示例。
2. 冻结字段：voice_id、version、status（voice: training/ready/failed/disabled；job: queued/processing/succeeded/failed，cancelled 预留）、consent_id、job_id、output_id、generation_id、ref_audio_path（仅服务端内部）、prompt_text、prompt_lang、text、text_lang、speed_factor、error.code、error.message。
3. 明确前端不得拿到内部绝对路径或密钥；下载/试听只返回业务 URL。
4. 写清业务 POST /api/tts 与官方 POST /tts 的字段映射表，以及失败时如何把官方 400 JSON 转成业务错误码。
5. 给出错误码初稿，至少覆盖：文件类型非法、超过时长、未授权、路径非法、参考音频缺失、官方服务不可达、推理失败。
6. 给出日志字段：request_id、job_id、stage、exit_or_http_code、duration_ms；禁止记录密钥和完整个人信息。

# 硬约束 / 禁止事项
- 禁止修改或“优化”官方 api_v2.py 的字段名。
- 禁止在契约里要求本周实现训练、水印检测、情感分类器。
- 禁止让前端直连 127.0.0.1:9880。
- 所有示例 JSON 必须可被 Pydantic 直接对照，不要写伪字段。

# 交付物与存放路径
- Project/Documents/Week1/api-contract-v0.1.md

# 验收标准
- LHY 能按该文档实现路由而不再追问字段含义。
- WGX 能按该文档画表单和轮询，而不猜测状态枚举。
- 契约中每个官方映射都能在 api_v2.py 注释或代码里找到对应项。

# 完成后交给谁
冻结后交给 LHY（实现）和 WGX（联调），抄送 LJQ（确认参考音频与提示文本字段）。
```

#### CXY-N4 情感标签与固定回归文本

本周不接分类器，但必须先冻结标签体系和听测文本，避免后续各写各的。标签至少覆盖中性、开心、悲伤、愤怒/严肃；强度先占 3 档。回归文本用于零样本连续 3 次和韵律对照。

```text
# 角色
你是语音评测设计助手，协助队长 CXY 制定第一周情感标签占位和固定回归文本。只输出规范，不生成音频，不训练模型。

# 背景与必读文件
- Project/Documents/Task1. DevelopmentSketch.md（第 3.3 节情感控制对象、第 8.2 节指标）
- Project/Documents/Task2. DivisionOfLabor(Theoretical).md（CXY 向算法/前端输出的成果）
- Project/Documents/Task3. Week1DevelopmentPlan.md（本周验收与明确不做）

# 本节点唯一目标
冻结 4 类情感标签、3 档强度占位、统一控制对象 JSON，以及不少于 5 条固定中文回归文本。

# 必须完成的工作
1. 标签枚举使用英文 key + 中文显示名：neutral/开心happy/悲伤sad/愤怒或严肃 angry_or_serious。解释本周这些标签只用于对照实验和 UI 占位，不代表分类器已上线。
2. 强度 3 档建议：0.3 / 0.6 / 0.9，并给出与语速、音高、能量、停顿的“占位映射草稿”，标明未经验证。
3. 统一控制对象必须包含 Task1 示例字段：emotion、intensity、speed、pitch_semitone、energy、pause_scale。
4. 设计 5 条固定中文回归文本：覆盖陈述、疑问、感叹、较长复合句、含数字/专名；每条注明预计时长和适用语种 zh。
5. 另给 1 条零样本参考提示文本（prompt_text）撰写要求：与参考音频内容一致，由 LJQ 按真实 ASR/人工校对填写，你不得编造具体台词冒充已有录音。
6. 给出听测记录表头：样音文件名、文本编号、参数、可懂度、音色一致性、情感可感知度（可感知/弱感知/无效或失真）、备注。

# 硬约束 / 禁止事项
- 禁止声称情感识别准确率或跨语言迁移已实现。
- 禁止生成或要求使用 AI 合成的假参考音频。
- 禁止把 GRL/对抗解耦写进本周标签体系。
- 文本必须适合公开演示，不含敏感词和未授权人名。

# 交付物与存放路径
- Project/Documents/Week1/emotion-and-regression-texts.md

# 验收标准
- LJQ 能直接用这 5 条文本跑零样本 3 次和韵律对照。
- WGX 能按枚举做下拉框，且文案写明“本周为占位”。
- JSON 控制对象与 Task1 第 3.3 节字段一致。

# 完成后交给谁
交给 LJQ 做听测，交给 WGX 做控件文案，交给 LHY 预留 emotion_control 字段（本周可原样存储不解释）。
```

#### CXY-N5 安全策略初稿

本周只定策略和词库选型，不实现水印算法。明确敏感词命中后的拒绝/人工确认、授权范围与保存期限、水印候选（优先评估 AudioSeal）以及演示发布范围。

```text
# 角色
你是安全与合规起草助手，协助队长 CXY 输出第一周语音安全策略初稿。只写策略和词库结构，不实现水印，不把密钥写入文档。

# 背景与必读文件
- Project/Documents/Task1. DevelopmentSketch.md（第 3.4 节语音安全、第 9 节风险）
- Project/Documents/Task2. DivisionOfLabor(Theoretical).md（CXY 合规职责、LHY 安全实现边界）
- Project/Documents/Task3. Week1DevelopmentPlan.md（本周安全只做选型与词库）
- 如需引用 AudioSeal，只作为候选并标注“本周选型，第 3 周实验”，官方仓库 https://github.com/facebookresearch/audioseal

# 本节点唯一目标
形成可执行的敏感词策略、授权/保存期限、水印候选结论和审计字段，供 LHY 第 3 周实现、本周最多落词库文件。

# 必须完成的工作
1. 敏感词：定义规范化规则（大小写、繁简、空格、常见变形的处理原则，不要写可滥用的绕过清单）、命中动作（拒绝 / 需确认）、规则版本号字段。
2. 给出词库文件格式建议（纯文本或 JSON）和存放路径 Project/backend/modules/safety/sensitive_words.v0.txt；词库内容只放少量演示用假词，真正敏感词由人工后续添加。
3. 授权：上传时必须确认授权范围、是否允许训练、保存期限；consent_id 与音频、后续音色绑定。
4. 水印：对比 AudioSeal 与“可检测扩频/频域实验方案”的选型表（许可证、依赖、是否需要 GPU、音质风险、本周结论）。结论只能是“候选”，不能写“已实现”。
5. 密钥管理原则：水印密钥只来自服务端环境变量，不进代码、不进 Git、不进日志、不进本策略文档的示例值。
6. 演示发布范围：本机/内网演示，不公开未授权音色。

# 硬约束 / 禁止事项
- 禁止提供真实攻击性绕过方法或“如何去掉水印”。
- 禁止编造检测率、不可移除等安全承诺。
- 禁止在文档中写入任何真实密钥、账号、个人信息。
- 禁止要求本周完成后端水印嵌入。

# 交付物与存放路径
- Project/Documents/Week1/safety-policy-draft.md
- 可选草稿：Project/backend/modules/safety/sensitive_words.v0.txt（仅演示假词）

# 验收标准
- LHY 能根据策略实现上传授权字段，而不需要自行解释法律含义。
- 水印部分明确是选型，证据是对比表而不是代码。
- 词库带 version，后续变更可审计。

# 完成后交给谁
交给 LHY 落实授权字段与词库读取预留，交给 WGX 写授权文案和拦截提示，抄送 LJQ 避免用未授权音频。
```

#### CXY-N6 联调主持与本周验收

对照 CXY-N2 证据矩阵，组织「算法基线 → 后端代理 → 前端闭环」的顺序验收。未完成功能必须降级标注，不能写成已实现。

```text
# 角色
你是验收会议秘书，协助队长 CXY 汇总第一周联调证据并起草验收结论。你只整理已有日志、路径和听测表，不补做实验，不编造通过项。

# 背景与必读文件
- Project/Documents/Week1/requirement-evidence-matrix.md
- Project/Documents/Week1/api-contract-v0.1.md
- Project/Documents/Week1/zeroshot-run-log.md（若已存在）
- Project/Documents/Week1/audio-quality-report.md（若已存在）
- Project/Documents/Week1/prosody-ab-listen.md（若已存在）
- LHY 的 OpenAPI 或测试输出、WGX 的浏览器验证记录（若已存在）
- Project/Documents/Task3. Week1DevelopmentPlan.md（第 0.1 节本周验收）

# 本节点唯一目标
生成第一周验收记录：通过项、证据链接、失败项、降级为增强/预研的项、下周风险。

# 必须完成的工作
1. 按顺序检查：官方零样本 3 次 WAV 是否真实存在；8–15 分钟授权数据是否有有效分钟数；韵律对照样音是否为固定音色只改参数；后端代理是否经业务 API 而不是前端直连 9880；前端是否在目标浏览器实际播放。
2. 每一项写：结论（通过/未通过/部分通过）、证据路径、记录人、日期。
3. 部分通过必须写清缺口，并决定进入第 2 周还是标为增强。
4. 列出已知限制：显存、音质、情感占位未验证、水印未实现等。
5. 起草 10 分钟演示脚本提纲：环境、上传授权、零样本合成、对照试听、失败展示。

# 硬约束 / 禁止事项
- 没有文件路径的项一律不得标“通过”。
- 禁止用截图代替音频文件作为 TTS 通过证据。
- 禁止把计划中的第 2、3 周能力写进“已完成”。
- 若某交付物缺失，明确写“缺失”，不要用 AI 补一段假日志。

# 交付物与存放路径
- Project/Documents/Week1/week1-acceptance.md

# 验收标准
- 三个本周验收项都有明确通过或未通过。
- 问题清单、责任人和下周动作完整。
- 队长能拿该文档独立向他人说明与官方 GPT-SoVITS 的差异：本周只完成业务编排的零样本闭环，尚未少样本训练。

# 完成后交给谁
CXY 签字后分发全员，作为第 2 周开工输入。
```

### 1.4 队长本周验收清单

- [ ] 版本基线表已填实测值，不是待确认占满。
- [ ] 需求/证据矩阵覆盖 Task1 第 1 周全部条目，且无越界。
- [ ] 接口契约 v0.1 已冻结，LHY 与 WGX 书面确认。
- [ ] 4 类情感 + 5 条回归文本可用。
- [ ] 安全策略与水印候选已书面记录。
- [ ] 周五验收文档能回溯到真实 WAV、数据和接口日志。

---

## 2. LJQ 算法负责人

### 2.1 本周角色目标

在官方 GPT-SoVITS 上跑通环境、授权数据质量和零样本推理，向系统提供可复现的参考音频、`.list`、样音和参数说明。本周不负责业务 API、数据库和页面，也不启动正式少样本训练。

### 2.2 节点总览

| 节点 | 依赖 | 产出 | 交给谁 |
|---|---|---|---|
| LJQ-N1 官方环境冒烟 | CXY-N1 | 环境实测写入 version-baseline；WebUI/API 启动记录 | CXY、LHY |
| LJQ-N2 授权音频规范与采集 | CXY-N5 授权原则 | 8–15 分钟授权音频 + 质量报告 | CXY、LHY |
| LJQ-N3 官方数据准备 | LJQ-N2 | 切分结果、ASR 抽检、标准 `.list` | LHY（路径约定） |
| LJQ-N4 零样本连续 3 次 | LJQ-N1、CXY-N4 | 3 个可播放 WAV + 运行日志 | CXY、LHY |
| LJQ-N5 基线音色—韵律对照 | LJQ-N4 | 对照样音 + 听测表 | CXY、WGX |
| LJQ-N6 算法交接契约 | LJQ-N3–N5 | `algorithm-handoff.md` | LHY、WGX、CXY |

### 2.3 逐节点工作与提示词

#### LJQ-N1 官方环境冒烟

按官方文档和 CXY-N1 基线，在 Windows GPU 上安装并启动 WebUI 与 `api_v2.py`。先证明官方链路可推理，再谈业务封装。

```text
# 角色
你是 GPT-SoVITS 环境工程师，协助算法负责人 LJQ 在 Windows GPU 上完成官方环境冒烟。你只帮助阅读官方文件、整理检查步骤和记录模板，不编造“已经跑通”。

# 背景与必读文件
- Reference-Project/GPT-SoVITS-main/docs/cn/README.md
- Reference-Project/GPT-SoVITS-main/requirements.txt
- Reference-Project/GPT-SoVITS-main/api_v2.py（文件头启动命令）
- Project/Documents/Week1/version-baseline.md（若已有）
- Project/Documents/Task3. Week1DevelopmentPlan.md（LJQ-N1）
官方启动示例：python api_v2.py -a 127.0.0.1 -p 9880 -c GPT_SoVITS/configs/tts_infer.yaml

# 本节点唯一目标
给出一份可执行的官方环境冒烟清单，使 LJQ 能启动 WebUI 和 api_v2，并记录 CUDA 可用与预训练权重是否为 v2Pro。

# 必须完成的工作
1. 根据官方 README 整理 Windows 安装检查项（conda/python、CUDA 设备、预训练目录、ffmpeg）。
2. 写出启动 WebUI 与 api_v2 的命令、工作目录必须是 GPT-SoVITS 根目录、以及如何判断服务已监听 9880。
3. 写出最小探活方法：访问 /tts 缺参应返回官方 400 JSON，而不是连接失败。
4. 提供记录模板：命令、退出码、显存占用、权重文件名、失败栈摘要。
5. 若环境失败，按日志分类：驱动/CUDA、权重缺失、依赖冲突、端口占用；每类只给官方或源码内的下一步，不给来路不明的下载链接。

# 硬约束 / 禁止事项
- 禁止修改官方 api_v2.py、webui.py 的推理逻辑来“先跑通”。
- 禁止建议从非官方来源下载权重。
- 禁止本周启动 s1_train.py / s2_train.py。
- 禁止把 CPU 成功当成 GPU 基线通过；若只能 CPU，必须在记录里标为降级。

# 交付物与存放路径
- 更新 Project/Documents/Week1/version-baseline.md 的算法环境实测栏
- 启动记录可附在 Project/Documents/Week1/zeroshot-run-log.md 的“环境冒烟”一节

# 验收标准
- api_v2.py 在 127.0.0.1:9880 保持可访问。
- torch.cuda.is_available() 与 GPU 名称已记录。
- 预训练权重文件名和是否 v2Pro 已核对。

# 完成后交给谁
环境实测交给 CXY 归档；9880 地址与健康状况交给 LHY 写适配层。
```

#### LJQ-N2 授权音频规范与采集

准备一套 8–15 分钟有效授权语音，并做质量检查。没有授权确认的音频不得进入 `data/`。

```text
# 角色
你是语音数据质检助手，协助 LJQ 制定授权音频采集与质量检查规范，并生成可审查的检查脚本草稿。脚本必须由人工检查边界后再在授权数据上运行。

# 背景与必读文件
- Project/Documents/Task1. DevelopmentSketch.md（第 3.1 节数据准备、第 9 节数据质量风险）
- Project/Documents/Task2. DivisionOfLabor(Theoretical).md（LJQ 工作内容第 1 条）
- Project/Documents/Week1/safety-policy-draft.md（若已有授权条款）
- Project/Documents/Task3. Week1DevelopmentPlan.md（LJQ-N2）

# 本节点唯一目标
产出音频质量规范、采集清单和质检脚本草稿，确保本周有一套 8–15 分钟有效授权测试语音。

# 必须完成的工作
1. 规范字段：说话人一致性、语种、授权范围、保存期限、原始格式、采样率、声道、有效时长（去静音后）、削波、噪声、文本覆盖（朗读材料类型）。
2. 建议目标：有效语音 8–15 分钟；另准备约 5 秒干净参考片段用于零样本。
3. 编写质量检查脚本草稿（建议 Python + librosa/soundfile）：输出每条音频的时长、采样率、声道、峰值、静音比例、是否削波；汇总有效分钟数。
4. 给出人工抽检表：听感噪声、错人、过短切片、含音乐/重叠人声。
5. 明确目录：原始授权音频不进 Git；建议本地 data/uploads/<consent_id>/，脚本只打印统计，不上传云端。

# 硬约束 / 禁止事项
- 禁止使用未授权的第三方主播/影视音频。
- 禁止让 AI 生成假音频充当采集结果。
- 禁止在提示或代码中要求把原始人声发给公共 AI。
- 脚本不得删除用户原始文件；有问题只标记。

# 交付物与存放路径
- Project/Documents/Week1/audio-quality-report.md（先出模板，跑完后填实测）
- 质检脚本建议：Project/tests/ 或由 LJQ 放在本地工具目录，不写入官方仓库内部。

# 验收标准
- 报告能回答：授权是否存在、有效分钟数是否落在 8–15、参考 5 秒片段是否可用。
- 不合格项有处理意见（重录、剪静音、放弃降噪等）。
- 脚本在人工审查后再运行，边界条件（空文件、非音频、损坏头）有处理。

# 完成后交给谁
质量报告交给 CXY；可用文件路径和 consent 信息交给 LHY 做上传校验对照。
```

#### LJQ-N3 官方数据准备

使用官方切分、可选降噪/人声分离和 ASR 工具，生成 GPT-SoVITS 标准 `.list`，并人工抽检 ASR。本周停在数据集，不训练。

```text
# 角色
你是 GPT-SoVITS 数据准备助手，协助 LJQ 用官方工具把授权音频做成标准 .list。以本地官方脚本为真值，不重写训练格式。

# 背景与必读文件
- Reference-Project/GPT-SoVITS-main/docs/cn/README.md 与 WebUI 数据工具说明
- 官方脚本线索：tools/slice_audio.py、tools/asr/、GPT_SoVITS/prepare_datasets/
- Project/Documents/Task1. DevelopmentSketch.md（第 3.1 节复用能力）
- Project/Documents/Week1/audio-quality-report.md
- Project/Documents/Task3. Week1DevelopmentPlan.md（LJQ-N3，明确不训练）

# 本节点唯一目标
整理官方 切分 → 可选降噪 → ASR → .list 的操作步骤和记录模板，完成本周数据集，不做 1A/1B/1C 之后的 s1/s2 训练。

# 必须完成的工作
1. 按官方流程列出每一步的入口（WebUI 或脚本）、关键参数、输入输出目录、预计失败点。
2. 说明 .list 的官方格式字段，并要求抽检至少 N 条（建议 20 条或 10%，取高）ASR 文本。
3. 记录：脚本/页面提交、数据量、耗时、显存、日志路径、失败原因。
4. 计算并写入有效分钟数；不足 8 分钟必须标风险，不得假装达标。
5. 输出给后端的路径约定：dataset 根目录、.list 绝对路径、切片 wav 目录。使用短 ASCII 路径建议。

# 硬约束 / 禁止事项
- 禁止本周运行 s1_train.py、s2_train.py。
- 禁止手写一套非官方 list 格式“先用着”。
- 禁止用 AI 直接改写全部 ASR 文本而不抽检。
- 禁止把数据集提交到 Git。

# 交付物与存放路径
- 更新 Project/Documents/Week1/audio-quality-report.md，增加“数据准备”一节
- .list 与切片留在本地 data/datasets/<exp_name>/

# 验收标准
- 至少一份合法 .list 能被官方工具识别。
- 抽检记录和有效分钟数完整。
- 路径可被 LHY 原样写入数据库。

# 完成后交给谁
.list 路径和 exp_name 交给 LHY；抽检结论交给 CXY。
```

#### LJQ-N4 零样本连续 3 次

用固定回归文本和约 5 秒参考音频，经官方 `/tts` 连续 3 次生成可播放 WAV。这是本周算法侧的硬验收。

```text
# 角色
你是 TTS 推理实验助手，协助 LJQ 用官方 api_v2.py 完成零样本连续 3 次生成。所有音频必须来自真实推理，不允许用静音或 TTS 网站替代。

# 背景与必读文件
- Reference-Project/GPT-SoVITS-main/api_v2.py 文件头（POST /tts 字段）
- Project/Documents/Week1/emotion-and-regression-texts.md（固定文本）
- Project/Documents/Week1/version-baseline.md
- Project/Documents/Task3. Week1DevelopmentPlan.md（本周验收第 1 条）

# 本节点唯一目标
设计并记录零样本实验：同一参考音频、同一组固定文本，连续 3 次成功写出可播放 WAV，并记录耗时与失败。

# 必须完成的工作
1. 给出调用官方 POST http://127.0.0.1:9880/tts 的请求示例，字段仅使用官方已有项：text、text_lang、ref_audio_path、prompt_text、prompt_lang、speed_factor、text_split_method、media_type。
2. 要求 ref_audio_path 是本机真实存在的授权 5 秒参考音频；prompt_text 必须与参考音频内容一致。
3. 连续 3 次的定义：三次独立请求都返回可被播放器打开的 WAV，记录每次 HTTP 状态、字节数、时长、GPU 显存。
4. 提供失败记录模板：400 校验、CUDA OOM、参考音频无效、文本为空。
5. 听测最少记录可懂度、杂音、断句；不填写无依据的相似度百分比。

# 硬约束 / 禁止事项
- 禁止 Mock 音频、禁止复制旧 wav 改名充当第 2、3 次。
- 禁止为了通过而降低为“只跑成功 1 次就算过”。
- 禁止把业务 FastAPI 未完成当成算法失败；本节点走官方 9880。
- 禁止在日志中粘贴完整未授权音频或个人敏感文本。

# 交付物与存放路径
- Project/Documents/Week1/zeroshot-run-log.md
- 样音建议：data/outputs/week1/zeroshot_{1,2,3}.wav（不提交 Git）

# 验收标准
- 3 个 WAV 均可播放，日志能一对一对应。
- 使用的回归文本来自 CXY-N4，而不是临时乱打的句子。
- 若第 3 次失败，写明原因和复现步骤，不得删失败记录。

# 完成后交给谁
样音和日志交给 CXY 验收；参考音频路径、prompt_text、成功请求体交给 LHY 做代理对照。
```

#### LJQ-N5 基线音色—韵律对照

固定同一参考音色，只改变韵律相关条件（优先 `speed_factor`，可选不同风格参考片段），证明「音色通道固定、韵律通道变化」的 MVP 叙述有样音。

```text
# 角色
你是韵律对照实验助手，协助 LJQ 做第一周基线音色—韵律实验。本周只做参数化解耦，不训练风格向量，不上 GRL。

# 背景与必读文件
- Project/Documents/Task1. DevelopmentSketch.md（第 3.2 节 MVP 参数化解耦）
- Reference-Project/GPT-SoVITS-main/api_v2.py（speed_factor 等官方可调参数）
- Project/Documents/Week1/emotion-and-regression-texts.md
- Project/Documents/Week1/zeroshot-run-log.md
- Project/Documents/Task3. Week1DevelopmentPlan.md（LJQ-N5）

# 本节点唯一目标
在固定参考音频和固定文本下，产出至少 2 组韵律参数对照样音，并给出可重复的听测/声学记录表。

# 必须完成的工作
1. 对照组设计：同一 ref_audio_path、同一 text；A 组 speed_factor=1.0；B 组 speed_factor 明显偏离（如 0.85 与 1.15，以实际可推理值为准）。
2. 可选第三组：更换风格参考片段或 prompt 语气，但仍用同一说话人授权音频。
3. 记录主观听测：语速是否按预期变化、音色是否明显跑偏、失真情况。
4. 若本机已有 librosa，可起草 F0/能量/时长统计脚本；没有则只做听测，不要假装有客观指标。
5. 明确结论用语：只能写“可感知变化/弱感知/无效或失真”，不能写“已完成解耦模型”。

# 硬约束 / 禁止事项
- 禁止画双分支架构图代替样音。
- 禁止修改生产模型或开对抗训练实验分支并称为本周成果。
- 禁止用不同说话人音频冒充“只改韵律”。
- 禁止把情感分类准确率写进本实验。

# 交付物与存放路径
- Project/Documents/Week1/prosody-ab-listen.md
- 对照 wav 放入 data/outputs/week1/prosody_* （不提交 Git）

# 验收标准
- 至少一组固定音色、只改参数的对照可播放。
- 参数、文件名、听测结论一一对应。
- 已知失败（变化不明显或失真）如实记录。

# 完成后交给谁
对照结论交给 CXY；参数上下限和听感说明交给 WGX 做控件提示。
```

#### LJQ-N6 算法交接契约

把本周算法产物整理成后端/前端能用的说明：路径、默认值、错误条件和限制。这是第 2 周训练封装的输入，不是训练本身。

```text
# 角色
你是算法交付文档助手，协助 LJQ 把第一周真实实验整理成交接说明书。只汇总已发生的事实，不补充未做实验。

# 背景与必读文件
- Project/Documents/Week1/audio-quality-report.md
- Project/Documents/Week1/zeroshot-run-log.md
- Project/Documents/Week1/prosody-ab-listen.md
- Project/Documents/Week1/api-contract-v0.1.md
- Project/Documents/Task2. DivisionOfLabor(Theoretical).md（LJQ 向其他角色输出的成果）

# 本节点唯一目标
输出算法交接文档：可加载的参考音频与提示文本、推荐默认参数、错误条件、模型卡片草稿和已知限制。

# 必须完成的工作
1. 列出本周可用零样本配置：ref_audio 绝对路径、prompt_text、prompt_lang、text_lang、推荐 speed_factor、text_split_method。
2. 列出 .list 与切片目录、有效分钟数、授权/consent 摘要（不要复制隐私原文）。
3. 给出推理失败条件：参考音频过短/过吵、语种不匹配、显存不足、官方服务未启动。
4. 模型卡片草稿：GPT-SoVITS 官方预训练、v2Pro、适用语种、许可证、本周未训练少样本权重。
5. 写下周需要但本周未做的：1A/1B/1C、s1/s2、成对权重校验。

# 硬约束 / 禁止事项
- 禁止把“计划训练的音色”写成 ready 少样本音色。
- 禁止编造 F0 数值或相似度。
- 禁止在文档中粘贴密钥或完整身份证/联系方式等授权原件内容。

# 交付物与存放路径
- Project/Documents/Week1/algorithm-handoff.md

# 验收标准
- LHY 不看聊天记录也能完成零样本代理联调。
- WGX 能获得默认语种、参考音频是否就绪、失败提示文案。
- 所有路径都是本机真实路径或明确的相对约定。

# 完成后交给谁
主送 LHY，抄送 WGX 与 CXY。
```

### 2.4 算法本周验收清单

- [ ] WebUI 与 `api_v2.py` 可启动，CUDA 状态已记录。
- [ ] 一套授权音频有效时长落在 8–15 分钟，有抽检。
- [ ] 至少一份官方格式 `.list`。
- [ ] 零样本连续 3 次 WAV 可播放。
- [ ] 固定音色韵律对照样音和听测表齐全。
- [ ] 交接文档含路径、默认值和限制，无假权重。

---

## 3. LHY 系统开发人员

### 3.1 本周角色目标

搭起 FastAPI 业务后端，让前端只通过业务 API 完成上传、授权、任务查询、零样本合成和试听下载。本周适配官方 `api_v2.py` 的零样本推理，不封装训练脚本，不设计页面视觉。

### 3.2 节点总览

| 节点 | 依赖 | 产出 | 交给谁 |
|---|---|---|---|
| LHY-N1 项目骨架 | CXY-N1 | `backend/` 可启动、健康检查、目录 | CXY、WGX |
| LHY-N2 SQLite 最小模型 | CXY-N3 | `Consent` `Voice` `TTSJob` `Audit` 迁移 | CXY |
| LHY-N3 上传 / 授权 / 路径白名单 | CXY-N3、CXY-N5 | `POST /api/audio/upload` | WGX、LJQ |
| LHY-N4 零样本代理 | LJQ-N1、CXY-N3 | `adapters/gpt_sovits` + `POST /api/tts` | WGX、LJQ |
| LHY-N5 任务状态机最小实现 | LHY-N2、LHY-N4 | `GET /api/tasks/{id}`，重启不丢 | WGX |
| LHY-N6 测试与 OpenAPI | LHY-N3–N5 | pytest + OpenAPI 示例 | WGX、CXY |

### 3.3 逐节点工作与提示词

#### LHY-N1 项目骨架

按 Task1 目录创建 FastAPI 应用、环境变量、数据目录、Windows 启动脚本和健康检查。业务进程与官方 `api_v2.py` 分离。

```text
# 角色
你是 FastAPI 后端工程师，协助系统开发人员 LHY 创建第一周项目骨架。只搭可运行空壳和约定，不实现训练，不接前端样式。

# 背景与必读文件
- Project/Documents/Task1. DevelopmentSketch.md（第 4 节目录、第 5 节规范）
- Project/Documents/Task2. DivisionOfLabor(Theoretical).md（LHY 工作内容第 1、11 条）
- Project/Documents/Week1/version-baseline.md
- Project/Documents/Task3. Week1DevelopmentPlan.md（LHY-N1 与第 0.3 节）
- FastAPI 官方文档：https://fastapi.tiangolo.com/

# 本节点唯一目标
在 Project/backend/ 落地可启动的 FastAPI 应用：配置、目录、健康检查、与官方 9880 分离的进程模型。

# 必须完成的工作
1. 创建目录：api/、services/、adapters/gpt_sovits/、modules/{emotion,prosody,safety}/、db/；空模块放 README 说明本周范围。
2. 配置从环境变量读取：DATABASE_URL、DATA_ROOT、GPT_SOVITS_API_BASE（默认 http://127.0.0.1:9880）、日志级别。提供 .env.example，不提交真实 .env。
3. 实现 GET /api/health：返回应用状态，并可选探测 9880 是否可达（探测失败不得让整个后端无法启动）。
4. 提供 Windows 启动说明或 deploy 脚本：先起官方 api_v2.py，再起业务后端；工作目录与短路径建议。
5. data/ 下创建 uploads、datasets、voices、outputs、watermarks；写入 .gitignore。
6. 先写一个健康检查的 pytest，再补实现。

# 硬约束 / 禁止事项
- 禁止把官方 GPT-SoVITS 源码复制进 backend 当依赖分叉。
- 禁止在骨架阶段实现 s1/s2 训练调用。
- 禁止写入假的模型权重或 Mock 音频到 data/ 冒充联调成功。
- 禁止把密钥写进代码。

# 交付物与存放路径
- Project/backend/ 可运行入口
- Project/deploy/ 或 README 中的 Windows 启动步骤
- Project/tests/ 至少 1 个健康检查测试
- .env.example

# 验收标准
- 全新终端能启动业务服务并访问 /api/health。
- 官方 9880 未启动时，业务服务仍能启动，health 中如实报告依赖状态。
- 目录与 Task1 第 4 节一致。

# 完成后交给谁
启动地址交给 WGX；健康检查字段交给 CXY 备案。
```

#### LHY-N2 SQLite 最小模型

落地本周实体：授权、零样本占位音色、合成任务、审计。其余 Task1 实体可建表留空，但不要写假业务。

```text
# 角色
你是数据建模工程师，协助 LHY 实现第一周 SQLite 模型与迁移。先按契约字段建模，再写 CRUD。

# 背景与必读文件
- Project/Documents/Task1. DevelopmentSketch.md（第 6.1–6.2 节）
- Project/Documents/Week1/api-contract-v0.1.md
- Project/Documents/Task3. Week1DevelopmentPlan.md（LHY-N2）
- Project/Documents/Task2. DivisionOfLabor(Theoretical).md（LHY 工作内容第 2 条）

# 本节点唯一目标
用 SQLite 落地 Consent、Voice、TTSJob、Output、Audit 的最小字段，保证任务与音色元数据在进程重启后仍在。

# 必须完成的工作
1. Voice 本周表示零样本占位：status 可用 ready/failed/disabled；gpt_weight_path 与 sovits_weight_path 可空，表示尚未少样本训练。
2. TTSJob 保存 text、text_lang、voice_id、emotion_control（JSON 原文）、prosody_params、status、output_id、error。
3. Output 保存 generation_id、wav_path、created_at；watermark_id 本周可空。
4. Consent 保存授权范围、保存期限、关联上传。
5. Audit 保存 operation、actor、policy_version、timestamp。
6. 提供迁移方式和一条“插入后重启进程仍能读到”的测试思路。

# 硬约束 / 禁止事项
- 禁止用内存字典冒充持久化还称为已完成。
- 禁止本周实现完整权限系统和多租户。
- 禁止把内部权重路径作为公开 API 响应字段。
- 表结构必须能对上契约，不得擅自改枚举字符串。

# 交付物与存放路径
- Project/backend/db/ 模型与迁移
- 字段说明可补进 Project/Documents/Week1/api-contract-v0.1.md 附录，或单独 db 说明

# 验收标准
- 重启业务进程后，已有 job 与 consent 仍可查询。
- Voice 不会因为空权重被标成“少样本 ready”。
- 失败任务不会把 Voice 写成可用训练音色。

# 完成后交给谁
ER/字段说明交给 CXY；voice_id 与 job 状态枚举交给 WGX。
```

#### LHY-N3 上传 / 授权 / 路径白名单

实现上传校验和授权确认，这是本周后端安全底线。

```text
# 角色
你是文件上传与安全工程师，协助 LHY 实现授权音频上传。先写失败用例，再写实现。重点是路径与类型安全。

# 背景与必读文件
- Project/Documents/Week1/api-contract-v0.1.md
- Project/Documents/Week1/safety-policy-draft.md
- Project/Documents/Task1. DevelopmentSketch.md（第 3.1、3.4 节）
- Project/Documents/Task2. DivisionOfLabor(Theoretical).md（LHY 工作内容第 3 条）
- Project/Documents/Task3. Week1DevelopmentPlan.md（LHY-N3）

# 本节点唯一目标
实现 POST /api/audio/upload：校验类型/大小/时长、强制授权确认、规范化到 DATA_ROOT 白名单短路径，并写入 Consent。

# 必须完成的工作
1. 先写测试：非法扩展名、MIME 不匹配、超大文件、路径穿越文件名（../、绝对路径、盘符）、未勾选授权、正常 wav 上传。
2. 实现扩展名与 MIME 检查、大小限制、时长限制（可用 ffprobe 或 soundfile；缺依赖时测试用短 wav fixture）。
3. 存储路径必须落在 DATA_ROOT/uploads 下，文件名使用短 ASCII（uuid 或 hash），禁止保留用户原始路径。
4. 未确认授权不得落库为可用音频。
5. 错误码与契约一致；日志不打印完整用户原始文件名中的个人目录（如有）。
6. 不实现切分/ASR 后台任务（那是第 2 周 /api/datasets）。

# 硬约束 / 禁止事项
- 禁止信任客户端传来的绝对路径。
- 禁止把上传文件直接暴露成静态任意路径下载。
- 禁止为了测试把真实授权人声提交到 Git；测试用合成的短 fixture wav。
- 禁止本周做多 GPU 或批量上传队列优化。

# 交付物与存放路径
- Project/backend/api/ 上传路由
- Project/tests/ 对应单测与接口测试
- 请求/响应示例更新到 OpenAPI 或契约附录

# 验收标准
- 契约中的上传成功/失败示例都能复现。
- 路径穿越用例全部被拒绝。
- WGX 只需 multipart 字段名即可对接。

# 完成后交给谁
字段与错误文案交给 WGX；抽检规则可与 LJQ 的质量规范对齐但以后端校验为准。
```

#### LHY-N4 零样本代理

业务 `POST /api/tts` 通过 HTTP 调用官方 `/tts`，把参考音频限制在白名单路径内，把官方音频流落盘为 Output。

```text
# 角色
你是模型服务适配工程师，协助 LHY 编写 GPT-SoVITS 零样本适配层。官方 api_v2.py 是真值，业务层只做校验、映射、落盘和错误转换。

# 背景与必读文件
- Reference-Project/GPT-SoVITS-main/api_v2.py（TTS_Request 与 /tts 行为：成功返回 wav 流，失败 400 JSON）
- Project/Documents/Week1/api-contract-v0.1.md
- Project/Documents/Week1/algorithm-handoff.md 或 zeroshot-run-log.md
- Project/Documents/Task2. DivisionOfLabor(Theoretical).md（LHY 工作内容第 4 条）
- Project/Documents/Task3. Week1DevelopmentPlan.md（LHY-N4）

# 本节点唯一目标
实现 adapters/gpt_sovits 客户端和 POST /api/tts 零样本代理：前端永不直连 9880。

# 必须完成的工作
1. 客户端封装官方 POST /tts，字段映射：text、text_lang、ref_audio_path、prompt_text、prompt_lang、speed_factor。
2. ref_audio_path 只能来自已上传且授权的白名单文件，或 LJQ 交接的受控路径；拒绝任意用户字符串路径。
3. 官方 200 wav 流保存到 data/outputs/，写入 Output.generation_id 与 TTSJob。
4. 官方不可达、超时、400 必须转成契约错误码；保存错误摘要。
5. /set_gpt_weights 与 /set_sovits_weights 可写客户端方法但本周不接训练产物；不要在本周切换未知权重。
6. 先用 TestClient + httpx mock 官方响应写接口测试；再在真实 9880 上做至少一次可选集成测试（标记 gpu/integration）。

# 硬约束 / 禁止事项
- 禁止 subprocess 调用训练脚本。
- 禁止前端或适配层修改官方模型文件。
- 禁止用预置假 wav 当作代理成功（mock 仅限单测隔离）。
- 禁止日志打印完整官方请求中的无关本地隐私路径以外的必要排错信息时，需脱敏用户目录。

# 交付物与存放路径
- Project/backend/adapters/gpt_sovits/
- Project/backend/api/ TTS 路由
- 集成测试说明：如何启动 9880 再跑

# 验收标准
- 真实联调至少 1 次经业务 API 得到可播放 WAV。
- 与 LJQ 官方 3 次实验使用同一条回归文本时，业务链路也能出音。
- 9880 关闭时，任务失败原因明确，服务不崩溃。

# 完成后交给谁
TTS 示例请求交给 WGX；真实耗时和失败码交给 CXY 与 LJQ。
```

#### LHY-N5 任务状态机最小实现

合成改为异步任务：创建后返回 `job_id`，前端轮询。本周单 GPU 可先串行执行一个推理，不需要完整队列产品化，但状态必须可查询且重启可恢复记录。

```text
# 角色
你是任务编排工程师，协助 LHY 实现第一周最小状态机。先保证状态诚实，再谈进度百分比。

# 背景与必读文件
- Project/Documents/Week1/api-contract-v0.1.md
- Project/Documents/Task1. DevelopmentSketch.md（任务状态与风险：显存争用）
- Project/Documents/Task2. DivisionOfLabor(Theoretical).md（LHY 工作内容第 5、6 条）
- Project/Documents/Task3. Week1DevelopmentPlan.md（LHY-N5；cancelled 本周可不实现）

# 本节点唯一目标
实现 queued → processing → succeeded/failed，GET /api/tasks/{task_id} 返回阶段、错误摘要；进程重启后记录仍在。

# 必须完成的工作
1. POST /api/tts 立即返回 job_id 与 queued；后台执行官方调用。
2. processing 时记录 stage（例如 validate / infer / save）。
3. 成功写 output_id；失败写 error.code/message，不产生假 Output。
4. 本周可用单线程/单 worker 串行，避免与人工官方 WebUI 抢 GPU；文档写明互斥是人工约定。
5. 测试：查询不存在任务、失败任务、重启后读库。
6. 超时可先做硬超时配置，取消按钮本周不做也要在 API 文档标明。

# 硬约束 / 禁止事项
- 禁止成功状态但文件不存在。
- 禁止失败任务把 Voice 标成新的训练完成音色。
- 禁止本周实现多 GPU 调度。
- 禁止用前端计时器冒充服务端状态。

# 交付物与存放路径
- Project/backend/services/ 任务执行
- GET /api/tasks/{task_id} 与 GET /api/outputs/{output_id}

# 验收标准
- WGX 能仅靠轮询渲染 queued/processing/succeeded/failed。
- 重启业务进程后，已有终态任务仍能查到。
- 输出下载不暴露 DATA_ROOT 以外的文件。

# 完成后交给谁
状态枚举、轮询建议间隔交给 WGX。
```

#### LHY-N6 测试与 OpenAPI

补齐本周测试和给前端的说明书，作为联调输入。

```text
# 角色
你是后端测试与文档工程师，协助 LHY 补齐第一周 pytest 与 OpenAPI 示例。测试必须覆盖正常、异常和路径攻击；集成测试与单测分开。

# 背景与必读文件
- Project/Documents/Week1/api-contract-v0.1.md
- Project/Documents/Task1. DevelopmentSketch.md（第 5.3 节最小复核、第 8.1 节测试层级）
- Project/Documents/Task2. DivisionOfLabor(Theoretical).md（LHY 工作内容第 12 条、AI 辅助方式）
- 已实现的 backend 代码

# 本节点唯一目标
让核心上传、任务、TTS 代理、输出下载的接口测试可重复运行，并输出前端可复制的 OpenAPI/示例。

# 必须完成的工作
1. 列出本周测试清单：upload 合法/非法、路径穿越、未授权、health、tts 创建、task 查询、官方失败转换、output 下载权限。
2. 单测默认 mock 9880；名为 integration 的测试才访问真实 api_v2。
3. 生成或导出 OpenAPI，并手工补 3 个前端最需要的示例：上传、创建 TTS、轮询到 succeeded。
4. 用第二种审查视角自检：路径白名单、状态一致性、日志脱敏；写出采纳/拒绝项。
5. 修复后要求重启服务再跑测试，不要只热重载口头宣布。

# 硬约束 / 禁止事项
- 禁止删除失败测试来让 CI 变绿。
- 禁止把 GPU 集成测试当成默认必须在无显卡机器通过。
- 禁止在示例中写真实密钥或个人音频路径。
- 禁止宣称训练接口已测通。

# 交付物与存放路径
- Project/tests/ 本周测试
- Project/Documents/Week1/ 下的 OpenAPI 导出或 frontend-handoff 示例（可写在 api-contract-v0.1.md 更新节）

# 验收标准
- 无 GPU 时纯单测可重复通过。
- 有 GPU 且 9880 已启动时，至少一次真实代理成功有记录。
- WGX 不需要读源码即可对接。

# 完成后交给谁
OpenAPI 与示例交给 WGX；测试报告摘要交给 CXY。
```

### 3.4 后端本周验收清单

- [ ] FastAPI 与 `/api/health` 在全新终端可启动。
- [ ] 上传校验、授权、路径白名单测试通过。
- [ ] `POST /api/tts` 经官方 `/tts` 代理，前端不直连 9880。
- [ ] 任务状态重启后可查，失败不产生假成功输出。
- [ ] OpenAPI/示例已交给前端。
- [ ] 未实现的训练/水印接口未对外称为完成。

---

## 4. WGX 前端交互人员

### 4.1 本周角色目标

用 Vue 3 搭起演示壳，让用户走通「上传并确认授权 → 提交零样本合成 → 播放/下载」。本周情感控件只占位，不接分类器；不做完整历史追溯和水印检测页。不直连官方 9880，不实现训练算法。

### 4.2 节点总览

| 节点 | 依赖 | 产出 | 交给谁 |
|---|---|---|---|
| WGX-N1 脚手架与信息架构 | 无（对照草图） | Vue 3 工程 + 页面清单 | CXY |
| WGX-N2 低保真原型与组件清单 | WGX-N1 | 原型说明 + 状态清单 | CXY、LHY |
| WGX-N3 上传与授权页 | CXY-N3、LHY-N3 | 上传授权流程 | LHY |
| WGX-N4 TTS 合成表单壳 | CXY-N4 | 合成页占位控件 | LHY、LJQ |
| WGX-N5 播放器与空失败态 | WGX-N4 | 播放/下载/生成标识占位 | CXY |
| WGX-N6 对接后端零样本 | LHY-N6、LHY-N4 | 浏览器实操通过记录 | CXY |

### 4.3 逐节点工作与提示词

#### WGX-N1 脚手架与信息架构

按开发草图四步建 Vue 3 路由：数据准备、音色（本周只展示占位）、合成、结果。先能本地启动。

```text
# 角色
你是 Vue 3 前端工程师，协助 WGX 创建第一周演示脚手架和信息架构。先定页面和路由，再堆组件。

# 背景与必读文件
- Project/Documents/Task1. DevelopmentSketch.md（第 1.2 节用户闭环、第 4 节 frontend/）
- Project/Documents/Task2. DivisionOfLabor(Theoretical).md（WGX 工作内容第 1 条）
- Project/Documents/开发草图.png（四步：数据准备、音色克隆、合成、结果展示）
- Project/Documents/Task3. Week1DevelopmentPlan.md（第 4 章，本周不做追溯/水印页）

# 本节点唯一目标
初始化 Project/frontend/ 的 Vue 3 工程，落地本周四个主页面的路由和空状态标题，统一中文文案方向。

# 必须完成的工作
1. 使用与现有仓库不冲突的 Vue 3 + Vite 常规脚手架；不要引入无关 UI 框架全家桶，除非团队已约定。
2. 路由建议：/upload、/voices、/tts、/result；voices 本周仅说明“零样本参考音频，少样本训练第 2 周”。
3. 画出信息架构：每页入口、主按钮、返回关系。
4. 配置开发代理时只指向业务后端，不指向 9880。
5. README 写明 npm 安装与启动。

# 硬约束 / 禁止事项
- 禁止页面直接 fetch 127.0.0.1:9880。
- 禁止本周做登录、分享、权限系统。
- 禁止用假波形图声称已经合成成功。
- 禁止把案例里的 90% 相似度写到界面营销文案。

# 交付物与存放路径
- Project/frontend/ 可启动工程
- 信息架构写入 Project/Documents/Week1/ 或前端 README

# 验收标准
- npm 启动后四个路由可切换。
- 页面标题与开发草图四步对应。
- 无业务后端时页面仍能打开并显示空状态，而不是白屏报死。

# 完成后交给谁
路由清单交给 CXY；所需接口顺序交给 LHY。
```

#### WGX-N2 低保真原型与组件清单

补齐空、加载、成功、失败、离线等状态，避免联调时才发现没有失败页。

```text
# 角色
你是交互设计助手，协助 WGX 输出第一周低保真说明和组件清单。可用 Markdown 线框，不要求精美视觉。

# 背景与必读文件
- Project/Documents/Task2. DivisionOfLabor(Theoretical).md（WGX 工作内容第 2 条）
- Project/Documents/Week1/api-contract-v0.1.md（若已冻结）
- Project/Documents/Task3. Week1DevelopmentPlan.md（WGX-N2）

# 本节点唯一目标
列出本周组件和每页的空/加载/成功/失败/离线/未授权状态，以及文案原则。

# 必须完成的工作
1. 组件清单：上传区、授权复选、任务进度、音色只读卡片、TTS 表单、播放器、错误条。
2. 为 queued/processing/succeeded/failed 各写一句用户能懂的中文。
3. 明确不可用音色、服务离线、上传校验失败的展示。
4. 标注本周不做：水印检测结果页、完整 lineage、A/B 高级对比器（N5 只需单条播放）。
5. 向 LHY 列出需要的分页/轮询/错误字段，若契约已有则对照差异。

# 硬约束 / 禁止事项
- 禁止发明契约里没有的状态字符串。
- 禁止在原型里承诺“一键训练 10 分钟必成功”。
- 禁止展示内部绝对路径或密钥。

# 交付物与存放路径
- Project/Documents/Week1/ 可写 frontend-prototype.md
- 或放在 frontend/docs/prototype.md

# 验收标准
- 每个主按钮都有失败态去向。
- LHY 能从清单看出轮询和错误展示需求。
- CXY 能据此讲演示路径。

# 完成后交给谁
原型给 CXY 评审；字段需求给 LHY。
```

#### WGX-N3 上传与授权页

实现用户能选择音频、勾选授权、看到校验错误和上传进度。授权未确认不能提交。

```text
# 角色
你是 Vue 表单工程师，协助 WGX 实现上传与授权页。严格按契约字段对接，先做前端校验提示，最终以后端错误为准。

# 背景与必读文件
- Project/Documents/Week1/api-contract-v0.1.md
- Project/Documents/Week1/safety-policy-draft.md
- Project/Documents/Task2. DivisionOfLabor(Theoretical).md（WGX 工作内容第 3 条）
- Project/Documents/Task3. Week1DevelopmentPlan.md（WGX-N3）

# 本节点唯一目标
实现 /upload：格式与时长说明、授权确认、进度、成功/失败原因；禁止绕过业务后端。

# 必须完成的工作
1. 展示允许的格式、时长和“必须授权”说明。
2. 授权复选未勾选时禁用提交。
3. 调用 POST /api/audio/upload，展示进度与后端错误码对应文案。
4. 成功后保存业务返回的音频/consent 标识，供合成页使用。
5. 处理离线、413/校验失败、未授权。
6. 不用真实隐私音频做仓库内截图素材。

# 硬约束 / 禁止事项
- 禁止把文件直接 POST 到 9880。
- 禁止在控制台打印完整本地文件绝对路径作为产品功能。
- 禁止跳过授权确认的“开发者后门”留在演示分支。
- 禁止本周做数据集切分进度的假动画冒充训练。

# 交付物与存放路径
- Project/frontend/ 上传页组件
- 交互说明更新到原型文档

# 验收标准
- 未授权无法上传成功。
- 后端拒绝时用户能看懂下一步。
- 刷新后应能从后端或明确提示中恢复，不假装本地假成功。

# 完成后交给谁
联调问题反馈给 LHY；授权文案给 CXY 审核。
```

#### WGX-N4 TTS 合成表单壳

实现合成页：文本、语种、参考音频/占位音色、情感标签与强度占位、语速。情感模式本周只展示，不调用分类器。

```text
# 角色
你是 Vue 表单工程师，协助 WGX 实现 TTS 合成表单壳。字段必须与契约和 CXY-N4 标签一致，本周不接自动情感 API。

# 背景与必读文件
- Project/Documents/Week1/emotion-and-regression-texts.md
- Project/Documents/Week1/api-contract-v0.1.md
- Project/Documents/Task1. DevelopmentSketch.md（第 3.3 节控制对象）
- Project/Documents/Task3. Week1DevelopmentPlan.md（WGX-N4）

# 本节点唯一目标
实现 /tts 表单：文本、语种、音色/参考音频、手动情感占位、强度、语速；提交走业务 POST /api/tts（可先接到 mock，N6 再换真后端）。

# 必须完成的工作
1. 文本框与字数提示；预留回归文本快捷填入（5 条固定文本）。
2. 语种默认 zh。
3. 情感下拉 4 类 + 强度 3 档，旁边文案写“本周为占位，不自动识别”。
4. 语速控件映射 speed 或 speed_factor，范围与交接文档一致；未知则先 0.8–1.2。
5. 自动模式开关可禁用或显示“第 3 周”。
6. 提交前做前端必填校验；参数按契约组装 emotion_control JSON（即使后端本周只原样存储）。

# 硬约束 / 禁止事项
- 禁止调用未约定的第三方情感识别 SaaS。
- 禁止把占位标签写成“已识别为开心 80%”。
- 禁止直连官方 /tts。
- 禁止在表单展示内部权重路径。

# 交付物与存放路径
- Project/frontend/ 合成页
- 控件与字段对照表（可附原型文档）

# 验收标准
- 5 条回归文本可一键填入。
- 提交 payload 字段名与契约一致。
- 用户能理解情感控件本周不会自动分类。

# 完成后交给谁
默认值问题反馈 LJQ；字段差异反馈 LHY。
```

#### WGX-N5 播放器与空失败态

结果页能播放、暂停、下载，并展示 AI 生成标识占位。空数据和失败必须可理解。

```text
# 角色
你是前端音频体验工程师，协助 WGX 实现第一周播放器与结果状态。先保证真实 wav 能播，再谈波形美化。

# 背景与必读文件
- Project/Documents/Task2. DivisionOfLabor(Theoretical).md（WGX 工作内容第 8、9 条）
- Project/Documents/Week1/api-contract-v0.1.md（outputs 与 generation_id）
- Project/Documents/Task3. Week1DevelopmentPlan.md（WGX-N5）

# 本节点唯一目标
实现结果区：播放/暂停、进度、音量、下载、AI 生成标识占位，以及空/失败/处理中状态。

# 必须完成的工作
1. 使用业务 GET /api/outputs/{output_id} 的可访问 URL，不拼接本地磁盘路径。
2. 展示 generation_id 或“本音频由 AI 生成”文案占位。
3. processing 显示进度或阶段文本；failed 显示后端错误摘要的用户版。
4. 下载文件名使用业务 id，不暴露服务器绝对路径。
5. 本周 A/B 对照可以是两个结果手动切换播放，不强制波形对比组件。

# 硬约束 / 禁止事项
- 禁止用无声假文件做演示录屏还称为通过。
- 禁止展示水印密钥或检测概率假数据。
- 禁止自动外链分享未授权音频。
- 修复后必须在浏览器里点播放，不能只看组件挂载。

# 交付物与存放路径
- Project/frontend/ 播放器与结果页
- 状态文案表

# 验收标准
- 真实 wav 在目标 Windows 浏览器可播可下载。
- 失败和空状态不白屏。
- 生成标识可见。

# 完成后交给谁
演示路径交给 CXY；播放 URL 问题交给 LHY。
```

#### WGX-N6 对接后端零样本

按 OpenAPI 把上传、创建任务、轮询、播放串起来，在目标浏览器完整点一遍。

```text
# 角色
你是前端联调工程师，协助 WGX 把第一周页面接到真实业务后端。必须在 Windows 目标浏览器实操，而不是只看网络面板截图。

# 背景与必读文件
- LHY 提供的 OpenAPI 或 api-contract-v0.1.md 更新节
- Project/Documents/Week1/algorithm-handoff.md
- Project/Documents/Task2. DivisionOfLabor(Theoretical).md（WGX 验收标准）
- Project/Documents/Task3. Week1DevelopmentPlan.md（本周前端闭环定义）

# 本节点唯一目标
完成浏览器端路径：授权上传 → 选择该参考音频 → 填回归文本 → 提交合成 → 轮询至 succeeded → 播放下载。

# 必须完成的工作
1. 按契约实现轮询 GET /api/tasks/{task_id}，注意停止条件，避免无限请求。
2. 处理竞态：用户重复提交、切换页面再回来，状态以服务端为准。
3. 记录浏览器、版本、逐步截图或操作记录、控制台错误、实际播放结果。
4. 若后端未就绪，页面应显示离线，而不是用前端假成功。
5. 走查响应式基本可用性（桌面为主，窄屏不严重错位即可）。

# 硬约束 / 禁止事项
- 禁止为演示在前端写死一个本地 wav 当作合成结果。
- 禁止直连 9880 来“先给老师看”。
- 禁止忽略授权页直接进合成。
- 禁止把联调失败改成“后端问题”而不留下复现步骤。

# 交付物与存放路径
- 浏览器验证记录：Project/Documents/Week1/frontend-browser-check.md
- 必要的前端 bugfix

# 验收标准
- 目标 Windows 浏览器上完整走通一次真实音频播放。
- 刷新后任务状态与后端一致。
- 有一份给 CXY 的演示操作顺序。

# 完成后交给谁
验证记录交给 CXY，作为 CXY-N6 证据；缺陷清单交给 LHY/LJQ。
```

### 4.4 前端本周验收清单

- [ ] Vue 3 四个主路由可启动。
- [ ] 上传必须勾选授权，错误可理解。
- [ ] 合成表单字段与契约一致，情感为占位。
- [ ] 播放器能播业务 API 返回的真实 WAV。
- [ ] 不直连 9880，不暴露内部路径。
- [ ] 目标浏览器实操记录已交给队长。

---

## 附录 A. 跨角色交接表

| 产出 | 来源 | 接收方 | 最晚节点 |
|---|---|---|---|
| 版本基线表 | CXY-N1，LJQ/LHY 填实测 | 全员 | 环境开工前 |
| 需求与证据矩阵 | CXY-N2 | 全员 | 接口冻结前 |
| 接口契约 v0.1 | CXY-N3 | LHY、WGX、LJQ | LHY-N3 / WGX-N3 前 |
| 情感标签与 5 条回归文本 | CXY-N4 | LJQ、WGX、LHY | LJQ-N4 / WGX-N4 前 |
| 安全策略与授权文案 | CXY-N5 | LHY、WGX、LJQ | 上传开发前 |
| 官方 9880 可访问证明 | LJQ-N1 | LHY、CXY | LHY-N4 前 |
| 授权音频、有效分钟数、5 秒参考片段 | LJQ-N2 | CXY、LHY | 零样本前 |
| `.list` 与数据目录 | LJQ-N3 | LHY、CXY | 本周结束（供第 2 周） |
| 零样本 3 次 WAV 与日志 | LJQ-N4 | CXY、LHY | 周五验收前 |
| 韵律对照样音与听测 | LJQ-N5 | CXY、WGX | 周五验收前 |
| 算法交接（路径/默认值/限制） | LJQ-N6 | LHY、WGX、CXY | 联调前尽量给出，周五必须齐 |
| 后端地址与 health | LHY-N1 | WGX、CXY | 前端联调前 |
| 上传 API | LHY-N3 | WGX | WGX-N3 |
| 零样本代理 TTS API | LHY-N4 | WGX、LJQ | WGX-N6 |
| 任务状态与 OpenAPI 示例 | LHY-N5/N6 | WGX、CXY | WGX-N6 |
| 浏览器验证记录 | WGX-N6 | CXY | CXY-N6 |
| 本周验收结论 | CXY-N6 | 全员 | 周五 |

## 附录 B. 建议会议节点

| 时间 | 会议 | 必须带着的东西 |
|---|---|---|
| 周初 | 规范冻结 | CXY-N1 草稿、环境分工 |
| 环境就绪后 | 接口冻结 | CXY-N3 草稿，LHY/WGX 当场确认字段 |
| 零样本跑通后 | 代理联调 | LJQ 的 9880 样音 + LHY 的业务 API |
| 周五 | 本周验收 | 三个验收项的原始证据，填写 `week1-acceptance.md` |

周五验收顺序固定为：先听 LJQ 官方零样本与对照样音，再验 LHY 业务代理与安全上传，最后由 WGX 在目标浏览器走通页面。任一层失败时，上层不得用 Mock 结果顶替。

## 附录 C. 本周团队验收清单

对照 Task1 第 1 周，全员共同勾选。没有文件路径的项不得勾选。

**基线与规范**

- [ ] GPU / CUDA / Python / PyTorch、GPT-SoVITS 提交、`v2Pro` 已写入 `version-baseline.md` 实测值。
- [ ] 接口契约 v0.1 已冻结，错误码与状态枚举前后端一致。
- [ ] 4 类情感标签、3 档强度占位、5 条固定回归文本已发布。
- [ ] 敏感词策略、授权保存期限、水印候选（AudioSeal 优先评估）已书面记录。

**数据与算法**

- [ ] 一套 8–15 分钟授权测试语音，有效分钟数和抽检表可核对。
- [ ] 官方 WebUI / `api_v2.py` 已跑通，至少一份标准 `.list`。
- [ ] 零样本链路连续 3 次生成可播放 WAV，日志与文件一一对应。
- [ ] 固定音色下的韵律对照样音与听测表齐全，结论未夸大为解耦模型。

**业务与界面**

- [ ] 上传校验、授权确认、路径白名单可重复测试。
- [ ] 前端只通过业务 API 完成上传、查询、合成、播放，不直连 `9880`。
- [ ] 任务记录在服务重启后可查询；失败任务没有假成功输出。
- [ ] 目标 Windows 浏览器实操走通「授权上传 → 合成 → 播放」。

**范围诚实性**

- [ ] 未把 `s1_train.py` / `s2_train.py`、情感分类器、水印嵌入检测写成已实现。
- [ ] 未使用 Mock 音频作为本周里程碑证据。
- [ ] 未完成项已标为增强或预研，并写入 `week1-acceptance.md`。

---

使用方式：每人只复制自己章节中对应节点的提示词，完成交付物后再进入下一节点。提示词里的路径以本仓库为准；若文件尚未生成，先完成该节点的上游依赖，不要让 AI 用假日志填空。