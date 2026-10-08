// 页面内共用音频：提前下载，播放器用本地 URL，跟读复用解码结果。
// 不存本地练习数据到持久缓存；离开页面后由浏览器释放。
window.ShadowAudio = (() => {
  const entries = new Map();
  function entry(src) {
    if (!entries.has(src)) {
      const item = {};
      const abort = new AbortController();
      const timeout = setTimeout(() => abort.abort(), 20000);
      item.blob = fetch(src, { signal: abort.signal })
        .then((response) => {
          if (!response.ok) throw new Error(`音频没取到（${response.status}）`);
          return response.blob();
        }).finally(() => clearTimeout(timeout)).catch((err) => {
          if (entries.get(src) === item) entries.delete(src);
          throw err;
        });
      entries.set(src, item);
    }
    return entries.get(src);
  }
  return {
    peek(src) { return entries.get(src)?.objectUrl; },
    url(src) {
      const item = entry(src);
      if (!item.url) item.url = item.blob.then((blob) => {
        item.objectUrl = URL.createObjectURL(blob);
        return item.objectUrl;
      });
      return item.url;
    },
    decode(src, context) {
      const item = entry(src);
      if (!item.decoded) {
        item.decoded = item.blob.then((blob) => blob.arrayBuffer())
          .then((data) => context.decodeAudioData(data))
          .catch((err) => { item.decoded = null; throw err; });
      }
      return item.decoded;
    },
  };
})();
