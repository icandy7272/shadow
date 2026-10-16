/* Native mobile controls, independent of learning and recorder APIs. */
function clampNumber(value,min,max,fallback){const n=value===''?NaN:Number(value);return Math.min(max,Math.max(min,Number.isFinite(n)?Math.round(n):fallback));}
function canDismissDrag(dy,dx,elapsed){return dy>0&&dy>Math.abs(dx)*1.2&&(dy>=90||(dy>=30&&dy/Math.max(1,elapsed)>.6));}
function finishState({recording=false,submitting=false,pending=[],analysis=null}={}){return submitting?'submitting':recording?'recording':pending?.length?'pending':analysis?'saved':'draft';}
function setDisabledIfChanged(control,value){value=Boolean(value);if(control&&control.disabled!==value)control.disabled=value;}
function dockActionRole(id,saved=false){if(id==='stop-take')return 'stop';if(id==='next-sentence')return saved?'primary':'secondary';return ['skip-drill','extra-record','redo-take'].includes(id)?'secondary':'primary';}
function dockMode({recording=false,stopVisible=false,submitting=false,pending=false,saved=false}={}){return recording?(stopVisible?'recording':'prelisten'):submitting?'analysing':pending?'retry':saved?'saved':'ready';}
function syncDockProxy(original,proxy){
 for(const key of ['hidden','disabled','innerHTML'])if(proxy[key]!==original[key])proxy[key]=original[key];
 const space=original.classList.contains('space-target');if(proxy.classList.contains('space-target')!==space)proxy.classList.toggle('space-target',space);
}
if(typeof module!=='undefined')module.exports={syncDockProxy,dockActionRole,dockMode,clampNumber,canDismissDrag,finishState,setDisabledIfChanged};
if(typeof document!=='undefined')(()=>{
 const stack=[];const openers=new WeakMap(),replaced=new WeakSet();let sheetSequence=0;let scroll=0,restoring=false,skipPop=0;
 function lock(){if(stack.length!==1)return;scroll=window.scrollY;document.body.style.position='fixed';document.body.style.top=`-${scroll}px`;document.body.style.width='100%';}
 function unlock(){if(stack.length)return;document.body.style.position='';document.body.style.top='';document.body.style.width='';window.scrollTo(0,scroll);}
 function open(dialog){
  if(!dialog||dialog.open)return false;
  const previous=stack.at(-1);if(previous?.dataset.sheetLocked==='true')return false;
  const active=document.activeElement;
  const trigger=previous?.contains(active)?openers.get(previous)||active:active;
  if(previous){replaced.add(previous);stack.splice(stack.indexOf(previous),1);previous.close();}
  register(dialog);openers.set(dialog,trigger);dialog.showModal();stack.push(dialog);
  if(!previous)lock();
  if(!restoring){if(previous)history.replaceState({...history.state,shadowSheet:dialog.id},'');else history.pushState({...history.state,shadowSheet:dialog.id},'');}
  return true;
 }
 function close(dialog){if(!dialog?.open||dialog.dataset.sheetLocked==='true')return;dialog.close();}
 function register(dialog){if(dialog.dataset.nativeSheet)return;if(!dialog.id)dialog.id=`shadow-sheet-${++sheetSequence}`;dialog.dataset.nativeSheet='true';
  const handle=document.createElement('button');handle.type='button';handle.className='sheet-grabber';handle.setAttribute('aria-label','关闭面板');handle.addEventListener('click',()=>close(dialog));dialog.prepend(handle);
  let drag=null;handle.addEventListener('pointerdown',e=>{drag={x:e.clientX,y:e.clientY,time:performance.now()};handle.setPointerCapture(e.pointerId)});
  handle.addEventListener('pointermove',e=>{if(drag)dialog.style.translate=`0 ${Math.max(0,e.clientY-drag.y)}px`});
  handle.addEventListener('pointerup',e=>{if(drag&&canDismissDrag(e.clientY-drag.y,e.clientX-drag.x,performance.now()-drag.time))close(dialog);drag=null;dialog.style.translate=''});
  handle.addEventListener('pointercancel',()=>{drag=null;dialog.style.translate=''});
  dialog.addEventListener('click',e=>{if(e.target===dialog)close(dialog)});
  dialog.addEventListener('close',()=>{
   if(replaced.has(dialog)){replaced.delete(dialog);return;}
   const i=stack.indexOf(dialog);if(i<0)return;stack.splice(i,1);unlock();
   if(!restoring&&history.state?.shadowSheet===dialog.id){skipPop++;history.back()}
   const trigger=openers.get(dialog);if(!stack.length&&trigger?.isConnected)queueMicrotask(()=>trigger.focus({preventScroll:true}));
  });
  dialog.addEventListener('cancel',event=>{if(dialog.dataset.sheetLocked==='true')event.preventDefault()});

  new MutationObserver(()=>{if(dialog.open&&!stack.includes(dialog)){stack.push(dialog);lock();history.pushState({...history.state,shadowSheet:dialog.id},'')}}).observe(dialog,{attributes:true,attributeFilter:['open']});
 }
 document.querySelectorAll('dialog').forEach(register);
 new MutationObserver(()=>document.querySelectorAll('dialog').forEach(register)).observe(document.body,{childList:true,subtree:true});
 document.addEventListener('click',e=>{const trigger=e.target.closest('[data-open-dialog]');if(trigger){e.preventDefault();open(document.getElementById(trigger.dataset.openDialog));}if(e.target.closest('[data-close-dialog]'))close(e.target.closest('dialog'));});
 window.addEventListener('popstate',()=>{if(skipPop){skipPop--;return;}if(restoring)return;const top=stack.at(-1);if(top){if(top.dataset.sheetLocked==='true'){history.pushState({...history.state,shadowSheet:top.id},'');return;}restoring=true;close(top);restoring=false;}});
 window.ShadowSheets={open,close};
 window.ShadowUI={
  toast(message){let box=document.getElementById('app-toast');if(!box){box=document.createElement('div');box.id='app-toast';box.className='app-toast';box.setAttribute('role','status');document.body.append(box)}clearTimeout(box._timer);box.textContent=message;box.hidden=false;box._timer=setTimeout(()=>box.hidden=true,4000)},
  confirm({title,message,confirm='确认',danger=false}){return new Promise(resolve=>{const dialog=document.createElement('dialog');dialog.className='settings-dialog confirm-dialog';dialog.id=`confirm-${Date.now()}`;const body=document.createElement('div');body.className='sheet-body';const heading=document.createElement('h2');heading.textContent=title;heading.id=dialog.id+'-title';dialog.setAttribute('aria-labelledby',heading.id);const p=document.createElement('p');p.textContent=message;const yes=document.createElement('button');yes.type='button';yes.className=danger?'danger':'primary';yes.textContent=confirm;const no=document.createElement('button');no.type='button';no.textContent='取消';let result=false;yes.addEventListener('click',()=>{result=true;close(dialog)});no.addEventListener('click',()=>close(dialog));dialog.addEventListener('close',()=>{resolve(result);dialog.remove()},{once:true});body.append(heading,p,yes,no);dialog.append(body);document.body.append(dialog);register(dialog);open(dialog)})}
 };
 document.querySelectorAll('.card-menu').forEach((menu,index)=>{const summary=menu.querySelector('summary');summary?.addEventListener('click',event=>{event.preventDefault();const dialog=document.createElement('dialog');dialog.id=`source-menu-${index}`;dialog.className='settings-dialog';dialog.setAttribute('aria-label','素材操作');const body=document.createElement('div');body.className='sheet-body grouped-list';for(const original of menu.querySelectorAll('.card-actions > *')){const item=original.cloneNode(true);item.classList.add('grouped-row');if(item.tagName==='BUTTON')item.addEventListener('click',()=>{original.click()});body.append(item)}dialog.append(body);document.body.append(dialog);dialog.addEventListener('close',()=>dialog.remove(),{once:true});register(dialog);open(dialog)})});

 const viewport=window.visualViewport;function sizeSheets(){document.documentElement.style.setProperty('--sheet-height',`${viewport?.height||window.innerHeight}px`);document.documentElement.style.setProperty('--viewport-top',`${viewport?.offsetTop||0}px`)}viewport?.addEventListener('resize',sizeSheets);viewport?.addEventListener('scroll',sizeSheets);sizeSheets();
 // Give number fields an explicit touch target, keeping the original input and events.
 document.querySelectorAll('input[type=number]').forEach(input=>{if(input.closest('.number-stepper'))return;const wrap=document.createElement('span');wrap.className='number-stepper';input.before(wrap);wrap.append(input);
  const change=delta=>{input.value=clampNumber(Number(input.value)+delta,Number(input.min||0),Number(input.max||999),Number(input.defaultValue||0));input.dispatchEvent(new Event('input',{bubbles:true}));input.dispatchEvent(new Event('change',{bubbles:true}));};
  for(const [label,delta] of [['−',-1],['＋',1]]){const b=document.createElement('button');b.type='button';b.textContent=label;b.setAttribute('aria-label',`${delta<0?'减少':'增加'}${input.id==='takes'?'录音遍数':input.id==='prelisten'?'预听次数':'次数'}`);let timer,repeat;const stop=()=>{clearTimeout(timer);clearInterval(repeat)};b.addEventListener('click',()=>change(delta));b.addEventListener('pointerdown',()=>{timer=setTimeout(()=>{repeat=setInterval(()=>change(delta),80)},400)});for(const event of ['pointerup','pointercancel','pointerleave'])b.addEventListener(event,stop);wrap.append(b)}
  input.addEventListener('focus',()=>input.select());input.addEventListener('blur',()=>{input.value=clampNumber(input.value,Number(input.min||0),Number(input.max||999),Number(input.defaultValue||0));input.dispatchEvent(new Event('change',{bubbles:true}))});});
 document.querySelectorAll('.app-search input').forEach(input=>{const b=document.createElement('button');b.type='button';b.className='search-clear';b.textContent='×';b.setAttribute('aria-label','清空搜索');b.hidden=!input.value;b.addEventListener('click',()=>{input.value='';input.dispatchEvent(new Event('input',{bubbles:true}));input.focus()});input.addEventListener('input',()=>b.hidden=!input.value);input.after(b)});
 const root=document.getElementById('practice');if(!root)return;
 const dock=document.getElementById('practice-dock');
 if(dock&&typeof ResizeObserver!=='undefined')new ResizeObserver(()=>document.documentElement.style.setProperty('--practice-dock-height',`${Math.ceil(dock.getBoundingClientRect().height)}px`)).observe(dock);
 // Keep originals in their steps so recorder shortcuts and replay counts retain their targets.
 const proxies=[];for(const [selector,stage] of [['#step-listen button.play','listen'],['#submit-drill','drill'],['#skip-drill','drill'],['#practice-continue','drill']]){const original=root.querySelector(selector);if(!original)continue;original.classList.add('dock-source-control');const proxy=original.cloneNode(true);proxy.removeAttribute('id');proxy.classList.remove('dock-source-control');proxy._shortcutSource=original;proxy.dataset.dockStage=stage;proxy.dataset.actionId=original.id||'play';proxy.addEventListener('click',()=>original.click());dock.append(proxy);proxies.push({original,proxy});}
 const syncDock=()=>{
  if(dock.hidden)dock.hidden=false;
  for(const {original,proxy}of proxies)syncDockProxy(original,proxy);
  const mode=dockMode({recording:root.dataset.recording==='true',stopVisible:!document.getElementById('stop-take')?.hidden,submitting:root.dataset.submitting==='true',pending:root.dataset.pending==='true',saved:!document.getElementById('extra-record')?.hidden});
  if(root.dataset.dockMode!==mode)root.dataset.dockMode=mode;
  const controls=[...dock.querySelectorAll(':scope > button,.dock-pager')];
  for(const control of controls){
   const id=control.classList.contains('dock-pager')?'next-sentence':control.dataset.actionId||control.id;
   if(!id)continue;const role=dockActionRole(id,mode==='saved');if(control.dataset.actionEmphasis!==role)control.dataset.actionEmphasis=role;
  }
  const ordered=controls.slice().sort((a,b)=>Number(a.dataset.actionEmphasis!=='secondary')-Number(b.dataset.actionEmphasis!=='secondary'));
  if(ordered.some((control,index)=>control!==controls[index]))for(const control of ordered)dock.append(control);
  setDisabledIfChanged(document.getElementById('practice-minimize'),root.dataset.recording==='true'||root.dataset.mutating==='true');
 };

 new MutationObserver(syncDock).observe(root,{subtree:true,childList:true,attributes:true,attributeFilter:['class','hidden','disabled','data-active-step','data-mutating','data-recording','data-submitting','data-pending']});syncDock();
 const elapsed=document.getElementById('session-elapsed');const tick=()=>{const start=window.ShadowSession?.snapshot()?.startedAt;if(start&&elapsed){const minutes=Math.max(0,Math.floor((Date.now()-start)/60000));elapsed.textContent=` · ${minutes} 分钟`}};setInterval(tick,15000);document.addEventListener('shadow:session-restored',tick);tick();
 const finish=document.getElementById('session-finish'),error=document.getElementById('session-finish-error'),discard=document.getElementById('session-discard'),save=document.getElementById('session-save-exit');
 document.getElementById('practice-finish')?.addEventListener('click',()=>{const session=window.ShadowSession;const state=finishState({...session?.capture(),recording:session?.isRecording(),submitting:root.dataset.submitting==='true'||root.dataset.mutating==='true'});error.textContent='';discard.dataset.confirm='false';discard.textContent='放弃未提交的录音';discard.hidden=state!=='pending';save.disabled=state==='pending'||state==='recording'||state==='submitting';document.getElementById('session-finish-note').textContent=state==='submitting'?'正在保存与分析录音，请等待结果后结束。':state==='recording'?'这遍还在录音，请先点击「说完了」。':state==='pending'?'录音尚未保存到服务。请返回重新提交；如果放弃，只删除未提交的录音，已保存的记录会保留。':state==='saved'?'这句已保存。追加的每一遍都记在同一轮中。': '已保存的盲听和默写记录会保留，结束后将清除这次草稿。';const data=session?.capture()?.analysis;const summary=document.getElementById('session-summary');summary.replaceChildren();if(data)for(const [v,label]of [[data.count,'录音遍数'],[`${data.accuracy}%`,'中位可懂度'],[data.issues.length,'待改问题']]){const item=document.createElement('div'),b=document.createElement('b'),span=document.createElement('span');b.textContent=v;span.textContent=label;item.append(b,span);summary.append(item)}open(finish)});
 async function end(){save.disabled=true;discard.disabled=true;try{await window.ShadowSession.clear();window.location.assign('/today')}catch(_){error.textContent='草稿未能清除，请重试。';save.disabled=false;discard.disabled=false}}
 save?.addEventListener('click',end);discard?.addEventListener('click',()=>{if(discard.dataset.confirm==='true'){end();return;}discard.dataset.confirm='true';discard.textContent='确认放弃这些未提交录音';error.textContent='此操作无法撤销。已保存到服务的记录不受影响。'});
})();
