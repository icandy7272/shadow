const {test}=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
async function run(where,prelisten=1){
 const source=fs.readFileSync('src/shadow/web/static/app.js','utf8'),a=source.indexOf('  async function recordRound(extra) {'),b=source.indexOf('\n  // 录音只存在这个页面里',a);
 const events=[];
 const helper={};const ui=fs.readFileSync('src/shadow/web/static/ui.js','utf8');vm.runInNewContext(ui.slice(ui.indexOf('function captureAudioSession(')),helper);
 const audioSession={type:'auto'};
 let earClosed=0;
 let active=0;
 let busy=false,stopped=0,closed=0,recorded=0,submitted=0,raised;
 const classes={add(){},remove(){}};const settings={takes:{value:'3'},prelisten:{value:String(prelisten)}};
 const start={disabled:false},stop={hidden:true},redo={hidden:true};
 const pauseButton={hidden:true,setAttribute(){}};
 const speaker={context:{},ready:async()=>{},close(){closed++},play:async()=>{events.push('play');assert.equal(active,0,'reference playback must not hold the microphone');assert.equal(audioSession.type,'playback');if(where==='play'||where==='ear-late-fail')throw Error('playback failed')},beep:async()=>{}};
 const context={takeCount:0,startButton:start,stopButton:stop,redoButton:redo,pauseButton,activeSpeaker:null,activeRecorderControl:null,recordingPaused:false,setPauseAvailable:(on,keepVisible=false)=>{pauseButton.hidden=!(on||keepVisible);pauseButton.disabled=false},setRecording:on=>busy=on,captureAudioSession:helper.captureAudioSession,createSpeaker:()=>{if(where==='speaker')throw Error('no audio context');return speaker},document:{getElementById:id=>settings[id]||{classList:classes,prepend(){}}},navigator:{audioSession,mediaDevices:{getUserMedia:async()=>{active++;events.push('mic');return {getTracks:()=>[{stop(){stopped++;active--}}]}}}},micWanted:()=>({}),status:{classList:classes},fillMics(){},listenTo:async()=>{events.push('ear-start');if(where==='ear-delay'||where==='ear-late-fail')return new Promise(resolve=>setImmediate(()=>{events.push('ear-ready');resolve({close(){earClosed++}})}));events.push('ear-ready');return null;},watchLevel(){},micMeter:null,autoBox:{checked:true},sleep:async()=>{},awake:async()=>{},GAP_MS:100,BEEP_MS:20,minTake:.1,minSpoken:.1,recordOne:async()=>{assert.equal(active,1);assert.equal(audioSession.type,'play-and-record');events.push('record');recorded++;if(where==='recorder'||(where==='partial'&&recorded===2))throw Error('recording failed');return {blob:{},seconds:1,loudest:null}},submit:async blobs=>submitted=blobs.length,el:()=>({})};
 try{await vm.runInNewContext(source.slice(a,b)+'\nrecordRound(false)',context)}catch(e){raised=e}
 assert.equal(audioSession.type,'auto');
 return {earClosed:()=>earClosed,events,busy,stopped,closed,submitted,raised,start,stop,redo};
}
for(const where of ['speaker','play','recorder'])test(`${where} errors unlock controls and close acquired resources`,async()=>{const result=await run(where);assert.equal(result.busy,false);assert.equal(result.start.disabled,false);assert.equal(result.stop.hidden,true);assert.equal(result.redo.hidden,true);assert.equal(result.raised,undefined);assert.equal(result.stopped,where==='speaker'||where==='play'?0:1);assert.equal(result.closed,where==='speaker'?0:1)});
test('clips recorded before a later failure still reach submission',async()=>{const result=await run('partial');assert.equal(result.busy,false);assert.equal(result.submitted,1);assert.equal(result.stopped,2);assert.equal(result.closed,1)});

test('every preview finishes before acquiring the microphone; analyser is ready before recording',async()=>{
 for(const pre of [0,1,2]){
  const result=await run('ear-delay',pre);
  assert.equal(result.raised,undefined);assert.equal(result.submitted,3);
  assert.equal(result.stopped,3);
  const events=result.events;
  for(let i=0;i<events.length;i++)if(events[i]==='record'){
   assert.equal(events[i-1],'ear-ready');
   assert.equal(events[i-2],'ear-start');
   assert.equal(events[i-3],'mic');
  }
 }
});
test('preview failure never acquires the microphone or leaks an analyser',async()=>{
 const result=await run('ear-late-fail',2);
 assert.equal(result.raised,undefined);assert.equal(result.busy,false);
 assert.equal(result.stopped,0);assert.equal(result.closed,1);assert.equal(result.earClosed(),0);
});
