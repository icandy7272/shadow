// 两张对比图，直接画进 DOM。
//
// 之前是服务端出 PNG 再内嵌，图里的字随图片缩放，页面一宽字就小得看不清。
// 现在几何走 SVG，文字全是普通 HTML，字号跟页面走，跟容器宽度无关。

const GAP = 34;
const CALLOUT_ROW = 17;   // 词标错行的行距
const CALLOUT_ROWS = 4;   // 最多错这么多行；再挤只可能是一遍录得离谱，叠就叠吧
const LABEL_HEIGHT = 15;  // 一行 12px 词标实际占的高
const LABEL_GAP_PX = 6;   // 同一行两个标签之间至少空这么多
const TICK_STEPS = [0.5, 1, 2, 5, 10, 15, 30, 60];
const TICK_MIN_PX = 40;   // 刻度数字之间至少这么宽，不然挤成一串
const MISHEARD_SHOWN = 6; // 每遍「没听对」最多列这么多处
const NEAR_BLOCK_SEC = 0.25;  // 点在块外多远还算点中它           // 节奏图两行之间留给落后连线的高度
const PER_SEMITONE = 7;   // 一个半音多少 px，固定不变，句与句之间才可比
const TRACE_PAD = 10;     // 折线上下留白，笔画不贴边
const PITCH_PAD = 8;
const PITCH_MIN = 90;     // 整句都是平的时候也别塌成一条线
const MIN_SLOT_PX = 52;   // 一格至少这么宽，否则词标会挤成一团
const SLOT_GAP_PX = 8;
const FALLBACK_WIDTH = 760;
const WORD_PAD = 0.06;    // 单词试听前后各留一点，免得削掉爆破音
const WORD_GAP_MS = 240;  // 两条之间留个空，耳朵才分得开
const WORD_ROUNDS = 2;    // 原声→你的，来回两遍
const PRE_ROLL = 0.15;    // 两条都提前一点起播：正好切在词头会削掉爆破音的起音，
                          // 两边削掉的还不一样多，听着就像没对齐

const svgNS = "http://www.w3.org/2000/svg";
const HELP_KEY = "shadow.fig-help";

// 图的说明第一次有用，之后每次都占地方：收起来，想看再点。展开与否记在本机
function figHelp(title, text) {
  const box = el("details", "fig-help");
  box.append(el("summary", null, title), el("p", null, text));
  try { box.open = localStorage.getItem(HELP_KEY) === "1"; } catch (err) { /* 无所谓 */ }
  box.addEventListener("toggle", () => {
    try { localStorage.setItem(HELP_KEY, box.open ? "1" : "0"); } catch (err) { /* 无所谓 */ }
  });
  return box;
}

function svg(tag, attrs) {
  const node = document.createElementNS(svgNS, tag);
  Object.entries(attrs).forEach(([k, v]) => node.setAttribute(k, v));
  return node;
}

