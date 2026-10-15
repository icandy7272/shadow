/* Navigation state is per browser tab; audio drafts remain owned by session.js. */
(function () {
  function sectionFor(path) {
    if (path === '/today') return 'today';
    if (path === '/plan' || path === '/plan/guide') return 'plan';
    if (['/start','/chain','/talk'].includes(path)) return 'start';
    if (/^\/records(?:\/|$)/.test(path)) return 'records';
    if (path === '/vocab' || /^\/sources(?:\/|$)/.test(path)) return 'library';
    return null;
  }
  function retainedURL(value, section, origin) {
    try {
      const url = new URL(value, origin);
      if (url.origin !== origin || sectionFor(url.pathname) !== section || url.hash) return null;
      return url.pathname + url.search;
    } catch (_) { return null; }
  }
  function readViewState(raw) {
    try {
      const value = JSON.parse(raw);
      if (!value || typeof value !== 'object') return null;
      return {scroll:Number.isFinite(value.scroll)?Math.max(0,Math.min(value.scroll,1e7)):0,
        search:typeof value.search==='string'?value.search.slice(0,500):'',
        filter:['all','review','fresh','issues','unheard'].includes(value.filter)?value.filter:'all'};
    } catch (_) { return null; }
  }
  if (typeof module !== 'undefined') module.exports = {sectionFor,retainedURL,readViewState};
  if (typeof document === 'undefined') return;
  const section=sectionFor(location.pathname), url=location.pathname+location.search;
  const prefix='shadow.navigation.v1:', viewKey=prefix+'view:'+url;
  function read(key) { try { return sessionStorage.getItem(key); } catch (_) { return null; } }
  function write(key,value) { try { sessionStorage.setItem(key,value); } catch (_) {} }
  const search=document.querySelector('.app-search input');
  function save() {
    if (!section) return;
    // A sheet freezes body scrolling. Keep the preceding list offset in that case.
    const offset=document.body.style.position==='fixed'?Math.max(0,-parseFloat(document.body.style.top)||0):window.scrollY;
    write(viewKey,JSON.stringify({scroll:offset,search:search?.value||'',filter:document.querySelector('#filters .chosen')?.dataset.filter||'all'}));
    write(prefix+'section:'+section,url);
  }
  const arriving=read(prefix+'arriving')===url;
  if (arriving) write(prefix+'arriving','');
  const historyReturn=performance.getEntriesByType('navigation')[0]?.type==='back_forward';
  const saved=(arriving||historyReturn)&&readViewState(read(viewKey));
  if (saved) {
    if (search) { search.value=saved.search; search.dispatchEvent(new Event('input',{bubbles:true})); }
    document.querySelector(`#filters [data-filter="${saved.filter}"]`)?.click();
    requestAnimationFrame(()=>requestAnimationFrame(()=>window.scrollTo(0,saved.scroll)));
  }
  const tabs=[...document.querySelectorAll('.app-tabs a')].map(link=>({link,root:new URL(link.href).pathname,targetSection:sectionFor(new URL(link.href).pathname)}));
  function refreshTab(tab) {
    const {link,root,targetSection}=tab;
    const retained=retainedURL(read(prefix+'section:'+targetSection),targetSection,location.origin);
    link.href=targetSection!==section&&retained?retained:root;
  }
  const refreshTabs=()=>tabs.forEach(refreshTab);
  refreshTabs();window.addEventListener('pageshow',refreshTabs);
  tabs.forEach(tab=>{
    if (!tab.targetSection) return;
    tab.link.addEventListener('click',event=>{
      if(event.defaultPrevented||event.metaKey||event.ctrlKey||event.shiftKey||event.altKey)return;
      save();refreshTab(tab);write(prefix+'arriving',new URL(tab.link.href).pathname+new URL(tab.link.href).search);
    });
  });
  window.addEventListener('pagehide',save);
})();
