// 刻意不用框架：每一步就是一段表单，唯一需要 JS 的是连播和录音。

// ---------- 首页：揭晓未练过的原文（需要显式勾选）----------
const reveal = document.getElementById("reveal");
if (reveal) {
  const apply = () => {
    document.querySelectorAll(".masked").forEach((span) => {
      span.textContent = reveal.checked ? span.dataset.text
                                        : span.dataset.placeholder;
    });
  };
  document.querySelectorAll(".masked").forEach((span) => {
    span.dataset.placeholder = span.textContent.trim();
  });
  reveal.checked = localStorage.getItem("shadow.reveal") === "1";
  reveal.addEventListener("change", () => {
    localStorage.setItem("shadow.reveal", reveal.checked ? "1" : "0");
    apply();
  });
  apply();
}

// ---------- 首页筛选 ----------
// 盲听自评一直存着却没人用过。它正好回答一个问题：哪些句子是真没听懂的。
const filters = document.getElementById("filters");
if (filters) {
  const body = document.querySelector("table.units tbody");
  const rows = [...body.querySelectorAll("tr")];
  const count = document.getElementById("filter-count");
  const keep = {
    all: () => true,
    review: (row) => row.dataset.review === "1",     // 服务端按日课的规则算好了
    fresh: (row) => Number(row.dataset.runs) === 0,
    issues: (row) => Number(row.dataset.issues) > 0,
    unheard: (row) => row.dataset.rating !== "" && Number(row.dataset.rating) <= 2,
  };
  const rank = (row) => Number(row.dataset.reviewRank) || Infinity;

  filters.addEventListener("click", (event) => {
    const button = event.target.closest("button");
    if (!button) return;
    filters.querySelectorAll("button").forEach(
      (one) => one.classList.toggle("chosen", one === button));
    const name = button.dataset.filter;
    const test = keep[name];
    let shown = 0;
    rows.forEach((row) => {
      const ok = test(row);
      row.hidden = !ok;
      if (ok) shown += 1;
      // 从筛选点进去的句子，练习页的「下一句」也在同一个筛选里找
      const link = row.querySelector('a[href^="/practice/"]');
      if (link) {
        link.dataset.base ??= link.getAttribute("href");
        link.setAttribute("href",
          name === "all" ? link.dataset.base : `${link.dataset.base}?from=${name}`);
      }
    });
    // 「该复习」按急迫程度重排（名次是服务端算的）：老问题、没听懂、逾期久的排前面。
    // 别的筛选回到原文顺序。
    const walk = name === "review"
      ? [...rows].sort((one, other) => rank(one) - rank(other))
      : rows;
    walk.forEach((row) => body.append(row));
    // 「该复习」把列表重排过，不说一句会以为是乱序
    count.textContent = name === "all" ? ""
      : name === "review" ? `${shown} 句 · 按急迫程度排` : `${shown} 句`;
  });
}

// ---------- 首页：今天的日课 ----------
// 勾选存在服务里，手机和电脑看到的一样；卡片收起与否只是这台设备上的习惯，存在本机。
const planCard = document.getElementById("plan");
if (planCard) {
  const OPEN_KEY = "shadow.plan-open";
  try {
    if (localStorage.getItem(OPEN_KEY) === "0") planCard.open = false;
  } catch (err) { /* 隐私模式下读不到，默认展开 */ }
  // 顶栏的「日课」指到这里：收着的话先打开，再滚过去
  if (window.location.hash === "#plan") {
    planCard.open = true;
    planCard.scrollIntoView({ block: "start" });
  }
  planCard.addEventListener("toggle", () => {
    try { localStorage.setItem(OPEN_KEY, planCard.open ? "1" : "0"); } catch (err) { /* 无所谓 */ }
  });

  const summary = planCard.querySelector("summary");
  const showDone = (allDone) => {
    const badge = summary.querySelector(".plan-done");
    if (allDone && !badge) {
      summary.insertBefore(el("span", "plan-done", "做完了"), summary.querySelector(".plan-toggle"));
    }
    if (!allDone && badge) badge.remove();
  };

  planCard.querySelectorAll(".plan-check").forEach((box) => {
    box.addEventListener("change", async () => {
      const step = box.closest(".plan-step");
      const wanted = box.checked;
      step.classList.toggle("done", wanted);
      step.querySelector(".plan-error")?.remove();
      try {
        const response = await fetch("/api/plan", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ step: box.dataset.step, done: wanted }),
        });
        if (!response.ok) throw new Error(String(response.status));
        showDone((await response.json()).all_done);
      } catch (err) {
        // 没存上就退回去，别让人以为勾上了
        box.checked = !wanted;
        step.classList.toggle("done", !wanted);
        step.querySelector(".plan-body").append(el("span", "plan-error", "没存上，服务恢复后再勾一次"));
        service.check();
      }
    });
  });

  // 「筛出该复习的 N 句」：点中列表上的筛选，再滚到列表
  planCard.querySelectorAll("[data-filter-link]").forEach((link) => {
    link.addEventListener("click", (event) => {
      const button = document.querySelector(
        `#filters button[data-filter="${link.dataset.filterLink}"]`);
      if (!button) return;
      event.preventDefault();
      button.click();
      const still = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
      document.getElementById("units").scrollIntoView(
        { behavior: still ? "auto" : "smooth", block: "start" });
    });
  });
}

// ---------- 练习页 ----------
// 点了打分、对答案、开始，还在连播的原声就停：听两遍就懂了，不必等十遍放完
const loops = new Set();
function stopLoops() {
  loops.forEach((stop) => stop());
}

// 跟读那一步一开始，原声就由它自己按节奏放。这时别处再放一路，两个原声叠在一起，
// 跟读全废——所以从「开始」到收工，连播的按钮一律停用（键盘也走同一条路）。
let recording = false;
function setRecording(on) {
  recording = on;
  stopLoops();
  document.querySelectorAll("button.play").forEach((button) => {
    button.disabled = on;
  });
}

