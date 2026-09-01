# LOOKME — CXY 视角（Week 1）

> 你是 **CXY**：范围、数据、评测、文档与验收负责人，也是 Week 1 的**协调入口**。  
> 你不替 LHY/WGX/LJQ 写主责代码，但要**先发出 DoD 和契约**，并在最后**收证据、下结论**。  
> 细节节点见：[WorkScheduleGuide/CXY Nodes.md](Project/Documents/Week1/WorkScheduleGuide/CXY%20Nodes.md)  
> CXY-N1 交付物：[CXY-N1 Scope and DoD.md](Project/Documents/Week1/CXY-N1%20Scope%20and%20DoD.md)

---

## 你本周只有 3 个节点

```text
CXY-N1  冻结范围与验收口径
   ↓
CXY-N2  授权资产与契约 v0.1
   ↓
（等三人交付汇合）
   ↓
CXY-N3  预演、证据与验收
```

---

## 第一步：你现在立刻做 CXY-N1

**要产出**

- Week 1 DoD（本周什么叫「过」）
- 四页侧栏导航文案（音频处理 / 音色克隆 / 文本合成 / 结果管理）
- 禁止事项清单（不做训练、API、数据库、2×2 同屏、假音频等）

**依据文档**

- [newplan.md](Project/Documents/newplan.md)
- [New-Task1. AI Project Execution Plan.md](Project/Documents/New-Task1.%20AI%20Project%20Execution%20Plan.md)

**做完之后发给谁**

| 交给 | 他们去干什么 |
|---|---|
| **WGX** | 开始 **WGX-N1**（页面架构，对齐导航文案） |
| **LHY** | 开始 **LHY-N1**（工程骨架，对齐模块边界） |
| **LJQ** | 可对齐验收口径；同时 LJQ 本来就可以并行做 **LJQ-N1**（环境锁定） |

**你要做的协调动作**

- 把 DoD 和导航文案发到群里，请三人回复「已接收」或提出问题。
- 未确认前，他们的相关节点记为「待交接」。

---

## 第二步：接着做 CXY-N2（依赖 N1 完成）

**要产出**

- 授权音频清单（一段短参考 + 一段长音频，附授权说明）
- 1 条试听文本 + 5 条回归文本
- **contract-v0.1**（四个 service 的函数名、字段、统一 `AppError`）

**做完之后发给谁**

| 交给 | 他们去干什么 |
|---|---|
| **LJQ** | **LJQ-N2** 用统一参考/文本出 3 条真实 WAV；**LJQ-N3** 用长音频做切分/ASR 并对照契约字段 |
| **LHY** | **LHY-N2** 按契约写 services/schemas；**LHY-N3** 接 LJQ 的真实 TTS 参数 |
| **WGX** | **WGX-N2** 按契约字段搭四页空壳控件 |

**说明**

- v0.1 只是草案；**Week 2 保存第一个音色前**才正式冻结成 v1.0。
- 你发完 N2 后，**你自己的编码型工作告一段落**，进入「跟进度 + 收交接」模式。

---

## 第三步：你等大家 —— 谁该在什么顺序干活

下面四条链**并行**，不必互相等页面或模型全部就绪：

```text
LJQ：N1 环境 → N2 三条WAV → N3 切分/ASR说明
LHY：N1 骨架 → N2 services → N3 桩函数/错误 → N4 集成 app.py
WGX：N1 架构 → N2 四页空壳 → N3 切换/State → N4 浏览器联调
```

**会回到你手里的关键交付**（收齐后再做 CXY-N3）

| 谁 | 节点 | 交什么给你 | 用途 |
|---|---|---|---|
| LJQ | N1 | 个人环境基线 + [全组环境矩阵 §6](Project/Documents/GPU%20Environment%20Baseline.md) | N3 验收 GPU/环境 |
| LJQ | N2 | 3 条本机真实 WAV + 日志 | N3 核心证据 |
| LJQ | N3 | 切分/ASR 结果 + 算法 I/O 说明 | N3 核心证据 |
| LHY | N4 | 一键启动的集成版 `app.py` | N3 现场预演 |
| WGX | N4 | 浏览器切换截图 + 联调记录 | N3 页面证据 |

