const {test}=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
function simulate({speechMs=3000,volume=.08,auto=true,pauseMs=0,leadMs=0,noise=.001}){
 const source=fs.readFileSync('src/shadow/web/static/app.js','utf8');
 const constants=source.slice(source.indexOf('  const HUSH_MS ='),source.indexOf('  // iOS needs'));
 const begin=source.indexOf('  const recordOne ='),end=source.indexOf('  // 服务端按音频时长',begin);
 let now=0,tick,stopped=false;
 class Recorder{constructor(){this.state='inactive';this.events={}}addEventListener(n,f){this.events[n]=f}start(){this.state='recording'}stop(){this.state='inactive';stopped=true;this.events.stop()}}
 const context={MediaRecorder:Recorder,Blob,performance:{now:()=>now},stopButton:{},redoButton:{},loudestOf:()=>null,levelDb:()=>-40,minTake:1.3,minTotal:7800,setInterval(fn){tick=fn;return 1},clearInterval(){}};
 const ear={noiseFloor:noise,level:()=>now>=leadMs&&now<leadMs+speechMs?(pauseMs&&now>1000&&now<1000+pauseMs?noise:volume):noise};
 vm.runInNewContext(constants+source.slice(begin,end)+';recordOne({},ear,3000,auto)',{...context,ear,auto});
 while(now<30000&&!stopped){now+=50;tick()}
 return {stopped,now};
}
for(const config of [{speechMs:3000},{speechMs:1200},{speechMs:4000,volume:.004},{speechMs:4000},{leadMs:500,speechMs:4000,volume:.008,noise:.004}])test(`speech followed by silence stops: ${JSON.stringify(config)}`,()=>{
 const result=simulate(config);assert.equal(result.stopped,true);assert.ok(result.now>=7800&&result.now<15000);
});
test('manual mode never auto-stops',()=>assert.equal(simulate({auto:false}).stopped,false));
test('short hesitation does not stop before reference minimum duration',()=>assert.ok(simulate({speechMs:5000,pauseMs:2300}).now>=7800));

test('room noise without speech never counts as a finished attempt',()=>assert.equal(simulate({speechMs:0,noise:.004}).stopped,false));