function within(index, range) {
  return range !== null && index >= range[0] && index <= range[1];
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
  const callouts = el("div", "callouts");
  const trackRow = el("div", "track-row");
  const track = el("div", "track");

  trackRow.append(el("span", "tag", name), track);
  // 词标和「后面该停没停」这类提示排在同一层里一起错行：
  // 提示原来贴在色带正上方，跟词标各排各的，窄屏上正好压在词标上
  const labels = [];
  spans.forEach((span) => {
    const band = el("div", "span");
    band.style.left = `${(span.start / seconds) * 100}%`;
    band.style.width = `${((span.end - span.start) / seconds) * 100}%`;
    track.append(band);
    const flag = el("span", "flag", span.flag);
    const centre = (span.start + span.end) / 2;
    flag.style.left = `${(centre / seconds) * 100}%`;
    callouts.append(flag);
    labels.push({ node: flag, centre });
  });

  const tags = [];              // 和 blocks 一一对应：试听、拖选时按下标找
  blocks.forEach((block) => {
    const box = el("div", block.matched ? "blk" : "blk missed");
    box.style.left = `${(block.start / seconds) * 100}%`;
    box.style.width = `${(block.width / seconds) * 100}%`;
    track.append(box);

    // 词标放在块外面：横轴是真实秒数，块不能为了放字而加宽
    const tag = el("span", block.matched ? null : "missed", block.text);
    const centre = block.start + block.width / 2;
    tag.style.left = `${(centre / seconds) * 100}%`;
    callouts.append(tag);
    tags.push(tag);
    labels.push({ node: tag, centre });
  });

  row.append(...(role === "ref" ? [callouts, trackRow] : [trackRow, callouts]));

  // 词一多标签就会挤在一起。量出实际宽度，从左往右贪心地放：这一行放不下就换下一行，
  // 行不够就再开一行（最多 CALLOUT_ROWS 行），第 0 行离词块最近，每个标签画一根引线。
  // 窄屏上原来只有两行，第三个挤的词只能叠上去
  const place = () => {
    const width = track.clientWidth;
    if (!width) return;
    const placed = labels
      .map((label) => ({ ...label, x: (label.centre / seconds) * width,
                         half: label.node.offsetWidth / 2 }))
      .sort((a, b) => a.x - b.x);
    const rights = [];
    placed.forEach((label) => {
      let line = rights.findIndex((right) => label.x - label.half > right + LABEL_GAP_PX);
      if (line < 0 && rights.length < CALLOUT_ROWS) line = rights.push(-Infinity) - 1;
      if (line < 0) line = rights.indexOf(Math.min(...rights));
      rights[line] = Math.max(rights[line], label.x + label.half);
      label.line = line;
    });
    const rows = Math.max(2, rights.length);
    callouts.style.height = `${rows * CALLOUT_ROW + 2}px`;
    placed.forEach(({ node, line }) => {
      if (role === "ref") {        // 词标在词块上方：离块最近的一行排在最底下
        node.style.top = `${(rows - 1 - line) * CALLOUT_ROW}px`;
        node.style.setProperty("--drop", `${(line + 1) * CALLOUT_ROW + 2 - LABEL_HEIGHT}px`);
      } else {
        node.style.top = `${line * CALLOUT_ROW}px`;
        node.style.setProperty("--drop", `${4 + line * CALLOUT_ROW}px`);
      }
    });
  };
  if (window.ResizeObserver) new ResizeObserver(place).observe(track);

  // 哪个词块落在这个横坐标上。块可以窄到 20px，点不准是常事，
  // 所以就近吸附；离所有块都远才算没点中。
  const blockAt = (clientX) => {
    const rect = track.getBoundingClientRect();
    if (!rect.width) return -1;
    const at = ((clientX - rect.left) / rect.width) * seconds;
    const inside = blocks.findIndex(
      (block) => at >= block.start && at <= block.start + block.width);
    if (inside >= 0) return inside;
    let best = -1;
    let gap = NEAR_BLOCK_SEC;
    blocks.forEach((block, index) => {
      const centre = block.start + block.width / 2;
      if (Math.abs(at - centre) < gap) { gap = Math.abs(at - centre); best = index; }
    });
    return best;
  };

  const mark = (range, className) => {
    track.querySelectorAll(".blk").forEach((node, index) =>
      node.classList.toggle(className, within(index, range)));
    tags.forEach((node, index) => node.classList.toggle(className, within(index, range)));
  };

  return {
    node: row,
    tint: (range, on) => mark(on ? range : null, "hear"),
    pick(handler) {
      let from = -1;
      row.style.cursor = "pointer";
      row.addEventListener("mousedown", (event) => {
        from = blockAt(event.clientX);
        if (from >= 0) { mark([from, from], "picked"); event.preventDefault(); }
      });
      row.addEventListener("mousemove", (event) => {
        if (from < 0) return;
        const to = blockAt(event.clientX);
        if (to >= 0) mark([Math.min(from, to), Math.max(from, to)], "picked");
      });
      window.addEventListener("mouseup", (event) => {
        if (from < 0) return;
        const to = blockAt(event.clientX);
        const range = to < 0 ? [from, from]
                             : [Math.min(from, to), Math.max(from, to)];
        from = -1;
        mark(null, "picked");
        handler(role, range);
      });
    },
  };
}


