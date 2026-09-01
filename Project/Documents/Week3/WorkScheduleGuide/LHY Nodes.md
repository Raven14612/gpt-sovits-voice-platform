# LHY Week 3 节点：Python 业务与集成

## LHY-N1：实现 tts_service 正式合成

**目标**  
封装 GPT-SoVITS 正式文本合成，支持情绪参考选用与 GPU 单任务互斥。

**输入**

- Week 2 `tts_service` 试听封装。
- CXY-N1 契约 v2.0。
- LJQ-N1 合成参数与 LJQ-N2 情绪选用规则。

**工作**

- 扩展 `voice_service.add_emotion_reference`：仅在存在合法同说话人样本时写入 `emotion_refs`，校验授权、3–10 秒、参考文本和语种，并原子更新 `voice.json`/`voices.json`。
- 实现 `synthesize(voice_id, text, text_lang, emotion, speed_factor, fragment_interval, ...)`。
- 从 `voice.json` 读取参考；按情绪选用 `emotion_refs` 或回退 neutral。
- 输出写入 `data/results/{result_id}/output.wav`；返回路径、时长和元数据。
- GPU 重任务串行；忙碌时返回明确 `AppError`。
- 文本空、超长、音色无效、参考缺失时阻断，不启动推理。
- 编写非 GPU 单测与 GPU 集成记录。

**输出**

- 可调用的 `tts_service.synthesize`。
- 条件性的 `add_emotion_reference` 与索引刷新能力；无合法素材时保留接口但不伪造样本。
- 至少 2 条真实 `output.wav` 样例。
- 函数说明与参数对照。

**三个指标**

- **哪些人的工作会影响我？** Week 2 `tts_service` 是硬依赖；CXY-N1、LJQ-N1/N2 是软依赖，收到后对齐。
- **我需要交付什么内容？** 合成服务、情绪样本写入接口、真实样例、测试与函数说明。
- **谁需要等待我完成该工作？** LHY-N3 等真实失败隔离；WGX-N1 等绑定；LJQ-N3 等项目内验证入口。LHY-N2 可按冻结 schema 并行实现。

**完成判定**

- `output.wav` 来自本机本次推理。
- 情绪参考缺失时不会静默 fallback 到错误说话人。

**AI 参考提示词**

```text
请根据以下contract-v2.0和LJQ参数实现tts_service.synthesize：
<粘贴契约>
<粘贴参数与情绪规则>

要求：
- 从voice.json读取参考，按emotion选用emotion_refs；
- 输出到data/results/{result_id}/output.wav；
- GPU串行，忙碌返回AppError；
- 文本空/超长/音色无效/参考缺失阻断；
- 进程内调用TTS.py，不修改模型核心；
- 非GPU单测+GPU测试独立标记。

禁止Mock WAV、HTTP API和自动情绪分类硬编码。
```

---

## LHY-N2：实现 history_service 与原子索引

**目标**  
合成成功后写入历史，支持列表、复用、删除与按时间倒序展示。

**输入**

- CXY-N1 冻结的合成返回结构和 `GenerationRecord` schema；开发与单测阶段可使用构造的合法记录。
- CXY-N1 的 `GenerationRecord` 与 `history.json` schema。

**工作**

- 实现 `save_result`、`list_history`、`get_result`、`delete_result`、`rebuild_history`。
- 仅 `synthesize` 成功时调用 `save_result`；写入 `history.json` 与结果目录。
- 复用返回原始 `text`、`voice_id`、`emotion`、`speed_factor`、`fragment_interval` 等字段。
- 临时文件写入后原子替换 `history.json`。
- 删除时同步更新索引与文件（或标记删除策略按契约）。
- 编写相关 pytest。

**输出**

- `history_service.py`。
- 真实 `history.json` 样例。
- 复用/删除函数说明。

**三个指标**

- **哪些人的工作会影响我？** CXY-N1 在首次写入前是硬依赖；LHY-N1 仅在最终绑定真实合成结果时是硬依赖，服务实现与单测可并行。
- **我需要交付什么内容？** 历史服务、样例、测试与接口说明。
- **谁需要等待我完成该工作？** LHY-N3 等失败隔离；WGX-N2 等历史 UI；CXY-N3 等抽检。

