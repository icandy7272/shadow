const {test}=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
async function run(where){
 const source=fs.readFileSync('src/shadow/web/static/app.js','utf8'),a=source.indexOf('  async function recordRound(extra) {'),b=source.indexOf('\n  // 录音只存在这个页面里',a);
 let busy=false,stopped=0,closed=0,recorded=0,submitted=0,raised;
 const classes={add(){},remove(){}};const settings={takes:{value:'3'},prelisten:{value:'1'}};
 const start={disabled:false},stop={hidden:true},redo={hidden:true};
 const speaker={context:{},ready:async()=>{},close(){closed++},play:async()=>{if(where==='play')throw Error('playback failed')},beep:async()=>{}};
 const context={takeCount:0,startButton:start,stopButton:stop,redoButton:redo,setRecording:on=>busy=on,createSpeaker:()=>{if(where==='speaker')throw Error('no audio context');return speaker},document:{getElementById:id=>settings[id]||{classList:classes,prepend(){}}},navigator:{mediaDevices:{getUserMedia:async()=>({getTracks:()=>[{stop(){stopped++}}]})}},micWanted:()=>({}),status:{classList:classes},fillMics(){},listenTo:async()=>null,watchLevel(){},micMeter:null,autoBox:{checked:true},sleep:async()=>{},awake:async()=>{},GAP_MS:100,BEEP_MS:20,minTake:.1,minSpoken:.1,recordOne:async()=>{recorded++;if(where==='recorder'||(where==='partial'&&recorded===2))throw Error('recording failed');return {blob:{},seconds:1,loudest:null}},submit:async blobs=>submitted=blobs.length,el:()=>({})};
 try{await vm.runInNewContext(source.slice(a,b)+'\nrecordRound(false)',context)}catch(e){raised=e}
 return {busy,stopped,closed,submitted,raised,start,stop,redo};
}
for(const where of ['speaker','play','recorder'])test(`${where} errors unlock controls and close acquired resources`,async()=>{const result=await run(where);assert.equal(result.busy,false);assert.equal(result.start.disabled,false);assert.equal(result.stop.hidden,true);assert.equal(result.redo.hidden,true);assert.equal(result.raised,undefined);assert.equal(result.stopped,where==='speaker'?0:1);assert.equal(result.closed,where==='speaker'?0:1)});
test('clips recorded before a later failure still reach submission',async()=>{const result=await run('partial');assert.equal(result.busy,false);assert.equal(result.submitted,1);assert.equal(result.stopped,1);assert.equal(result.closed,1)});
