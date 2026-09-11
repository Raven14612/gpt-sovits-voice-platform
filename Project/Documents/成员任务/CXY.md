# CXY Week 3 任务单：契约、真实回归与验收

## CXY-W3-01：冻结合成契约与回归口径（P0）

- 输入：Week 2 验收、`GenerationRecord`、整合包 `api.py/api_v2.py`、当前 TTS 页面。
- 工作：定义合成请求/结果字段、真实支持的高级参数、5 条固定中文文本、失败码和 Week 3 DoD。
- 产物：`Documents/契约/tts-history-v1.md`。
- 通过：每个字段能对应源码；不支持的参数不显示为可用；固定文本不含敏感内容。

**AI 节点提示词**

```text
阅读 Week3安排、Week2真实闭环记录、models/schemas.py、adapters/gpt_sovits.py、services/tts_service.py 和整合包 api.py/api_v2.py。核对请求字段和真实引擎能力，编写 tts-history-v1 契约：输入、输出、状态、错误码、历史字段、文件生命周期、5条固定回归文本和验收方法。不得根据 UI 控件猜测参数。
```

## CXY-W3-02：50 系真实合成与参数对照（P0）

- 输入：冻结契约、`citlali` 和 `buer-w2-project` 正式音色。
- 工作：生成 5 条真实 WAV，其中同一实例连续生成至少 3 条；对语速和停顿各做一组单变量对照。
- 产物：`data/outputs/` WAV、合成日志、`Documents/环境/Week3-50series-regression.md`。
- 通过：WAV 可读取且不是旧文件；参数、耗时、结果 ID 可追溯；人工记录音色、清晰度和异常。

**AI 节点提示词**

```text
按 tts-history-v1 契约在 RTX 50 系项目页面或 service 执行 5 条真实合成。至少 3 条必须在同一服务实例连续完成；只改变一个变量做语速与停顿对照。逐条记录 result_id、voice_id、文本、参数、耗时、WAV 参数、日志和 SHA-256。不得复制旧 WAV 或代替人工听感结论。
```

## CXY-W3-03：Week 3 产品闭环验收（P0）

- 输入：全员节点产物和人工听测结论。
- 工作：现场检查合成、结果、下载、删除、复用、失败隔离和重启恢复。
- 产物：`Documents/环境/Week3-acceptance.md`、`Decisions.md` 更新。
- 通过：Week 3 过线标准全部有证据；未通过项明确阻塞或降级，不发布假成功。

**AI 节点提示词**

```text
汇总 Week3 全部代码、测试、WAV、日志、截图和听测记录，按 Week3安排逐条验收。区分自动测试、真实 GPU 证据和人工判断；执行一次重启恢复与一次故意失败。输出通过/失败/限制和下一阶段入口，并更新 Decisions.md，不得把缺失证据写成通过。
```
