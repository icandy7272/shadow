/* UI only: existing recorder and API remain responsible for data. */
function nextPracticeStep(active,status){
  if(active==='listen'&&status.listen&&status.skipped)return 'record';
  if(active==='listen'&&status.listen&&!status.drill)return 'drill';
  if(active==='drill'&&status.skipped)return 'record';
  return active;
}
function focusPracticeStep(step, desktop, controls) {
  if (!desktop) return;
  if (step === 'drill') controls.typed?.focus({ preventScroll: true });
  if (step === 'record') controls.start?.focus({ preventScroll: true });
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

if(typeof module!=='undefined')module.exports={nextPracticeStep,focusPracticeStep,guardPracticeNavigation};
if(typeof document!=='undefined')(()=>{
 const theme=document.getElementById('app-theme');
 if(theme){theme.value=document.documentElement.dataset.theme||'system';theme.addEventListener('change',()=>{if(theme.value==='system')delete document.documentElement.dataset.theme;else document.documentElement.dataset.theme=theme.value;try{localStorage.setItem('shadow.theme',theme.value)}catch(_){}})}
 document.addEventListener('click',event=>{const open=event.target.closest('[data-open-dialog]');if(open)document.getElementById(open.dataset.openDialog)?.showModal();const close=event.target.closest('[data-close-dialog]');if(close)close.closest('dialog')?.close()});
 document.querySelectorAll('dialog').forEach(dialog=>dialog.addEventListener('click',event=>{if(event.target===dialog)dialog.close()}));
 document.addEventListener('keydown',event=>{if(document.querySelector('dialog[open]'))event.stopImmediatePropagation()},true);
 const viewport=window.visualViewport;if(viewport){const resize=()=>{const inset=Math.max(0,window.innerHeight-viewport.height-viewport.offsetTop);document.documentElement.style.setProperty('--keyboard-inset',`${inset}px`);document.body.classList.toggle('keyboard-open',inset>100)};viewport.addEventListener('resize',resize);viewport.addEventListener('scroll',resize);resize()}
 for(const [id,selector] of [['library-search','#cards .card'],['vocab-search','#vocab .vocab-item']]){const input=document.getElementById(id);input?.addEventListener('input',()=>{const query=input.value.trim().toLocaleLowerCase();document.querySelectorAll(selector).forEach(card=>card.hidden=!card.textContent.toLocaleLowerCase().includes(query))})}
 const root=document.getElementById('practice');if(!root)return;
 const ids=['listen','drill','record'],panels=ids.map(id=>document.getElementById(`step-${id}`)),tabs=[...document.querySelectorAll('[data-practice-step]')];let active='listen';
 const dock=document.getElementById('practice-dock'),next=document.getElementById('practice-continue'),more=document.getElementById('rec-more'),settings=document.getElementById('record-settings');
 const isBusy=()=>recording||root.dataset.pending==='true';
 const navigationNote=document.createElement('p');navigationNote.className='hint navigation-note';navigationNote.setAttribute('role','status');navigationNote.hidden=true;dock.append(navigationNote);
 guardPracticeNavigation(document,window,isBusy,()=>{navigationNote.textContent='录音还没有保存。请先完成录音或重新提交，再离开这句。';navigationNote.hidden=false});
 const pager=root.querySelector('.pager'),nextSentence=pager?.querySelector('a.next'),dockPager=document.createElement('nav');dockPager.className='pager dock-pager';if(nextSentence)dock.append(dockPager);
 const recSettings=more?.querySelector('.rec-settings');if(settings&&recSettings)settings.querySelector('.sheet-body').append(recSettings);
 more?.querySelector('summary')?.addEventListener('click',event=>{event.preventDefault();settings.showModal()});
 for(const id of ['start-record','extra-record','stop-take','redo-take','resubmit']){const control=document.getElementById(id);if(control)dock.append(control)}
 function show(id,scroll=true){if(!ids.includes(id)||document.getElementById(`step-${id}`).classList.contains('locked'))return;active=id;root.dataset.activeStep=id;if(nextSentence){const target=id==='record'?dockPager:pager;if(nextSentence.parentElement!==target)target.append(nextSentence)}panels.forEach((panel,index)=>{if(panel.hidden!==(ids[index]!==id))panel.hidden=ids[index]!==id});tabs.forEach(tab=>tab.setAttribute('aria-selected',String(tab.dataset.practiceStep===id)));if(dock.hidden!==(id!=='record'))dock.hidden=id!=='record';if(id==='drill'&&!panels[1].classList.contains('graded')&&!panels[1].classList.contains('done'))focusPracticeStep(id,window.matchMedia('(hover: hover)').matches,{typed:document.getElementById('dictation-text')});if(scroll)root.scrollIntoView({block:'start',behavior:window.matchMedia('(prefers-reduced-motion: reduce)').matches?'auto':'smooth'})}
 document.addEventListener('keydown',event=>{if(event.metaKey||event.ctrlKey||event.altKey||event.repeat||event.target.closest('input,textarea,select,[contenteditable]'))return;if(/^[rnt]$/i.test(physicalKey(event))&&!panels[2].classList.contains('locked')&&!document.querySelector('dialog[open]'))show('record',false)},true);
 tabs.forEach(tab=>tab.addEventListener('click',()=>{stopLoops();show(tab.dataset.practiceStep)}));next.addEventListener('click',()=>show('record'));
 const micFeedback=document.createElement('p');micFeedback.className='hint';micFeedback.setAttribute('role','status');settings.querySelector('.sheet-body').append(micFeedback);
 const updateMicFeedback=()=>{micFeedback.textContent=[document.getElementById('rec-status')?.textContent,document.getElementById('mic-note')?.textContent].filter(Boolean).join(' · ')};
 const micObserver=new MutationObserver(updateMicFeedback);for(const id of ['rec-status','mic-note']){const el=document.getElementById(id);if(el)micObserver.observe(el,{childList:true,characterData:true,subtree:true})}
 let previous={listen:false,drill:false,skipped:false};
 function sync(){const status={listen:panels[0].classList.contains('complete'),drill:!panels[2].classList.contains('locked'),skipped:panels[1].classList.contains('skipped')};for(const tab of tabs){const locked=document.getElementById(`step-${tab.dataset.practiceStep}`).classList.contains('locked'),busy=isBusy();if(tab.disabled!==(locked||busy))tab.disabled=locked||busy}if(next.hidden!==!status.drill)next.hidden=!status.drill;let target=active;if(status.listen!==previous.listen||status.skipped!==previous.skipped)target=nextPracticeStep(active,status);if(typeof recording!=='undefined'&&recording)target='record';if(target!==active)show(target);if(dockPager.inert!==isBusy())dockPager.inert=isBusy();if(!isBusy()&&!navigationNote.hidden)navigationNote.hidden=true;const extra=document.getElementById('extra-record'),start=document.getElementById('start-record'),hasResult=Boolean(extra&&!extra.hidden);if(start.classList.contains('secondary-action')!==hasResult)start.classList.toggle('secondary-action',hasResult);previous=status}
 new MutationObserver(sync).observe(root,{subtree:true,attributes:true,attributeFilter:['class','hidden','disabled','data-pending'],childList:true});document.addEventListener('shadow:analysed',()=>show('record'));show('listen',false);sync();
})();