**硬依赖（缺了不能验收）**

- LJQ-N3、LHY-N4

**软依赖（初次预演可稍后补，正式验收前必须有）**

- WGX-N4

**汇合点**

- 全员在 **LHY-N4**（集成）和 **LJQ-N3**（算法证据）处汇合；你不在中间写代码，只跟踪节点状态。

---

## 第四步：收齐后你做 CXY-N3

**输入**

- 上表里的 WAV、切分/ASR、集成 app、浏览器截图、契约 v0.1、环境矩阵

**你要做**

1. 按 Week 1 DoD **逐项现场预演**（不要只看口头汇报）
2. 填验收表：通过 / 部分通过 / 失败
3. 整理证据清单（路径、日志、截图）
4. 排出阻断问题优先级和负责人
5. 宣布：**能否进入 Week 2**

**Week 1 Demo 时你在台上展示**

- 契约草案、证据清单、验收结论（LHY 启动、WGX 切页、LJQ 播 WAV 由各自演示）

**特殊判定**

- 只有官方 WebUI 能出声、本项目 `app.py` 还没接入 → 记 **「部分通过」**，不写成完整闭环
- Mock 音频、预录 WAV、AI 口头判断 → **不能**当验收证据

---

## 一张图：你的时间线

```text
你：  [N1 DoD/导航] → [N2 资产/契约] → ……跟进度…… → [N3 验收]

WGX：      N1 ──→ N2 ──→ N3 ──→ N4 ────────────────┐
LHY：      N1 ──→ N2 ──→ N3 ──→ N4 ────────────────┤→ 你 N3
LJQ：      N1 ──→ N2 ──→ N3 ───────────────────────┘
```

---

## 作为主导者，N2 之后你要盯的 4 件事

1. **交接确认**：每次有人发出产物，要求接收方半天内回复「已接收」或问题（见 [Week1 Development Guide §6](Project/Documents/Week1/Week1%20Development%20Guide.md)）。
2. **阻断升级**：有人节点「阻塞」（尤其 LJQ 环境/WAV 不出声）→ 当天排优先级，必要时砍页面精修、先修环境。
3. **范围守护**：有人提训练、FastAPI、第五页、2×2 同屏 → 用 N1 禁止清单挡回去。
4. **证据先行**：验收前向 LJQ 要 WAV 路径和日志，向 LHY 要启动命令，向 WGX 要截图——缺一项就不过。

---

## 文档索引（需要时再点开）

| 文档 | 用途 |
|---|---|
| [WorkScheduleGuide/CXY Nodes.md](Project/Documents/Week1/WorkScheduleGuide/CXY%20Nodes.md) | 你的三节点全文 + AI 提示词 |
| [CXY-N1 Scope and DoD.md](Project/Documents/Week1/CXY-N1%20Scope%20and%20DoD.md) | CXY-N1 已冻结的范围与 DoD |
| [Week1/Week1 Development Guide.md](Project/Documents/Week1/Week1%20Development%20Guide.md) | 四人总览、依赖图、交接表 |
| [Week1/WorkScheduleGuide/](Project/Documents/Week1/WorkScheduleGuide/) | 组员各自节点 |
| [GPU Environment Baseline.md](Project/Documents/GPU%20Environment%20Baseline.md) | 40/50 系环境怎么记录 |
| [env/README.md](Project/Documents/env/README.md) | 个人环境基线放哪 |

---

## Week 1 过线标准（你 N1 里要写进 DoD 的摘要）

- [ ] 一个命令打开 Gradio；侧栏四项，主区一次一页；环境状态不是第五页
- [ ] 本机 3 条真实 WAV + 一次真实切分/ASR
- [ ] services / schemas / 错误结构有骨架
- [ ] 授权素材、契约 v0.1、交接记录完整
- [ ] 四人环境矩阵各有记录

**Week 1 结束后**：根据实际完成情况，再微调 [Week2 计划](Project/Documents/Week2/Week2%20Development%20Guide.md)。
