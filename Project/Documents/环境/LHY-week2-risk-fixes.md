# LHY Week 2 后端风险修复记录

日期：2026-09-08。基础提交：`91ed580`。

用户已确认整合包的真实训练、音频生成和听感正常，Citlali 正式音色结论保留。本次修复针对项目后端代码，不修改整合包权重、正式音色索引和既有 WAV。

## 修复与验证

| 问题 | 修复 | 回归证据 |
|---|---|---|
| 无操作命令可把旧权重登记为本次训练成功 | 每个训练阶段启动前流式计算对应权重 SHA-256，归档前要求权重新生成或内容变化；失败持久化且不登记音色 | GPT 未变化、SoVITS 未变化、两者均未变化均失败；仅更新时间也失败；新文件可正常归档；保留大小和时间的内容变化仍可识别 |
| 音色 ID 可导致归档越界 | 启动任务前校验单层目录名，拒绝路径分隔符、绝对路径、Windows 保留名和非法字符；归档前再次校验解析后的目标路径 | 非法 ID 均被拒绝；真实 Windows 目录联接越界被拒绝；文件链接目标越界通过路径解析替身验证，外部文件未改动 |
| 终态任务再次运行会泄漏 GPU 锁 | 状态转换放入锁的 try/finally 生命周期，操作错误单独处理 | succeeded/failed/cancelled 均拒绝再次运行且释放锁；后续任务成功；GPU_BUSY 不释放现有任务持有的锁 |

权重格式检查同时改为只读取前 1024 字节，避免为检查文件头将整个 checkpoint 读入内存。格式检查仍是基础文件检查，不替代模型加载和听感验收。

## 复验命令

在 `Project` 下运行：

```powershell
$env:GPT_SOVITS_REAL_GPT_WEIGHT='D:\Documents\GPT-SoVITS-v2pro-20250604-nvidia50\GPT_weights_v2Pro\Citlali-e15.ckpt'
$env:GPT_SOVITS_REAL_SOVITS_WEIGHT='D:\Documents\GPT-SoVITS-v2pro-20250604-nvidia50\SoVITS_weights_v2Pro\Citlali_e8_s208.pth'
python -m unittest discover -v
python -m compileall -q models services adapters tests ui app.py
python -c "import models.schemas, services.task_service, services.voice_service, adapters.gpt_sovits"
```

结果：36 项测试全部通过，无跳过；编译和导入通过。成功路径使用真实 checkpoint 的临时副本，测试命令只复制文件，没有调用 GPU 训练。未配置真实权重环境变量时，两项依赖真实 checkpoint 的测试会跳过。

## 剩余接入项

- `train_voice` 仍要求显式传入 GPT/SoVITS stage command，缺失时返回 `NOT_IMPLEMENTED`。
- `audio_service.process_audio` 仍为未接入接口。
- WGX-W2-01/02 的页面接线尚未完成，不能将本次后端回归通过计作这两个节点完成。
- 已有权重未变化时，应使用已有正式音色；本次训练接口会拒绝将它再次记作新的训练成果。
