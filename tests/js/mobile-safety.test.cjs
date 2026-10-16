const {test}=require('node:test');const assert=require('node:assert/strict');
const {focusPracticeStep,guardPracticeNavigation}=require('../../src/shadow/web/static/mobile.js');
test('desktop activates the dictation input, touch devices keep keyboard closed',()=>{let focused=0;const controls={typed:{focus(){focused++}}};focusPracticeStep('drill',true,controls);assert.equal(focused,1);focusPracticeStep('drill',false,controls);assert.equal(focused,1)});
function harness(){const docEvents={},windowEvents={};let busy=true,notice=0;guardPracticeNavigation({addEventListener:(n,f)=>docEvents[n]=f},{addEventListener:(n,f)=>windowEvents[n]=f},()=>busy,()=>notice++);return {docEvents,windowEvents,setBusy:v=>busy=v,notices:()=>notice};}
function event(target){return {target,prevented:false,stopped:false,preventDefault(){this.prevented=true},stopImmediatePropagation(){this.stopped=true}};}
test('active or pending recordings protect previous, next, header and retirement actions',()=>{const h=harness();for(const action of ['a[href]','#retire','#unretire']){const e=event({closest:selector=>selector.includes(action)?{}:null});h.docEvents.click(e);assert.equal(e.prevented,true);assert.equal(e.stopped,true)}h.setBusy(false);const e=event({closest:()=>({})});h.docEvents.click(e);assert.equal(e.prevented,false)});
test('navigation keys are protected but typing arrows remain normal',()=>{const h=harness();for(const key of ['ArrowRight','ArrowLeft','k']){const e=event({closest:()=>null});e.key=key;h.docEvents.keydown(e);assert.equal(e.prevented,true)}const typing=event({closest:()=>({})});typing.key='ArrowLeft';h.docEvents.keydown(typing);assert.equal(typing.prevented,false)});
test('refresh or closing a page warns until pending audio is saved',()=>{const h=harness();const e=event({});h.windowEvents.beforeunload(e);assert.equal(e.prevented,true);h.setBusy(false);const done=event({});h.windowEvents.beforeunload(done);assert.equal(done.prevented,false)});

test('rubber-band scrolling and browser zoom never look like a software keyboard',()=>{const {keyboardInset}=require('../../src/shadow/web/static/mobile.js');assert.equal(keyboardInset({innerHeight:844,viewportHeight:844,offsetTop:-280,editing:false,scale:1}),0);assert.equal(keyboardInset({innerHeight:844,viewportHeight:700,offsetTop:-200,editing:false,scale:1}),0);assert.equal(keyboardInset({innerHeight:844,viewportHeight:420,offsetTop:0,editing:true,scale:2}),0);assert.equal(keyboardInset({innerHeight:844,viewportHeight:510,offsetTop:0,editing:true,scale:1}),334);assert.equal(keyboardInset({innerHeight:844,viewportHeight:800,offsetTop:0,editing:true,scale:1}),0)});
test('every actual step transition stops playback before hiding the old panel',()=>{
 const fs=require('node:fs'),vm=require('node:vm');const source=fs.readFileSync('src/shadow/web/static/mobile.js','utf8');
 const begin=source.indexOf(' function show('),end=source.indexOf('\n document.addEventListener',begin);
 for(const initial of ['listen','drill','record'])for(const target of ['listen','drill','record']){
  const calls=[],ids=['listen','drill','record'];const panels=ids.map(()=>({hidden:false,classList:{contains:()=>false}}));
  const context={ids,panels,active:initial,root:{dataset:{},scrollIntoView(){}},nextSentence:null,tabs:[],dock:{hidden:false},
   document:{getElementById:id=>panels[ids.indexOf(id.replace('step-',''))]},stopLoops:()=>calls.push('stop'),window:{matchMedia:()=>({matches:false})},focusPracticeStep:()=>{}};
  vm.runInNewContext(source.slice(begin,end)+`;show('${target}',false);`,context);
  assert.equal(calls.length,initial===target?0:1,`${initial} to ${target}`);assert.equal(context.root.dataset.activeStep,target);
 }
});
