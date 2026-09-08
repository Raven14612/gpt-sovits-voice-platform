# WGX Week 2 浏览器冒烟记录

日期：2026-09-08。代执行：本机 CXY。范围：WGX-W2-01 至 WGX-W2-04。

## 节点交付

| 节点 | 产物 | 结论 |
|---|---|---|
| WGX-W2-01 | `ui/audio_page.py`；`services/dataset_service.py` 上传和校对保存接口；`tests/test_audio_page.py` | 通过（UI 与数据保存） |
| WGX-W2-02 | `ui/voice_page.py`、`ui/task_status.py`；task_service 忙碌查询和日志摘要；`tests/test_ui_tasks.py` | 通过（UI 边界） |
| WGX-W2-03 | `ui/layout.py`、TTS/结果页共享状态、响应式样式、浏览器脚本与截图 | 通过 |
| WGX-W2-04 | 全量 unittest、compileall、构建/导入及 UI 服务边界检查 | 通过 |

跨目录支持改动仅用于 UI 所需的数据保存、忙碌查询、日志读取和受限结果路径解析。页面没有启动外部模型进程，也没有读取整合包内部文件。

## 浏览器验证

使用 Playwright 和本机 Edge，无头浏览器视口为 1440×1000、390×844。`scripts/wgx_smoke_server.py` 启动真实 app，但将可写索引和数据目录重定向至临时目录；正式 Citlali 档案只复制供展示。测试结束关闭 7861 测试服务并清理临时数据。7860 保留给用户使用。

| 操作 | 预期与实际 | 证据 |
|---|---|---|
| 打开默认页 | 仅音频页显示；无数据集时提交禁用 | `01-audio-empty-desktop.png` |
| 切换四页 | 每次只有一个业务页可见，导航高亮同步 | 桌面与 `mobile-0` 至 `mobile-3` |
| 选择 Citlali 后转到合成页 | 音色保留，仅显示已有 neutral 参考；合成未接入提示准确 | `02-voice-desktop.png`、`03-shared-voice.png` |
| 导入真实 Citlali WAV | 音频复制至临时数据集，路径显示；播放器加载真实音频 | `04-audio-unimplemented.png` |
| 点击切分并识别 | 返回 `NOT_IMPLEMENTED`，不显示任务成功 | `04-audio-unimplemented.png` |
| 导入真实 .list，选择切片、更新标签并保存 | 表格/编辑区联动；未保存提示准确；跨页返回保留选择；文本/标签写入隔离索引 | `05-correction-save.png` |
| 在训练页提交已校对数据集 | 显示训练命令缺失的 `NOT_IMPLEMENTED`，恢复提交按钮，不新增音色档案 | `06-training-unimplemented.png` |
| 选择实际失败的测试进程任务 | 状态为失败，显示 validating 和退出码 7 的日志 | `08-failed-task-log.png` |
| 390px 四页和长中文 | 无页面横向溢出、白屏或内容重叠，长路径可换行/滚动 | `mobile-0.png` 至 `mobile-3.png` |
| 刷新、键盘 Enter/Tab | 返回默认页，清空会话选择；已存索引仍可选，不虚构恢复中的任务 | `07-mobile-keyboard-refresh.png` |

截图与机器结果在 `evidence/wgx-week2/`，浏览器未捕获页面 JavaScript 异常。失败任务来自明确执行 `SystemExit(7)` 的工程探针，不是 GPT-SoVITS 训练失败。校对测试中使用的 sad 标签仅检查保存行为，不作为对真实录音的人工情绪判断。

GPU_BUSY 的按钮禁用/锁释放后恢复，以及 pending/running/succeeded/failed/cancelled 五种状态由单元测试验证，不把这些替身状态记为真实模型运行。

## 复验

最终结果：unittest **47/47 通过，无跳过**；compileall 通过；构建输出 `BUILD PASS 95`；UI 源码未检出模型进程命令、个人绝对路径或直接读写文件。完整测试输出见 `evidence/wgx-week2/unittest.txt`。

在 `Project` 下，配置真实 checkpoint 的环境变量后运行：

```powershell
python -m unittest discover -v
python -m compileall -q models services adapters tests ui scripts/wgx_smoke_server.py app.py
python -c "from app import build_app; app=build_app(); print('BUILD PASS',len(app.blocks))"
```

浏览器测试需 Node.js 可解析 `playwright/test`，并已安装 Edge。`WGX_REAL_AUDIO` 指向授权的真实 PCM WAV；`WGX_REAL_LIST` 指向对应的真实 UTF-8 `.list`。两者通过环境变量传入，不写进源码。运行：

```powershell
python scripts/wgx_smoke_server.py
```

项目启动仍使用 `python app.py`，本次没有新增运行时依赖。上传暂支持 PCM WAV；压缩音频支持不在本次验收内。

## 业务边界与人工项

- WGX 四个节点在任务单允许的未接入提示边界内完成；音频切分/ASR 和训练配置仍需 CXY/LHY 接线，合成模型服务属于后续主线工作。
- 人工需要判断的是正式数据集逐句文本是否准确、neutral/happy/sad 是否符合听感，以及将来项目页面新生成音频的听感。现有 Citlali 成功训练/生成及用户听感确认继续有效。
- 本次没有重新训练模型，没有修改正式 WAV、权重或索引，也没有将临时校对结果作为正式验收成果。
