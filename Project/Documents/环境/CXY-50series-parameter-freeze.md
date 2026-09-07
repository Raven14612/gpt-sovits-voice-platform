# CXY-W2-01：50 系参数冻结

依据：整合包 `webui.py`、`logs/Columbina/config.json`、Week 1 实际日志和已归档页面截图。

| 阶段 | 冻结参数/入口 | 输入 | 输出/判定 |
|---|---|---|---|
| 切分 | threshold=-34、min_length=4000、min_interval=300、hop_size=10、max_sil_kept=500、max=0.9、alpha=0.25、GPU=0 | 原始 WAV | `output/slicer_opt/*.wav` |
| ASR | FunASR large、zh、float32 | 切片目录 | `output/asr_opt/slicer_opt.list` |
| 1A 文本 | `1-get-text.py`、BERT chinese-roberta-wwm-ext-large、GPU 0、单分片 | list、切片目录 | `logs/<name>/2-name2text.txt` |
| 1B 声学 | `2-get-hubert-wav32k.py`；v2Pro 追加 `2-get-sv.py`；GPU 0、fp16 | 文本、切片、HuBERT/SV 预训练模型 | `4-cnhubert`、`5-wav32k`、`7-sv_cn` |
| 1C 语义 | `3-get-semantic.py`、s2v2Pro 配置、s2Gv2Pro、GPU 0 | list、特征目录 | `6-name2semantic.tsv` |
| SoVITS | v2Pro；batch=4；epoch=8；text_low_lr_rate=0.4；save_every=4；GPU=0；fp16；保存最新和最终权重 | `logs/Columbina` 特征 | `Columbina_e8_s192.pth` |
| GPT | batch=4；epoch=15；save_every=5；GPU=0；fp16；DPO=false；保存最新和最终权重 | `2-name2text.txt`、`6-name2semantic.tsv` | `Columbina-e15.ckpt` |
| 推理 | GPT/SoVITS 训练权重；中文；并行/批量推理关闭；GPU=0；speed=1；interval=0.3；top_k=15；top_p=1；temperature=1 | 3–10 秒参考 WAV/文本、目标文本 | 有效 WAV、HTTP 200 |

个人绝对路径不写入业务代码；运行时路径只由 `engine.local.json` 提供。
