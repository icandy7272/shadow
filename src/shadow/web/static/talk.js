// 自己开口说：挑几个表达，连着说一段，录下来回听、和上周比。
//
// 和跟读那边不一样，这里不放原声、不比对、不打分——一开口就只剩你自己，
// 所以页面上要给的只有三样：还剩多久、在不在录、录完了在哪听。
(() => {
  const root = document.getElementById("talk");
  if (!root) return;
  const startButton = document.getElementById("talk-start");
  const stopButton = document.getElementById("talk-stop");
  const clock = document.getElementById("talk-clock");
  const status = document.getElementById("talk-status");
  const bar = document.getElementById("talk-bar");
  const list = document.getElementById("talk-list");
  const empty = document.getElementById("talk-empty");
  const count = document.getElementById("talk-count");
  const kind = root.dataset.kind;
  const limit = Math.max(10, Number(root.dataset.seconds) || 120);
  const idle = startButton.textContent;

  if (!window.isSecureContext) {
    const note = document.getElementById("no-mic");
    if (note) note.hidden = false;
    startButton.disabled = true;
    startButton.title = "需要 HTTPS 或 localhost";
  }

  const mmss = (seconds) => {
    const whole = Math.max(0, Math.round(seconds));
    return `${Math.floor(whole / 60)}:${String(whole % 60).padStart(2, "0")}`;
  };

  // 挑了几个。3–5 个是日课里的建议，挑多了 2 分钟塞不下
  const boxes = [...root.querySelectorAll(".talk-pick")];
  const picked = () => boxes.filter((box) => box.checked).map((box) => box.value);
  const refreshCount = () => {
    if (!count) return;
    const chosen = picked().length;
    count.textContent = chosen ? `已挑 ${chosen} 个` : "挑 3–5 个";
  };
  boxes.forEach((box) => box.addEventListener("change", refreshCount));

  // 嘀一声再开口：数字在屏幕上跳，人不一定看着屏幕
  const beep = async (ctx) => {
    const osc = ctx.createOscillator();
    const gain = ctx.createGain();
    osc.frequency.value = 880;
    gain.gain.setValueAtTime(0.0001, ctx.currentTime);
    gain.gain.exponentialRampToValueAtTime(0.22, ctx.currentTime + 0.015);
    gain.gain.exponentialRampToValueAtTime(0.0001, ctx.currentTime + 0.14);
    osc.connect(gain).connect(ctx.destination);
    osc.start();
    osc.stop(ctx.currentTime + 0.16);
    await new Promise((resolve) => setTimeout(resolve, 200));
  };

  const takeCard = (take) => {
    const item = el("li", "talk-take");
    item.dataset.id = take.id;
    const head = el("div", "talk-take-head");
    head.append(el("b", null, take.when),
                el("span", "talk-when", `${take.date} · ${take.length}`));
    const drop = el("button", "talk-drop", "删除");
    drop.title = "删除这一段";
    head.append(drop);
    const audio = el("audio");
    audio.controls = true;
    audio.preload = "none";
    audio.src = take.url;
    item.append(head, audio);
    if (take.picks && take.picks.length) {
      item.append(el("p", "talk-used", `用了 ${take.picks.join(" · ")}`));
    }
    return item;
  };

  // 删掉：16k 的 wav 一分钟两兆，天天录是要占地方的
  list?.addEventListener("click", async (event) => {
    const button = event.target.closest(".talk-drop");
    if (!button) return;
    const item = button.closest(".talk-take");
    if (!window.confirm("删除这一段录音？")) return;
    button.disabled = true;
    try {
      const response = await fetch(`/api/talk/${item.dataset.id}`, { method: "DELETE" });
      if (!response.ok) throw new Error((await response.json()).detail || response.status);
      item.remove();
      if (empty && !list.children.length) empty.hidden = false;
    } catch (err) {
      button.disabled = false;
      status.textContent = `删不掉：${err.message}`;
    }
  });

  const send = async (blob, picks) => {
    const form = new FormData();
    form.append("kind", kind);
    form.append("file", blob, "talk.webm");
    picks.forEach((pick) => form.append("picks", pick));
    const response = await fetch("/api/talk", { method: "POST", body: form });
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || `保存失败（${response.status}）`);
    return data.talk;
  };

  let stream = null;
  let recorder = null;
  let timer = 0;

  const release = () => {
    clearInterval(timer);
    stream?.getTracks().forEach((track) => track.stop());
    stream = null;
    stopButton.hidden = true;
    startButton.hidden = false;
    startButton.textContent = idle;
    status.classList.remove("live");
    bar.hidden = true;
    clock.textContent = "";
  };

  // 到点和自己点走同一条路：先停表再停录音，不然 200 毫秒后又停一次，
  // 停第二次是会抛错的
  const finish = () => {
    clearInterval(timer);
    if (recorder && recorder.state !== "inactive") recorder.stop();
  };

  startButton.addEventListener("click", async () => {
    const picks = picked();
    status.textContent = "";
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    } catch (err) {
      status.textContent = `拿不到麦克风：${err.message}`;
      return;
    }
    const Context = window.AudioContext || window.webkitAudioContext;
    const ctx = new Context();
    await ctx.resume().catch(() => {});
    await beep(ctx);
    ctx.close().catch(() => {});

    const chunks = [];
    recorder = new MediaRecorder(stream);
    recorder.addEventListener("dataavailable", (e) => chunks.push(e.data));
    recorder.addEventListener("stop", async () => {
      const blob = new Blob(chunks);
      release();
      status.textContent = "在保存…";
      try {
        const take = await send(blob, picks);
        list.prepend(takeCard(take));
        if (empty) empty.hidden = true;
        // 录过就算做过了：日课卡片自己会划掉这一步，不用再回去勾一次
        status.textContent = `录下了 ${take.length}。回听一遍；日课里这一步已经算做过了。`;
      } catch (err) {
        status.textContent = `没存上：${err.message}`;
      }
    });

    const began = performance.now();
    recorder.start();
    startButton.hidden = true;
    stopButton.hidden = false;
    bar.hidden = false;
    status.classList.add("live");
    status.textContent = "说着呢——说不顺也别停，接着往下说。";
    timer = setInterval(() => {
      const spent = (performance.now() - began) / 1000;
      clock.textContent = `还有 ${mmss(limit - spent)}`;
      bar.querySelector("i").style.width = `${Math.min(100, spent / limit * 100)}%`;
      if (spent >= limit) finish();             // 到点自己停，手上不用动
    }, 200);
  });

  stopButton.addEventListener("click", finish);
})();
