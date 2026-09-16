// 串起来：今天练过的几句连着放，跟着读，中间不停下来改。
(() => {
  const controls = document.getElementById("chain-controls");
  const list = document.getElementById("chain-list");
  if (!controls || !list) return;
  const button = document.getElementById("chain-play");
  const progress = document.getElementById("chain-progress");
  const rounds = Math.max(1, Number(controls.dataset.rounds) || 1);
  const items = [...list.querySelectorAll(".chain-item")];
  const idle = button.textContent;
  const GAP_MS = 600;            // 两句之间留一口气，但不够停下来改
  let audio = null;
  let timer = null;
  let playing = false;

  const stop = (note = "") => {
    clearTimeout(timer);
    if (audio) { audio.pause(); audio = null; }
    playing = false;
    button.textContent = idle;
    button.classList.remove("stop");
    items.forEach((item) => item.classList.remove("now"));
    progress.textContent = note;
  };

  const playFrom = (round, index) => {
    if (round > rounds) {
      stop(`跟完了 ${rounds} 遍`);
      return;
    }
    if (index >= items.length) {
      timer = setTimeout(() => playFrom(round + 1, 0), GAP_MS);
      return;
    }
    items.forEach((item, i) => item.classList.toggle("now", i === index));
    progress.textContent = `第 ${round}/${rounds} 遍 · 第 ${index + 1}/${items.length} 句`;
    audio = speed.apply(new Audio(items[index].dataset.src));
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
