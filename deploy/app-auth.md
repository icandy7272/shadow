# 应用内登录迁移

新功能使用 Passkey（面容、指纹或设备解锁）、90 天登录 Cookie、备用密码和一次性设备码。仅一个所有者，沿用当前全部练习数据；不增加游客服务器访问。不开启时保留现有本机使用模式。

## 初始化与验证

1. 更新并安装依赖：`uv sync`。
2. 在运行 Shadow 的电脑里执行 `uv run shadow auth setup --origin https://shadow.cheerup.tech`。密码通过隐藏输入设置两遍，不要把密码放入命令、脚本或聊天。必须为 6 位数字（0–9），可以以 0 开头。认证数据保存在数据目录的独立 `auth.sqlite3`，不要提交或公开该文件。
3. 重启 Shadow，保持 nginx 原来的访问密码。若电脑本地 HTTP 页面需要登录，正式验证应从已配置的 HTTPS 域名进行，因为 Passkey 与该域名绑定，写请求也校验这个 Origin。
4. 域名访问 `/login`，使用备用密码。登录后到设置→账号与设备绑定 Passkey；退出后用 Passkey 再登录。Cookie 默认 90 天，未选记住设备为 12 小时。签名验证使用 py_webauthn，要求真实用户验证。
5. 已登录设备生成设备码，新设备扫码或输入码。码在 10 分钟内仅可用一次；扫码地址把码放在 URL 片段中，不放进服务器请求日志。二维码本地生成，不请求第三方服务。
6. 验证未登录窗口不能读取 `/today`、`/api/sources`、`/audio/…` 或 `/take/…`；验证退出所有设备后旧登录状态不可再用。验证 Passkey 成功和备用密码成功，再进行下一步。

## 替换 nginx 密码层

只有上面的应用内认证验证成功后，才将现有站点的 `auth_basic` 改为 `off`，不再使用 `auth_basic_user_file`。完整参考 `nginx.app-auth.conf.example`，保留已有的域名、证书、转发端口和流式分析配置。

修改前备份原配置，运行 `nginx -t` 成功后再重载。新开未登录窗口应进入 Shadow 登录页，不再弹浏览器密码框；未登录 API 应返回 401，而不是拿到练习数据。若失败，恢复原 nginx 配置。不要通过删除认证库来“修复”登录，那会回到无应用认证的本机模式。

本文不会自动修改线上 nginx，也不会替用户输入密码或触发设备上的 Face ID。

## 恢复与会话

遗失登录方式时，在本机执行 `uv run shadow auth reset --origin https://shadow.cheerup.tech`，隐藏输入新的备用密码。重置会撤销全部会话、设备码、旧 Passkey；练习数据保留，之后重新绑定 Passkey。退出所有设备撤销登录和待用设备码，但保留 Passkey。

练习中 Cookie 过期时，录音不会被当作不合格而丢弃；页面内重新登录后点击重新提交，沿用原提交编号。Safari 与主屏幕 App 的存储是否共享需要实体设备确认。

## 复用与许可

参考 openGym e348fc17c42c7e9a211c5972e573ad3698190ee2 的 Login.jsx、api/server.js 和 api/device-link.js 的认证流程。openGym 是 AGPL，Shadow 现有代码是 MIT。本实现没有复制其受许可覆盖的实现代码；直接复用兼容许可的 py_webauthn（BSD-3-Clause）与 qrcode（BSD）库，保留 Python 服务及现有部署，不增加 Node 服务。浏览器使用标准 WebAuthn API。
