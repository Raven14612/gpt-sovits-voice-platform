# Week 3 节点化开发计划：总览

> 本周目标：完成“选音色 → 输入文本 → 真实合成 → 结果页播放/下载/历史 → 复用回填”的产品闭环；接入手动情绪参考切换，并完成轻量双条件对照。  
> 工作方式：**CXY 与 LHY 两条关键链**并行，在契约冻结、事件集成和最终验收处汇合；LJQ/WGX 提供非阻断补充证据。  
> 协作模式真值：[Team Plan v2 (CXY-Led).md](../Team%20Plan%20v2%20(CXY-Led).md) · 决议台账：[Decisions.md](../Decisions.md)

## 1. 三个协作指标

每个节点必须回答：

1. **哪些人的工作会影响我？**  
   只描述上游依赖，不写时间：
   - 无依赖：可独立开始；
   - 软依赖：可先工作，收到结果后对齐；
   - 硬依赖：必须收到指定交付物才能继续。

2. **我需要交付什么内容？**  
   必须是可检查的代码、页面、真实音频、JSON、日志、测试或文档。

3. **谁需要等待我完成该工作？**  
   写明接收人和用途；没有下游时写“无”。

节点状态沿用 Week 1/2：未开始、可开始、进行中、待交接、已完成、阻塞。

### 执行节奏与容量

- 单个节点预计不超过 **1.5 人日**；周三中午前必须有可集成的中性合成与历史服务最小版本。
- `tts_service` 与 `history_service` 按冻结契约并行实现，只有最终“合成成功后写历史”绑定需要汇合。
- 情绪样本追加属于条件功能：周三前没有合法同说话人素材，立即按“中性必做、其他情绪置灰”收口。
- 周四完成 5 条回归、跨页闭环与重启预演；周五不再增加主功能。

## 2. 执行文件与本周负载

| 角色 | 执行文件 | 本周范围 | 节点数 |
|---|---|---|---:|
| **CXY** | [CXY Nodes.md](WorkScheduleGuide/CXY%20Nodes.md) | 契约 v2.0 冻结、合成参数与情绪映射、合成页与结果页、回归与双条件对照、验收 | 5 |
| **LHY** | [LHY Nodes.md](WorkScheduleGuide/LHY%20Nodes.md) | `tts_service`、`history_service`、失败隔离与历史恢复、事件集成 | 4 |
| LJQ | [LJQ Nodes.md](WorkScheduleGuide/LJQ%20Nodes.md) | 人工听测与情绪素材（非阻断） | 1 |
| WGX | [WGX Nodes.md](WorkScheduleGuide/WGX%20Nodes.md) | 浏览器冒烟与截图归档（非阻断） | 1 |

参考文档：[GPU Environment Baseline.md](../GPU%20Environment%20Baseline.md)（环境矩阵由 CXY 维护）。

交接只用一种格式：`[节点ID] 产物路径 + 一行说明 + 已知限制`，**不需要接收人回复确认**；异议按单条书面问题写入 [Decisions.md](../Decisions.md)，CXY 24 小时内裁定。

## 3. 工程主流程

```mermaid
flowchart LR
    VoiceList[已保存音色] --> SynthPage[合成页选音色与文本]
    SynthPage --> Emotion[选择情绪与高级设置]
    Emotion --> TTS[tts_service真实合成]
    TTS --> Output[output.wav]
    Output --> History[写入history.json]
    History --> ResultPage[切到结果页]
    ResultPage --> Reuse[复用回填合成页]
```

情绪与对照（本周最小范围）：

```text
固定 voice_id + 固定文本 + 固定引擎
→ 只换 emotion_refs（中性 / 开心 / 悲伤）
→ 或只改 speed_factor / fragment_interval
→ 记录：明显 / 较弱 / 无效 / 失真 / 音色漂移
```

自动情绪分类如有余力可作为**默认关闭**的实验开关，**不作为本周 DoD**。

## 4. 节点链

```text
CXY（关键链）：
  CXY-N1 契约v2.0冻结
    ├→ CXY-N2 合成参数与情绪映射 ─────┐
    └→ CXY-N3 合成页与结果页（含跨页跳页与复用State）
                                      ↓
                            CXY-N4 回归与双条件对照 ─→ CXY-N5 闭环验收决议

LHY（关键链）：
  LHY-N1 tts_service合成 ─┐
  LHY-N2 history_service与原子索引 ─┴→ LHY-N3 失败隔离与历史重启恢复
    → LHY-N4 合成页与结果页事件集成

LJQ（旁路）：LJQ-N1 人工听测与情绪素材
WGX（旁路）：WGX-N1 浏览器冒烟与截图归档
```

## 5. 跨角色依赖

```mermaid
flowchart TD
    CXY1[CXY-N1契约v2.0] --> CXY2[CXY-N2参数与情绪映射]
    CXY1 --> CXY3[CXY-N3合成页结果页]
    CXY2 --> CXY4[CXY-N4回归与对照]
    CXY3 --> CXY4
    CXY4 --> CXY5[CXY-N5闭环验收]

    LHY1[LHY-N1tts_service] --> LHY3[LHY-N3失败隔离恢复]
    LHY2[LHY-N2history_service] --> LHY3
    LHY3 --> LHY4[LHY-N4事件集成]

    CXY1 --> LHY1
    CXY1 --> LHY2
    CXY2 --> LHY1
    LHY1 --> CXY3
    LHY2 --> CXY3
    LHY1 --> CXY4
    CXY3 --> LHY4
    LHY4 --> CXY5

    LJQ1[LJQ-N1听测与情绪素材] -.-> CXY5
    WGX1[WGX-N1浏览器截图] -.-> CXY5
```

