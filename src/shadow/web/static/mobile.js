/* UI only: existing recorder and API remain responsible for data. */
function answersRevealed({graded=false,skipped=false}={}) { return graded || skipped; }
function nextPracticeStep(active,status){
  if(active==='listen'&&status.listen&&!status.record&&!status.drill)return 'record';
  if(active==='record'&&status.record&&!status.drill)return 'drill';
  if(active==='drill'&&status.skipped)return 'record';
  return active;
}
function focusPracticeStep(step, desktop, controls) {
  if (!desktop) return;
  if (step === 'drill') controls.typed?.focus({ preventScroll: true });
  if (step === 'record') controls.start?.focus({ preventScroll: true });
}

function keyboardInset({innerHeight,viewportHeight,offsetTop=0,scale=1,editing=false}) {
  if(!editing||Math.abs(scale-1)>.05)return 0;
  const inset=Math.max(0,innerHeight-viewportHeight-Math.max(0,offsetTop));
  return inset>100?inset:0;
}

function sessionNavigationBusy(recording, pending, session) {
  return Boolean(recording || session?.isMutating?.() || (pending && !session?.durable));
}

function guardPracticeNavigation(doc, win, busy, notify) {
  const block = event => {
    event.preventDefault();
    event.stopImmediatePropagation();
    notify();
  };
  doc.addEventListener('click', event => {
    if (busy() && event.target.closest('a[href],#retire,#unretire')) block(event);
  }, true);
  doc.addEventListener('keydown', event => {
    if (!busy() || event.target.closest('input,textarea,select,[contenteditable]')) return;
    const key = typeof physicalKey === 'function' ? physicalKey(event) : event.key;
    if (['ArrowLeft', 'ArrowRight', 'k'].includes(key)) block(event);
  }, true);
  win.addEventListener('beforeunload', event => {
    if (!busy()) return;
    event.preventDefault();
    event.returnValue = '';
  });
}

