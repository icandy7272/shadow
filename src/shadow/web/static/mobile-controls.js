/* Touch controls reuse the existing form, audio and session state. */
function textScale(value) { const size=Number(value); return [100,125,150,200].includes(size)?size/100:1; }
function selectOption(select, value) {
  const option = [...select.options].find(item => item.value === value && !item.disabled);
  if (select.disabled || !option) return false;
  if (select.value !== value) {
    select.value = value;
    select.dispatchEvent(new Event('change', {bubbles: true}));
  }
  return true;
}
function practicePhase({recording=false, submitting=false, pending=false, saved=false, step='listen'}={}) {
  if (recording) return '正在练习';
  if (step === 'drill') return '默写';
  if (submitting) return '分析中';
  if (pending) return '等待提交';
  if (step === 'record' && saved) return '已保存';
  return {listen:'盲听', drill:'默写', record:saved?'已保存':'录音就绪'}[step] || '已保存';
}
function createAwakeController({request, onError=()=>{}}) {
  let wanted=false, lock=null, pending=null;
  const controller={async update(active) {
    wanted=Boolean(active);
    if (!wanted) {
      const previous=lock; lock=null;
      if (previous) await previous.release().catch(()=>{});
      return;
    }
    if (lock || pending) return pending;
    pending=(async()=>{
      let failed=false;
      try {
        const acquired=await request();
        if (!wanted) await acquired.release().catch(()=>{});
        else {
          lock=acquired;
          acquired.addEventListener?.('release',()=>{if(lock===acquired)lock=null;},{once:true});
        }
      } catch(error) {failed=true;onError(error);}
      finally {pending=null;if(wanted&&!lock&&!failed)await controller.update(true); }
    })();
    return pending;
  }};
  return controller;
}
if (typeof module!=='undefined') module.exports={selectOption,practicePhase,createAwakeController,textScale};
if (typeof document!=='undefined') (()=>{
  const sheets=window.ShadowSheets;
  const textSize=document.getElementById('app-text-size');
  if(textSize){let saved='100';try{saved=localStorage.getItem('shadow.textSize')||'100'}catch(_){}textSize.value=String(textScale(saved)*100);textSize.addEventListener('change',()=>{const scale=textScale(textSize.value);document.documentElement.style.setProperty('--text-scale',String(scale));try{localStorage.setItem('shadow.textSize',String(scale*100))}catch(_){}})}
  function picker({title,choices,current,choose}) {
    const dialog=document.createElement('dialog');
    dialog.className='settings-dialog picker-dialog';dialog.id=`picker-${Date.now()}`;
    const header=document.createElement('div');header.className='sheet-header';
    const heading=document.createElement('h2');heading.textContent=title;heading.id=`${dialog.id}-title`;
    dialog.setAttribute('aria-labelledby',heading.id);
    const close=document.createElement('button');close.type='button';close.textContent='取消';close.dataset.closeDialog='';
    header.append(heading,close);
    const body=document.createElement('div');body.className='sheet-body action-list';body.setAttribute('role','listbox');body.setAttribute('aria-label',title);
    for (const item of choices) {
      const row=document.createElement('button');row.type='button';row.className='grouped-row picker-option';row.disabled=Boolean(item.disabled);
      row.setAttribute('role','option');row.setAttribute('aria-selected',String(item.value===current));
      const label=document.createElement('span');label.textContent=item.label;
      const check=document.createElement('span');check.textContent=item.value===current?'✓':'';check.setAttribute('aria-hidden','true');
      row.append(label,check);row.addEventListener('click',()=>{if(choose(item.value)!==false)sheets.close(dialog)});body.append(row);
    }
    dialog.append(header,body);document.body.append(dialog);
    dialog.addEventListener('close',()=>dialog.remove(),{once:true});sheets.open(dialog);
  }
  for (const [id,title] of [['app-theme','显示模式'],['app-text-size','文字大小'],['mic','麦克风']]) {
    const source=document.getElementById(id);if(!source)continue;
    const button=document.createElement('button');button.type='button';button.className='picker-value';button.setAttribute('aria-haspopup','dialog');source.after(button);source.classList.add('picker-source');
    const refresh=()=>{const label=source.selectedOptions[0]?.textContent||'请选择';if(button.textContent!==`${label} ›`)button.textContent=`${label} ›`;if(button.disabled!==source.disabled)button.disabled=source.disabled;button.setAttribute('aria-label',`${title}：${label}`)};
    source.addEventListener('change',refresh);new MutationObserver(refresh).observe(source,{childList:true,subtree:true,attributes:true});refresh();
    button.addEventListener('click',()=>picker({title,current:source.value,choices:[...source.options].map(option=>({value:option.value,label:option.textContent,disabled:option.disabled})),choose:value=>selectOption(source,value)}));
  }
  function enhanceSpeed(source){
    if(source.classList.contains('picker-source'))return;
    const originals=[...source.querySelectorAll('button')];if(!originals.length)return;
    const button=document.createElement('button');button.type='button';button.className='speed-picker picker-value';button.setAttribute('aria-haspopup','dialog');source.before(button);source.classList.add('picker-source');
    const refresh=()=>{const text=`播放速度 · ${originals.find(item=>item.classList.contains('chosen'))?.textContent||'原速'} ›`;if(button.textContent!==text)button.textContent=text};refresh();new MutationObserver(refresh).observe(source,{attributes:true,subtree:true,attributeFilter:['class']});
    button.addEventListener('click',()=>picker({title:'播放速度',current:String(originals.findIndex(item=>item.classList.contains('chosen'))),choices:originals.map((item,index)=>({value:String(index),label:item.textContent})),choose:value=>{originals[Number(value)]?.click();return true}}));
  }
  const enhanceSpeeds=()=>document.querySelectorAll('.speeds').forEach(enhanceSpeed);enhanceSpeeds();new MutationObserver(enhanceSpeeds).observe(document.body,{childList:true,subtree:true});
  for (const [id,selector,noun] of [['library-search','#cards .card','份素材'],['vocab-search','#vocab .vocab-item','个生词']]) {
    const input=document.getElementById(id);if(!input)continue;
    const note=document.createElement('p');note.className='search-summary';note.setAttribute('role','status');input.closest('.app-search').after(note);
    const refresh=()=>{const all=[...document.querySelectorAll(selector)],shown=all.filter(item=>!item.hidden).length;const text=input.value.trim()?(shown?`找到 ${shown} ${noun}`:'没有匹配结果，试试其他关键词。'):`共 ${all.length} ${noun}`;if(note.textContent!==text)note.textContent=text};input.addEventListener('input',()=>queueMicrotask(refresh));
    const list=document.querySelector(id==='library-search'?'#cards':'#vocab');if(list)new MutationObserver(refresh).observe(list,{childList:true,subtree:true,attributes:true,attributeFilter:['hidden']});refresh();
  }
  document.querySelectorAll('.filters').forEach(strip=>{
    const reveal=()=>{const selected=strip.querySelector('.chosen');if(!selected)return;const box=selected.getBoundingClientRect(),parent=strip.getBoundingClientRect();if(box.left<parent.left)strip.scrollLeft-=parent.left-box.left+8;else if(box.right>parent.right)strip.scrollLeft+=box.right-parent.right+8;};
    new MutationObserver(reveal).observe(strip,{subtree:true,attributes:true,attributeFilter:['class']});reveal();
  });
  const root=document.getElementById('practice');
  const awakeInput=document.getElementById('keep-screen-awake');let enabled=false;
  try {enabled=localStorage.getItem('shadow.keep-awake')==='1'} catch(_) {}
  if(awakeInput){awakeInput.checked=enabled;awakeInput.disabled=!navigator.wakeLock;const note=document.getElementById('keep-awake-note');if(!navigator.wakeLock&&note)note.textContent='这个浏览器不支持保持亮屏，练习仍可正常使用。';awakeInput.addEventListener('change',()=>{enabled=awakeInput.checked;try{localStorage.setItem('shadow.keep-awake',enabled?'1':'0')}catch(_){}updateAwake()});}
  const awake=navigator.wakeLock?createAwakeController({request:()=>navigator.wakeLock.request('screen'),onError:()=>{const note=document.getElementById('keep-awake-note');if(note)note.textContent='系统暂时不允许保持亮屏，练习仍可正常使用。'}}):null;
  function updateAwake(){awake?.update(Boolean(root&&enabled&&document.visibilityState==='visible'));}
  document.addEventListener('visibilitychange',updateAwake);window.addEventListener('pagehide',()=>awake?.update(false));updateAwake();
  if(!root)return;
  const dock=document.getElementById('practice-dock'),state=document.createElement('div');state.className='dock-state';
  const phase=document.createElement('span');phase.className='dock-phase';const status=document.getElementById('rec-status'),bar=document.getElementById('rec-progress');state.append(phase);if(status)state.append(status);if(bar)state.append(bar);dock.prepend(state);
  const sync=()=>{
    const step=root.dataset.activeStep||'listen';const label=practicePhase({step,recording:window.ShadowSession?.isRecording(),submitting:root.dataset.submitting==='true',pending:root.dataset.pending==='true',saved:Boolean(window.ShadowSession?.capture()?.analysis)});
    if(phase.textContent!==label)phase.textContent=label;
    if(state.classList.contains('is-record')!==(step==='record'))state.classList.toggle('is-record',step==='record');
    if(status&&status.hidden!==(step!=='record'))status.hidden=step!=='record';if(bar&&bar.classList.contains('dock-progress-inactive')!==(step!=='record'))bar.classList.toggle('dock-progress-inactive',step!=='record');
    for(const tab of document.querySelectorAll('[data-practice-step]')){const panel=document.getElementById(`step-${tab.dataset.practiceStep}`),done=panel.classList.contains('complete')||panel.classList.contains('skipped');if(tab.dataset.complete!==String(done))tab.dataset.complete=String(done);const stateLabel=panel.classList.contains('skipped')?'已跳过':done?'已完成':panel.classList.contains('locked')?'未解锁':tab.getAttribute('aria-selected')==='true'?'当前步骤':'可回看';const label=`${tab.textContent.trim()}，${stateLabel}`;if(tab.getAttribute('aria-label')!==label)tab.setAttribute('aria-label',label);}
  };
  new MutationObserver(sync).observe(root,{subtree:true,attributes:true,attributeFilter:['class','data-active-step','data-pending','data-submitting','disabled'],childList:true});document.addEventListener('shadow:session-restored',sync);document.addEventListener('shadow:session-saved',sync);sync();
})();
