// 两张对比图，直接画进 DOM。
//
// 之前是服务端出 PNG 再内嵌，图里的字随图片缩放，页面一宽字就小得看不清。
// 现在几何走 SVG，文字全是普通 HTML，字号跟页面走，跟容器宽度无关。

const GAP = 34;           // 节奏图两行之间留给落后连线的高度
const PER_SEMITONE = 7;   // 一个半音多少 px，固定不变，句与句之间才可比
const TRACE_PAD = 10;     // 折线上下留白，笔画不贴边
const PITCH_PAD = 8;
const PITCH_MIN = 90;     // 整句都是平的时候也别塌成一条线
const MIN_SLOT_PX = 52;   // 一格至少这么宽，否则词标会挤成一团
const SLOT_GAP_PX = 8;
const FALLBACK_WIDTH = 760;

const svgNS = "http://www.w3.org/2000/svg";

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function svg(tag, attrs) {
  const node = document.createElementNS(svgNS, tag);
  Object.entries(attrs).forEach(([k, v]) => node.setAttribute(k, v));
  return node;
}

function playhead() {
  const head = el("div", "playhead");
  head.hidden = true;
  head.append(el("i"));
  return head;
}

// ---------- 图 1 · 节奏 ----------

function lane(role, name, blocks, spans, seconds) {
  const row = el("div", `lane ${role}`);
  row.append(el("span", "tag", name));
  const track = el("div", "track");
  spans.forEach((span) => {
    const band = el("div", "span");
    band.style.left = `${(span.start / seconds) * 100}%`;
    band.style.width = `${((span.end - span.start) / seconds) * 100}%`;
    band.append(el("span", "span-flag", span.flag));
    track.append(band);
  });
  blocks.forEach((block) => {
    const box = el("div", "blk", block.text);
    box.title = block.text;          // 窄块放不下的词，鼠标停一下能看到
    box.style.left = `${(block.start / seconds) * 100}%`;
    box.style.width = `${(block.width / seconds) * 100}%`;
    track.append(box);
  });
  row.append(track);

  // 放不下的词用省略号收尾；窄到连两三个字母都摆不开就干脆空着——
  // 露出半个词比空着还难认。鼠标停一下都还能看到全词。
  const fit = () => track.querySelectorAll(".blk").forEach((box) => {
    box.textContent = box.clientWidth < 30 ? "" : box.title;
  });
  if (window.ResizeObserver) new ResizeObserver(fit).observe(track);
  return row;
}

function rhythmFigure(rhythm) {
  const seconds = rhythm.seconds || 1;
  const node = el("figure", "fig");
  node.append(el("figcaption", null,
    "图 1 · 节奏：横轴是真实秒数，块宽 = 时长，空隙 = 真实停顿。" +
    "红线标出你在这个词上已经落后多少（横轴单位：秒）"));

  const body = el("div", "fig-body");
  const head = playhead();
  body.append(head);
  body.append(lane("ref", "原声", rhythm.ref,
                   rhythm.spans.filter((s) => s.row === "ref"), seconds));

  const gap = el("div", "gap");
  const lines = svg("svg", { class: "lag-layer", viewBox: `0 0 1000 ${GAP}`,
                             preserveAspectRatio: "none" });
  rhythm.lags.forEach((lag) => {
    lines.append(svg("line", {
      x1: (lag.refAt / seconds) * 1000, y1: 0,
      x2: (lag.usrAt / seconds) * 1000, y2: GAP,
      class: lag.marked ? "lag marked" : "lag",
      "vector-effect": "non-scaling-stroke",
    }));
  });
  gap.append(lines);
  rhythm.lags.filter((lag) => lag.marked).forEach((lag) => {
    const note = el("span", "lag-note",
                    `${lag.seconds > 0 ? "+" : ""}${lag.seconds}秒`);
    note.style.left = `${((lag.refAt + lag.usrAt) / 2 / seconds) * 100}%`;
    gap.append(note);
  });
  body.append(gap);

  body.append(lane("usr", "你", rhythm.usr,
                   rhythm.spans.filter((s) => s.row === "usr"), seconds));
  node.append(body);

  const ticks = el("div", "ticks");
  for (let t = 0; t <= seconds + 1e-6; t += 0.5) {
    const tick = el("span", null, t.toFixed(1));
    tick.style.left = `${(t / seconds) * 100}%`;
    ticks.append(tick);
  }
  node.append(ticks);

  return {
    node,
    move(frame) {
      head.hidden = false;
      const ratio = Math.max(0, Math.min(1, frame.elapsed / seconds));
      head.firstChild.style.left = `${ratio * 100}%`;
    },
    hide() { head.hidden = true; },
  };
}

