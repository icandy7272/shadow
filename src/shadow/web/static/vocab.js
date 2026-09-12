// 生词本：点「记住了」就从本子里拿掉。
(() => {
  const list = document.getElementById("vocab");
  if (!list) return;
  const count = document.getElementById("vocab-count");

  list.addEventListener("click", async (event) => {
    const button = event.target.closest("button[data-action=forget]");
    if (!button) return;
    const item = button.closest(".vocab-item");
    button.disabled = true;
    try {
      const response = await fetch(`/api/vocab/${encodeURIComponent(item.dataset.word)}`,
                                   { method: "DELETE" });
      // 已经不在了（另一个页面删过）也算删掉了
      if (!response.ok && response.status !== 404) throw new Error(String(response.status));
    } catch (err) {
      button.disabled = false;
      button.textContent = "没删掉，再点一次";
      service.check();
      return;
    }
    item.remove();
    const left = list.querySelectorAll(".vocab-item").length;
    if (!left) {
      window.location.reload();       // 换成空状态的说明
      return;
    }
    if (count) count.textContent = `${left} 个词`;
  });
})();
