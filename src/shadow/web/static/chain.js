// 连着放：今天练过的（串起来）或本周练过的（整段跟读），跟着读，中间不停下来改。
(() => {
  const controls = document.getElementById("chain-controls");
  const list = document.getElementById("chain-list");
  if (!controls || !list) return;
  const button = document.getElementById("chain-play");
  const progress = document.getElementById("chain-progress");
  const rounds = Math.max(1, Number(controls.dataset.rounds) || 1);
  const step = controls.dataset.step;      // 跟完了在日课里划掉的是哪一步
  const items = [...list.querySelectorAll(".chain-item")];
  const idle = button.textContent;
  // 跟读要跟的是真速度，所以这儿自成一档，默认原速：盲听那边调慢了，串起来不跟着慢。
  // 真想放慢也行，按钮就在旁边，调了下次还记得
  const chainSpeed = makeSpeed("shadow.chain-speed");
  controls.append(speedControl(chainSpeed));
  const GAP_MS = 600;            // 两句之间留一口气，但不够停下来改
  let audio = null;
  let timer = null;
  let playing = false;

  const stop = (note = "") => {
    clearTimeout(timer);
    if (audio) { audio.pause(); chainSpeed.forget(audio); audio = null; }
    playing = false;
    button.textContent = idle;
    button.classList.remove("stop");
    items.forEach((item) => item.classList.remove("now"));
    progress.textContent = note;
  };

  // 从头放到尾就是做完了。跟完还要回首页勾一次，是同一件事确认两遍——
  // 这里替人勾上；中途停下的不算。
  const tick = async () => {
    if (!step) return;
    try {
      const response = await fetch("/api/plan", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ step, done: true }),
      });
      if (response.ok) progress.textContent += " · 日课里已勾上";
    } catch (err) { /* 服务断了就算了，人回首页自己勾 */ }
  };

  const playFrom = (round, index) => {
    if (round > rounds) {
      stop(`跟完了${rounds > 1 ? ` ${rounds} 遍` : ""}`);
      tick();
      return;
    }
    if (index >= items.length) {
      timer = setTimeout(() => playFrom(round + 1, 0), GAP_MS);
      return;
    }
    items.forEach((item, i) => item.classList.toggle("now", i === index));
    progress.textContent = `第 ${round}/${rounds} 遍 · 第 ${index + 1}/${items.length} 句`;
    if (audio) chainSpeed.forget(audio);          // 上一句放完了，别攒在那儿
    audio = chainSpeed.follow(new Audio(items[index].dataset.src));
    // 某一句的音频取不到就跳过，不能让整串停在这儿
    const next = () => { timer = setTimeout(() => playFrom(round, index + 1), GAP_MS); };
    audio.addEventListener("ended", next, { once: true });
    audio.addEventListener("error", next, { once: true });
    audio.play().catch((err) => { if (err.name !== "AbortError") throw err; });
  };

  const start = (index) => {
    playing = true;
    button.textContent = "■ 停";
    button.classList.add("stop");
    playFrom(1, index);
  };

  button.addEventListener("click", () => (playing ? stop() : start(0)));

  // 点某一句，从这句接着往下放
  list.addEventListener("click", (event) => {
    const item = event.target.closest(".chain-item");
    if (!item || event.target.closest("a")) return;
    stop();
    start(items.indexOf(item));
  });
})();
