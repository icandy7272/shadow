# 用自己的域名打开 Shadow（经云服务器中转）

## 要解决的问题

- 网址记不住。电脑上是 `127.0.0.1:8000`，手机上是局域网 IP，路由器还会换 IP。
- 手机上跟读用不了。局域网打开走的是 HTTP，浏览器只在 HTTPS 或 localhost 下给麦克风权限。

## 使用场景

在家练，练的时候 Mac 开着 `shadow serve`。Mac 关着时不要求能用。

## 方案

不拆功能，也不同步数据。云服务器只做中转，所有计算和数据都留在本机：

```
浏览器 ──HTTPS + 访问密码──▶ 云服务器 nginx ──▶ 服务器 127.0.0.1:<remote_port>
                                                   │ SSH 反向隧道
                                                   ▼
                                         本机 shadow（127.0.0.1:8000）
```

- 网址是 `https://<子域名>`，电脑和手机用同一个。
- 隧道由 `shadow serve` 顺带拉起，Ctrl+C 一起停，不在后台常驻。
- 服务器上用 nginx + Let's Encrypt，证书自动续期，访问要输密码（HTTP Basic Auth）。

### 为什么不直接把域名指到 Mac 的局域网 IP

- 局域网 IP 没法用 HTTP 验证签证书，只能走 DNS 验证，Mac 上就得放 DNS 服务商的 API 密钥。
- 路由器换了 IP，要自动去改解析。
- Mac 上开着代理（假 IP 模式），本机解析会被截走；有的路由器还会拦「公网域名解析到内网 IP」。

## 本机部分

### 配置 `~/.shadow/tunnel.toml`

这是个人配置，不进仓库：

```toml
ssh_host = "cloud"                 # ~/.ssh/config 里的主机名，用密钥登录
remote_port = 18000                # 服务器上 nginx 转发到的端口
url = "https://shadow.example.com" # 打印给人看的网址
```

- 文件不存在：不开隧道，行为和原来一样。
- 写错了（缺字段、端口不在 1024–65535、网址不是 https）：`serve` 在 stderr 说明哪个文件哪里不对，照常起本地服务。

### `src/shadow/tunnel.py`

- `load()` 读配置，返回 `TunnelConfig | None`，写错抛 `TunnelError`（带文件路径）。
- `ssh_command(cfg, local_port)` 拼出隧道命令：
  - `ssh -N -o BatchMode=yes -o ExitOnForwardFailure=yes -o ServerAliveInterval=15 -o ServerAliveCountMax=3 -R 127.0.0.1:<remote_port>:127.0.0.1:<local_port> <ssh_host>`
  - 转发端口只绑服务器的回环地址，外面只能经 nginx 进来。
  - 没配好密钥时直接失败，不会卡在输密码上。
  - 端口没占上就退出，好让守护线程重连，而不是连着却不转发。
- `release_command(cfg)`：上一条隧道断得不干净时（比如网络切换），服务器上那个 sshd 会话会一直占着端口。这条命令只杀占着该端口的 `sshd` 进程，别的进程不碰。
- `Tunnel(cfg, local_port)`：一个后台线程守着 ssh。
  - 连上后等一小会儿还活着，就报「已连上：<url>」。
  - 断了报原因（stderr 最后一行）。遇到「remote port forwarding failed」先清掉残留端口再重连。
  - 重连间隔依次是 2、5、15、30 秒。连着超过一分钟才算恢复，间隔清零。
  - `stop()` 终止 ssh、等线程退出，不再重连。
  - 起进程、跑命令、打印、等待时间都能从参数换掉，测试不连真服务器、不真的等。

### `shadow serve`

- 读到配置就起 `Tunnel`，打印公网网址和本机网址。
- `uvicorn.run` 包在 `try/finally` 里，无论正常退出还是出错都会 `stop()`。
- 新增 `--no-tunnel`，这一次不开隧道。

## 服务器部分

仓库里放两份通用模板：`deploy/nginx.conf.example` 和 `deploy/offline.html`。

nginx 站点配置：

- 80 端口：保留证书验证路径，其余请求跳转到 https。
- 443 端口：
  - 证书，访问密码 `auth_basic`。
  - `client_max_body_size 50m`：几遍录音一起上传，默认的 1m 不够。
  - `proxy_buffering off`：跟读比对的进度是一行一行流式返回的，缓冲住就看不到进度条。
  - `proxy_read_timeout 300s`。
  - 502/504 时显示离线页：「家里电脑上的 Shadow 没开」加启动命令，每 10 秒自动刷新，服务一起来就回到原页面。离线页返回的状态码仍是 502，页面顶上的服务指示灯会照常变红。
- 证书用 `certbot certonly --nginx`，和服务器上现有站点同一套自动续期。
- 密码文件 `/etc/nginx/shadow.htpasswd`：由用户自己在终端里输密码生成，用 `openssl passwd -apr1`，属主 root:www-data，权限 640。密码不经过任何脚本或对话。

## 不做

- 云上跑转写和比对。
- 数据同步。
- 多用户、Mac 关机时可用。

## 测试

- `tests/test_tunnel.py`：
  - 读配置，包括缺文件、各种写错的情况。
  - 命令只绑回环地址。
  - 清理命令只针对 sshd。
  - 用假进程测：断了会重连，端口转发失败会先清理，其他失败不碰服务器，`stop` 后不再重连。
  - 重连间隔会变长、有上限。
- `tests/test_cli.py`：
  - 有配置时 `serve` 起隧道并打印网址。
  - 服务出错也会关隧道。
  - `--no-tunnel` 不起隧道。
  - 配置写错照样起本地服务。
- 部署后：
  - 不带密码访问返回 401，证书有效。
  - 在服务器上直接请求隧道端口，能拿到 `/api/health`。
  - 手机上输密码后走完一句：盲听、默写、跟读录音。

## 实施步骤

1. `tunnel.py` 的配置读取和命令拼接（TDD）。
2. `Tunnel` 守护线程（TDD）。
3. `serve` 接入隧道和 `--no-tunnel`（TDD）。
4. 部署模板和 README「挂到自己的域名上」一节。
5. 服务器部署。
   - 用户：在 DNS 加 A 记录，自己设访问密码。
   - 部署的人：放离线页、HTTP 站点，签证书，上 HTTPS 站点，`nginx -t` 后重载。
   - 写本机的 `tunnel.toml`。
6. 端到端验证（见上面「测试」），然后提交、推送。
