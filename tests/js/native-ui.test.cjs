const test=require('node:test');const assert=require('node:assert/strict');
const {clampNumber,canDismissDrag,finishState}=require('../../src/shadow/web/static/native-ui.js');
test('numeric controls clamp at business bounds',()=>{assert.equal(clampNumber('',1,6,3),3);assert.equal(clampNumber(99,1,6,3),6);assert.equal(clampNumber(-1,0,20,4),0)});
test('sheet drag only accepts deliberate downward grabber movement',()=>{assert.equal(canDismissDrag(95,0,800),true);assert.equal(canDismissDrag(40,2,50),true);assert.equal(canDismissDrag(10,100,20),false);assert.equal(canDismissDrag(-100,0,50),false)});
test('completion requires no active or unsaved recording',()=>{assert.equal(finishState({recording:true,pending:[],analysis:{}}),'recording');assert.equal(finishState({pending:[{}],analysis:{}}),'pending');assert.equal(finishState({pending:[],analysis:{}}),'saved');assert.equal(finishState({pending:[],analysis:null}),'draft')});

test('inflight submission cannot be discarded',()=>assert.equal(finishState({submitting:true,pending:[{}],analysis:{}}),'submitting'));

test('busy control synchronization does not retrigger identical disabled mutations',()=>{const {setDisabledIfChanged}=require('../../src/shadow/web/static/native-ui.js');let value=false,writes=0;const control={get disabled(){return value},set disabled(next){value=next;writes++}};setDisabledIfChanged(control,true);setDisabledIfChanged(control,true);assert.equal(writes,1);setDisabledIfChanged(control,false);assert.equal(writes,2)});

test('all practice phases use one action hierarchy, with destructive stop on primary side',()=>{const {dockActionRole}=require('../../src/shadow/web/static/native-ui.js');for(const id of ['submit-drill','practice-continue','start-record','resubmit','play'])assert.equal(dockActionRole(id,false),'primary');for(const id of ['skip-drill','extra-record','redo-take','pause-take'])assert.equal(dockActionRole(id,true),'secondary');assert.equal(dockActionRole('next-sentence',true),'primary');assert.equal(dockActionRole('next-sentence',false),'secondary');assert.equal(dockActionRole('stop-take',false),'stop')});

test('recording lifecycle overrides saved results and pending clips in the action bar',()=>{const {dockMode}=require('../../src/shadow/web/static/native-ui.js');assert.equal(dockMode({recording:true,stopVisible:true,pending:true,saved:true}),'recording');assert.equal(dockMode({recording:true,stopVisible:false,saved:true}),'prelisten');assert.equal(dockMode({submitting:true,pending:true,saved:true}),'analysing');assert.equal(dockMode({pending:true,saved:true}),'retry');assert.equal(dockMode({saved:true}),'saved');assert.equal(dockMode({}),'ready')});
test('a visible pause button keeps recorder controls in the mobile dock during prelisten',()=>{const {dockMode}=require('../../src/shadow/web/static/native-ui.js');assert.equal(dockMode({recording:true,stopVisible:false,pauseVisible:true}),'recording');assert.equal(dockMode({recording:true,stopVisible:false,pauseVisible:false}),'prelisten')});
test('dock playback proxy keeps the current space shortcut and disabled state',()=>{
 const {syncDockProxy}=require('../../src/shadow/web/static/native-ui.js');
 const classes=new Set();const proxy={hidden:false,disabled:false,innerHTML:'old',classList:{contains:key=>classes.has(key),toggle:(key,want)=>want?classes.add(key):classes.delete(key)}};
 const original={hidden:false,disabled:false,innerHTML:'play <kbd>Space</kbd>',classList:{contains:key=>key==='space-target'}};
 syncDockProxy(original,proxy);assert.equal(classes.has('space-target'),true);assert.equal(proxy.innerHTML,original.innerHTML);
 original.disabled=true;original.classList.contains=()=>false;syncDockProxy(original,proxy);assert.equal(proxy.disabled,true);assert.equal(classes.has('space-target'),false);
});
test('space target marks both original and dock proxy without oscillation',()=>{
 const fs=require('node:fs'),vm=require('node:vm');const source=fs.readFileSync('src/shadow/web/static/app.js','utf8');
 const begin=source.indexOf('  const markSpace = () => {'),end=source.indexOf('\n  };',begin)+5;
 function button(){const values=new Set();return {classList:{contains:k=>values.has(k),toggle:(k,want)=>want?values.add(k):values.delete(k)}}}
 const original=button(),proxy=button(),other=button();proxy._shortcutSource=original;
 vm.runInNewContext(source.slice(begin,end)+';markSpace();markSpace();',{spaceTarget:()=>original,root:{querySelectorAll:()=>[original,proxy,other]}});
 assert.equal(original.classList.contains('space-target'),true);assert.equal(proxy.classList.contains('space-target'),true);assert.equal(other.classList.contains('space-target'),false);
});
test('finish summary hides analysis until dictation reveal',()=>{
 const {practiceSummary}=require('../../src/shadow/web/static/native-ui.js');
 const data={count:3,accuracy:90,issues:['one']};
 assert.deepEqual(practiceSummary(data,false),[[3,'录音遍数']]);
 assert.deepEqual(practiceSummary(data,true),[[3,'录音遍数'],['90%','中位可懂度'],[1,'待改问题']]);
});
