# 第三方来源与交付范围

本平台应用代码适用根目录 LICENSE。第三方代码、模型、工具和运行时保留各自许可，不能用应用的 MIT 许可替代。

| 组件 | 来源及许可证据 |
| --- | --- |
| GPT-SoVITS v2Pro | https://github.com/RVC-Boss/GPT-SoVITS ，引擎 LICENSE；基础资源字节和来源锁定在 config/environment-resources.json |
| Python UI 运行时 | https://www.python.org/ ，PSF；config/ui-runtime.lock.json 与运行时 LICENSE.txt |
| Python 模型运行时 | 整合包中的独立 Python，运行时 LICENSE.txt；实际版本和安装依赖写入 release-environment.json |
| Python 依赖及嵌套库 | 保留 dist-info 中的许可证，release-licenses.json 列出随包告知文件，release-environment.json 记录包名、版本、声明许可及项目网址 |
| FFmpeg / FFprobe | https://ffmpeg.org/ ，实际编译版本、选项和许可输出写入 release-environment.json；分发前还须匹配该二进制的源码与许可义务 |
| 中文情绪模型 | https://huggingface.co/Johnson8187/Chinese-Emotion-Small ，固定 revision 及文件 SHA-256 见随模型 model-manifest.json；模型卡声明 MIT，上游缺少独立许可证文本，包内 LICENSE.txt 如实记录证据 |

组装脚本保留可找到的 LICENSE、NOTICE、COPYING、版权告知和模型卡，并生成索引。这是来源和告知盘点，不能自动判定全部再分发条件已满足。当前运行包为本地验收候选，未经第三方再分发核实、接收机验收和人工听测，不标记为正式公开发行版。

发布包不包含个人音频、训练结果、已安装音色、上传者私钥、工坊数据库或本地配置。情绪模型是明确列入的基础资源，其独立许可证说明保留。工坊服务地址由部署者填写，默认不启动开发服务器。
