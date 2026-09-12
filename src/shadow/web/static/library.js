// 素材库：导入、看进度、重试、删除。
(() => {
  const form = document.getElementById("import-form");
  const list = document.getElementById("cards");
  if (!form || !list) return;
  const note = document.getElementById("import-note");
  const POLL_MS = 2000;
  const busy = (status) => status !== "ready" && status !== "failed";
  const cards = () => [...list.querySelectorAll(".card")];

  async function send(url, options) {
    const response = await fetch(url, options);
    const body = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(body.detail || `没做成（${response.status}）`);
    return body;
  }

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const button = form.querySelector("button");
    button.disabled = true;
    try {
      await send("/api/sources", { method: "POST", body: new FormData(form) });
      window.location.reload();
    } catch (err) {
      note.textContent = err.message;
      note.classList.add("error");
      button.disabled = false;
    }
  });

  list.addEventListener("click", async (event) => {
    const button = event.target.closest("button[data-action]");
    if (!button) return;
    const card = button.closest(".card");
    try {
      if (button.dataset.action === "retry") {
        await send(`/api/sources/${card.dataset.id}/retry`, { method: "POST" });
      } else {
        const title = card.querySelector(".card-title").textContent.trim();
        const { sentences, rounds, takes } = card.dataset;
        const sure = window.confirm(
          `删除「${title}」？\n\n${sentences} 个句子、${rounds} 轮练习记录、${takes} 遍录音会全部删掉，不能恢复。`
          + "\n打卡格子和连续天数会保留。");
        if (!sure) return;
        await send(`/api/sources/${card.dataset.id}`, { method: "DELETE" });
      }
      window.location.reload();
    } catch (err) {
      window.alert(err.message);
    }
  });

  // 导入中的卡片每两秒看一眼：还在导入就只换步骤名，导完或失败了整页重画
  async function poll() {
    try {
      const { sources } = await send("/api/sources", { cache: "no-store" });
      const changed = sources.length !== cards().length || sources.some((source) => {
        const card = list.querySelector(`.card[data-id="${source.id}"]`);
        if (!card) return true;
        if (busy(card.dataset.status) && busy(source.status)) {
          card.dataset.status = source.status;
          card.querySelector(".card-step").textContent = source.step;
          return false;
        }
        return card.dataset.status !== source.status;
      });
      if (changed) {
        window.location.reload();
        return;
      }
    } catch (err) {
      // 服务断了由顶上的指示灯提示，这里接着等
    }
    if (cards().some((card) => busy(card.dataset.status))) setTimeout(poll, POLL_MS);
  }
  if (cards().some((card) => busy(card.dataset.status))) setTimeout(poll, POLL_MS);
})();
