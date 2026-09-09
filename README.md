# Shadow

英语影子跟读训练工具（命令行内核，M1 + M2）。

针对一个具体问题：**英语是「读」出来的，不是「听」出来的。** 开字幕懂 80%、关字幕掉到
40%，开口时每个词都发满、没有弱读和节奏起伏。这个工具做的事是把训练材料切成可跟读的
片段，然后在你跟读之后告诉你**具体哪个词读错了、哪里节奏不对**——而不是笼统地说「再练练」。

设计与取舍见 [`docs/superpowers/specs/2026-09-09-english-shadowing-design.md`](docs/superpowers/specs/2026-09-09-english-shadowing-design.md)。

## 安装

```bash
brew install ffmpeg yt-dlp
uv sync
```

首次运行 `import` 或 `compare` 会自动下载 Whisper 模型 `large-v3-turbo`（约 1.5 GB）。

## 用法

```bash
uv run shadow import <url>          # 导入素材，自动转写并切成 30-90s 片段
uv run shadow list -s               # 列出素材与片段
uv run shadow export <segment_id> -o /tmp/ref.wav   # 导出片段用于跟读
uv run shadow compare --segment <id> --user /tmp/me.wav -o /tmp/out.png
```

也可以完全脱离素材库，直接比较两个 wav：

```bash
uv run shadow compare --ref ref.wav --user me.wav -o out.png
```

## 反馈图怎么看

**Panel 1 · 语调轮廓** — 蓝实线是原声，红虚线是你。看**形状**，不看高低：纵轴已按各自
基频中位数归一化成半音，所以男声女声也能直接叠。原声通常是波浪线，你大概率是接近平的
——那就是「逐词等重音」。

**Panel 2 · 轻重分布** — 能量包络。原声有明显的强弱交替，你的可能是均匀的锯齿。

**Panel 3 · 节奏（主图）** — 每个词「你的时长 ÷ 原声时长」。
- 柱子**高于 1.0** = 你把这个词拖长了。如果它是 `have` / `to` / `the` 这类功能词，
  说明你该弱读的地方发满了——这是中文母语者最典型的问题。
- **红底红字的词** = Whisper 没在你的录音里听出这个词。这是硬指标，没有辩解空间。

## 数据位置

默认 `~/.shadow`，可用环境变量 `SHADOW_DATA_DIR` 覆盖：

```
~/.shadow/
├── shadow.db
└── audio/{sources,segments,attempts}/
```

## 开发

```bash
uv run pytest        # 84 个测试
```

纯函数模块（`analysis/` 四个 + `ingest/segmenter.py` + `drill/blanks.py`）不碰数据库和
网络，可脱离环境单独测试——切片边界、挖空选词、时间弯折是最容易出静默 bug 的地方。