// ---------- 图 2 · 音高 ----------

// 一个词的音高走向画成折线。null 处断开——那里没有浊音。
function traceLine(canvas, y, x0, width, trace, className) {
  if (!trace || !trace.length) return;
  const step = width / trace.length;
  let run = [];
  const flush = () => {
    if (run.length > 1) {
      canvas.append(svg("polyline", { points: run.join(" "), class: className }));
    }
    run = [];
  };
  trace.forEach((value, index) => {
    if (value === null) { flush(); return; }
    run.push(`${x0 + (index + 0.5) * step},${y(value)}`);
  });
  flush();
}

// 纵轴按这一句实际用到的音域收紧，免得图上一大半是空白。
// 每半音多少像素是固定的，所以不同句子之间仍然可比。
function pitchScale(slots) {
  const values = [];
  slots.forEach((slot) => {
    [slot.refTrace, slot.usrTrace].forEach((trace) => {
      (trace || []).forEach((v) => { if (v !== null) values.push(v); });
    });
  });
  if (!values.length) values.push(0);
  const top = Math.max(...values);
  const bottom = Math.min(...values);
  const height = Math.max(
    PITCH_MIN, (top - bottom) * PER_SEMITONE + 2 * TRACE_PAD + 2 * PITCH_PAD);
  const zero = (height - (top - bottom) * PER_SEMITONE) / 2 + top * PER_SEMITONE;
  return { height, y: (semitones) => zero - semitones * PER_SEMITONE };
}

// 每格给一个最小宽度，剩下的按相对时长分。挤不下就横向滚动——
// 十几个词硬塞进一屏，词标会叠成一堆，那才是真看不懂。
function layout(slots, available) {
  const natural = slots.map((s) => Math.max(s.refWidth, s.usrWidth) || 0.001);
  const sum = natural.reduce((a, b) => a + b, 0) || 1;
  const room = Math.max(0, available - SLOT_GAP_PX * (slots.length - 1));
  const widths = natural.map((w) => Math.max(MIN_SLOT_PX, (w / sum) * room));
  const xs = [];
  let cursor = 0;
  widths.forEach((w) => { xs.push(cursor); cursor += w + SLOT_GAP_PX; });
  return { xs, widths, natural, total: Math.max(0, cursor - SLOT_GAP_PX) };
}

