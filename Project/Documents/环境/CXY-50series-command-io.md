# CXY-W1-02：50 系真实命令与 I/O 附录

来源：整合包 `webui.py`、`api.py`、启动记录及 2026-09-06 RTX 5060 Laptop 实机探测。个人绝对路径只保留在本机证据，不写入业务源码。

## 已确认入口

| 能力 | 实际入口/命令 | 输入 | 输出/判定 |
|---|---|---|---|
| probe_environment | `<python> -c import sys,torch...` | engine_root、python_path | Python/Torch/CUDA/GPU；退出码 0 且输出完整 |
| slice_audio | `<python> -s tools/slice_audio.py <source> <output> -34 4000 300 10 500 0.9 0.25 0 1` | 原始 WAV、输出目录 | 输出 WAV 切片；终端提示执行完毕 |
| run_asr | `<python> -s tools/asr/funasr_asr.py -i <slice_dir> -o <output_dir> -s large -l zh -p float32` | 切片目录 | `slicer_opt.list`；每段有文本 |
| feature_text (1A) | `set env inp_text=<list>; inp_wav_dir=<wav目录>; exp_name=<name>; opt_dir=logs/<name>; bert_pretrained_dir=<路径>; i_part=0; all_parts=1; _CUDA_VISIBLE_DEVICES=0; is_half=True` 后执行 `<python> -s GPT_SoVITS/prepare_datasets/1-get-text.py` | 校对后的 `.list`、32k WAV 目录、BERT 预训练目录 | `logs/<name>/2-name2text.txt`；本次实际存在 |
| feature_hubert (1B) | 同上设置 `cnhubert_base_dir=<路径>; sv_path=GPT_SoVITS/pretrained_models/sv/pretrained_eres2netv2w24s4ep4.ckpt`，执行 `<python> -s GPT_SoVITS/prepare_datasets/2-get-hubert-wav32k.py`；v2Pro 追加 `<python> -s GPT_SoVITS/prepare_datasets/2-get-sv.py` | 文本文件、WAV 目录、Chinese-HuBERT、SV 模型 | `logs/<name>/4-cnhubert`、`5-wav32k`、`7-sv_cn`；本次实际存在 |
| feature_semantic (1C) | 设置 `inp_text=<list>; exp_name=<name>; opt_dir=logs/<name>; pretrained_s2G=GPT_SoVITS/pretrained_models/v2Pro/s2Gv2Pro.pth; s2config_path=GPT_SoVITS/configs/s2v2Pro.json; i_part=0; all_parts=1; _CUDA_VISIBLE_DEVICES=0; is_half=True` 后执行 `<python> -s GPT_SoVITS/prepare_datasets/3-get-semantic.py` | list、实验目录、预训练 SoVITS-G、v2Pro 配置 | `logs/<name>/6-name2semantic.tsv`；本次实际存在 |
| train_voice | `<python> -s GPT_SoVITS/s2_train.py --config <TEMP yaml>`；`<python> -s GPT_SoVITS/s1_train.py --config_file <TEMP yaml>` | 特征目录、训练配置 | `SoVITS_weights_v2Pro/<name>_e*.pth`、`GPT_weights_v2Pro/<name>-e*.ckpt` |
| synthesize | `api.py` HTTP GET `/` | GPT/SoVITS 权重、参考 WAV/文本/zh、目标文本/zh | HTTP 200，响应 WAV；本次已验证 32kHz mono 16-bit |

## 本次真实证据

- 运行时：Python 3.9.13，Torch 2.7.0+cu128，CUDA 12.8，RTX 5060 Laptop GPU。
- 权重：`Columbina-e15.ckpt`、`Columbina_e8_s192.pth`。
- 新输出：`output/evidence_cxy_20260906.wav`，684844 bytes，10.7 s，WAV 结构有效。
- API 日志：整合包控制台记录 `GET / ... 200 OK`；完整探测摘要见本机 `logs/cxy-50-probe-20260906.txt`。

## 适配器边界

所有路径由 `engine.local.json` 提供并先解析为绝对路径；GPU 任务串行，`parallel_infer=false`。未通过源码或真实证据确认的 WebUI 内部参数仍标记待实测，不能写死到 services。
