# 创意工坊服务

本服务是本地工具的可选远程共享音色库：客户端负责本地训练、安装和合成，服务端只负责包、封面及元数据。最终部署在独立服务器，多个客户端连接同一 HTTPS 地址。`WORKSHOP_DATA_DIR` 就是服务端保存文件的目录，客户端通过 API 访问；不支持直接将普通网盘链接或共享文件夹路径填作服务地址。

## 开发阶段的本机联调

将 `config/workshop.example.json` 复制为 `config/workshop.local.json`，仅开发联调时将 `auto_start_local` 设为 `true`。双击 `start.bat` 后，进入工坊或测试连接时才自动启动 `http://127.0.0.1:8090`。无需安装另一套 Python 或手填令牌，默认数据目录为 `data/workshop/`；已有根目录下的 `workshop_data/` 时继续使用它。首次进入空列表是正常状态，通过页面“上传本地音色”加入条目。发布模板的 `auto_start_local` 为 `false`。

工坊是 HTTP 服务；把权重放入普通文件夹不能代替启动服务和上传音色包。连接失败时先退出旧版本平台进程，再启动更新后的平台。未知程序占用端口时不会被终止；可以在 `config/workshop.local.json` 修改 `base_url` 的端口。

## 手动部署

正式客户端配置真实 HTTPS 工坊地址并设置 `auto_start_local: false`；以下启动命令用于服务器侧，回环监听可放在 HTTPS 反向代理之后。普通客户端使用者无需运行这些服务端命令。远端部署与两台客户端的最终共享验收仍待完成。

独立部署只需 `workshop_server/`，不需要模型或 GPU。使用 Python 3.11 以上版本，在包含该目录的工作目录执行：

```powershell
python -m pip install -r workshop_server/requirements.txt
$env:WORKSHOP_DATA_DIR = "./workshop_data"
$env:WORKSHOP_UPLOAD_TOKEN = "替换为自己生成的随机长令牌"
python -m uvicorn workshop_server.app:create_app --factory --host 127.0.0.1 --port 8090
```

客户端配置参考 `config/workshop.example.json`，保存为 `config/workshop.local.json`。手动管理服务时设 `auto_start_local` 为 `false`；远程地址始终不会在桌面本机启动服务。远程上传时在页面填写服务端上传令牌，可选从私人配置的 `upload_token` 读取。封面修改使用上传时绑定的独立上传者凭据，通用上传令牌不授予他人条目的修改权。

当前无账号登录系统，以平台数据目录中按服务地址保存的随机凭据识别上传者。凭据保存在 `data/private/workshop-publishers.json`，本地上传关联保存在 `data/index/workshop-uploads.json`。重启保留身份；迁移机器时须随私人数据备份，不随发布包分发。同一份平台数据的使用者共用上传身份，需要不同身份时使用独立平台数据。远程服务使用 HTTPS 保护传输中的凭据。

适用于单机、小规模可信社区，不支持多实例部署。外部访问时由部署者配置监听地址、防火墙、HTTPS 和反向代理。

这里的“单机”指一台服务器服务多个客户端，不代表工坊只能在用户自己电脑上运行。

## 存储和维护

“卸载模型”仅将本机音色移入回收站，不影响远程发布。上传者在详情弹窗中确认“下架我上传的音色”后，服务端记录 `withdrawn_at`，停止公开列表、封面访问和新下载，保留已有客户端副本。`DELETE /api/v1/voices/{id}` 必须携带该条目上传者的 `X-Publisher-Key`，共享上传令牌不授予下架权；同一上传者重复下架返回成功，首次时间不变。数据库在启动时自动补充可空列，旧条目无归属时不能认领。服务器包和封面保留，清理存档另行维护；已开始的下载允许结束。

停服后成套备份 `workshop.sqlite3`、`packages/`、`covers/`。`tmp/` 是接收暂存目录，失败请求会清理自身文件。磁盘容量不足时先停止新上传、扩充存储或恢复完整备份，不直接删数据库引用的文件。

封面支持最大 4 MiB、1600 万像素的 PNG/JPEG/WebP，服务端转换为不含原始元数据的 640×400 PNG。封面按哈希保存，替换后旧图片保留。封面独立于 `.rvoice`，更换封面不需要重新上传模型。旧客户端可浏览下载，上传需升级以发送上传者凭据。旧条目无归属时默认禁止修改，管理员核实上传者后离线迁移；不提供根据名称或下载包认领所有权的网络接口。

`GET /health` 检查服务，`GET /api/v1/voices` 搜索列表，`POST /api/v1/voices` 上传音色包，`GET /api/v1/voices/{id}/download` 下载包，`POST /api/v1/voices/{id}/cover` 保存封面，`GET /api/v1/voices/{id}/cover` 读取封面。上传需同时携带 `X-Upload-Token` 和 64 位十六进制随机 `X-Publisher-Key`；服务端只存后者的 SHA-256。封面写入必须匹配该条目上传者。列表可携带上传者凭据获得 `can_edit_cover`，不返回凭据哈希。服务端不执行或加载网络权重。
