// 页面共用的小东西：建元素、认按键、统一的播放速度。

function el(tag, className, text) {  // eslint-disable-line no-unused-vars
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

// 中文输入法开着的时候，Chrome 先把键交给输入法：event.key 变成 "Process"，
// 于是所有按键名都对不上，快捷键集体失灵——而页面上还写着「1–5 打分」。
// event.code 是键盘上那个物理键位，跟输入法、跟键盘布局都无关，按它判断才稳。
function physicalKey(event) {  // eslint-disable-line no-unused-vars
  const code = event.code || "";
  const digit = /^(?:Digit|Numpad)(\d)$/.exec(code);
  if (digit) return digit[1];
  if (code === "Space") return " ";
  if (code === "Enter" || code === "NumpadEnter") return "Enter";
  if (code === "ArrowLeft" || code === "ArrowRight") return code;
  return event.key;                     // 合成事件没有 code，退回 key
}

// 变速只作用于「听」：盲听、重听、图 2 的对比。
//
// 录音前的那几遍原声永远原速——那是你马上要模仿的东西，放慢了就不是它了，
// 而比对仍然拿原速的原声当基准，每个词都会显得拖长。
//
// preservesPitch 浏览器默认开着：放慢只拉长时间，不会把音调一起拉低。
// 听清连读要的是时间，不是把人变成另一个嗓音。
const SPEEDS = [0.5, 0.75, 1];

// 「听」和「跟读」是两回事，各记各的速度：盲听调慢了，串起来那边还是原速开始。
function makeSpeed(key) {  // eslint-disable-line no-unused-vars
  const store = {
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

    // 放完就扔的（串起来里一句一个 Audio），别一直攒着
    forget(media) {
      this.tracked.delete(media);
      return media;
    },

    set(rate) {
      this.rate = rate;
      this.tracked.forEach((media) => { media.playbackRate = rate; });
      this.controls.forEach((refresh) => refresh(rate));
      try { localStorage.setItem(key, String(rate)); } catch (err) { /* 无所谓 */ }
    },
  };
  try {
    const saved = Number(localStorage.getItem(key));
    if (SPEEDS.includes(saved)) store.rate = saved;
  } catch (err) { /* 隐私模式下读不到，用默认值 */ }
  return store;
}

const speed = makeSpeed("shadow.speed");

function speedControl(store = speed) {  // eslint-disable-line no-unused-vars
  const box = el("div", "speeds");
  box.append(el("span", "speeds-label", "速度"));
  const buttons = SPEEDS.map((rate) => {
    const button = el("button", null, rate === 1 ? "原速" : `${rate}×`);
    button.addEventListener("click", () => store.set(rate));
    box.append(button);
    return [rate, button];
  });
  const refresh = (rate) => buttons.forEach(
    ([value, button]) => button.classList.toggle("chosen", value === rate));
  store.controls.add(refresh);
  refresh(store.rate);
  return box;
}
