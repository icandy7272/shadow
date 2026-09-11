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

// ---------- 练习页 ----------
const root = document.getElementById("practice");
if (root) {
  const segment = root.dataset.segment;
  const unit = root.dataset.unit;
  const counts = new WeakMap();

  // 连播：一遍放完接着下一遍，中途可停
  document.querySelectorAll("button.play").forEach((button) => {
    const row = button.parentElement;
    const label = row.querySelector(".plays");
    const stop = row.querySelector("button.stop");
    const timesInput = row.querySelector("input.times");
    counts.set(button, 0);
    let audio = null;
    let left = 0;

    const finish = () => {
      if (audio) { audio.pause(); audio = null; }
      left = 0;
      button.disabled = false;
      if (stop) stop.hidden = true;
    };

    const playOnce = () => {
      audio = new Audio(button.dataset.src);
      audio.addEventListener("ended", () => {
        counts.set(button, counts.get(button) + 1);
        if (label) label.textContent = `听了 ${counts.get(button)} 遍`;
        left -= 1;
        if (left > 0) setTimeout(playOnce, 500);
        else finish();
      });
      audio.play();
    };

    button.addEventListener("click", () => {
      left = Math.max(1, Number(timesInput ? timesInput.value : 1) || 1);
      button.disabled = true;
      if (stop) stop.hidden = false;
      playOnce();
    });
    if (stop) stop.addEventListener("click", finish);
  });

  // 第一步：盲听打分
  const listenStep = document.getElementById("step-listen");
  listenStep.querySelectorAll(".rating button").forEach((button) => {
    button.addEventListener("click", async () => {
      listenStep.querySelectorAll(".rating button")
        .forEach((b) => b.classList.remove("chosen"));
      button.classList.add("chosen");
      const body = new FormData();
      body.append("segment", segment);
      body.append("unit", unit);
      body.append("rating", button.dataset.rating);
      const response = await fetch("/api/rating", { method: "POST", body });
      const note = listenStep.querySelector(".saved");
      note.hidden = false;
      note.textContent = response.ok ? "记下了。" : "保存失败。";
      // 没有挖空位时第二步整个不存在，直接解锁跟读，不让人多点一次
      const next = document.getElementById("step-drill")
                || document.getElementById("step-record");
      next.classList.remove("locked");
    });
  });

  // 第二步：填空（这一句没有挖空位时整段不存在）
  const drillStep = document.getElementById("step-drill");
  document.getElementById("submit-drill")?.addEventListener("click", async () => {
    const answers = [...drillStep.querySelectorAll(".slot")].map((slot) => ({
      index: Number(slot.querySelector("input[type=text]").dataset.index),
      guess: slot.querySelector("input[type=text]").value.trim(),
      guessed: slot.querySelector("input[type=checkbox]").checked,
    }));
    const replayButton = drillStep.querySelector("button.play");
    const response = await fetch("/api/gapfill", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        segment: Number(segment), unit: Number(unit),
        answers, replays: counts.get(replayButton) || 0,
      }),
    });
    const data = await response.json();
    const box = drillStep.querySelector(".result");
    box.hidden = false;
    box.innerHTML =
      `<p>${data.correct}/${data.total} 对，其中 <b>${data.heard}</b> 个是听出来的` +
      (data.replays ? `，重听 ${data.replays} 遍` : "，一遍过") + "</p>" +
      data.items.map((item) => {
        if (item.correct && item.heard) return `<div class="ok">✓ ${item.answer}</div>`;
        if (item.correct) return `<div class="guessed">○ ${item.answer} （猜的，不算听力）</div>`;
        const wrote = item.guess ? `你填了 “${item.guess}”` : "空着";
        return `<div class="bad">✗ ${item.answer} —— ${wrote}，` +
               `原声只有 ${item.ms} 毫秒</div>`;
      }).join("");
    document.getElementById("step-record").classList.remove("locked");
    // 原文已经揭晓，把这一步收起来：跟读时屏幕上不该有字
    drillStep.classList.add("done");
  });
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
  const startButton = document.getElementById("start-record");
  const src = `/audio/${segment}/${unit}`;

  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

  const playOnce = () => new Promise((resolve) => {
    const audio = new Audio(src);
    audio.addEventListener("ended", resolve, { once: true });
    audio.addEventListener("error", resolve, { once: true });
    audio.play();
  });

  // 嘀一声：戴着耳机时看不见屏幕，必须用声音提示开录
  const beep = async () => {
    const ctx = new (window.AudioContext || window.webkitAudioContext)();
    const osc = ctx.createOscillator();
    const gain = ctx.createGain();
    osc.frequency.value = 880;
    gain.gain.setValueAtTime(0.0001, ctx.currentTime);
    gain.gain.exponentialRampToValueAtTime(0.25, ctx.currentTime + 0.02);
    gain.gain.exponentialRampToValueAtTime(0.0001, ctx.currentTime + 0.14);
    osc.connect(gain).connect(ctx.destination);
    osc.start();
    osc.stop(ctx.currentTime + 0.15);
    await sleep(220);
    ctx.close();
  };

  const recordOne = (stream) => new Promise((resolve) => {
    const chunks = [];
    const recorder = new MediaRecorder(stream);
    let began = 0;
    recorder.addEventListener("dataavailable", (e) => chunks.push(e.data));
    recorder.addEventListener("stop", () => resolve({
      blob: new Blob(chunks),
      seconds: (performance.now() - began) / 1000,
    }));
    stopButton.hidden = false;
    stopButton.onclick = () => { stopButton.hidden = true; recorder.stop(); };
    recorder.start();
    began = performance.now();
  });

  // 服务端按音频时长卡 config.MIN_ATTEMPT_SEC。这里量的是墙上时间，比实际音频略长，
  // 留一点余量，免得刚过线的又被服务端拒掉。
  const minTake = Number(root.dataset.minTake || 1) + 0.3;

  startButton?.addEventListener("click", async () => {
    const takes = Math.max(1, Number(document.getElementById("takes").value) || 1);
    const pre = Math.max(0, Number(document.getElementById("prelisten").value) || 0);
    startButton.disabled = true;
    let stream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    } catch (err) {
      status.textContent = "拿不到麦克风权限。浏览器地址栏左侧可以重新允许。";
      startButton.disabled = false;
      return;
    }

    const blobs = [];
    let short = 0;
    for (let take = 1; take <= takes; ) {
      status.classList.remove("live");
      for (let i = 1; i <= pre; i += 1) {
        status.textContent = `第 ${take}/${takes} 遍 —— 先听 ${i}/${pre}`;
        await playOnce();
        await sleep(400);
      }
      status.textContent = `第 ${take}/${takes} 遍 —— 嘀一声之后开始说`;
      await beep();
      status.textContent = `第 ${take}/${takes} 遍 —— 录音中，说完点「说完了」`;
      status.classList.add("live");
      const clip = await recordOne(stream);

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
      take += 1;
    }
    stream.getTracks().forEach((t) => t.stop());
    status.classList.remove("live");
    if (!blobs.length) {
      startButton.disabled = false;
      return;
    }
    status.textContent = "正在转写和比对，大约十几秒 …";

    const body = new FormData();
    body.append("segment", segment);
    body.append("unit", unit);
    body.append("saw_text", sawText ? "1" : "0");
    blobs.forEach((blob, i) => body.append("files", blob, `take${i + 1}.webm`));
    const response = await fetch("/api/takes", { method: "POST", body });
    startButton.disabled = false;
    const box = document.getElementById("rec-result");
    box.hidden = false;
    if (!response.ok) {
      const detail = await response.json().catch(() => ({}));
      status.textContent = "";
      box.innerHTML = `<p class="bad">${detail.detail || "比对失败"}</p>`;
      return;
    }

    bar.hidden = false;
    bar.classList.add("working");
    fill.style.width = "0%";
    const last = await readEvents(response, (p) => {
      fill.style.width = `${Math.round((p.done / p.total) * 100)}%`;
      status.textContent = `${p.label}（${p.done + 1}/${p.total}）`;
    });
    bar.classList.remove("working");
    bar.hidden = true;
    status.textContent = "";
    if (!last || last.error) {
      box.innerHTML =
        `<p class="bad">${(last && last.error) || "比对中断了，重录一遍试试。"}</p>`;
      return;
    }
    const data = last.result;
    box.innerHTML =
      `<div class="metrics"><span>可懂度 <b>${data.accuracy}%</b></span>` +
      `<span>发声 <b>${data.speech}x</b></span>` +
      `<span>停顿 <b>${data.pause === null ? "—" : data.pause + "x"}</b></span>` +
      `<span>${data.count} 遍</span></div>` +
      data.rejected.map((r) =>
        `<p class="bad">第 ${r.index} 遍没收进来：${r.reason}</p>`).join("") +
      data.skipped.map((s) =>
        `<p class="bad">跳过第 ${s.index} 遍：开头有 ${s.drift} 秒的话没进转写，比不了</p>`).join("") +
      (data.problems.length
        ? "<p>机器没听对的词：" + data.problems.map((p) =>
            p.kind === "missing" ? `漏 ${p.ref}`
            : p.kind === "wrong" ? `${p.ref}→听成 ${p.usr}` : `多 ${p.usr}`
          ).join("、") + "</p>"
        : "<p class='ok'>发音层面没问题——每个词机器都听出来了。</p>") +
      (data.issues.length
        ? "<p><b>下一遍改这些：</b></p>" + data.issues.map((i) =>
            `<div class="issue"><b>${i.title}</b>（${i.hits}/${i.total} 次）` +
            `<span>${i.detail}</span><span>${i.action}</span></div>`).join("")
        : "<p class='ok'>没有反复出现的问题。</p>") +
      (data.good.length ? `<p class="guessed">做对了，保持：${data.good.join(" / ")}</p>` : "");
    box.append(renderFigures(data.view));
  });
}