function pitchFigure(slots) {
  const node = el("figure", "fig");
  const caption = el("figcaption", null,
    "图 2 · 音高：一词一格，线的高低 = 音高，线的走向 = 这个词从头到尾怎么走的。");
  caption.append(el("i", "legend-ref", "原声（虚线）"));
  caption.append(el("i", "legend-usr", "你（实心）"));
  node.append(caption);

  const scroll = el("div", "pitch-scroll");
  const body = el("div", "fig-body pitch");
  const head = playhead();
  const bands = el("div", "slot-bands");
  const labels = el("div", "slot-labels");
  const notes = el("div", "slot-flags");
  const scale = pitchScale(slots);
  let placed = layout(slots, FALLBACK_WIDTH);

  function draw(available) {
    placed = layout(slots, available);
    body.style.width = `${placed.total}px`;
    bands.textContent = "";
    labels.textContent = "";
    notes.textContent = "";

    const canvas = svg("svg", { class: "quads",
                                viewBox: `0 0 ${placed.total} ${scale.height}` });
    canvas.style.height = `${scale.height}px`;
    canvas.style.width = `${placed.total}px`;
    canvas.append(svg("line", { x1: 0, y1: scale.y(0), x2: placed.total,
                                y2: scale.y(0), class: "baseline" }));

    slots.forEach((slot, index) => {
      const x0 = placed.xs[index];
      const width = placed.widths[index];
      const natural = placed.natural[index];

      const band = el("div", index % 2 ? "band odd" : "band");
      band.style.left = `${x0}px`;
      band.style.width = `${width}px`;
      bands.append(band);

      if (slot.usrTrace && slot.usrTrace.length) {
        traceLine(canvas, scale.y, x0, (slot.usrWidth / natural) * width,
                  slot.usrTrace, slot.flag ? "usr flagged" : "usr");
      }
      traceLine(canvas, scale.y, x0, (slot.refWidth / natural) * width,
                slot.refTrace, "ref");

      const label = el("span", null, slot.text);
      label.title = slot.text;
      label.style.left = `${x0}px`;
      label.style.width = `${width}px`;
      labels.append(label);
      if (slot.flag) {
        const note = el("span", null, slot.flag);
        note.style.left = `${x0 - 20}px`;
        note.style.width = `${width + 40}px`;
        notes.append(note);
      }
    });

    const old = body.querySelector("svg.quads");
    if (old) old.replaceWith(canvas);
    else labels.after(canvas);
  }

  body.append(head, bands, labels, notes);
  draw(FALLBACK_WIDTH);
  scroll.append(body);
  node.append(scroll);

  // ResizeObserver 首次观测就会回调，拿到真实宽度再排一次
  let lastRoom = FALLBACK_WIDTH;
  if (window.ResizeObserver) {
    new ResizeObserver((entries) => {
      const width = entries[0].contentRect.width;
      if (width > 0 && Math.abs(width - lastRoom) > 1) {
        lastRoom = width;
        draw(width);
      }
    }).observe(scroll);
  }

  // 当前时刻落在哪一格的什么位置。图 2 的横轴不是时间，得逐格换算。
  function locate(frame) {
    const useRef = frame.ref !== null;
    const time = useRef ? frame.ref : frame.usr;
    if (time === null) return null;
    for (let i = 0; i < slots.length; i += 1) {
      const at = useRef ? slots[i].refAt : slots[i].usrAt;
      if (!at) continue;
      if (time < at[0]) return placed.xs[i];
      if (time < at[1]) {
        const share = (time - at[0]) / Math.max(at[1] - at[0], 1e-6);
        return placed.xs[i] + share * placed.widths[i];
      }
    }
    return placed.total;
  }

  return {
    node,
    move(frame) {
      const x = locate(frame);
      if (x === null) return;
      head.hidden = false;
      head.firstChild.style.left = `${x}px`;
      // 长句子要横向滚动，别让播放头跑出视野
      const left = scroll.scrollLeft;
      const edge = 48;
      if (x < left + edge || x > left + scroll.clientWidth - edge) {
        scroll.scrollLeft = Math.max(0, x - scroll.clientWidth / 2);
      }
    },
    hide() { head.hidden = true; },
  };
}

// ---------- 播放 ----------

