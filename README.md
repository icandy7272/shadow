# Shadow

英语影子跟读训练工具：盲听、整句默写、跟读比对，一句一句练。

针对一个具体问题：**英语是「读」出来的，不是「听」出来的。** 开字幕懂 80%、关字幕掉到
40%，开口时每个词都发满、没有弱读和节奏起伏。这个工具把素材切成一句一句，先逼你不看字去听，
再让你把听到的写出来，最后跟读录音，告诉你**具体哪个词节奏不对、哪里音调没跟上**——
而不是笼统地说「再练练」。

## 环境

- macOS，Apple Silicon（转写用的是 [mlx-whisper](https://github.com/ml-explore/mlx-examples)）
- Python 3.12+、[uv](https://docs.astral.sh/uv/)
- ffmpeg、yt-dlp

## 安装

```bash
brew install ffmpeg yt-dlp
uv sync
uv run shadow dict install    # 可选：离线英汉词典，默写时给释义（下载约 66 MB）
```

第一次导入素材时会自动下载 Whisper 模型 `large-v3-turbo`（约 1.5 GB）和强制对齐用的
wav2vec2 模型。

## 启动

```bash
uv run shadow serve           # 打开 http://127.0.0.1:8000
```

- `--lan`：同一 Wi-Fi 下的手机也能打开。浏览器只在 HTTPS 或 localhost 下给麦克风权限，
  所以手机上盲听和默写照常，跟读要用电脑。
- 服务在终端里跑，关掉终端就停了；页面顶上的指示灯会提示，并给出重新启动的命令。

### 挂到自己的域名上（可选）

局域网 IP 记不住，手机上又得是 HTTPS 才给麦克风——可以借一台有公网 IP 的服务器中转：
浏览器 → 服务器 nginx（HTTPS + 访问密码）→ SSH 反向隧道 → 本机。活全在本机干，服务器只转发。

1. 域名加一条 A 记录指向服务器；服务器上照 [`deploy/nginx.conf.example`](deploy/nginx.conf.example)
   配 nginx、签证书、设访问密码，离线页用 [`deploy/offline.html`](deploy/offline.html)。
2. 确认本机能用密钥 `ssh <主机名>` 登上服务器，然后写 `~/.shadow/tunnel.toml`：

   ```toml
   ssh_host = "cloud"                   # ~/.ssh/config 里的主机名
   remote_port = 18000                  # 和 nginx 里 proxy_pass 的端口一致
   url = "https://shadow.example.com"
   ```

3. 照常 `uv run shadow serve`，隧道会一起连上，断了自动重连，Ctrl+C 一起停。
   这一次不想开隧道就加 `--no-tunnel`。

## 一句怎么练

1. **盲听。** 不看文字，连播几遍，给自己打分（1 几乎没听懂 … 5 每个词都清楚）。
   这一步不能省：这套训练要治的就是「英语以视觉形式存储」，先看到字，听力就没在练了。
   听懂了随时点分数，还在放的原声会停下。
2. **默写。** 每个词一个等宽的框，写出听到的整句。不会的勾「不会」。
   判对不管大小写、标点和撇号（`im` 算 `I'm` 对）。对完答案逐词着色，写错和不会的词给出
   音标、释义和原形；不会的自动记进生词本，写错的可以手动加入。
3. **跟读。** 每遍录音前自动放几次原声，嘀一声开口，说完点「说完了」；念砸了点「这遍重来」。
   默认录 3 遍一起比对。

练过的句子才在列表里显示原文；首页有打卡格子和连续天数，列表可以筛出没练过、
问题没解决、没听懂的句子。播放可以放慢到 0.5× / 0.75×，只作用于「听」，跟读前的示范永远原速。

## 反馈怎么看

**单次录音的随机波动和真实进步是同一个量级。** 所以一轮录几遍，指标取中位数，
而且**只报在半数以上的遍数里都出现的问题**——一致性才是信号，某一遍特别糟很可能只是噪声。

- **可懂度**：机器听出了原句多少个词。
- **发声 / 停顿**：分开看。整句只慢 8% 看着没问题，实际可能是发声慢了 16%、停顿少了 40%，
  两个方向相反的偏差在总时长上抵消了。

两张图各只编码一个变量：

- **图 1 · 节奏**：真实秒数轴，原声和你上下两行。块宽 = 这个词读了多久，空隙 = 停顿；
  红线标出你在哪个词上已经落后多少。
- **图 2 · 音高**：一词一格，虚线 = 原声，实线 = 你，已按各自的基频归一化，男声女声可以直接比。
  线往下走 = 降调。词多了自动折行。点一个词（或拖选几个）会原声、你的轮流放。

## 素材库和生词本

- **素材库**：贴一个链接导入（YouTube、播客都行，60 分钟以内），下载、转写、切句在后台跑，
  期间可以照常练别的。可以切换素材；删除一份素材会删掉它的全部录音和记录，只保留打卡格子和连续天数。
- **生词本**：默写里记下的词，带释义、记过几次，以及出自哪句——点原句能回去再练。记住了就移出。

导入的素材和录音只存在本机，仅供个人练习。

## 命令行

网页之外，命令行也能用：

```bash
uv run shadow import <url>              # 导入素材：下载、转写、强制对齐、切句
uv run shadow list -s                   # 列出素材和片段
uv run shadow units <segment_id>        # 看一个片段切成了哪几句
uv run shadow audit                     # 全库体检，挑出切坏的句子
uv run shadow export <segment_id> -u 2  # 导出某一句的音频
uv run shadow progress                  # 跨天的练习记录
uv run shadow recompute                 # 分析规则改了之后，用新代码重算历史录音
uv run shadow dict lookup <word>        # 查词
```

## 数据位置

默认 `~/.shadow`，可以用环境变量 `SHADOW_DATA_DIR` 换地方：

```
~/.shadow/
├── shadow.db       # 素材、句子、练习记录、生词本
├── dict.sqlite     # 离线词典（shadow dict install 装的）
└── audio/          # 原声、切好的句子、每遍录音
```

## 开发

```bash
uv run pytest
```

设计文档和实施计划在 [`docs/superpowers/`](docs/superpowers/)。分析模块（`analysis/`）和切句
（`ingest/segmenter.py`、`drill/units.py`）都是纯函数，不碰数据库和网络，可以单独测试。

## 许可证

[MIT](LICENSE)。离线词典来自 [ECDICT](https://github.com/skywind3000/ECDICT)（MIT），
安装时下载，不随仓库分发。
