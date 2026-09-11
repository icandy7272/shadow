// 服务还在不在。
//
// 服务是从终端里开的，关掉终端（或者退出 Claude）它就跟着停了。页面却还开着、
// 看着一切正常，点下去才发现什么都存不进去——刚录的几遍白录。
// 所以每个页面顶上都挂一盏灯：断了立刻变红并说清怎么恢复，恢复了自己变回来。

const service = (() => {  // eslint-disable-line no-unused-vars
  const light = document.getElementById("service");
  const banner = document.getElementById("service-banner");
  if (!light || !banner) return { check: async () => true };

  const UP_EVERY = 20000;     // 在线时隔这么久看一眼
  const DOWN_EVERY = 3000;    // 断了就勤着点，一恢复马上知道
  const RECHECK = 1500;       // 失败一次先别报：改代码自动重载，重启要一两秒
  const TIMEOUT = 5000;
  const BACK_NOTE = 4000;
  const label = light.querySelector("span");
  const command = light.dataset.start;
  let state = "up";           // 页面刚从它那儿拿来，一开始当然在线
  let timer = null;
  let running = null;

  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

  async function ping() {
    const abort = new AbortController();
    const cut = setTimeout(() => abort.abort(), TIMEOUT);
    try {
      const response = await fetch("/api/health",
                                   { cache: "no-store", signal: abort.signal });
      return response.ok ? await response.json() : null;
    } catch (err) {
      return null;
    } finally {
      clearTimeout(cut);
    }
  }

  function downBanner() {
    banner.append(el("b", null, "服务断了"),
                  el("span", null, "打分、填空、录音比对都存不进去。在终端里运行"),
                  el("code", null, command));
    if (navigator.clipboard) {
      const copy = el("button", null, "复制");
      copy.addEventListener("click", async () => {
        try {
          await navigator.clipboard.writeText(command);
          copy.textContent = "已复制";
        } catch (err) {
          copy.textContent = "复制不了，手动选中";
        }
      });
      banner.append(copy);
    }
    const retry = el("button", null, "再试一次");
    retry.addEventListener("click", check);
    banner.append(el("span", "service-hint", "恢复后这里会自己变回绿色。"), retry);
  }

  function staleBanner() {
    const reload = el("button", "primary", "刷新");
    reload.addEventListener("click", () => window.location.reload());
    banner.append(el("span", null, "页面代码更新过，刷新一下才是最新的。"
                                   + "正在录音的话，录完再刷。"), reload);
  }

  function show(next) {
    const was = state;
    state = next;
    light.className = `service ${next}`;
    banner.replaceChildren();
    banner.className = `service-banner ${next}`;
    banner.hidden = next === "up";
    if (next === "down") {
      label.textContent = "服务断了";
      downBanner();
      return;
    }
    if (next === "stale") staleBanner();
    if (was !== "down") {
      label.textContent = "服务在线";
      return;
    }
    label.textContent = "服务恢复了";
    setTimeout(() => {
      if (state !== "down") label.textContent = "服务在线";
    }, BACK_NOTE);
  }

  function schedule() {
    clearTimeout(timer);
    // 看不见的标签页不查，切回来时立刻查一次
    if (document.hidden) return;
    timer = setTimeout(check, state === "down" ? DOWN_EVERY : UP_EVERY);
  }

  async function probe() {
    let health = await ping();
    if (!health && state !== "down") {
      await sleep(RECHECK);
      health = await ping();
    }
    const next = !health ? "down"
      : health.assets !== light.dataset.assets ? "stale" : "up";
    if (next !== state) show(next);
    schedule();
    return next !== "down";
  }

  // 同时有几处要查（定时器、切回标签页、提交失败）时只发一次
  function check() {
    clearTimeout(timer);
    if (!running) running = probe().finally(() => { running = null; });
    return running;
  }

  document.addEventListener("visibilitychange", () => {
    if (document.hidden) clearTimeout(timer);
    else check();
  });
  window.addEventListener("online", check);
  window.addEventListener("offline", check);
  schedule();

  return { check };
})();
