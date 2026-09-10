// 两张对比图，直接画进 DOM。
//
// 之前是服务端出 PNG 再内嵌，图里的字随图片缩放，页面一宽字就小得看不清。
// 现在几何走 SVG，文字全是普通 HTML，字号跟页面走，跟容器宽度无关。

const GAP = 34;           // 两行之间留给落后连线的高度
const PER_SEMITONE = 7;   // 一个半音多少 px，固定不变，句与句之间才可比
const BLOCK_HALF = 7;     // 音高块的半高
const PITCH_PAD = 8;      // 上下各留一点，块不贴边
const PITCH_MIN = 90;     // 整句都是平的时候也别塌成一条线

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

function lane(name, blocks, spans, seconds) {
  const row = el("div", "lane");
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
    box.style.left = `${(block.start / seconds) * 100}%`;
    box.style.width = `${(block.width / seconds) * 100}%`;
    track.append(box);
  });
  row.append(track);
  return row;
}

function rhythmFigure(rhythm) {
  const seconds = rhythm.seconds || 1;
  const figure = el("figure", "fig");
  figure.append(el("figcaption", null,
    "图 1 · 节奏：横轴是真实秒数，块宽 = 时长，空隙 = 真实停顿。" +
    "红线标出你在这个词上已经落后多少（横轴单位：秒）"));

  const body = el("div", "fig-body");
  body.append(lane("原声", rhythm.ref,
                   rhythm.spans.filter((s) => s.row === "ref"), seconds));

  const gap = el("div", "gap");
  const lines = svg("svg", { class: "lag-layer", viewBox: `0 0 1000 ${GAP}`,
                             preserveAspectRatio: "none" });
  rhythm.lags.forEach((lag) => {
    const line = svg("line", {
      x1: (lag.refAt / seconds) * 1000, y1: 0,
      x2: (lag.usrAt / seconds) * 1000, y2: GAP,
      class: lag.marked ? "lag marked" : "lag",
      "vector-effect": "non-scaling-stroke",
    });
    lines.append(line);
  });
  gap.append(lines);
  rhythm.lags.filter((lag) => lag.marked).forEach((lag) => {
    const note = el("span", "lag-note", `${lag.seconds > 0 ? "+" : ""}${lag.seconds}秒`);
    note.style.left = `${((lag.refAt + lag.usrAt) / 2 / seconds) * 100}%`;
    gap.append(note);
  });
  body.append(gap);

  body.append(lane("你", rhythm.usr,
                   rhythm.spans.filter((s) => s.row === "usr"), seconds));
  figure.append(body);

  const ticks = el("div", "ticks");
  for (let t = 0; t <= seconds + 1e-6; t += 0.5) {
    const tick = el("span", null, t.toFixed(1));
    tick.style.left = `${(t / seconds) * 100}%`;
    ticks.append(tick);
  }
  figure.append(ticks);
  return figure;
}

function quad(y, x0, x1, from, to, attrs) {
  const y0 = y(from);
  const y1 = y(to);
  return svg("polygon", {
    points: `${x0},${y0 - BLOCK_HALF} ${x0},${y0 + BLOCK_HALF} ` +
            `${x1},${y1 + BLOCK_HALF} ${x1},${y1 - BLOCK_HALF}`,
    "vector-effect": "non-scaling-stroke",
    ...attrs,
  });
}

// 纵轴按这一句实际用到的音域收紧，免得图上一大半是空白。
// 每半音多少像素是固定的，所以不同句子之间仍然可比。
function pitchScale(slots) {
  const values = [];
  slots.forEach((slot) => {
    values.push(slot.refFrom, slot.refTo);
    if (slot.usrFrom !== null) values.push(slot.usrFrom, slot.usrTo);
  });
  const top = Math.max(...values);
  const bottom = Math.min(...values);
  const height = Math.max(
    PITCH_MIN, (top - bottom) * PER_SEMITONE + 2 * BLOCK_HALF + 2 * PITCH_PAD);
  const zero = (height - (top - bottom) * PER_SEMITONE) / 2 + top * PER_SEMITONE;
  return { height, y: (semitones) => zero - semitones * PER_SEMITONE };
}


function pitchFigure(slots) {
  const figure = el("figure", "fig");
  const caption = el("figcaption", null,
    "图 2 · 音高：一词一格，块的高低 = 音高，块的斜度 = 词内升降（向下斜 = 降调）。");
  caption.append(el("i", "legend-ref", "原声（虚线）"));
  caption.append(el("i", "legend-usr", "你（实心）"));
  figure.append(caption);

  const body = el("div", "fig-body pitch");
  const labels = el("div", "slot-labels");
  const notes = el("div", "slot-flags");
  const scale = pitchScale(slots);
  const canvas = svg("svg", { class: "quads", viewBox: `0 0 1000 ${scale.height}`,
                              preserveAspectRatio: "none" });
  canvas.style.height = `${scale.height}px`;
  canvas.append(svg("line", { x1: 0, y1: scale.y(0), x2: 1000, y2: scale.y(0),
                              class: "baseline",
                              "vector-effect": "non-scaling-stroke" }));

  slots.forEach((slot) => {
    const x0 = slot.x * 1000;
    let width = slot.refWidth;
    if (slot.usrFrom !== null) {
      canvas.append(quad(scale.y, x0, x0 + slot.usrWidth * 1000,
                         slot.usrFrom, slot.usrTo,
                         { class: slot.flag ? "usr flagged" : "usr" }));
      width = Math.max(slot.refWidth, slot.usrWidth);
    }
    canvas.append(quad(scale.y, x0, x0 + slot.refWidth * 1000,
                       slot.refFrom, slot.refTo, { class: "ref" }));

    const centre = `${(slot.x + width / 2) * 100}%`;
    const label = el("span", null, slot.text);
    label.style.left = centre;
    labels.append(label);
    if (slot.flag) {
      const note = el("span", null, slot.flag);
      note.style.left = centre;
      notes.append(note);
    }
  });

  body.append(labels, canvas, notes);
  figure.append(body);
  return figure;
}

// 给 app.js 用：返回一个包含两张图的元素
function renderFigures(view) {  // eslint-disable-line no-unused-vars
  const box = el("div", "figures");
  box.append(rhythmFigure(view.rhythm), pitchFigure(view.pitch));
  return box;
}
