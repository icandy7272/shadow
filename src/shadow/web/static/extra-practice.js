// 加练会话只在当前页面维护。录音仍由现有接口分别保存。
window.ShadowExtraPractice = (() => {
  const unavailable = (take, issue) => (take.uncertain || []).includes(issue.ref_index)
    || (take.uncertain_issues || []).includes(key(issue));
  const key = (issue) => `${issue.kind}:${issue.ref_index}`;
  function session() {
    return {
      baseline: null, latest: null, attempts: [],
      accept(result, extra) {
        if (!extra || !this.baseline) {
          this.baseline = result;
          this.attempts = [];
        } else this.attempts.push(...result.view.takes);
        this.latest = result;
      },
      rows() {
        return (this.baseline?.issues || []).map((issue) => {
          const comparable = this.attempts.filter((take) =>
            !unavailable(take, issue));
          const latest = this.attempts.at(-1);
          const uncertain = latest && unavailable(latest, issue);
          return {...issue, beforeHits: issue.hits, beforeTotal: issue.total,
            hits: comparable.filter((take) => take.issues.some((one) => key(one) === key(issue))).length,
            total: comparable.length,
            state: uncertain ? 'uncertain' : latest?.issues.some((one) => key(one) === key(issue)) ? 'present' : 'absent'};
        });
      },
    };
  }

  function panel(state, begin) {
    const section = el('section', 'extra-practice');
    section.append(el('h3', null, '加练前后对比'));
    section.append(el('p', 'hint', `已加练 ${state.attempts.length} 遍。单遍变化只说明这次表现，不代表已经稳定掌握。`));
    const before = state.baseline.view;
    const after = state.latest.view.takes[state.latest.view.chosen];
    const select = el('select');
    select.setAttribute('aria-label', '选择加练前的录音');
    before.takes.forEach((take, index) => {
      const option = el('option', null, `加练前第 ${index + 1} 遍${index === before.chosen ? '（代表遍）' : ''}`);
      option.value = index;
      select.append(option);
    });
    select.value = before.chosen;
    section.append(select);
    const audioRow = el('div', 'extra-audio');
    const ref = new Audio(after.audio.ref);
    const old = new Audio(before.takes[before.chosen].audio.usr);
    const current = new Audio(after.audio.usr);
    const tracks = [ref, old, current];
    const labels = ['原声', '加练前', '加练后'];
    let timer = null, generation = 0, cancel = null;
    const stop = () => {
      generation += 1;
      clearInterval(timer);
      cancel?.(); cancel = null;
      tracks.forEach((media) => media.pause());
    };
    loops.add(stop);
    const play = async (range) => {
      if (recording) return;
      stopLoops();
      const token = generation;
      status.textContent = '';
      // 用户点击时先解锁三条音轨，兼容手机浏览器的播放权限。
      tracks.forEach((media) => { const p = media.play(); media.pause(); p?.catch(() => {}); });
      try {
        for (let index = 0; index < tracks.length; index += 1) {
          if (token !== generation) return;
          const media = tracks[index];
          if (media.readyState < 1) {
            await new Promise((resolve, reject) => {
              cancel = resolve;
              const started = Date.now();
              const interval = setInterval(() => {
                if (token !== generation || media.readyState >= 1) {
                  clearInterval(interval); if (token === generation) cancel = null; resolve();
                } else if (media.error || Date.now() - started > 8000) {
                  clearInterval(interval); if (token === generation) cancel = null; reject(new Error('音频加载失败，请重试。'));
                }
              }, 30);
              timer = interval;
            });
          }
          if (token !== generation) return;
          const take = index === 1 ? before.takes[Number(select.value)] : after;
          const bounds = range !== null ? take.pitch[range]?.[index === 0 ? 'refAt' : 'usrAt'] : null;
          if (range !== null && !bounds) throw new Error('这个词缺少可靠的时间边界，请听整句。');
          media.currentTime = bounds ? Math.max(0, bounds[0] - 0.06) : 0;
          status.textContent = `正在播放：${labels[index]}`;
          await media.play();
          if (token !== generation) return;
          await new Promise((resolve, reject) => {
            cancel = resolve;
            const started = Date.now();
            const interval = setInterval(() => {
              if (token !== generation || media.ended || (bounds && media.currentTime >= bounds[1] + 0.06)) {
                clearInterval(interval); if (token === generation) cancel = null; media.pause(); resolve();
              } else if (media.error || Date.now() - started > 90000) {
                clearInterval(interval); if (token === generation) cancel = null; media.pause(); reject(new Error('音频播放失败，请重试。'));
              }
            }, 30);
            timer = interval;
          });
        }
        if (token === generation) status.textContent = '前后对比播放完了。';
      } catch (err) { if (token === generation) { stop(); status.textContent = err.message; } }
    };
    select.addEventListener('change', () => { stop(); old.src = before.takes[Number(select.value)].audio.usr; });
    const whole = el('button', null, '▶ 原声 → 加练前 → 加练后');
    whole.addEventListener('click', () => play(null));
    const halt = el('button', null, '停止试听'); halt.addEventListener('click', stop);
    const status = el('p', 'hint'); status.setAttribute('role', 'status');
    audioRow.append(whole, halt); section.append(audioRow, status);
    const rows = state.rows();
    if (!rows.length) section.append(el('p', 'hint', '加练前没有反复出现的问题，可以回听前后录音，观察整体变化。'));
    rows.forEach((row) => {
      const item = el('div', 'issue');
      item.append(el('b', null, row.title));
      const text = row.state === 'uncertain' ? '这次无法可靠判断'
        : row.state === 'present' ? '这次仍检测到'
        : row.total >= 3 && row.hits === 0 ? `加练的 ${row.total} 遍均未再检测到`
        : '这次未检测到';
      item.append(el('span', null, `加练前 ${row.beforeHits}/${row.beforeTotal} 遍出现；${text}。加练中 ${row.hits}/${row.total} 遍出现（只计可比较的录音）。`));
      const local = el('button', null, '听这一处前后对比');
      local.addEventListener('click', () => play(row.ref_index));
      item.append(local); section.append(item);
    });
    const extra = el('button', 'primary', '再加练 1 遍');
    extra.addEventListener('click', begin); section.append(extra);
    return {node: section, dispose: () => {stop(); loops.delete(stop);}};
  }
  return {session, panel};
})();
