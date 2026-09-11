// 页面共用的小东西：建元素、统一的播放速度。

function el(tag, className, text) {  // eslint-disable-line no-unused-vars
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

// 变速只作用于「听」：盲听、重听、图 2 的对比。
//
// 录音前的那几遍原声永远原速——那是你马上要模仿的东西，放慢了就不是它了，
// 而比对仍然拿原速的原声当基准，每个词都会显得拖长。
//
// preservesPitch 浏览器默认开着：放慢只拉长时间，不会把音调一起拉低。
// 听清连读要的是时间，不是把人变成另一个嗓音。
const SPEEDS = [0.5, 0.75, 1];
const SPEED_KEY = "shadow.speed";

const speed = {
  rate: 1,
  tracked: new Set(),
  controls: new Set(),

  apply(media) {
    media.playbackRate = this.rate;
    if ("preservesPitch" in media) media.preservesPitch = true;
    return media;
  },

  // 长期存在的元素用这个，改速度时跟着变
  follow(media) {
    this.tracked.add(this.apply(media));
    return media;
  },

  set(rate) {
    this.rate = rate;
    this.tracked.forEach((media) => { media.playbackRate = rate; });
    this.controls.forEach((refresh) => refresh(rate));
    try { localStorage.setItem(SPEED_KEY, String(rate)); } catch (err) { /* 无所谓 */ }
  },
};

try {
  const saved = Number(localStorage.getItem(SPEED_KEY));
  if (SPEEDS.includes(saved)) speed.rate = saved;
} catch (err) { /* 隐私模式下读不到，用默认值 */ }

function speedControl() {  // eslint-disable-line no-unused-vars
  const box = el("div", "speeds");
  box.append(el("span", "speeds-label", "速度"));
  const buttons = SPEEDS.map((rate) => {
    const button = el("button", null, rate === 1 ? "原速" : `${rate}×`);
    button.addEventListener("click", () => speed.set(rate));
    box.append(button);
    return [rate, button];
  });
  const refresh = (rate) => buttons.forEach(
    ([value, button]) => button.classList.toggle("chosen", value === rate));
  speed.controls.add(refresh);
  refresh(speed.rate);
  return box;
}