function rhythmFigure(rhythm) {
  const seconds = rhythm.seconds || 1;
  const node = el("figure", "fig");
  node.append(figHelp("图 1 · 节奏",
    "横轴是真实秒数，块宽 = 时长，空隙 = 真实停顿，" +
    "红线标出你在这个词上已经落后多少。虚线框的词是机器在另一行里没找到的。" +
    "点词只放那一行——点原声放原声，点你的放你的；按住拖可以连着几个词。"));

  const body = el("div", "fig-body");
  const head = playhead();
  body.append(head);
  const lanes = {
    ref: lane("ref", "原声", rhythm.ref,
              rhythm.spans.filter((s) => s.row === "ref"), seconds),
    usr: lane("usr", "你", rhythm.usr,
              rhythm.spans.filter((s) => s.row === "usr"), seconds),
  };
  body.append(lanes.ref.node);

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

  body.append(lanes.usr.node);
  node.append(body);

  // 刻度间隔跟着宽度和时长走：原来固定每 0.5 秒一个，录音一长或屏幕一窄就糊成一串
  const ticks = el("div", "ticks");
  const drawTicks = () => {
    const width = ticks.clientWidth || FALLBACK_WIDTH;
    const step = TICK_STEPS.find((one) => (one / seconds) * width >= TICK_MIN_PX)
      || TICK_STEPS[TICK_STEPS.length - 1];
    ticks.replaceChildren();
    for (let i = 0; i * step <= seconds + 1e-6; i += 1) {
      const t = i * step;
      const tick = el("span", null, step < 1 ? t.toFixed(1) : String(t));
      tick.style.left = `${(t / seconds) * 100}%`;
      ticks.append(tick);
    }
  };
  drawTicks();
  if (window.ResizeObserver) new ResizeObserver(drawTicks).observe(ticks);
  node.append(ticks);

  return {
    node,
    onPick(handler) {
      Object.values(lanes).forEach((one) => one.pick(handler));
    },
    tint(role, range, on) {
      Object.entries(lanes).forEach(([name, one]) =>
        one.tint(range, on && name === role));
    },
    move(frame) {
      head.hidden = false;
      const ratio = Math.max(0, Math.min(1, frame.elapsed / seconds));
      head.firstChild.style.left = `${ratio * 100}%`;
    },
    hide() {
      head.hidden = true;
      Object.values(lanes).forEach((one) => one.tint(null, false));
    },
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

// 每格给一个最小宽度，剩下的按相对时长分。十几个词硬塞进一行，词标会叠成一堆，
// 所以挤不下时不压窄格子，而是折行（见 wrap）。
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

// 一行放不下就折到下一行，像文字换行。以前是横向滚动，划着看不方便。
// 格子宽度就用整句排一行时的比例（短词照样抬到最小宽度），挤不下也不放大、
// 不压窄，只换行，行尾可能空一截：长词在哪一行都一样宽，词与词的长短才比得了。
// 别按「几行的总宽」重新分配——短词被抬宽的那部分永远多出来，行数会一路加到
// 一词一行，每格还被放大好几倍。
const WRAP_SLACK_PX = 0.5;        // 刚好放满时，别让浮点误差把最后一格挤到下一行

function wrap(slots, available) {
  const placed = layout(slots, available);
  const rows = [];
  const where = [];               // 第 i 格：在第几行、行内的 x、宽度
  let row = null;
  placed.widths.forEach((raw, index) => {
    const width = Math.min(raw, available);
    if (!row || row.end + SLOT_GAP_PX + width > available + WRAP_SLACK_PX) {
      row = { slots: [], end: -SLOT_GAP_PX };
      rows.push(row);
    }
    const x = row.end + SLOT_GAP_PX;
    row.slots.push(index);
    row.end = x + width;
    where.push({ row: rows.length - 1, x, width });
  });
  return { rows, where, natural: placed.natural };
}

function pitchFigure(slots) {
  const node = el("figure", "fig");
  const caption = figHelp("图 2 · 音高",
    "一词一格（横轴不是时间），线的高低 = 音高，"
    + "线的走向 = 这个词从头到尾怎么走的。点一个词：先放原声再放你的，来回两遍；"
    + "按住往旁边拖，可以把连读的几个词连起来听。");
  // 图例是看图的钥匙，留在标题行上，不跟着说明收起来
  caption.querySelector("summary").append(el("i", "legend-ref", "原声（虚线）"),
                                          el("i", "legend-usr", "你（实心）"));
  node.append(caption);

  const rows = el("div", "pitch-rows");
  const scale = pitchScale(slots);    // 各行共用一套纵轴，音高跨行才比得了
  let placed = wrap(slots, FALLBACK_WIDTH);
  let bodies = [];
  let heads = [];
  let bands = [];                     // 按格子下标存：跨行也能一起点亮
  let labels = [];

  function drawRow(row) {
    const body = el("div", "fig-body pitch");
    const head = playhead();
    const bandRow = el("div", "slot-bands");
    const labelRow = el("div", "slot-labels");
    const notes = el("div", "slot-flags");
    const canvas = svg("svg", { class: "quads",
                                viewBox: `0 0 ${row.end} ${scale.height}` });
    canvas.style.height = `${scale.height}px`;
    canvas.style.width = `${row.end}px`;
    canvas.append(svg("line", { x1: 0, y1: scale.y(0), x2: row.end,
                                y2: scale.y(0), class: "baseline" }));

    row.slots.forEach((index) => {
      const slot = slots[index];
      const { x: x0, width } = placed.where[index];
      const natural = placed.natural[index];

      const band = el("div", index % 2 ? "band odd" : "band");
      band.style.left = `${x0}px`;
      band.style.width = `${width}px`;
      bandRow.append(band);
      bands[index] = band;

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
      labelRow.append(label);
      labels[index] = label;
      if (slot.flag) {
        const note = el("span", null, slot.flag);
        note.style.left = `${x0 - 20}px`;
        note.style.width = `${width + 40}px`;
        notes.append(note);
      }
    });

    body.append(head, bandRow, labelRow, canvas, notes);
    return { body, head };
  }

  function draw(available) {
    placed = wrap(slots, available);
    bands = [];
    labels = [];
    const drawn = placed.rows.map(drawRow);
    bodies = drawn.map((row) => row.body);
    heads = drawn.map((row) => row.head);
    rows.replaceChildren(...bodies);
  }

  draw(FALLBACK_WIDTH);
  node.append(rows);

  // ResizeObserver 首次观测就会回调，拿到真实宽度再排一次
  let lastRoom = FALLBACK_WIDTH;
  if (window.ResizeObserver) {
    new ResizeObserver((entries) => {
      const width = entries[0].contentRect.width;
      if (width > 0 && Math.abs(width - lastRoom) > 1) {
        lastRoom = width;
        draw(width);
      }
    }).observe(rows);
  }

  // 当前时刻落在哪一格的什么位置。图 2 的横轴不是时间，得逐格换算。
  function locate(frame) {
    const useRef = frame.ref !== null;
    const time = useRef ? frame.ref : frame.usr;
    if (time === null) return null;
    for (let i = 0; i < slots.length; i += 1) {
      const at = useRef ? slots[i].refAt : slots[i].usrAt;
      if (!at) continue;
      const spot = placed.where[i];
      if (time < at[0]) return { row: spot.row, x: spot.x, index: -1 };
      if (time < at[1]) {
        const share = (time - at[0]) / Math.max(at[1] - at[0], 1e-6);
        return { row: spot.row, x: spot.x + share * spot.width, index: i };
      }
    }
    const last = placed.rows.length - 1;
    return { row: last, x: placed.rows[last].end, index: -1 };
  }

  // 横轴不是时间，指针在长词上慢、短词上快。把当前那一格点亮，
  // 这种快慢才读得懂：不是走得不稳，是正走在哪个词上。
  function highlight(index) {
    bands.forEach((node, i) => node.classList.toggle("active", i === index));
    labels.forEach((node, i) => node.classList.toggle("active", i === index));
  }

  // 点到的是哪一格：先看落在哪一行，再看行内的横坐标。
  function slotAt(clientX, clientY) {
    for (let r = 0; r < bodies.length; r += 1) {
      const rect = bodies[r].getBoundingClientRect();
      if (clientY < rect.top || clientY > rect.bottom) continue;
      const x = clientX - rect.left;
      const hit = placed.rows[r].slots.find((i) => {
        const spot = placed.where[i];
        return x >= spot.x && x <= spot.x + spot.width;
      });
      return hit === undefined ? -1 : hit;
    }
    return -1;
  }

  function tint(range, side) {
    bands.forEach((node, i) => {
      node.classList.toggle("hear-ref", within(i, range) && side === "ref");
      node.classList.toggle("hear-usr", within(i, range) && side === "usr");
    });
  }

  function select(range) {
    bands.forEach((node, i) => node.classList.toggle("picked", within(i, range)));
  }

  return {
    node,
    onPick(handler) {
      // 拖着选一段，可以跨行。连读时单个词只有几十毫秒，拆开听不出什么，得连着放。
      let from = -1;
      rows.style.cursor = "pointer";

      rows.addEventListener("mousedown", (event) => {
        from = slotAt(event.clientX, event.clientY);
        if (from >= 0) {
          select([from, from]);
          event.preventDefault();      // 别让拖动变成选中词标文字
        }
      });
      rows.addEventListener("mousemove", (event) => {
        if (from < 0) return;
        const to = slotAt(event.clientX, event.clientY);
        if (to >= 0) select([Math.min(from, to), Math.max(from, to)]);
      });
      window.addEventListener("mouseup", (event) => {
        if (from < 0) return;
        const to = slotAt(event.clientX, event.clientY);
        const range = to < 0 ? [from, from]
                             : [Math.min(from, to), Math.max(from, to)];
        from = -1;
        select(null);
        handler(range, (side) => tint(side === null ? null : range, side));
      });
    },
    move(frame) {
      const at = locate(frame);
      if (at === null) return;
      highlight(at.index);
      // 指针只出现在正在播的那一行
      heads.forEach((head, r) => {
        head.hidden = r !== at.row;
        if (r === at.row) head.firstChild.style.left = `${at.x}px`;
      });
    },
    hide() {
      heads.forEach((head) => { head.hidden = true; });
      highlight(-1);
      tint(null, null);
      select(null);
    },
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
  [ref, usr].forEach((media) => { media.preload = "auto"; speed.follow(media); });
  const offsets = new Map([[ref, audio.refOffset], [usr, audio.usrOffset]]);
  const panners = new Map();
  const primed = new WeakSet();
  const LOAD_WAIT_MS = 8000;      // 元数据等这么久还没来，就当加载失败
  const SEEK_WAIT_MS = 1500;
  const RESUME_WAIT_MS = 1000;
  let context = null;
  let timer = null;
  let session = 0;

  const sleep = (ms) => new Promise((done) => setTimeout(done, ms));

  // iPhone 不会自己去加载音频，也不让「不是点出来的」播放出声：preload 被无视，
  // 等 loadedmetadata 会一直等下去（实测原声只发了个 2 字节的试探请求），
  // 隔了几个 await 再 play() 也会被拒。所以在点击里、任何 await 之前，
  // 先让要用的那条起播一下再立刻停：它从此开始加载，之后再 play 也放行。
  function prime(media) {
    if (primed.has(media)) return;
    primed.add(media);
    const attempt = media.play();
    media.pause();
    if (attempt) attempt.catch(() => {});   // 立刻暂停会报「被打断」，是预期内的
  }

  // 元数据没到位时 currentTime 定位会被忽略，两条音轨就会各从头播，听着一前一后。
  // 等不来返回 false：宁可这次不放，也别让按钮一直停在「停」上
  const ready = (media) => (media.readyState >= 1
    ? Promise.resolve(true)
    : new Promise((done) => {
      const giveUp = setTimeout(() => done(false), LOAD_WAIT_MS);
      media.addEventListener("loadedmetadata", () => {
        clearTimeout(giveUp);
        done(true);
      }, { once: true });
    }));

  // 定位没落定就 play，会从旧位置开始放然后跳一下
  const settled = (media) => (media.seeking
    ? new Promise((done) => {
      const giveUp = setTimeout(done, SEEK_WAIT_MS);
      media.addEventListener("seeked", () => {
        clearTimeout(giveUp);
        done();
      }, { once: true });
    })
    : Promise.resolve());

  // 起播；被拒（没有点击时 iPhone 会拒）返回 false
  const begin = (media) => {
    const attempt = media.play();
    return attempt ? attempt.then(() => true, () => false) : Promise.resolve(true);
  };

  // 放不出来时按时长兜底：这一段放完再多等两秒
  const limit = (seconds) => (seconds / (speed.rate || 1)) * 1000 + 2000;

  // 叫醒声音。Safari 没有点击时 resume() 可能一直不给结果，最多等一会儿
  const wake = () => (context.state === "suspended"
    ? Promise.race([context.resume().catch(() => {}), sleep(RESUME_WAIT_MS)])
    : Promise.resolve());

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
    tracks.forEach(prime);                 // 必须在第一个 await 之前
    graph();
    await wake();
    const loaded = await Promise.all(tracks.map(ready));
    if (mine !== session) return;          // 加载期间被叫停了
    if (!loaded.every(Boolean)) {
      stop();
      return;
    }

    tracks.forEach((media) => {
      const panner = panners.get(media);
      if (panner) panner.pan.value = spread ? (media === ref ? -0.8 : 0.8) : 0;
      media.currentTime = Math.max(0, offsets.get(media) - PRE_ROLL);
    });
    await Promise.all(tracks.map(settled));
    if (mine !== session) return;
    const started = await Promise.all(tracks.map(begin));
    if (mine !== session) return;
    if (!started.every(Boolean)) {
      stop();
      return;
    }

    // 跟音频自己的时钟走，不用墙上时间：起播有几十毫秒延迟，缓冲还可能再顿一下。
    // 计时用 setInterval 而不是 requestAnimationFrame：切到别的标签页 rAF 会整个
    // 停掉，声音还在放而播放头卡住，按钮永远停在「停」上。
    // 墙上时间只用来兜底：音频要是一直不走，到点也收掉。
    const since = performance.now();
    const cap = limit(rhythm.seconds);
    timer = setInterval(() => {
      const elapsed = Math.max(...tracks.map((m) => m.currentTime - offsets.get(m)));
      onFrame({
        elapsed,
        ref: tracks.includes(ref) ? ref.currentTime : null,
        usr: tracks.includes(usr) ? usr.currentTime : null,
      });
      if (tracks.every((media) => media.ended) || elapsed > rhythm.seconds + 0.6
          || performance.now() - since > cap) {
        stop();
      }
    }, 16);
  }

  function clip(media, from, to, mine) {
    return new Promise((done) => {
      media.currentTime = Math.max(0, from);
      const since = performance.now();
      const cap = limit(to - from);
      let watch = null;
      const finish = () => {
        clearInterval(watch);
        media.pause();
        done();
      };
      watch = setInterval(() => {
        if (mine !== session || media.currentTime >= to || media.ended
            || performance.now() - since > cap) {
          finish();
        }
      }, 10);
      timer = watch;
      begin(media).then((ok) => { if (!ok) finish(); });   // 放不出来就当这段放完了
    });
  }

  // 单词层级的对比：同一个词，先放原声再放你的，来回两遍。
  // 一个词只有两三百毫秒，两条叠在一起听不出什么，得挨着放。
  async function compare(slot, onSide) {
    halt();
    const mine = session;
    [ref, usr].forEach(prime);             // 必须在第一个 await 之前
    graph();
    await wake();
    const loaded = await Promise.all([ready(ref), ready(usr)]);
    if (mine !== session) return;
    if (!loaded.every(Boolean)) {
      stop();
      return;
    }

    const parts = [[ref, slot.refAt, "ref"], [usr, slot.usrAt, "usr"]]
      .filter(([, at]) => at);
    for (let round = 0; round < WORD_ROUNDS; round += 1) {
      for (const [media, at, side] of parts) {
        if (mine !== session) return;
        const panner = panners.get(media);
        if (panner) panner.pan.value = 0;      // 单独听，不分左右耳
        onSide(side);
        await clip(media, at[0] - WORD_PAD, at[1] + WORD_PAD, mine);
        if (mine !== session) return;
        onSide(null);
        await sleep(WORD_GAP_MS);
      }
    }
    if (mine === session) stop();
  }

  // 只放一条：图 1 的两行各属于一个音源，点哪行就放哪行
  async function playOne(side, at, onSide) {
    halt();
    const mine = session;
    const media = side === "ref" ? ref : usr;
    prime(media);                          // 必须在第一个 await 之前
    graph();
    await wake();
    const loaded = await ready(media);
    if (mine !== session) return;
    if (!loaded) {
      stop();
      return;
    }
    const panner = panners.get(media);
    if (panner) panner.pan.value = 0;

    for (let round = 0; round < WORD_ROUNDS; round += 1) {
      if (mine !== session) return;
      onSide(true);
      await clip(media, at[0] - WORD_PAD, at[1] + WORD_PAD, mine);
      if (mine !== session) return;
      onSide(false);
      await sleep(WORD_GAP_MS);
    }
    if (mine === session) stop();
  }

  return { ref, usr, play, stop, compare, playOne,
           playing: () => timer !== null };
}

function playbar(rhythm, audio, figures) {
  const bar = el("div", "playbar");
  const both = el("button", "primary", "▶ 同时播放");
  const one = el("button", null, "只听原声");
  const mine = el("button", null, "只听我的");
  const buttons = [both, one, mine];
  const labels = new Map(buttons.map((b) => [b, b.textContent]));

  const reset = () => {
    buttons.forEach((b) => {
      b.textContent = labels.get(b);
      b.classList.remove("stop");
    });
    figures.forEach((f) => f.hide());
  };
  const player = playback(rhythm, audio,
                          (frame) => figures.forEach((f) => f.move(frame)),
                          reset);

  const start = (button, tracks, spread) => {
    const active = button.classList.contains("stop");
    player.stop();
    if (active) return;                 // 正在放这一路，再点一次就是停
    // 三个键放着时都变成「■ 停」，和页面上别处的停一个样：原来只有「同时播放」会变字
    button.classList.add("stop");
    button.textContent = "■ 停";
    player.play(tracks, spread);
  };

  both.addEventListener("click", () => start(both, [player.ref, player.usr], true));
  one.addEventListener("click", () => start(one, [player.ref], false));
  mine.addEventListener("click", () => start(mine, [player.usr], false));

  bar.append(both, one, mine, speedControl(),
             el("span", "playbar-hint", "戴耳机：原声在左，你的在右"));
  return { node: bar, player };
}

// 选中的这几个词，在两条音频里各自的起止秒数。
// 中间有没对上的词也无所谓：从头放到尾，听的就是这一段。
function spanOf(slots, [low, high]) {
  const part = slots.slice(low, high + 1);
  const mine = part.filter((slot) => slot.usrAt);
  return {
    refAt: [part[0].refAt[0], part[part.length - 1].refAt[1]],
    usrAt: mine.length ? [mine[0].usrAt[0], mine[mine.length - 1].usrAt[1]] : null,
  };
}


// 图 1 里选中的这几个词，在那一行对应的音频里是第几秒到第几秒。
// 块的 start 是相对本行首词的，加上首词的绝对位置就是音频里的时刻。
function rangeOf(rhythm, audio, role, [low, high]) {
  const blocks = role === "ref" ? rhythm.ref : rhythm.usr;
  const offset = role === "ref" ? audio.refOffset : audio.usrOffset;
  const last = blocks[high];
  return [offset + blocks[low].start, offset + last.start + last.width];
}


// 一遍录音：播放条和两张图分开返回。
// 播放条要摆在结果最上面——录完第一件想做的事是听自己刚才那遍，
// 而它原来埋在指标和建议底下，得滚半屏才够得着。
function renderTake(take) {
  const node = el("div", "take-figures");
  const rhythm = rhythmFigure(take.rhythm);
  const pitch = pitchFigure(take.pitch);
  let bar = null;
  let player = null;
  if (take.audio) {
    bar = playbar(take.rhythm, take.audio, [rhythm, pitch]);
    player = bar.player;
    pitch.onPick((range, onSide) => {
      player.stop();               // 正在整句播放的话先停下
      player.compare(spanOf(take.pitch, range), onSide);
    });
    rhythm.onPick((role, range) => {
      player.stop();
      const at = rangeOf(take.rhythm, take.audio, role, range);
      player.playOne(role, at, (on) => rhythm.tint(role, range, on));
    });
  }
  node.append(rhythm.node, pitch.node);
  return { node, bar: bar && bar.node, stop: () => player && player.stop() };
}


// 给 app.js 用：返回一个包含两张图的元素。
// 指标是全部遍数的中位数，画的却只能是一遍——所以让人自己切着看。
function renderFigures(view) {  // eslint-disable-line no-unused-vars
  const controls = el("div", "figure-controls");
  const box = el("div", "figures");
  const tabs = el("div", "takes");
  const bar = el("div", "playbar-slot");
  const body = el("div", "take-body");
  let current = null;

  const numbers = (take) =>
    `可懂度 ${take.accuracy}% · 发声 ${take.speech.toFixed(2)}x · `
    + `停顿 ${take.pause === null ? "—" : take.pause.toFixed(2) + "x"}`;

  // 机器在这一遍里没听对的词。每一遍各说各的：切到哪一遍就看哪一遍。
  // 只列前几处——一遍录进了别的声音时会多出几十个词，全列出来占满半屏
  const misheardText = (take) => {
    if (!take.problems.length) return "每个词机器都听出来了";
    const listed = take.problems.slice(0, MISHEARD_SHOWN).map((problem) => (
      problem.kind === "missing" ? `漏 ${problem.ref}`
        : problem.kind === "wrong" ? `${problem.ref}→听成 ${problem.usr}`
          : `多 ${problem.usr}`)).join("、");
    const more = take.problems.length - MISHEARD_SHOWN;
    return `没听对：${listed}${more > 0 ? `……还有 ${more} 处` : ""}`;
  };

  // 三遍的结果一起列出来：哪一遍有问题一眼看得见，不用一遍遍切过去找。
  // 点哪一行，下面的两张图和播放条就换成哪一遍。
  const rows = view.takes.map((take, index) => {
    const row = el("button", "take-row");
    row.append(el("b", "take-name", `第 ${index + 1} 遍`),
               el("span", "take-numbers", numbers(take)),
               el("span", `take-said${take.problems.length ? "" : " ok"}`, misheardText(take)));
    if (index === view.chosen && view.takes.length > 1) {
      row.append(el("span", "take-pick", "代表这轮"));
    }
    row.addEventListener("click", () => show(index));
    return row;
  });

  function show(index) {
    if (current) current.stop();
    rows.forEach((row, i) => row.classList.toggle("chosen", i === index));
    body.textContent = "";
    bar.textContent = "";
    current = renderTake(view.takes[index]);
    if (current.bar) bar.append(current.bar);
    body.append(current.node);
  }

  tabs.append(...rows);
  controls.append(tabs, bar);
  box.append(body);
  show(view.chosen);
  return { controls, figures: box };
}