实线为硬依赖，虚线为非阻断补充证据。

避免循环等待：

- CXY-N1 先给出契约 v2.0 草案；首次写入 `history.json` 前必须冻结。
- CXY 的合成页/结果页（N3）不等待 GPU，收到 service 返回结构后对齐。
- LHY 不等待 UI 即可并行实现 `tts_service` 和 `history_service`；历史服务先用冻结 schema 与构造的合法记录做单测，不等待真实 GPU 输出。
- CXY 的参数与情绪映射（N2）与页面（N3）可并行。
- LHY-N4 是合成/结果页与 services 的统一汇合节点，CXY-N5 收口。

## 6. 关键交接

| 交接物 | 发出 → 接收 | 触发的下游工作 | 是否阻断 |
|---|---|---|---|
| Week 3 DoD 与契约 v2.0 | CXY-N1 → LHY | LHY-N1/N2 | 阻断 |
| 中性合成参数与情绪映射/置灰规则 | CXY-N2 → LHY | LHY-N1 | 阻断 |
| `tts_service` 合成入口 | LHY-N1 → CXY | CXY-N3/N4 | 阻断 |
| `history_service` 与样例 | LHY-N2 → CXY | CXY-N3 | 阻断 |
| 情绪参考写入接口 | LHY-N1 → CXY | CXY-N4 情绪对照 | 阻断（无素材时可置灰绕过） |
| 合成页/结果页模块与跨页 State | CXY-N3 → LHY | LHY-N4 | 阻断 |
| 失败隔离与历史恢复 | LHY-N3 → CXY | CXY-N5 | 阻断 |
| 集成版 `app.py` | LHY-N4 → CXY | CXY-N5 | 阻断 |
| 回归 WAV 与双条件对照结论 | CXY-N4 → CXY-N5 | 闭环验收 | 阻断 |
| 人工听测表与情绪素材 | LJQ-N1 → CXY | CXY-N5 证据补充 | 非阻断 |
| 浏览器冒烟截图 | WGX-N1 → CXY | CXY-N5 证据补充 | 非阻断 |

## 7. AI 使用规则

- 提示词使用前补充实际路径、契约、源码版本和真实输入。
- AI 可帮助实现和审查，但负责人必须运行测试并检查输出。
- 不上传未经授权声音、密钥、个人信息或 `.env`。
- 不执行来源不明的依赖安装或删除命令。
- 不允许 AI 生成假的合成 WAV、`history.json` 条目或成功状态。

## 8. 阶段 Demo

1. 一个命令启动 `app.py`。
2. 确认已保存音色出现在合成页下拉。
3. 选择音色，输入固定回归文本之一，选择中性情绪，执行真实合成。
4. 合成成功后自动切到结果页，播放并下载 WAV。
5. 确认 `history.json` 新增一条成功记录，且失败合成不会出现在成功列表。
6. 点击历史“复用”，回到合成页并回填文本、音色、情绪和高级参数。
7. 至少生成 5 条真实回归 WAV，覆盖 5 条固定文本；其中任选 3 条在同一服务实例中连续执行，用于稳定性验证。
8. 有合法 `emotion_refs` 时演示手动情绪切换；无样本时开心/悲伤置灰。
9. 展示一组轻量双条件对照（情绪或语速/停顿），如实记录效果。
10. 停止并重启应用，确认音色列表与历史仍可加载。
11. LJQ/WGX 若已交付，补充展示听测表与浏览器截图；未交付不影响阶段结论。

第 2–10 步由 CXY 现场操作，LHY 负责启动与后端问题现场排查。

验收：

- [ ] 保存音色后合成页下拉即时刷新。
- [ ] 5 条固定回归文本各有本机 WAV 与日志，其中至少 3 条在同一服务实例中连续成功。
- [ ] 合成成功自动切结果页；历史可播放、下载、复用和删除。
- [ ] 失败合成不写成功历史；`history.json` 与输出目录一致。
- [ ] 中性稳定可用；缺情绪参考时对应胶囊置灰。
- [ ] 有合法样本时至少一组情绪或韵律对照；无样本不阻断 MVP。
- [ ] 重启后音色与历史恢复。
- [ ] 自动情绪分类未开启或不作为通过条件。

## 9. 本阶段不做

- 不进入 Week 4 视觉精修、答辩录屏和 PPT 终稿（仅可准备素材）。
- 不把自动情绪分类写成正式能力或 DoD。
- 不进行少样本训练、GRL/对抗或模型级解耦。
- 不增加第五页、FastAPI、数据库或第二套前端。
- 不在未验证 FFmpeg 时默认展示 MP3 下载。
- 本周结束后冻结主功能，Week 4 只修问题。
- 不安排多方讨论会；范围与字段争议一律走 [Decisions.md](../Decisions.md) 由 CXY 裁定。
- 不把 LJQ/WGX 的旁路产物写成阶段通过的必要条件。

## 10. GPU 与环境（40 系 / 50 系）

合成与试听共用 GPU 链路，仍遵循单任务串行；主 GPU 轨道为 **CXY 本机（Track B，8 GB 显存）**。

- 真值文档：[GPU Environment Baseline.md](../GPU%20Environment%20Baseline.md)（§6 矩阵由 CXY 维护）
- Week 3 验收：`output.wav` 必须来自主 Demo 机的项目真实推理。
- 环境变更后 24 小时内更新基线表与矩阵。
- 回归 WAV 须可追溯至本机日志；显存紧张时缩短文本并关闭其他占用 GPU 的程序。