// 同时播放原声和你的录音。
//
// 两条人声叠在一起会糊成一团，所以分到左右耳——耳机里能直接听出谁走在前面。
// 两条各自跳到自己的第一个词再起播：起点对齐了，图上同一个 x 才是同一刻。
function playback(rhythm, audio, onFrame, onStopped) {
  const ref = new Audio(audio.ref);
  const usr = new Audio(audio.usr);
  [ref, usr].forEach((media) => { media.preload = "auto"; });
  const offsets = new Map([[ref, audio.refOffset], [usr, audio.usrOffset]]);
  const panners = new Map();
  let context = null;
  let timer = null;
  let session = 0;

  // 元数据没到位时 currentTime 定位会被忽略，两条音轨就会各从头播，听着一前一后
  const ready = (media) => (media.readyState >= 1
    ? Promise.resolve()
    : new Promise((done) => media.addEventListener("loadedmetadata", done,
                                                   { once: true })));

  function graph() {
    if (context) return;
    context = new (window.AudioContext || window.webkitAudioContext)();
    [ref, usr].forEach((media) => {
      const source = context.createMediaElementSource(media);
      if (context.createStereoPanner) {
        const panner = context.createStereoPanner();
        source.connect(panner).connect(context.destination);
        panners.set(media, panner);
      } else {
        source.connect(context.destination);   // 老浏览器没有声道平移
      }
    });
  }

  // halt 只停，不通知；stop 才通知。play 内部若用 stop，会把调用方刚设好的
  // 按钮状态立刻重置掉——按钮按下去就弹回来。
  function halt() {
    session += 1;
    if (timer) clearInterval(timer);
    timer = null;
    [ref, usr].forEach((media) => media.pause());
  }

  function stop() {
    halt();
    onStopped();
  }

  async function play(tracks, spread) {
    halt();
    const mine = session;
    graph();
    if (context.state === "suspended") await context.resume();
    await Promise.all(tracks.map(ready));
    if (mine !== session) return;          // 加载期间被叫停了

    tracks.forEach((media) => {
      const panner = panners.get(media);
      if (panner) panner.pan.value = spread ? (media === ref ? -0.8 : 0.8) : 0;
      media.currentTime = offsets.get(media);
    });
    tracks.forEach((media) => media.play());

    // 跟音频自己的时钟走，不用墙上时间：起播有几十毫秒延迟，缓冲还可能再顿一下。
    // 计时用 setInterval 而不是 requestAnimationFrame：切到别的标签页 rAF 会整个
    // 停掉，声音还在放而播放头卡住，按钮永远停在「停」上。
    timer = setInterval(() => {
      const elapsed = Math.max(...tracks.map((m) => m.currentTime - offsets.get(m)));
      onFrame({
        elapsed,
        ref: tracks.includes(ref) ? ref.currentTime : null,
        usr: tracks.includes(usr) ? usr.currentTime : null,
      });
      if (tracks.every((media) => media.ended) || elapsed > rhythm.seconds + 0.6) {
        stop();
      }
    }, 16);
  }

  return { ref, usr, play, stop, playing: () => timer !== null };
}

function playbar(rhythm, audio, figures) {
  const bar = el("div", "playbar");
  const both = el("button", "primary", "▶ 同时播放");
  const one = el("button", null, "只听原声");
  const mine = el("button", null, "只听我的");
  const buttons = [both, one, mine];

  const reset = () => {
    both.textContent = "▶ 同时播放";
    buttons.forEach((b) => b.classList.remove("playing"));
    figures.forEach((f) => f.hide());
  };
  const player = playback(rhythm, audio,
                          (frame) => figures.forEach((f) => f.move(frame)),
                          reset);

  const start = (button, tracks, spread) => {
    const active = button.classList.contains("playing");
    player.stop();
    if (active) return;                 // 正在放这一路，再点一次就是停
    button.classList.add("playing");
    if (button === both) both.textContent = "■ 停";
    player.play(tracks, spread);
  };

  both.addEventListener("click", () => start(both, [player.ref, player.usr], true));
  one.addEventListener("click", () => start(one, [player.ref], false));
  mine.addEventListener("click", () => start(mine, [player.usr], false));

  bar.append(both, one, mine,
             el("span", "playbar-hint", "戴耳机：原声在左，你的在右"));
  return bar;
}

// 给 app.js 用：返回一个包含两张图的元素
function renderFigures(view) {  // eslint-disable-line no-unused-vars
  const box = el("div", "figures");
  const rhythm = rhythmFigure(view.rhythm);
  const pitch = pitchFigure(view.pitch);
  if (view.audio) {
    box.append(playbar(view.rhythm, view.audio, [rhythm, pitch]));
  }
  box.append(rhythm.node, pitch.node);
  return box;
}