// 做完的一步，序号换成绿色对勾。灰色留给「还不能做」——做完了和没解锁不能长一个样
function markComplete(step) {
  if (!step || step.classList.contains("complete")) return;
  step.classList.add("complete");
  const badge = step.querySelector("h2 .n");
  if (badge) badge.textContent = "✓";
}

const root = document.getElementById("practice");
if (root) {
  const segment = root.dataset.segment;
  const unit = root.dataset.unit;
  const counts = new WeakMap();

  // 连播：一遍放完接着下一遍，中途可停
  document.querySelectorAll("button.play").forEach((button, index) => {
    const row = button.parentElement;
    const label = row.querySelector(".plays");
    const timesInput = row.querySelector("input.times");
    const idle = button.textContent;      // 放完要变回「▶ 播放（2.6s）」
    counts.set(button, 0);
    let audio = null;
    let left = 0;
    let gap = null;
    let playing = false;

    const finish = () => {
      clearTimeout(gap);        // 两遍之间有半秒空档，这时停也不能再冒出一遍
      if (audio) { audio.pause(); audio = null; }
      left = 0;
      playing = false;
      button.textContent = idle;
      button.classList.remove("stop");
    };
    loops.add(finish);

    const playOnce = () => {
      audio = speed.apply(new Audio(button.dataset.src));
      audio.addEventListener("ended", () => {
        counts.set(button, counts.get(button) + 1);
        if (label) label.textContent = `听了 ${counts.get(button)} 遍`;
        left -= 1;
        if (left > 0) gap = setTimeout(playOnce, 500);
        else finish();
      });
      // 刚开播就被停掉，play() 会报「被 pause 打断」，那是预期内的
      audio.play().catch((err) => { if (err.name !== "AbortError") throw err; });
    };

    button.addEventListener("click", () => {
      // 放着的时候，这个按钮就是「停」：另起一个按钮会让它旁边的东西跳位置
      if (playing) {
        finish();
        return;
      }
      stopLoops();              // 另一段还在放就先停，两段叠在一起什么都听不清
      left = Math.max(1, Number(timesInput ? timesInput.value : 1) || 1);
      playing = true;
      button.textContent = "■ 停";
      button.classList.add("stop");
      playOnce();
    });
    // 速度是全局的，两处播放共用一个设置：只在第一处显示，免得以为各管各的
    if (index === 0) row.append(speedControl());
  });

  // 第一步：盲听打分
  const listenStep = document.getElementById("step-listen");
  listenStep.querySelectorAll(".rating button").forEach((button) => {
    button.addEventListener("click", async () => {
      stopLoops();
      listenStep.querySelectorAll(".rating button")
        .forEach((b) => b.classList.remove("chosen"));
      button.classList.add("chosen");
      const body = new FormData();
      body.append("segment", segment);
      body.append("unit", unit);
      body.append("rating", button.dataset.rating);
      const note = listenStep.querySelector(".saved");
      note.hidden = false;
      try {
        const response = await fetch("/api/rating", { method: "POST", body });
        note.textContent = response.ok ? "记下了。" : "保存失败。";
        note.classList.toggle("bad", !response.ok);
      } catch (err) {
        // 听已经听过了，别因为存不上就卡住后面的步骤
        note.textContent = "没存上：服务断了。恢复后再点一次分数就行。";
        note.classList.add("bad");
        service.check();
      }
      const drill = document.getElementById("step-drill");
      drill.classList.remove("locked");
      markComplete(listenStep);
      // 展开了但页面不动，还得自己找下去。滚过去；电脑上顺手把光标放进输入框，
      // 手机上不聚焦——弹出的键盘会挡掉半屏
      const still = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
      drill.scrollIntoView({ behavior: still ? "auto" : "smooth", block: "start" });
      if (window.matchMedia("(hover: hover)").matches) {
        document.getElementById("dictation-text")?.focus({ preventScroll: true });
      }
    });
  });

  // 电脑上练一句，手要在鼠标和键盘之间来回好几趟。接管几个最常用的键；
  // 只要光标在输入框里，一律不接管——那时每个键都该是在打字。
  // 认键一律用 physicalKey：中文输入法开着时 event.key 会变成 "Process"
  document.addEventListener("keydown", (event) => {
    if (event.metaKey || event.ctrlKey || event.altKey || event.isComposing) return;
    if (event.target.closest("input, textarea, select, [contenteditable]")) return;
    const key = physicalKey(event);

    if (key === " ") {
      if (recording) {
        // 正在录这一遍：空格就是「说完了」。别的时候不放音——原声正按节奏走着
        const done = document.getElementById("stop-take");
        if (done && !done.hidden) {
          event.preventDefault();
          done.click();
        }
        return;
      }
      // 放最后展开的那一步的音：练到第二步了，空格该放的是第二步的重听
      const buttons = [...document.querySelectorAll(".step:not(.locked) button.play")];
      const play = buttons[buttons.length - 1];
      if (!play) return;
      event.preventDefault();
      play.click();
      return;
    }
    if (/^[1-5]$/.test(key)) {
      const rating = listenStep.querySelector(`.rating button[data-rating="${key}"]`);
      if (!rating) return;
      event.preventDefault();
      rating.click();
      return;
    }
    if (key === "ArrowRight" || key === "ArrowLeft") {
      if (recording) return;          // 录到一半翻页，刚录的几遍就没了
      const link = document.querySelector(
        key === "ArrowRight" ? ".pager a.next" : ".pager a:not(.next)");
      if (!link) return;
      event.preventDefault();
      window.location.assign(link.href);
    }
  });

  // 第二步：整句默写。一整句写在一个框里，漏了词挪光标补上；不会的词写一个 ?
  const drillStep = document.getElementById("step-drill");
  const submitDrill = document.getElementById("submit-drill");
  const typed = document.getElementById("dictation-text");
  const counter = document.getElementById("dictation-count");
  const wordTotal = Number(counter.dataset.total);
  const PLACEHOLDER = /^[?？]+$/;
  const HAS_WORD = /[a-z0-9]/i;        // 和服务端判分的拆法一致：纯标点不算词

  const refreshCount = () => {
    const written = typed.value.split(/\s+/)
      .filter((token) => PLACEHOLDER.test(token) || HAS_WORD.test(token)).length;
    counter.textContent = `已写 ${written} / ${wordTotal} 个词`;
    counter.classList.toggle("over", written > wordTotal);
  };
  typed.addEventListener("input", refreshCount);
  typed.addEventListener("keydown", (event) => {
    // 回车就是对答案；输入法选词的回车不算
    if (physicalKey(event) !== "Enter" || event.isComposing || event.shiftKey) return;
    event.preventDefault();
    submitDrill.click();
  });
  // 在光标处插一个 ?，前后补空格，光标停在它后面接着写
  document.getElementById("dictation-unknown").addEventListener("click", () => {
    const { selectionStart: from, selectionEnd: to, value } = typed;
    const before = value.slice(0, from).replace(/\s+$/, "");
    const after = value.slice(to).replace(/^\s+/, "");
    const head = `${before ? `${before} ` : ""}? `;
    typed.value = head + after;
    typed.focus();
    typed.setSelectionRange(head.length, head.length);
    refreshCount();
  });

  submitDrill.addEventListener("click", async () => {
    stopLoops();
    const replayButton = drillStep.querySelector("button.play");
    const box = drillStep.querySelector(".result");
    submitDrill.disabled = true;
    let response;
    try {
      response = await fetch("/api/dictation", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          segment: Number(segment), unit: Number(unit),
          replays: counts.get(replayButton) || 0,
          text: typed.value,
        }),
      });
    } catch (err) {
      // 写的还在框里：不揭晓、不收起，恢复后再点一次就行
      box.hidden = false;
      box.replaceChildren(el("p", "bad", "没连上服务，写的都还在。恢复后再点「对答案」。"));
      submitDrill.disabled = false;
      service.check();
      return;
    }
    box.hidden = false;
    if (!response.ok) {
      const detail = await response.json().catch(() => ({}));
      box.replaceChildren(el("p", "bad", `没存上：${detail.detail || response.status}`));
      submitDrill.disabled = false;
      return;
    }
    box.replaceChildren(...dictationResult(await response.json()));
    // 框收起来，只留答案和释义；开始跟读时整步再收起
    drillStep.classList.add("graded");
    markComplete(drillStep);
    setFolded(false);
    document.getElementById("step-record").classList.remove("locked");
  });

  // 默写收起后，点标题还能再打开：跟读分析完了，回头看默写错在哪、生词什么意思。
  // 分析一出来就自动打开——那时已经不怕看到原文了。
  const drillTitle = drillStep.querySelector("h2");
  function setFolded(folded) {
    drillStep.classList.add("foldable");
    drillStep.classList.toggle("done", folded);
    drillTitle.tabIndex = 0;
    drillTitle.setAttribute("role", "button");
    drillTitle.setAttribute("aria-expanded", String(!folded));
  }
  drillTitle.addEventListener("click", () => {
    if (drillStep.classList.contains("foldable")) setFolded(!drillStep.classList.contains("done"));
  });
  drillTitle.addEventListener("keydown", (event) => {
    const key = physicalKey(event);
    if (key !== "Enter" && key !== " ") return;
    event.preventDefault();
    drillTitle.click();
  });
  document.addEventListener("shadow:analysed", () => {
    if (!drillStep.classList.contains("graded")) return;
    // 上面多出一段，Safari 不会替你稳住滚动位置：手动补回去，眼前的分析结果不跳走
    const anchor = document.getElementById("step-record");
    const before = anchor.getBoundingClientRect().top;
    setFolded(false);
    window.scrollBy(0, anchor.getBoundingClientRect().top - before);
  });

  // 整句逐词着色：标点照原文放在词的前后。原文由对答案的结果带回来，页面上事先没有
  function gradedLine(line, items) {
    const guesses = new Map(items.map((item) => [item.index, item.guess]));
    const out = el("p", "graded-line");
    line.forEach((token) => {
      if (!token.status) {
        out.append(`${token.lead}${token.core}${token.trail} `);
        return;
      }
      const mark = el("span", `mark mark-${token.status}`, token.core);
      if (token.status === "wrong") mark.title = `你写了 ${guesses.get(token.index)}`;
      if (token.status === "missing") mark.title = "没写";
      out.append(token.lead, mark, `${token.trail} `);
    });
    return out;
  }

  function vocabButton(item, sentence) {
    if (item.status === "unknown") return el("span", "in-vocab", "已加入生词本");
    const button = el("button", "add-vocab", item.in_vocab ? "已在生词本" : "加入生词本");
    button.disabled = item.in_vocab;
    button.addEventListener("click", async () => {
      button.disabled = true;
      try {
        const response = await fetch("/api/vocab", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ word: item.answer, sentence,
                                 segment: Number(segment), unit: Number(unit) }),
        });
        if (!response.ok) throw new Error(String(response.status));
        button.textContent = "已在生词本";
      } catch (err) {
        button.disabled = false;
        button.textContent = "没存上，再点一次";
        service.check();
      }
    });
    return button;
  }

  function missCard(item, data) {
    const entry = item.entry;
    const meanings = el("div", "miss-meanings");
    if (entry && entry.meanings.length) {
      const list = el("ul", "meanings");
      entry.meanings.forEach((meaning) => list.append(el("li", null, meaning)));
      meanings.append(list);
    }
    if (entry && entry.lemma) {
      meanings.append(el("p", "lemma",
        `原形 ${entry.lemma.word}：${entry.lemma.meanings.join("；")}`));
    }
    if (data.dictionary && !(entry && (entry.meanings.length || entry.lemma))) {
      meanings.append(el("p", "lemma", "词典里没有"));
    }

    const card = el("div", `miss miss-${item.status}`);
    const head = el("div", "miss-head");
    // 错得多时，每个词都摊开释义就是一整屏。默认收起，点词才展开；
    // 「不会」的词本来就是要查的，直接展开
    const foldable = Boolean(meanings.childNodes.length);
    const word = foldable ? el("button", "miss-word", item.answer)
                          : el("b", "miss-word", item.answer);
    head.append(word);
    if (entry && entry.phonetic) head.append(el("span", "phonetic", `/${entry.phonetic}/`));
    head.append(el("span", "miss-guess", item.status === "unknown" ? "不会"
      : item.guess ? `你写了 ${item.guess}` : "没写"));
    head.append(vocabButton(item, data.sentence));
    card.append(head);
    if (!foldable) return card;

    card.append(meanings);
    const fold = (open) => {
      card.classList.toggle("open", open);
      word.setAttribute("aria-expanded", String(open));
    };
    fold(item.status === "unknown");
    word.addEventListener("click", () => fold(!card.classList.contains("open")));
    return card;
  }

  function dictationResult(data) {
    const summary = el("p", "tally");
    summary.append(el("b", "tally-ok", `写对 ${data.correct}`), " · ",
                   el("b", "tally-wrong", `写错 ${data.wrong}`), " · ",
                   el("b", "tally-missing", `漏写 ${data.missing}`), " · ",
                   el("b", "tally-unknown", `不会 ${data.unknown}`));
    if (data.extras.length) {
      summary.append(" · ", el("b", "tally-extra", `多写 ${data.extras.length}`));
    }
    // 这里只说点没点重听。原来写「一遍过」，配上「写错 1 · 不会 1」读着像全对了
    summary.append(data.replays ? `，重听 ${data.replays} 遍` : "，没重听");
    const nodes = [summary, gradedLine(data.line, data.items)];
    if (data.extras.length) {
      nodes.push(el("p", "extras", `多写了：${data.extras.join("、")}`));
    }
    const misses = data.items.filter((item) => item.status !== "ok");
    if (misses.length && !data.dictionary) {
      nodes.push(el("p", "hint", "词典还没装：在终端运行 uv run shadow dict install"));
    }
    if (misses.length) {
      const list = el("div", "misses");
      misses.forEach((item) => list.append(missCard(item, data)));
      nodes.push(list);
    }
    return nodes;
  }
}