**完成判定**

- 成功合成必有一条 `status=success` 记录。
- 复用参数与存储记录一致。

**AI 参考提示词**

```text
请实现history_service。

Schema：<粘贴GenerationRecord和history.json>

要求：
- save_result仅在合成成功后调用；
- list_history按created_at倒序；
- get_result/delete_result/rebuild_history；
- 原子写history.json；
- pytest覆盖写入、删除、复用字段。

禁止失败合成写success、禁止假历史条目。
```

---

## LHY-N3：失败隔离与历史重启恢复

**目标**  
确保合成失败不产生成功历史，并在重启后恢复历史列表。

**输入**

- LHY-N1/N2。
- CXY-N1 schema。

**工作**

- 在 `app.py` 或 service 层统一：`synthesize` 异常时不调用 `save_result`。
- 失败可写错误日志或 `status=failed` 记录（若契约允许），但**不得出现在成功结果列表**。
- 启动时校验 `history.json`，损坏时从 `data/results/` 重建。
- 输出文件缺失的历史条目跳过并记录日志。
- 防重复提交：执行中拒绝第二次合成请求。
- 编写失败隔离与重启测试。

**输出**

- 失败隔离实现。
- 历史重启恢复测试与日志。
- 重复提交阻断说明。

**三个指标**

- **哪些人的工作会影响我？** LHY-N1/N2 是硬依赖。
- **我需要交付什么内容？** 隔离逻辑、恢复测试和重复提交说明。
- **谁需要等待我完成该工作？** LHY-N4 等集成；CXY-N3/N4 等失败用例证据。

**完成判定**

- 人工触发合成失败时，成功列表条数不变。
- 重启后历史数量与内容一致（在无中途删除前提下）。

**AI 参考提示词**

```text
请实现合成失败隔离与history重启恢复。

要求：
- synthesize异常时不save_result；
- 成功列表只含status=success；
- 启动校验history.json，损坏从data/results重建；
- 缺失output.wav的条目跳过；
- 合成执行中阻断重复提交；
- pytest覆盖失败不写成功、损坏重建。

禁止把失败记录展示为可播放成功项。
```

---

## LHY-N4：合成页与结果页事件集成

**目标**  
将合成页和结果页接入真实 services，形成四页可演示的完整应用。

**输入**

- LHY-N1/N2/N3。
- WGX-N3 的页面、事件、跳页和 State。
- Week 2 集成版 `app.py`。

**工作**

- 绑定合成页：音色下拉、`list_voices`、合成按钮、进度/禁用态。
- 绑定结果页：当前结果、历史列表、播放、下载、复用、删除。
- 合成成功 → 写历史 → 切到结果页；复用 → 切回合成页并回填 State。
- 保存音色成功 → 刷新合成页音色下拉（与 WGX 对齐）。
- GPU 重任务使用 Gradio queue；环境状态显示真实音色数与历史数（若契约包含）。
- 输出启动说明、绑定表和日志。

**输出**

- Week 3 集成版 `app.py`。
- UI 事件到 service 的绑定表。
- 四页闭环联调入口和启动日志。

**三个指标**

- **哪些人的工作会影响我？** LHY-N1/N2/N3 和 WGX-N3 都是硬依赖。
- **我需要交付什么内容？** 一键启动集成版、绑定表、启动说明和日志。
- **谁需要等待我完成该工作？** WGX-N4 等浏览器联调；CXY-N4 等产品闭环预演。

**完成判定**

- 一个命令启动，合成→结果→复用主流程可运行。
- 不启动第二个服务，不绑定假音频或假历史。

**AI 参考提示词**

```text
请集成Week 3单体Gradio，将tts_page和result_page绑定到services。

输入：<ui模块>、<tts_service/history_service/voice_service>、<当前app.py>、<WGX-N3 State>

要求：
- 合成页：list_voices、synthesize、queue、防重复提交；
- 结果页：list_history、播放、下载、复用、删除；
- 合成成功切结果页并写历史；
- 复用回填合成页State；
- 保存音色刷新合成下拉；
- 展示真实AppError；
- 保留Week 2音频页与音色页。

输出修改步骤、事件绑定表、启动和冒烟清单。
```
