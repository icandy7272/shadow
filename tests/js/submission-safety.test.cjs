const {test}=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
function result(){return {run_id:4,count:3,accuracy:90,speech:1,pause:null,rejected:[],skipped:[],issues:[],good:[],view:{takes:[{},{},{}],chosen:0}};}
function setup(fetch){
 const source=fs.readFileSync('src/shadow/web/static/app.js','utf8'),a=source.indexOf('  function lost(count)'),b=source.indexOf('  function showResult(',a);
 const classes={add(){},remove(){},contains(){return false}};
 const context={root:{dataset:{}},pending:null,resubmitButton:{hidden:true},startButton:{},status:{},bar:{classList:classes},fill:{style:{}},FormData:class{append(){}},segment:1,unit:1,sawText:false,extraMode:false,latestRun:null,runId:4,submissionId:null,fetch,service:{check(){}},readEvents:async()=>({result:result()}),micNote:null,markComplete(){},stopLoops(){},resultFigures:[],extraButton:{},setLabel(){},showResult(){},window:{matchMedia:()=>({matches:true})},CustomEvent:class{},document:{getElementById:()=>({scrollIntoView(){}}),dispatchEvent(){}}};
 vm.runInNewContext(source.slice(a,b),context);return context;
}
test('waiting upload and failed connection keep pending audio available for retry',async()=>{let reject;const c=setup(()=>new Promise((_,r)=>reject=r)),audio=[{}];const submitted=c.submit(audio);assert.equal(c.root.dataset.pending,'true');reject(new Error('offline'));await submitted;assert.equal(c.pending,audio);assert.equal(c.root.dataset.pending,'true');assert.equal(c.resubmitButton.hidden,false)});
test('server 500 preserves audio for retry rather than discarding it',async()=>{const c=setup(async()=>({ok:false,status:500,json:async()=>({detail:'temporary failure'})})),audio=[{}];await c.submit(audio);assert.equal(c.pending,audio);assert.equal(c.root.dataset.pending,'true');assert.equal(c.resubmitButton.hidden,false)});
test('invalid silent audio releases protection so another recording can start',async()=>{const c=setup(async()=>({ok:false,status:422,json:async()=>({detail:'silent'})}));await c.submit([{}]);assert.equal(c.pending,null);assert.equal(c.root.dataset.pending,'false')});
test('successful save releases navigation protection',async()=>{const c=setup(async()=>({ok:true}));await c.submit([{}]);assert.equal(c.pending,null);assert.equal(c.root.dataset.pending,'false')});
test('a stream that ends without a result preserves audio for retry',async()=>{const c=setup(async()=>({ok:true}));c.readEvents=async()=>undefined;const audio=[{}];await c.submit(audio);assert.equal(c.pending,audio);assert.equal(c.root.dataset.pending,'true')});
test('retryable analysis errors preserve audio until a later successful retry',async()=>{const c=setup(async()=>({ok:true}));c.readEvents=async()=>({error:'temporary analysis failure',retryable:true});const audio=[{}];await c.submit(audio);assert.equal(c.pending,audio);c.readEvents=async()=>({result:result()});await c.submit(audio);assert.equal(c.pending,null);assert.equal(c.root.dataset.pending,'false')});

test('incomplete terminal result retains audio rather than unlocking and crashing',async()=>{const c=setup(async()=>({ok:true}));c.readEvents=async()=>({result:{}});const audio=[{}];await c.submit(audio);assert.equal(c.pending,audio);assert.equal(c.root.dataset.pending,'true');assert.equal(c.resubmitButton.hidden,false)});
test('unexpected result rendering failure also keeps retry recovery',async()=>{const c=setup(async()=>({ok:true}));c.showResult=()=>{throw new Error('missing graph data')};const audio=[{}];await c.submit(audio);assert.equal(c.pending,audio);assert.equal(c.root.dataset.pending,'true');assert.equal(c.resubmitButton.hidden,false)});
test('active submission stays protected through fetch and releases on failed response',async()=>{let reject;const c=setup(()=>new Promise((_,r)=>reject=r));const submitted=c.submit([{}]);assert.equal(c.root.dataset.submitting,'true');reject(Error('offline'));await submitted;assert.equal(c.root.dataset.submitting,'false')});

test('expired authentication and refused origin retain every clip for retry',async()=>{for(const status of [401,403]){const c=setup(async()=>({ok:false,status,json:async()=>({detail:'sign in'})})),audio=[{},{}];await c.submit(audio);assert.equal(c.pending,audio);assert.equal(c.root.dataset.pending,'true');assert.equal(c.resubmitButton.hidden,false)}});

test('saved blind shadowing retains its round for the following dictation',async()=>{
 const c=setup(async()=>({ok:true}));let completed=0,advanced=0;
 c.markComplete=()=>completed++;c.document.dispatchEvent=()=>advanced++;
 await c.submit([{}]);
 assert.equal(c.runId,4);assert.equal(completed,1);assert.equal(advanced,2);
 assert.notEqual(c.root.dataset.answersRevealed,'true');
});
test('failed shadowing never completes or advances to dictation',async()=>{
 const c=setup(async()=>({ok:false,status:500}));let completed=0,advanced=0;
 c.markComplete=()=>completed++;c.document.dispatchEvent=e=>{if(e.type==='shadow:analysed')advanced++};
 await c.submit([{}]);assert.equal(completed,0);assert.equal(advanced,0);
});

test('durably saved recording unlocks dictation while analysis is still pending',async()=>{
 let finish;const c=setup(()=>new Promise(resolve=>finish=resolve));c.runId=4;const events=[];
 c.document.dispatchEvent=e=>events.push(e.type);
 c.CustomEvent=class{constructor(type){this.type=type}};
 const task=c.submit([{}]);
 assert.ok(events.includes('shadow:recorded'));assert.equal(c.root.dataset.submitting,'true');
 assert.equal(c.root.dataset.analysisReady,undefined);
 finish({ok:true});await task;
});
test('analysis completion does not stop dictation playback or scroll the page',async()=>{
 const c=setup(async()=>({ok:true}));let stopped=0,scrolled=0;
 c.stopLoops=()=>stopped++;c.document.getElementById=()=>({scrollIntoView(){scrolled++}});
 await c.submit([{}]);assert.equal(stopped,0);assert.equal(scrolled,0);
});
test('failed local audio save waits for server success before opening dictation',async()=>{
 let finish;const c=setup(()=>new Promise(resolve=>finish=resolve)),events=[];
 c.window.ShadowSession={saveCurrent:async()=>{throw Error('storage full')}};
 c.CustomEvent=class{constructor(type){this.type=type}};c.document.dispatchEvent=e=>events.push(e.type);
 const task=c.submit([{}]);await new Promise(resolve=>setImmediate(resolve));
 assert.equal(events.includes('shadow:recorded'),false);
 finish({ok:true});await task;assert.equal(events.includes('shadow:recorded'),true);
});