if(typeof module!=='undefined')module.exports={answersRevealed,keyboardInset,nextPracticeStep,focusPracticeStep,guardPracticeNavigation,sessionNavigationBusy};
if(typeof document!=='undefined')(()=>{
 const theme=document.getElementById('app-theme');
 if(theme){theme.value=document.documentElement.dataset.theme||'system';theme.addEventListener('change',()=>{if(theme.value==='system')delete document.documentElement.dataset.theme;else document.documentElement.dataset.theme=theme.value;try{localStorage.setItem('shadow.theme',theme.value)}catch(_){}})}
 document.addEventListener('keydown',event=>{if(document.querySelector('dialog[open]'))event.stopImmediatePropagation()},true);
 const viewport=window.visualViewport;if(viewport){const resize=()=>{
  const active=document.activeElement,editing=Boolean(active?.matches('textarea,input:not([type=checkbox]):not([type=radio]):not([type=button]):not([type=submit]),[contenteditable="true"]'));
  const inset=keyboardInset({innerHeight:window.innerHeight,viewportHeight:viewport.height,offsetTop:viewport.offsetTop,scale:viewport.scale,editing});
  document.documentElement.style.setProperty('--keyboard-inset',`${inset}px`);document.body.classList.toggle('keyboard-open',inset>0)
 };viewport.addEventListener('resize',resize);viewport.addEventListener('scroll',resize);document.addEventListener('focusin',resize);document.addEventListener('focusout',()=>requestAnimationFrame(resize));resize()}
 for(const [id,selector] of [['library-search','#cards .card'],['vocab-search','#vocab .vocab-item']]){const input=document.getElementById(id);input?.addEventListener('input',()=>{const query=input.value.trim().toLocaleLowerCase();document.querySelectorAll(selector).forEach(card=>card.hidden=!card.textContent.toLocaleLowerCase().includes(query))})}
 const root=document.getElementById('practice');if(!root)return;
 const ids=['listen','drill','record'],panels=ids.map(id=>document.getElementById(`step-${id}`)),tabs=[...document.querySelectorAll('[data-practice-step]')];let active='listen';
 const dock=document.getElementById('practice-dock'),next=document.getElementById('practice-continue'),more=document.getElementById('rec-more'),settings=document.getElementById('record-settings');
 const isBusy=()=>sessionNavigationBusy(recording,root.dataset.pending==='true',window.ShadowSession);
 const navigationNote=document.createElement('p');navigationNote.className='hint navigation-note';navigationNote.setAttribute('role','status');navigationNote.hidden=true;dock.append(navigationNote);
 guardPracticeNavigation(document,window,isBusy,()=>{navigationNote.textContent=root.dataset.mutating==='true'?'正在保存这一步，请稍等。':recording?'这遍还在录音，请先点击「说完了」。':'录音草稿还没有安全保存，请保留此页面并重新提交。';navigationNote.hidden=false});
 const pager=root.querySelector('.pager'),nextSentence=pager?.querySelector('a.next'),dockPager=document.createElement('nav');dockPager.className='pager dock-pager';if(nextSentence)dock.append(dockPager);
 const menuBody=document.querySelector('#practice-menu .sheet-body');
 const retirement=document.getElementById('retire-row');if(menuBody&&retirement)menuBody.append(retirement);
 const prevSentence=pager?.querySelector('a:not(.next)');if(menuBody&&prevSentence){const back=prevSentence.cloneNode(true);back.classList.add('grouped-row');back.textContent='上一句';menuBody.append(back)}
 const queueNote=root.querySelector('.pager-note');if(menuBody&&queueNote)menuBody.append(queueNote);
 if(nextSentence){nextSentence.setAttribute('aria-label',nextSentence.textContent.trim());nextSentence.replaceChildren(document.createTextNode(new URL(nextSentence.href).pathname.startsWith('/practice/')?'练下一句':'完成，回素材'),el('kbd','key','→'))}
 const startControl=document.getElementById('start-record');
 const toDictation=document.getElementById('record-continue');
 const skipRecord=document.getElementById('skip-record');
 function openDictation(){if(isBusy())return;panels[1].classList.remove('locked');show('drill');}
 toDictation.addEventListener('click',openDictation);
 skipRecord.addEventListener('click',()=>{if(isBusy())return;panels[2].classList.add('skipped');openDictation()});
 dock.append(toDictation,skipRecord);

 startControl?.addEventListener('click',()=>{const dialog=startControl.closest('dialog');if(dialog?.open)window.ShadowSheets?.close(dialog)},true);
 const recSettings=more?.querySelector('.rec-settings');if(settings&&recSettings)settings.querySelector('.sheet-body').append(recSettings);
 more?.querySelector('summary')?.addEventListener('click',event=>{event.preventDefault();window.ShadowSheets?.open(settings)});
 for(const id of ['start-record','extra-record','stop-take','redo-take','resubmit']){const control=document.getElementById(id);if(control)dock.append(control)}
 function show(id,scroll=true){if(!ids.includes(id)||document.getElementById(`step-${id}`).classList.contains('locked'))return;if(active!==id)stopLoops();active=id;root.dataset.activeStep=id;if(nextSentence){const target=id==='record'?dockPager:pager;if(nextSentence.parentElement!==target)target.append(nextSentence)}panels.forEach((panel,index)=>{if(panel.hidden!==(ids[index]!==id))panel.hidden=ids[index]!==id});tabs.forEach(tab=>tab.setAttribute('aria-selected',String(tab.dataset.practiceStep===id)));if(dock.hidden!==(id!=='record'))dock.hidden=id!=='record';if(id==='drill'&&!panels[1].classList.contains('graded')&&!panels[1].classList.contains('done'))focusPracticeStep(id,window.matchMedia('(hover: hover)').matches,{typed:document.getElementById('dictation-text')});if(scroll)root.scrollIntoView({block:'start',behavior:window.matchMedia('(prefers-reduced-motion: reduce)').matches?'auto':'smooth'})}
 document.addEventListener('keydown',event=>{if(event.metaKey||event.ctrlKey||event.altKey||event.repeat||event.target.closest('input,textarea,select,[contenteditable]'))return;if(/^[rnt]$/i.test(physicalKey(event))&&!panels[2].classList.contains('locked')&&!document.querySelector('dialog[open]'))show('record',false)},true);
 tabs.forEach(tab=>tab.addEventListener('click',()=>show(tab.dataset.practiceStep)));next.addEventListener('click',()=>{if(isBusy()||panels[2].classList.contains('locked'))return;show('record')});
 const micFeedback=document.createElement('p');micFeedback.className='hint';micFeedback.setAttribute('role','status');settings.querySelector('.sheet-body').append(micFeedback);
 const updateMicFeedback=()=>{micFeedback.textContent=[document.getElementById('rec-status')?.textContent,document.getElementById('mic-note')?.textContent].filter(Boolean).join(' · ')};
 const micObserver=new MutationObserver(updateMicFeedback);for(const id of ['rec-status','mic-note']){const el=document.getElementById(id);if(el)micObserver.observe(el,{childList:true,characterData:true,subtree:true})}
 let previous={listen:false,record:false,drill:false,skipped:false};
 function sync(){const status={listen:panels[0].classList.contains('complete'),record:panels[2].classList.contains('complete'),drill:answersRevealed({graded:panels[1].classList.contains('graded'),skipped:panels[1].classList.contains('skipped')}),skipped:panels[1].classList.contains('skipped')};if(root.dataset.answersRevealed!==String(status.drill))root.dataset.answersRevealed=String(status.drill);
 const ready=!panels[1].classList.contains('locked')&&!status.drill&&!isBusy();
 if(toDictation.hidden!==!ready)toDictation.hidden=!ready;
 if(skipRecord.hidden!==Boolean(status.record||status.drill||isBusy()))skipRecord.hidden=Boolean(status.record||status.drill||isBusy());
 for(const tab of tabs){const locked=document.getElementById(`step-${tab.dataset.practiceStep}`).classList.contains('locked'),busy=isBusy();if(tab.disabled!==(locked||busy))tab.disabled=locked||busy}if(next.hidden!==!status.drill)next.hidden=!status.drill;let target=active;if(status.listen!==previous.listen||status.record!==previous.record||status.skipped!==previous.skipped)target=nextPracticeStep(active,status);if(typeof recording!=='undefined'&&recording)target='record';if(target!==active)show(target);if(dockPager.inert!==isBusy())dockPager.inert=isBusy();if(!isBusy()&&!navigationNote.hidden)navigationNote.hidden=true;const extra=document.getElementById('extra-record'),start=document.getElementById('start-record'),hasResult=Boolean(extra&&!extra.hidden);const targetParent=hasResult&&menuBody?menuBody:dock;if(start.parentElement!==targetParent)targetParent.append(start);
 if(start.firstChild?.nodeType===3){const label=hasResult?'新一轮跟读':'开始跟读';if(start.firstChild.textContent!==label)start.firstChild.textContent=label}
 const busy=Boolean(recording||root.dataset.submitting==='true'||root.dataset.pending==='true');
 if(root.dataset.savedActions!==String(hasResult&&!busy))root.dataset.savedActions=String(hasResult&&!busy);
 if(root.dataset.recordBusy!==String(busy))root.dataset.recordBusy=String(busy);
 if(extra&&extra.disabled!==start.disabled)extra.disabled=start.disabled;
 previous=status}
 new MutationObserver(sync).observe(root,{subtree:true,attributes:true,attributeFilter:['class','hidden','disabled','data-pending','data-mutating'],childList:true});document.addEventListener('shadow:session-saved',sync);document.addEventListener('shadow:analysed',()=>{panels[1].classList.remove('locked');show(answersRevealed({graded:panels[1].classList.contains('graded'),skipped:panels[1].classList.contains('skipped')})?'record':'drill')});document.addEventListener('shadow:session-restored',()=>{const restored=root.dataset.activeStep||'listen';sync();show(restored,false)});const initial=root.dataset.activeStep||'listen';sync();show(initial,false);
})();