// ---------- 看一眼原文 ----------
// 默认不显示。你是通过读学的英语，屏幕上有字就会去读它而不是模仿声音——
// 那正是这套练习要拆掉的习惯。但长句子超出工作记忆，记不住就录成一团糊，
// 所以留这个口子，并记下这一遍有没有用过。
let sawText = false;
const peekButton = document.getElementById("peek");
if (peekButton) {
  const peekText = document.getElementById("peek-text");
  peekButton.addEventListener("click", () => {
    peekText.hidden = !peekText.hidden;
    peekButton.textContent = peekText.hidden ? "看一眼原文" : "收起原文";
    if (!peekText.hidden) sawText = true;
  });
}

// ---------- 上次要改的：可以关掉 ----------
const historyBox = document.querySelector(".history");
if (historyBox) {
  const toggle = document.getElementById("history-off");
  const KEY = "shadow:history-off";
  let off = false;
  try { off = localStorage.getItem(KEY) === "1"; } catch (err) { off = false; }
  toggle.checked = off;
  historyBox.classList.toggle("off", off);
  toggle.addEventListener("change", () => {
    historyBox.classList.toggle("off", toggle.checked);
    // 隐私模式下写不了，忽略即可——关掉只是个方便，不是要紧状态
    try { localStorage.setItem(KEY, toggle.checked ? "1" : "0"); } catch (err) { /* 无所谓 */ }
  });
}

