const {test}=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
async function run(where,prelisten=1){
 const source=fs.readFileSync('src/shadow/web/static/app.js','utf8'),a=source.indexOf('  async function recordRound(extra) {'),b=source.indexOf('\n  // 录音只存在这个页面里',a);
 const events=[];
 let earClosed=0;
 let busy=false,stopped=0,closed=0,recorded=0,submitted=0,raised;
 const classes={add(){},remove(){}};const settings={takes:{value:'3'},prelisten:{value:String(prelisten)}};
 const start={disabled:false},stop={hidden:true},redo={hidden:true};
 const speaker={context:{},ready:async()=>{},close(){closed++},play:async()=>{events.push('play');if(where==='play'||where==='ear-late-fail')throw Error('playback failed')},beep:async()=>{}};
 const context={takeCount:0,startButton:start,stopButton:stop,redoButton:redo,setRecording:on=>busy=on,captureAudioSession:()=>()=>{},createSpeaker:()=>{if(where==='speaker')throw Error('no audio context');return speaker},document:{getElementById:id=>settings[id]||{classList:classes,prepend(){}}},navigator:{mediaDevices:{getUserMedia:async()=>({getTracks:()=>[{stop(){stopped++}}]})}},micWanted:()=>({}),status:{classList:classes},fillMics(){},listenTo:async()=>{events.push('ear-start');if(where==='ear-delay'||where==='ear-late-fail')return new Promise(resolve=>setImmediate(()=>{events.push('ear-ready');resolve({close(){earClosed++}})}));events.push('ear-ready');return null;},watchLevel(){},micMeter:null,autoBox:{checked:true},sleep:async()=>{},awake:async()=>{},GAP_MS:100,BEEP_MS:20,minTake:.1,minSpoken:.1,recordOne:async()=>{recorded++;if(where==='recorder'||(where==='partial'&&recorded===2))throw Error('recording failed');return {blob:{},seconds:1,loudest:null}},submit:async blobs=>submitted=blobs.length,el:()=>({})};
 try{await vm.runInNewContext(source.slice(a,b)+'\nrecordRound(false)',context)}catch(e){raised=e}
 return {earClosed:()=>earClosed,events,busy,stopped,closed,submitted,raised,start,stop,redo};
}
for(const where of ['speaker','play','recorder'])test(`${where} errors unlock controls and close acquired resources`,async()=>{const result=await run(where);assert.equal(result.busy,false);assert.equal(result.start.disabled,false);assert.equal(result.stop.hidden,true);assert.equal(result.redo.hidden,true);assert.equal(result.raised,undefined);assert.equal(result.stopped,where==='speaker'?0:1);assert.equal(result.closed,where==='speaker'?0:1)});
test('clips recorded before a later failure still reach submission',async()=>{const result=await run('partial');assert.equal(result.busy,false);assert.equal(result.submitted,1);assert.equal(result.stopped,1);assert.equal(result.closed,1)});

test('multi-preview starts audio while the level analyser prepares, but final preview waits',async()=>{
 const {events}=await run('ear-delay',2);
 const first=events.indexOf('play'),ready=events.indexOf('ear-ready');
 assert.ok(first<ready,events.join(','));
 assert.ok(events.indexOf('play',first+1)>ready,events.join(','));
});

test('single or zero preview retains analyser readiness before the recording cue',async()=>{
 for(const pre of [0,1]){const result=await run('ear-delay',pre);assert.equal(result.raised,undefined);assert.ok(result.events.includes('ear-ready'));if(pre===1)assert.ok(result.events.indexOf('ear-ready')<result.events.indexOf('play'));}
});

test('a late analyser is released when the first preview fails',async()=>{
 const result=await run('ear-late-fail',2);
 await new Promise(resolve=>setImmediate(resolve));
 assert.equal(result.raised,undefined);assert.equal(result.busy,false);assert.equal(result.stopped,1);assert.equal(result.closed,1);assert.equal(result.earClosed(),1);
});
