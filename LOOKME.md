# LOOKME — 当前项目入口（v3）

> 当前执行版本：2026-09-04 生效的 v3。  
> GPT-SoVITS 与第三方整合包是外部依赖；项目自研 UI、业务服务、数据管理和引擎适配层。

## 开始工作

1. 阅读 [项目文档入口](Project/Documents/README.md)。
2. 阅读 [当前执行计划 v3](Project/Documents/当前执行计划%20v3.md)。
3. 打开自己的任务单：
   - [CXY](Project/Documents/成员任务/CXY.md)
   - [LHY](Project/Documents/成员任务/LHY.md)
   - [LJQ](Project/Documents/成员任务/LJQ.md)
   - [WGX](Project/Documents/成员任务/WGX.md)
4. 公共接口以 [Engine Adapter 契约](Project/Documents/契约/engine-adapter-v0.1.md) 为准。
5. 范围、分工和降级以 [决议台账](Project/Documents/Decisions.md) 为准。

## 当前分工

| 负责人 | 领导领域 | Week 1 首要任务 |
|---|---|---|
| CXY | 产品、50 系主轨、最终验收 | 用现有训练权重补一条全新真实 WAV；冻结模型命令与 I/O |
| LHY | 后端、数据、任务与集成 | schemas、adapter、services、GPU 串行任务状态机 |
| LJQ | RTX 40 系兼容轨 | 代表机环境基线、adapter 探测、零样本推理 |
| WGX | Gradio 前端与体验 | 四页壳、共享 State、五种任务状态、浏览器冒烟 |

## 不再执行的内容

旧的 v1/v2 周计划、单点包揽式分工、过时环境结论和早期产品稿已经移入：

`Project/Documents/废案/2026-09-04-v2及更早/`

这些材料只用于历史追溯，不再作为任务输入。