// 服务端一行一个 JSON：带 done/total/label 的是进度，带 result 或 error 的是终局。
async function readEvents(response, onProgress) {
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let last = null;
  const take = (line) => {
    if (!line.trim()) return;
    const event = JSON.parse(line);
    if (event.result || event.error) last = event;
    else onProgress(event);
  };
  for (;;) {
    const chunk = await reader.read();
    if (chunk.done) break;
    buffer += decoder.decode(chunk.value, { stream: true });
    const lines = buffer.split("\n");
    buffer = lines.pop();          // 末尾可能是半行，留到下一轮
    lines.forEach(take);
  }
  take(buffer);
  return last;
}

// ---------- 第三步：浏览器录音 ----------
if (root) {
  const segment = root.dataset.segment;
  const unit = root.dataset.unit;
  const status = document.getElementById("rec-status");
  const bar = document.getElementById("rec-progress");
  const fill = bar.querySelector("i");
  const stopButton = document.getElementById("stop-take");
  const redoButton = document.getElementById("redo-take");
  const startButton = document.getElementById("start-record");
  const src = `/audio/${segment}/${unit}`;

  // 局域网 HTTP 下浏览器根本不给麦克风权限，点了也只会静默失败。
  // 与其让人一遍遍试，不如直接说清楚。
  if (!window.isSecureContext) {
    const note = document.getElementById("no-mic");
    if (note) note.hidden = false;
    if (startButton) {
      startButton.disabled = true;
      startButton.title = "需要 HTTPS 或 localhost";
    }
  }

  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

  // 跟读前的示范原声和开录前的嘀声，都走 Web Audio，不用 <audio>。
  //
  // iPhone 上麦克风一打开，<audio> 会被系统打断停在半路，也不再发 ended——
  // 实测只放了一遍，后面整个流程就卡在那儿等。Web Audio 的上下文趁点「开始」
  // 那一下解锁，之后每一遍都能放；万一 ended 还是没来，按时长兜底往下走。
  //
  // 这里刻意不套变速：这几遍是你马上要模仿的东西，放慢了就不是它了，
  // 而比对仍拿原速的原声当基准，每个词都会显得拖长。
  // 每遍原声之间空这么久，几遍下来就是一个节奏；提示音卡在空档正中间，
  // 响完正好是该开口的那一拍，不用先等提示音、再找拍子
  const GAP_MS = 400;
  const BEEP_MS = 120;

  function createSpeaker() {
    const Context = window.AudioContext || window.webkitAudioContext;
    const ctx = new Context();
    const wake = () => { ctx.resume().catch(() => {}); };   // 在点击里调用，iPhone 才放行
    wake();
    const clip = fetch(src)
      .then((response) => {
        if (!response.ok) throw new Error(`原声没取到（${response.status}）`);
        return response.arrayBuffer();
      })
      .then((data) => ctx.decodeAudioData(data));
    clip.catch(() => {});   // 先别报：等 ready() 时由调用方说清楚

    return {
      ready: () => clip,
      running: () => ctx.state === "running",
      wake,
      // 放一遍，放完才返回。ended 没来就按时长兜底，绝不卡住
      async play() {
        const buffer = await clip;
        const source = ctx.createBufferSource();
        source.buffer = buffer;
        source.connect(ctx.destination);
        await new Promise((resolve) => {
          const guard = setTimeout(resolve, buffer.duration * 1000 + 1500);
          source.addEventListener("ended", () => {
            clearTimeout(guard);
            resolve();
          }, { once: true });
          source.start();
        });
      },
      // 嘀一声：戴着耳机时看不见屏幕，必须用声音提示开录。
      // 时长由调用方给：它要卡进播放之间的空档里，不能自己拖时间
      async beep(seconds = BEEP_MS / 1000) {
        const osc = ctx.createOscillator();
        const gain = ctx.createGain();
        osc.frequency.value = 880;
        gain.gain.setValueAtTime(0.0001, ctx.currentTime);
        gain.gain.exponentialRampToValueAtTime(0.22, ctx.currentTime + 0.015);
        gain.gain.exponentialRampToValueAtTime(0.0001, ctx.currentTime + seconds);
        osc.connect(gain).connect(ctx.destination);
        osc.start();
        osc.stop(ctx.currentTime + seconds + 0.02);
        await sleep(seconds * 1000);
      },
      close: () => { ctx.close().catch(() => {}); },
      context: ctx,
    };
  }

  // 说完了自己停：盯着麦克风的实时响度，先出声、后安静一段，就是这一遍说完了。
  //
  // 一直等人点「说完了」，等于每录一遍都要腾出一只手；戴着耳机看不见屏幕时更别扭。
  //
  // 门限不写死——不同麦克风、不同房间的底噪能差一个数量级。两头各取一个：
  // 一头是开录后量到的本底，一头是你自己嗓门的一小截。后者要紧：嗓门轻的人
  // 整条曲线都低，只按绝对值卡，说着说着就会被当成已经不说了。
  //
  // 本底取那 300 毫秒里的**最小**值，不是最大值：嘀声一落就开口的人，最大值量到的
  // 是嗓门而不是底噪，门限会被顶得比说话还高——这一遍从头到尾都算静音，于是说到
  // 一半就收了。最小值即使在说话中间也仍然接近底噪。
  const HUSH_MS = 2200;        // 连着静这么久才算说完。头几遍还没顺下来时，句中犹豫能有两秒
  const CALIBRATE_MS = 300;    // 开录后先量本底
  const SPEECH_MS = 200;       // 累计出声这么久，才算开了口
  const WATCH_MS = 50;
  const FLOOR_CAP = 0.01;      // 本底最高按这个算
  const OF_PEAK = 0.07;        // 门限也不低于自己嗓门峰值的这一截
  const PEAK_DECAY = 0.995;    // 峰值慢慢往下掉：一声咳嗽不该把门限顶住整遍
  const QUIET = 0.005;         // 再低就是数字静音了

  // 上下文在 getUserMedia 之后单独开一个：iPhone 上先开上下文、后拿麦克风，
  // 分析器常年读到 0。开不起来（点击的额度已经用掉了）就借放音那个。
  async function listenTo(stream, spare) {
    const Context = window.AudioContext || window.webkitAudioContext;
    let own = new Context();
    await own.resume().catch(() => {});
    if (own.state !== "running") {
      own.close().catch(() => {});
      own = null;
    }
    const ctx = own || spare;
    if (!ctx) throw new Error("开不起音频上下文");
    const analyser = ctx.createAnalyser();
    if (typeof analyser.getFloatTimeDomainData !== "function") {
      if (own) own.close().catch(() => {});
      throw new Error("这个浏览器读不到实时响度");   // 老 Safari：退回手动
    }
    analyser.fftSize = 1024;
    ctx.createMediaStreamSource(stream).connect(analyser);   // 不接 destination：接了会啸叫
    const frame = new Float32Array(analyser.fftSize);
    return {
      level() {
        analyser.getFloatTimeDomainData(frame);
        let sum = 0;
        for (const sample of frame) sum += sample * sample;
        return Math.sqrt(sum / frame.length);
      },
      close: () => { if (own) own.close().catch(() => {}); },
    };
  }

  // 手机不让出声时（没有点击，iPhone 会把声音挂起），让人点一下：点击里再解锁一次
  const tapToContinue = (label, onTap) => new Promise((resolve) => {
    const button = el("button", "primary", label);
    button.addEventListener("click", () => {
      onTap();
      button.remove();
      resolve();
    }, { once: true });
    document.querySelector("#step-record .live-row").append(button);
  });

  // 声音被挂起了就先叫醒；叫不醒（没有点击不放行）才请人点一下
  const awake = async (speaker) => {
    if (speaker.running()) return;
    speaker.wake();
    for (let i = 0; i < 10 && !speaker.running(); i += 1) await sleep(50);
    if (speaker.running()) return;
    status.classList.remove("live");
    status.textContent = "手机把声音停了，点一下按钮接着放。";
    await tapToContinue("接着放", speaker.wake);
  };

  const recordOne = (stream, ear, minSpoken, autoStop) => new Promise((resolve) => {
    const chunks = [];
    const recorder = new MediaRecorder(stream);
    let began = 0;
    let dropped = false;
    let watch = 0;
    recorder.addEventListener("dataavailable", (e) => chunks.push(e.data));
    const heard = [];
    recorder.addEventListener("stop", () => resolve({
      blob: new Blob(chunks),
      seconds: (performance.now() - began) / 1000,
      dropped,
      loudest: loudestOf(heard),
    }));
    const finish = () => {
      clearInterval(watch);
      stopButton.hidden = true;
      if (redoButton) redoButton.hidden = true;
      recorder.stop();
    };
    stopButton.hidden = false;
    stopButton.onclick = finish;
    if (redoButton) {
      redoButton.hidden = false;
      // 说错了、卡壳了，当场作废重来。不作废的话这一遍会进比对，
      // 而一遍念砸的录音会把三遍的中位数一起带偏。
      redoButton.onclick = () => { dropped = true; finish(); };
    }
    recorder.start();
    began = performance.now();
    if (!ear) return;
    let floor = FLOOR_CAP;
    let peak = 0;
    let spoke = 0;
    let hushFrom = 0;
    watch = setInterval(() => {
      const level = ear.level();
      const now = performance.now();
      heard.push(levelDb(level));     // 音量条由外面那个循环一直画，这里只记这一遍多响
      if (!autoStop) return;
      if (now - began < CALIBRATE_MS) {
        floor = Math.min(floor, level);
        return;
      }
      peak = Math.max(level, peak * PEAK_DECAY);
      if (level > Math.max(floor * 3, peak * OF_PEAK, QUIET)) {
        spoke += WATCH_MS;
        hushFrom = 0;
        return;
      }
      if (spoke < SPEECH_MS) return;   // 还没开过口：不猜，等人点「说完了」
      // 安静了多久按时钟算，不按跑了几拍：切到别的标签页时 setInterval 会被压到一秒一次
      hushFrom = hushFrom || now;
      if (now - hushFrom < HUSH_MS) return;
      // 卡在句子中间的停顿不该算说完，所以看的是「真出过声的时长」够不够，
      // 不是「开录到现在多久」——犹豫再久也攒不出说话时间来
      if (spoke >= minSpoken && now - began >= Math.max(minTotal, minTake * 1000)) finish();
    }, WATCH_MS);
  });

  // 服务端按音频时长卡 config.MIN_ATTEMPT_SEC。这里量的是墙上时间，比实际音频略长，
  // 留一点余量，免得刚过线的又被服务端拒掉。
  const minTake = Number(root.dataset.minTake || 1) + 0.3;
  // 自动停之前至少要真出声这么久（不含停顿）。比的是原声里真出声的时长，不是整段
  // 时长——按整段算的话，跟得比原声快的人永远够不着，只能自己点。
  // 一半是「大致说完了」的下限：说到一半放弃的够不着，跟得比原声快的够得着。
  const refSpoken = Number(root.dataset.spoken || 0)
    || Number(root.dataset.seconds || 0) * 0.7;
  const minSpoken = refSpoken * 0.5 * 1000;
  // 再给一条按整段时长算的下限：头几遍还在把句子理顺，说半句、卡两秒、再接上是常事。
  // 光看「静了多久」分不出这种犹豫和说完，就干脆在原声时长的 1.3 倍之前一律不收。
  const minTotal = Number(root.dataset.seconds || 0) * 1.3 * 1000;

  // 自动停判错了（嗓门轻、句中停顿长），得有个地方关掉它，而不是每遍都被截一次。
  // 关掉就是从前那样：一直等人点「说完了」。存在本机，下次进来还是这个选择。
  const autoBox = document.getElementById("auto-stop");
  if (autoBox) {
    try { autoBox.checked = localStorage.getItem("shadow.auto-stop") !== "0"; }
    catch (err) { /* 隐私模式下读不到，默认开着 */ }
    autoBox.addEventListener("change", () => {
      try { localStorage.setItem("shadow.auto-stop", autoBox.checked ? "1" : "0"); }
      catch (err) { /* 无所谓 */ }
    });
  }

  // 麦克风：用的是哪个、现在有多响。录音全靠它，平时却完全看不见——
  // 实测音量一周里从 -25 dB 一路掉到 -50 dB，掉过判定线、三遍全废了才发现。
  const micSelect = document.getElementById("mic");
  const micMeter = document.getElementById("mic-meter");
  const micBar = micMeter?.querySelector("i");
  const micNote = document.getElementById("mic-note");
  const micTest = document.getElementById("mic-test");
  const MIC_KEY = "shadow.mic";
  const QUIET_DB = -52;      // 服务端判「没录上」的线，两边保持一致
  const LOW_DB = -46;        // 还没到线，但已经该往近处挪了
  const LOUD_FRAMES = 6;     // 「最响的 0.3 秒」：每 50 毫秒读一次，取 6 个

  const readMic = () => {
    try { return localStorage.getItem(MIC_KEY) || ""; } catch (err) { return ""; }
  };

  // 和服务端同一种算法：最响那一小段的中位数才是嗓门，不受停顿占多少影响
  const loudestOf = (levels) => {
    if (!levels.length) return null;
    const top = [...levels].sort((a, b) => b - a).slice(0, LOUD_FRAMES);
    return top[Math.floor(top.length / 2)];
  };

  const verdict = (db) => {
    const shown = `${db.toFixed(0)} dB`;
    if (db < QUIET_DB) return `太轻（${shown}），这样会被当成没录上：换个麦克风，或者凑近说`;
    if (db < LOW_DB) return `偏轻（${shown}），麦克风再凑近一点更稳`;
    return `够用（${shown}）`;
  };

  const levelDb = (level) => 20 * Math.log10(level + 1e-9);

  const showLevel = (db) => {
    if (!micMeter) return;
    micMeter.hidden = false;
    micBar.style.width = `${Math.max(2, Math.min(100, (db + 70) * 100 / 70))}%`;
    micMeter.classList.toggle("low", db < LOW_DB);
  };

  // 麦克风从点「开始」起就一直开着（Chrome 标签页上那个小红点就是它），
  // 音量条也就一直动：放原声时也看得见环境多吵、麦克风通不通。
  // 只有每遍录音那几秒的声音会被存下来，别的时候只是量响度。
  const watchLevel = (ear) => {
    const timer = setInterval(() => showLevel(levelDb(ear.level())), 50);
    return () => clearInterval(timer);
  };

  const say = (text, low) => {
    if (!micNote) return;
    micNote.textContent = text;
    micNote.classList.toggle("low", Boolean(low));
  };

  async function fillMics() {
    if (!micSelect || !navigator.mediaDevices?.enumerateDevices) return;
    let devices;
    try { devices = await navigator.mediaDevices.enumerateDevices(); } catch (err) { return; }
    const mics = devices.filter((device) => device.kind === "audioinput");
    if (!mics.length) return;
    const chosen = micSelect.value || readMic();
    micSelect.replaceChildren(...mics.map((mic, index) => {
      const option = el("option", null,
                        mic.label || `麦克风 ${index + 1}（点「试音」后显示名字）`);
      option.value = mic.deviceId;
      return option;
    }));
    if (mics.some((mic) => mic.deviceId === chosen)) micSelect.value = chosen;
  }

  micSelect?.addEventListener("change", () => {
    try { localStorage.setItem(MIC_KEY, micSelect.value); } catch (err) { /* 隐私模式 */ }
    showSettings();
  });
  fillMics();

  // 录几遍、听几次、自动停、麦克风都收进「设置」里：第一次打开这一步，
  // 六样东西挤成两行，不知道该先点哪个。收起时标题上写着当前是什么设置
  const more = document.getElementById("rec-more");
  const moreSummary = document.getElementById("rec-more-summary");
  const takesInput = document.getElementById("takes");
  const preInput = document.getElementById("prelisten");
  const MORE_KEY = "shadow.rec-more";

  function showSettings() {
    if (!moreSummary) return;
    const auto = autoBox?.checked === false ? " · 手动停" : "";
    moreSummary.textContent =
      `录 ${takesInput.value} 遍 · 每遍前听 ${preInput.value} 次${auto}`;
  }

  if (more) {
    try { more.open = localStorage.getItem(MORE_KEY) === "1"; }
    catch (err) { /* 隐私模式下读不到，默认收起 */ }
    more.addEventListener("toggle", () => {
      try { localStorage.setItem(MORE_KEY, more.open ? "1" : "0"); } catch (err) { /* 无所谓 */ }
    });
    [takesInput, preInput, autoBox].forEach(
      (input) => input?.addEventListener("change", showSettings));
    showSettings();
  }

  const micWanted = () => {
    const id = micSelect?.value || readMic();
    return {
      ...(id ? { deviceId: { exact: id } } : {}),
      // 开降噪：生活噪音一旦超过门限就会被当成发声起点，整段测量跟着前移。
      // 但不开自动增益——它会在静音处把底噪顶上来，正好帮倒忙。
      noiseSuppression: true, echoCancellation: true, autoGainControl: false,
    };
  };

  // 试音：五秒，边说边看音量条，完了给一句结论
  let testing = null;
  micTest?.addEventListener("click", async () => {
    if (testing) { testing(); return; }
    micTest.textContent = "停止试音";
    say("说句话看看 …");
    let stream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: micWanted() });
    } catch (err) {
      micTest.textContent = "试音";
      say("拿不到麦克风权限。浏览器地址栏左侧可以重新允许。", true);
      return;
    }
    await fillMics();          // 给过权限之后才拿得到设备名字
    let ear = null;
    try { ear = await listenTo(stream, null); } catch (err) { ear = null; }
    if (!ear) {
      stream.getTracks().forEach((track) => track.stop());
      micTest.textContent = "试音";
      say("这个浏览器读不到实时音量，直接录一遍看看吧。", true);
      return;
    }
    const heard = [];
    const timer = setInterval(() => {
      const db = levelDb(ear.level());
      heard.push(db);
      showLevel(db);
    }, 50);
    const stopAt = setTimeout(() => testing?.(), 5000);
    testing = () => {
      clearInterval(timer);
      clearTimeout(stopAt);
      ear.close();
      stream.getTracks().forEach((track) => track.stop());
      if (micMeter) micMeter.hidden = true;
      micTest.textContent = "试音";
      testing = null;
      const loudest = loudestOf(heard);
      say(loudest === null ? "没量到声音" : `刚才${verdict(loudest)}`,
          loudest !== null && loudest < LOW_DB);
    };
  });

  startButton?.addEventListener("click", async () => {
    setRecording(true);         // 连播还开着的话会录进去，别处也不许再放
    const speaker = createSpeaker();     // 趁这一下点击解锁声音，原声同时开始下载
    const takes = Math.max(1, Number(document.getElementById("takes").value) || 1);
    const pre = Math.max(0, Number(document.getElementById("prelisten").value) || 0);
    startButton.disabled = true;
    // 默写的答案和释义看完了，开录时收起来：跟读时屏幕上不该有原文
    document.getElementById("step-drill").classList.add("done");
    let stream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: micWanted() });
    } catch (err) {
      status.textContent = "拿不到麦克风权限。浏览器地址栏左侧可以重新允许。";
      speaker.close();
      setRecording(false);
      startButton.disabled = false;
      return;
    }
    fillMics();          // 给过权限之后才拿得到设备名字
    // 读不到实时响度（浏览器不给、上下文开不起来）就退回纯手动，不拦着人练。
    // 把自动停关了也照样读：音量条得一直看得见
    let ear = null;
    try {
      ear = await listenTo(stream, speaker.context);
    } catch (err) {
      ear = null;
    }
    const meterOff = ear ? watchLevel(ear) : null;
    const wrapUp = () => {
      setRecording(false);
      meterOff?.();
      stream.getTracks().forEach((t) => t.stop());
      ear?.close();
      speaker.close();
      if (micMeter) micMeter.hidden = true;
      status.classList.remove("live");
      startButton.disabled = false;
    };

    status.textContent = "正在准备原声 …";
    const outcome = await Promise.race([
      speaker.ready().then(() => "ok", (err) => err.message || "原声解不开"),
      sleep(20000).then(() => "原声 20 秒还没下载完"),
    ]);
    if (outcome !== "ok") {
      status.textContent = `${outcome}。检查一下网络，再点「开始」。`;
      wrapUp();
      return;
    }

    const blobs = [];
    let short = 0;
    for (let take = 1; take <= takes; ) {
      status.classList.remove("live");
      for (let i = 1; i <= pre; i += 1) {
        await awake(speaker);
        status.textContent = `第 ${take}/${takes} 遍 —— 先听 ${i}/${pre}`;
        await speaker.play();
        if (i < pre) await sleep(GAP_MS);      // 最后一遍的空档留给提示音
      }
      await awake(speaker);
      status.textContent = pre
        ? `第 ${take}/${takes} 遍 —— 跟着这个节奏开口`
        : `第 ${take}/${takes} 遍 —— 嘀一声之后开始说`;
      // 放完到开口，空得和前面每遍之间一样久，提示音卡在正中间
      const half = pre ? Math.max(0, (GAP_MS - BEEP_MS) / 2) : 0;
      await sleep(half);
      await speaker.beep();
      await sleep(half);
      // 音量条要一直读，所以 ear 一直在；会不会自动收得看那个勾
      status.textContent = ear && autoBox?.checked !== false
        ? `第 ${take}/${takes} 遍 —— 录音中，说完停一下就自动收`
        : `第 ${take}/${takes} 遍 —— 录音中，说完点「说完了」`;
      status.classList.add("live");
      const clip = await recordOne(stream, ear, minSpoken, autoBox?.checked !== false);

      if (clip.dropped) {
        status.classList.remove("live");
        status.textContent = `第 ${take} 遍作废，重来一次。`;
        await sleep(900);
        continue;
      }

      // 太短的就地重录这一遍。等录完三遍再由服务端拒收，等于逼人从头再来一轮。
      if (clip.seconds < minTake) {
        short += 1;
        status.classList.remove("live");
        if (short >= 3) {
          status.textContent = "连着三遍都太短。是不是「说完了」点早了？先歇一下再来。";
          break;
        }
        status.textContent = `第 ${take} 遍只录到 ${clip.seconds.toFixed(1)} 秒，太短了`
          + " —— 嘀声之后再开口，说完再点「说完了」。这一遍重来。";
        await sleep(2000);
        continue;
      }
      short = 0;
      blobs.push(clip.blob);
      // 每遍录完就说一句响度：太轻的话当场看见，不用等三遍录完被服务端拒收
      if (clip.loudest !== null) {
        say(`第 ${take} 遍${verdict(clip.loudest)}`, clip.loudest < LOW_DB);
      }
      take += 1;
    }
    wrapUp();      // 录完也要把上下文关掉：一次点「开始」漏一个，几轮之后浏览器就不再给了
    if (blobs.length) await submit(blobs);
  });

  // 录音只存在这个页面里。服务断了、提交失败，也不能把它们扔掉——
  // 留着，恢复后点「重新提交」，不用再录一轮。
  const resubmitButton = document.getElementById("resubmit");
  let pending = null;
  resubmitButton?.addEventListener("click", () => {
    if (pending) submit(pending);
  });

  function lost(count) {
    bar.classList.remove("working");
    bar.hidden = true;
    status.textContent = `没连上服务。刚录的 ${count} 遍还在这个页面里——`
      + "服务恢复后点「重新提交」，先别刷新页面。";
    if (resubmitButton) resubmitButton.hidden = false;
    service.check();
  }

  async function submit(blobs) {
    pending = blobs;
    if (resubmitButton) resubmitButton.hidden = true;
    startButton.disabled = true;
    status.textContent = "正在转写和比对，大约十几秒 …";
    const box = document.getElementById("rec-result");

    const body = new FormData();
    body.append("segment", segment);
    body.append("unit", unit);
    body.append("saw_text", sawText ? "1" : "0");
    blobs.forEach((blob, i) => body.append("files", blob, `take${i + 1}.webm`));

    let last;
    try {
      const response = await fetch("/api/takes", { method: "POST", body });
      if (!response.ok) {
        // 录音本身不合格（太短、静音），重交也没用
        pending = null;
        const detail = await response.json().catch(() => ({}));
        status.textContent = "";
        box.hidden = false;
        box.innerHTML = `<p class="bad">${detail.detail || "比对失败"}</p>`;
        return;
      }
      bar.hidden = false;
      bar.classList.add("working");
      fill.style.width = "0%";
      last = await readEvents(response, (p) => {
        fill.style.width = `${Math.round((p.done / p.total) * 100)}%`;
        status.textContent = `${p.label}（${p.done + 1}/${p.total}）`;
      });
    } catch (err) {
      // 连不上，或者比对到一半服务没了
      lost(blobs.length);
      return;
    } finally {
      startButton.disabled = false;
    }

    pending = null;
    bar.classList.remove("working");
    bar.hidden = true;
    status.textContent = "";
    box.hidden = false;
    if (!last || last.error) {
      box.innerHTML =
        `<p class="bad">${(last && last.error) || "比对中断了，重录一遍试试。"}</p>`;
      return;
    }
    // 分析完了：默写那一步可以重新打开，回头看错在哪
    markComplete(document.getElementById("step-record"));
    document.dispatchEvent(new CustomEvent("shadow:analysed"));
    showResult(last.result, box);
  }

  function showResult(data, box) {
    box.innerHTML =
      // 每一遍自己也有同名的三个数，不写清楚这是几遍的中位就容易混
      `<div class="metrics"><span class="metrics-label">${data.count} 遍的中位</span>` +
      `<span>可懂度 <b>${data.accuracy}%</b></span>` +
      `<span>发声 <b>${data.speech}x</b></span>` +
      `<span>停顿 <b>${data.pause === null ? "—" : data.pause + "x"}</b></span></div>` +
      data.rejected.map((r) =>
        `<p class="bad">第 ${r.index} 遍没收进来：${r.reason}</p>`).join("") +
      data.skipped.map((s) =>
        `<p class="bad">跳过第 ${s.index} 遍：开头有 ${s.drift} 秒的话没进转写，比不了</p>`).join("") +
      (data.issues.length
        ? "<p><b>下一遍改这些：</b></p>" + data.issues.map((i) =>
            `<div class="issue"><b>${i.title}</b>（${i.hits}/${i.total} 次）` +
            `<span>${i.detail}</span><span>${i.action}</span></div>`).join("")
        : "<p class='ok'>没有反复出现的问题。</p>") +
      (data.good.length ? `<p class="guessed">做对了，保持：${data.good.join(" / ")}</p>` : "");
    // 播放条摆在最前面：录完第一件想做的事是听自己刚才那遍
    const figures = renderFigures(data.view);
    box.prepend(figures.controls);
    box.append(figures.figures);
  }
}
