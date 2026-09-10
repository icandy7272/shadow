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
      document.getElementById("step-drill").classList.remove("locked");
    });
  });

  // 第二步：填空
  const drillStep = document.getElementById("step-drill");
  document.getElementById("submit-drill").addEventListener("click", async () => {
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
  });
}
