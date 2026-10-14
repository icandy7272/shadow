/* Versioned snapshots, never rendered HTML. IndexedDB commits precede resume pointers. */
(function () {
  const POINTER = 'shadow.session.resume';
  function practiceURL(value, origin) {
    try {
      const url = new URL(value, origin);
      if (url.origin !== origin || !/^\/practice\/[1-9]\d*\/[1-9]\d*$/.test(url.pathname) || url.hash) return null;
      if ([...url.searchParams.keys()].some(key => key !== 'from') || url.searchParams.getAll('from').length > 1) return null;
      if(url.searchParams.has('from')&&!['review','fresh','issues','unheard'].includes(url.searchParams.get('from')))return null;
      return url.pathname + url.search;
    } catch (_) { return null; }
  }
  function validGrading(data) {
    return Boolean(data&&Array.isArray(data.line)&&Array.isArray(data.items)&&Array.isArray(data.extras));
  }
  function completedSnapshot(saved) {
    const data=saved?.analysis;
    return !saved?.pending?.length && Boolean(data&&Number.isInteger(data.run_id)&&data.run_id>0&&Number.isInteger(data.count)&&data.count>0
      &&[data.accuracy,data.speech].every(Number.isFinite)&&(data.pause===null||Number.isFinite(data.pause))
      &&[data.rejected,data.skipped,data.issues,data.good].every(Array.isArray)&&data.view&&Array.isArray(data.view.takes)
      &&data.view.takes.length>0&&Number.isInteger(data.view.chosen)&&data.view.chosen>=0&&data.view.chosen<data.view.takes.length);
  }
  function indexedStore(indexedDB) {
    const opened = new Promise((resolve, reject) => {
      if (!indexedDB) return reject(new Error('浏览器无法保存练习草稿'));
      const request = indexedDB.open('shadow-practice', 1);
      request.onupgradeneeded = () => request.result.createObjectStore('sessions', {keyPath:'url'});
      request.onsuccess = () => resolve(request.result);
      request.onerror = () => reject(request.error);
    });
    opened.catch(()=>{}); // Storage capability failure is reported by each requested operation.
    const transact = async (mode, action) => {
      const db = await opened;
      return new Promise((resolve, reject) => {
        const tx = db.transaction('sessions', mode); let result;
        const request = action(tx.objectStore('sessions'));
        request.onsuccess = () => { result = request.result; };
        tx.oncomplete = () => resolve(result);
        tx.onerror = tx.onabort = () => reject(tx.error || request.error || new Error('练习草稿没有保存'));
      });
    };
    const change=async(url,expectedRevision,action)=>{const db=await opened;return new Promise((resolve,reject)=>{
      const tx=db.transaction('sessions','readwrite'),objectStore=tx.objectStore('sessions');let conflict;
      const read=objectStore.get(url);
      read.onsuccess=()=>{if((read.result?.storageRevision||0)!==expectedRevision){conflict=new Error('另一页面更新了这句练习。请回到保存录音的页面继续，避免覆盖录音。');tx.abort();return;}action(objectStore);};
      tx.oncomplete=()=>resolve();tx.onerror=tx.onabort=()=>reject(conflict||tx.error||new Error('练习草稿没有保存'));
    });};
    return {get:url=>transact('readonly',s=>s.get(url)),put:(value,revision)=>change(value.url,revision,s=>s.put(value)),delete:(url,revision)=>change(url,revision,s=>s.delete(url))};
  }
  function createSession({url,origin,store,pointer,onSaved=()=>{}}) {
    url = practiceURL(url,origin); let chain=Promise.resolve(), value=null, revision=0, replacementAllowed=false, storageRevision=0, startedAt=Date.now();
    const api={durable:false,error:null,ready:null,conflict:null,ending:false,ended:false,allowReplacement(){replacementAllowed=true;},
      save(snapshot){
        if(api.ending||api.ended)return Promise.resolve(null);
        // Clone now: callers may mutate recording arrays before the transaction runs.
        let saved; try {saved=structuredClone({...snapshot,startedAt,version:1,url,updatedAt:Date.now()});} catch(error){api.durable=false;return Promise.reject(error);}
        api.durable=false; const ownRevision=++revision;
        const operation=chain.catch(()=>{}).then(async()=>{
          if(!url)throw new Error('无效的练习地址');
          saved.storageRevision=globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random().toString(36).slice(2)}-${Math.random().toString(36).slice(2)}`;await store.put(saved,storageRevision);storageRevision=saved.storageRevision;value=saved;api.durable=ownRevision===revision;api.error=null;
          try {if(!api.conflict||replacementAllowed)pointer?.setItem(POINTER,JSON.stringify({version:1,url,updatedAt:saved.updatedAt}));}catch(_){}
          onSaved(saved);return saved;
        }).catch(error=>{api.durable=false;api.error=error;throw error});chain=operation;return operation;
      },flush:()=>chain, snapshot:()=>value,
      clear(){
        if(api.ending||api.ended)return chain;
        api.ending=true;
        const operation=chain.catch(()=>{}).then(async()=>{
          await store.delete(url,storageRevision);value=null;storageRevision=0;api.durable=false;api.ended=true;api.ending=false;
          try{const p=JSON.parse(pointer?.getItem(POINTER)||'null');if(p?.url===url)pointer.removeItem(POINTER)}catch(_){}
        }).catch(error=>{api.ending=false;api.ended=false;api.error=error;throw error;});chain=operation;return operation;
      }
    };
    api.ready=Promise.resolve().then(async()=>{let previous;try{previous=JSON.parse(pointer?.getItem?.(POINTER)||'null')}catch(_){}const priorURL=previous?.version===1&&practiceURL(previous.url,origin);if(priorURL&&priorURL!==url){const retained=await store.get(priorURL);if(retained?.version===1&&retained.url===priorURL&&!completedSnapshot(retained))api.conflict=retained;}return store.get(url);}).then(saved=>{if(saved?.version===1&&saved.url===url){if(Number.isInteger(saved.storageRevision)||typeof saved.storageRevision==='string')storageRevision=saved.storageRevision;if(Number.isFinite(saved.startedAt))startedAt=saved.startedAt;if(revision===0){value=saved;api.durable=true;}return saved}return null}).catch(error=>{api.error=error;return null});
    return api;
  }
  if(typeof module!=='undefined')module.exports={practiceURL,createSession,indexedStore,validGrading};
  if(typeof window==='undefined')return;
  let pointer;try{pointer=window.localStorage}catch(_){}
  const store=indexedStore(window.indexedDB);
  // Check the authoritative snapshot before advertising Resume.
  const updateLinks=async()=>{let p;try{p=JSON.parse(pointer?.getItem(POINTER)||'null')}catch(_){}const url=p?.version===1&&practiceURL(p.url,location.origin);if(!url)return;try{const saved=await store.get(url);if(saved?.version!==1||saved.url!==url)return;document.querySelectorAll('[data-session-start],[data-session-resume]').forEach(link=>{link.href=url;link.dataset.resume='true';link.classList.add('is-resume');link.hidden=false;link.setAttribute('aria-label','继续练习');const title=link.querySelector('[data-session-title]');if(title)title.textContent=saved.title||'继续练习';else{const label=link.querySelector('[data-session-label],span');if(label)label.textContent='继续';else link.textContent='继续';}})}catch(_){}};
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',updateLinks);else updateLinks();
  const url=practiceURL(location.href,location.origin);if(!url)return;
  const api=createSession({url,origin:location.origin,store,pointer,onSaved:saved=>{updateLinks();document.dispatchEvent(new CustomEvent('shadow:session-saved',{detail:saved}));}});
  api.validGrading=validGrading;
  const adapters=[];api.register=adapter=>adapters.push(adapter);
  api.capture=()=>Object.assign({startedAt:api.snapshot()?.startedAt||Date.now(),title:document.querySelector('#practice .session-header b')?.textContent||'继续练习'},...adapters.map(adapter=>adapter.capture()));
  api.saveCurrent=()=>api.save(api.capture());
  api.isRecording=()=>adapters.some(adapter=>adapter.recording?.());
  api.isMutating=()=>document.getElementById('practice')?.dataset.mutating==='true';
  api.restore=async()=>{const saved=await api.ready;
    if(api.conflict){
      await new Promise(resolve=>{
        const dialog=document.createElement('dialog');dialog.className='settings-dialog session-replacement';dialog.dataset.sheetLocked='true';dialog.setAttribute('aria-labelledby','session-replacement-title');
        const body=document.createElement('div');body.className='sheet-body';
        const title=document.createElement('h2');title.id='session-replacement-title';title.textContent='已有一场练习';
        const note=document.createElement('p');note.textContent=api.conflict.pending?.length?'上一句有已保存的录音等待提交。可以继续上一句，或保留草稿并开始这句。':'上一句的进度已保存。可以继续上一句，或保留草稿并开始这句。';
        const resume=document.createElement('button');resume.type='button';resume.className='primary';resume.textContent='继续上一句';
        const replace=document.createElement('button');replace.type='button';replace.textContent='保留草稿，开始这句';
        resume.addEventListener('click',()=>location.assign(api.conflict.url));
        replace.addEventListener('click',()=>{api.allowReplacement();dialog.close();dialog.remove();resolve();});
        dialog.addEventListener('cancel',event=>{event.preventDefault();location.assign(api.conflict.url);});
        body.append(title,note,resume,replace);dialog.append(body);document.body.append(dialog);dialog.showModal();
      });
    }
if(saved)adapters.forEach(adapter=>{try{adapter.restore(saved)}catch(error){api.error=error;api.durable=false;}});document.dispatchEvent(new CustomEvent('shadow:session-restored',{detail:saved}));return saved;};
  window.ShadowSession=api;
})();
