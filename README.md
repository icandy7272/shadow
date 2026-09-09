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

**每轮录 3 遍，一次全传进去：**

```bash
uv run shadow compare --segment 2 --unit 1 \
  --user t1.wav --user t2.wav --user t3.wav -o out.png
```

单次录音的随机波动和真实进步是同一个量级（实测句尾升降的标准差 1.68，
而目标值只有 −5.0）。传多个 take 时，工具取中位数、给出范围，并且
**只报在半数以上 take 里都出现的问题**——一致性才是信号，某一次特别糟
很可能只是噪声。排序也以一致性优先：3/3 次犯的小毛病，比 2/3 次犯的
大毛病更值得改。

也可以完全脱离素材库，直接比较两个 wav：

```bash
uv run shadow compare --ref ref.wav --user me.wav -o out.png
```

## 反馈怎么看

跑完 `compare` 会得到**一段文字诊断**和**两张图**。

### 文字诊断（终端直接输出）

先看这个。它已经排好序，直接告诉你下一遍改哪几处：

```
可懂度 100%（13 个词）
  发音层面没问题——每个词机器都听出来了。

发声 1.16x    停顿 0.60x    整句 1.08x

下一遍改这 3 处，按重要性排：

  1. "Today," 该升没升
     现状：原声在这个词里把音调抬起 3 个半音，你反而降了 2 个。
     怎么做：读 "Today," 时把声音往上挑一下。
  ...
```

**「发声」和「停顿」要分开看。** 上面这组数字里整句只慢 8%，看着没问题，
但实际上是发声慢了 16%、停顿少了 40%，两个偏差方向相反在总时长上抵消了。
只看整体语速会把真正的问题藏住。

### 图 1 · 节奏

真实秒数轴，上下两行。块宽 = 这个词读了多久，块之间的空隙 = 真实停顿。
红色竖带标出**原声有停顿而你没停**的位置，红线标出你在某个词上已经落后多少。

### 图 2 · 音高

一词一格，虚线框 = 原声，实心块 = 你，两者左对齐所以可以直接比。

- **块的高低** = 音高（已按各自基频中位数归一化，男声女声也能直接比）
- **块的斜度** = 词内的升降。**向下斜 = 降调**，句尾降调靠它才看得见
- 被点名的词会加粗描边并在下方标出问题

两张图刻意各只编码一个变量：图 1 只管时间，图 2 只管音高。之前把时长、
音高、能量塞进同一组曲线的版本，实测使用者完全读不懂。

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
