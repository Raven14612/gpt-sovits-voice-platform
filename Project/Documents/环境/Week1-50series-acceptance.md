# Week 1 50 系主线联调验收

| 验收项 | 结果 | 证据/说明 | 下一步 |
|---|---|---|---|
| 唯一入口 `Project/app.py` | 通过 | Gradio 5.50.0 已安装，7860 启动并返回 HTTP 200 | 后续接业务 service |
| 四页 UI 壳与单页切换 | 通过（结构） | `Project/ui/layout.py` 已实现四页和共享 State；默认音频页 | 窄窗口/键盘人工记录仍可补 |
| 环境探测 | 通过 | `probe_engine()` 实测 Python 3.9.13 / Torch 2.7.0+cu128 / CUDA 12.8 / RTX 5060 | 保持配置化 |
| 50 系切分与 ASR | 通过 | `output/slicer_opt` 12 段；`output/asr_opt/slicer_opt.list` | 后续接 adapter |
| 特征准备 | 通过 | `logs/Columbina` 下 3-bert、4-cnhubert、5-wav32k、7-sv_cn | 后续接任务服务 |
| SoVITS/GPT 训练 | 通过（整合包证据） | `Columbina_e8_s192.pth`、`Columbina-e15.ckpt` 存在 | 固定权重归档接口 |
| 真实 50 系合成 | 通过（API+adapter） | API 和项目 adapter 均生成真实 WAV，用户确认听感正常 | 进入 Week 2 service 接线 |
| 后端导入/测试 | 通过 | unittest、compileall 通过；adapter 真实直调日志已生成 | 接 UI service |
| 40 系兼容 | 延期 | 当前范围已收缩，不作为 MVP 条件 | 无 |

## Week 1 结论

50 系整合包训练与真实合成闭环、项目 adapter 环境探测和一次真实合成均已具备可复核文件证据。WGX/LHY Week 1 骨架已完成；窄窗口、键盘和刷新恢复仍属于未逐项人工记录的浏览器增强检查，不阻塞 Week 1 主线验收。
