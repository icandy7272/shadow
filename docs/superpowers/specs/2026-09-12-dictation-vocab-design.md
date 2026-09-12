# 默写和生词本

日期：2026-09-12
状态：已确认，开始实现

## 背景

练习页第二步「精听填空」只挖弱读的功能词，每句最多 12 个空。现在这些基本都能听清，改成整句默写：每个词都要写，不会的可以勾「不会」。不会的词给出释义，并记进生词本。

## 目标

- 第二步改成整句默写，每一句都有这一步
- 用离线英汉词典（ECDICT，MIT 协议）给不会和写错的词显示音标、中文释义
- 新增生词本页面：记下不会的词、出处原句、记过几次；「记住了」就移出

## 不做

- 联网或调用 Claude 生成语境解释
- 数字写法互通（30 和 thirty）
- 原文和实际读音对不上时的容错（比如音频说的是 why'd，原文写成 why did）
- 生词复习、导出

## 默写（练习页第二步）

- 标题「默写」。播放、连播、停、调速照旧
- 每个词一个等宽输入框，不泄露单词长短。词前后的标点显示在框外（`there.` → 框 + `.`）；纯标点的词直接显示，不出框
- 每个框下面一个「不会」勾选框，勾上后这个框变灰、清空，不用填
- 在框里按回车跳到下一个没勾「不会」的框；最后一个框按回车等于点「对答案」
- 点「对答案」后：
  - 顶部一行统计：写对 X · 写错 Y · 不会 Z，重听过就加上重听遍数
  - 整句按顺序显示，写对的绿色、写错的红色、不会的标出来
  - 写错和不会的词逐个列出：你写的（写错时）、正确答案、音标、释义
  - 写错的词旁边有「加入生词本」，点了变「已在生词本」；不会的词标「已加入生词本」
- 词典还没装：释义的位置提示「词典还没装：在终端运行 uv run shadow dict install」
- 对完答案解锁跟读，这一步收起来（照旧）。跟读一律是第 3 步

## 判对

- 忽略大小写、标点和撇号：`I'm` 写成 `Im` 或 `im` 都算对；`there.` 写 `there` 算对
- 空着又没勾「不会」，算写错
- 录音比对共用的 `text.normalise` 保留撇号，不去改它；默写用自己的比较规则

## 查词

- 查词键：小写，去掉首尾标点，保留词中间的撇号和连字符
- 查到：音标 + 释义，每行一个义项，最多显示 4 行
- 词条的词形变化字段里有 `0:原形`（变形词）时，追加原形的释义，比如 graduated → graduate
- 查不到：显示「词典里没有」（人名、地名常见）

## 生词本 `/vocab`

- 顶栏「素材库」旁边加「生词本」入口
- 按最近一次记下的时间倒序。每个词显示：单词、音标、释义、记过几次、第一次记下的日期、出处原句（一个词可以有多个出处）
- 出处的句子还在库里，就链到那句的练习页
- 「记住了」：连同出处一起移出生词本
- 空状态：「还没有生词。默写时勾「不会」的词会记到这里。」

## 数据

- `practice_runs` 迁移新增 `gapfill_unknown INTEGER`。默写沿用 `gapfill_correct`、`gapfill_total`、`gapfill_replays`；`gapfill_heard` 不再写入，旧记录原样保留
- 新表：
  - `vocab(word TEXT PRIMARY KEY, first_added TEXT NOT NULL, last_added TEXT NOT NULL, times INTEGER NOT NULL)`
  - `vocab_sources(word TEXT NOT NULL, sentence TEXT NOT NULL, segment_id INTEGER, unit_index INTEGER, added_at TEXT NOT NULL, PRIMARY KEY (word, sentence))`
- 出处不设外键：删素材时，生词本和出处原句都要留下。片段编号是 AUTOINCREMENT，不会复用，片段还在就能链回去
- 同一个词再次记下：`times + 1`，更新 `last_added`；同一句的出处不重复记
- 词库单独一个文件 `~/.shadow/dict.sqlite`，表 `entries(word TEXT PRIMARY KEY, original TEXT NOT NULL, phonetic TEXT, translation TEXT, exchange TEXT)`，`word` 存查词键

## 词典安装

- `uv run shadow dict install`：下载 `https://raw.githubusercontent.com/skywind3000/ECDICT/master/ecdict.csv`（约 66 MB），边下边显示进度；转成 `dict.sqlite`，先写临时文件，成功后再换上；下载的 CSV 用完即删
- 已经装过：提示已安装并退出；加 `--force` 重装
- 同一个查词键有多条（大小写不同，比如 Jobs 和 jobs）：保留原文本身就是小写的那条
- 释义里的换行在 CSV 里存成字面的 `\n`，建库时还原成真换行
- `uv run shadow dict lookup <词>`：在命令行查词，方便核对

## 接口

- `POST /api/dictation`：`{segment, unit, answers: [{index, guess, unknown}], replays, run_id}` → `{correct, wrong, unknown, total, replays, run_id, sentence, dictionary, items: [{index, answer, guess, status, in_vocab, entry}]}`。不会的词写进生词本；`entry` 只给写错和不会的词
- `POST /api/vocab`：`{word, sentence, segment, unit}`，手动加入 → `{word, times}`
- `DELETE /api/vocab/{word}` → `{removed: true}`；不存在返回 404
- `GET /vocab`：生词本页面
- 删掉 `POST /api/gapfill`

## 清理（功能做完后）

不再挖弱读功能词，下面这些就没用了，一并删掉：`drill/gapfill.py`、`drill/blanks.py`、导入时的 `_apply_blanks`、`Word.is_blank` 和 `with_blanks`、句子列表里的「空」那一列、`shadow units` 输出里的空数、`db.set_gapfill`。旧数据里存着的 `is_blank` 字段，读的时候忽略。

## 测试

- `drill/dictation`：拆出标点、判对（大小写 / 标点 / 撇号）、不会、空着算错、纯标点不判、统计
- `dictionary`：用几行的 CSV 夹具建库，不联网；查词、字面 `\n` 还原、变形词带原形、查不到、没装返回 None、大小写重复时取小写那条；`install` 用注入的下载函数
- db：加入生词、次数累加、同句出处不重复、移出；删素材后生词本还在；`set_dictation` 写入不会数
- web：每句都有默写一步、每个词一个框和「不会」、跟读是第 3 步；`/api/dictation` 的统计和生词写入；词典没装时 `entry` 为空、`dictionary` 为 false；`/api/vocab` 加入与移出；`/vocab` 列出词、出处和链接；顶栏有「生词本」
- cli：`dict install`（注入下载）、已装提示、`dict lookup`；`progress` 显示默写统计
