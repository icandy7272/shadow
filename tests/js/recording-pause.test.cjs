const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');

const source=fs.readFileSync('src/shadow/web/static/app.js','utf8');
const begin=source.indexOf('  const recordOne =');
const end=source.indexOf('  // 服务端按音频时长',begin);

test('the pause button remains visible and enabled between active audio segments',()=>{
 const beginSetter=source.indexOf('  const setPauseAvailable =');
 const endSetter=source.indexOf('\n  };',beginSetter)+5;
 const button={hidden:true,disabled:false,textContent:'暂停',setAttribute(){}};
 const context={pauseButton:button,recordingPaused:false};
 const setAvailable=vm.runInNewContext(source.slice(beginSetter,endSetter)+'\nsetPauseAvailable',context);
 setAvailable(false,true);
 assert.equal(button.hidden,false);assert.equal(button.disabled,false);
 setAvailable(true,true);
 assert.equal(button.hidden,false);assert.equal(button.disabled,false);
 setAvailable(false);
 assert.equal(button.hidden,true);assert.equal(button.disabled,false);
});

test('pausing a take freezes its recorded duration and exposes resume control',async()=>{
 let now=1000,control,stopHandler;
 class Recorder {
  constructor(){this.state='inactive';this.listeners={}}
  addEventListener(name,fn){this.listeners[name]=fn}
  start(){this.state='recording'}
  pause(){this.state='paused'}
  resume(){this.state='recording'}
  stop(){this.state='inactive';this.listeners.stop()}
 }
 const context={MediaRecorder:Recorder,Blob,performance:{now:()=>now},stopButton:{},redoButton:{},
  onControl:value=>control=value,
  loudestOf:()=>null,WATCH_MS:50,FLOOR_CAP:.01,setInterval:()=>1,clearInterval(){}};
 const record=vm.runInNewContext(source.slice(begin,end)+
  '\nrecordOne({},null,0,false,onControl)',context);
 await Promise.resolve();
 assert.equal(typeof control.pause,'function');
 assert.equal(typeof control.resume,'function');
 control.pause();now+=5000;control.resume();now+=1200;
 context.stopButton.onclick();
 const clip=await record;
 assert.equal(clip.seconds,1.2);
});

test('the recorder pause control can pause reference playback too',()=>{
 const markup=fs.readFileSync('src/shadow/web/templates/practice.html','utf8');
 assert.match(markup,/<button[^>]*id="pause-take"[^>]*aria-keyshortcuts="P"[^>]*hidden[^>]*>暂停<kbd[^>]*aria-hidden="true"[^>]*>P<\/kbd><\/button>/);
});

test('the pause button pauses and resumes both the speaker and microphone',()=>{
 const button={hidden:false,textContent:'暂停',attrs:{},listeners:{},setAttribute(k,v){this.attrs[k]=v},
  addEventListener(k,fn){this.listeners[k]=fn}};
 const speaker=[],recorder=[];const status={textContent:'录音中',classList:{live:true,
  contains(name){return name==='live'&&this.live},add(name){if(name==='live')this.live=true},
  remove(name){if(name==='live')this.live=false}}};const meter={hidden:false};
 const context={pauseButton:button,recordingPaused:false,pauseStatus:'',pauseMeterHidden:true,pauseWasLive:false,
  activeSpeaker:{pause(){speaker.push('pause')},resume(){speaker.push('resume')}},
  activeRecorderControl:{pause(){recorder.push('pause')},resume(){recorder.push('resume')}},status,micMeter:meter};
 const start=source.indexOf('  pauseButton.addEventListener("click"');
 const end=source.indexOf('\n  });',start)+6;
 vm.runInNewContext(source.slice(start,end),context);
 button.listeners.click();assert.deepEqual(speaker,['pause']);assert.deepEqual(recorder,['pause']);
 assert.equal(button.textContent,'继续');assert.equal(meter.hidden,true);assert.equal(status.classList.live,false);
 button.listeners.click();assert.deepEqual(speaker,['pause','resume']);assert.deepEqual(recorder,['pause','resume']);
 assert.equal(button.textContent,'暂停');assert.equal(meter.hidden,false);assert.equal(status.textContent,'录音中');
 assert.equal(status.classList.live,true);
});

test('outside recording the pause control stops only the current speaker sound',()=>{
 const button={hidden:false,textContent:'暂停',attrs:{},listeners:{},setAttribute(k,v){this.attrs[k]=v},
  addEventListener(k,fn){this.listeners[k]=fn}};let stopped=0;
 const context={pauseButton:button,recordingPaused:false,pauseStatus:'',pauseMeterHidden:true,pauseWasLive:false,
  activeSpeaker:{stopCurrent(){stopped++;return true}},activeRecorderControl:null,
  status:{textContent:'正在播放原声',classList:{contains:()=>false,add(){},remove(){}}},micMeter:{hidden:true}};
 const start=source.indexOf('  pauseButton.addEventListener("click"');
 const end=source.indexOf('\n  });',start)+6;
 vm.runInNewContext(source.slice(start,end),context);
 button.listeners.click();
 assert.equal(stopped,1);assert.equal(context.recordingPaused,false);
 assert.equal(button.textContent,'暂停');assert.equal(button.attrs['aria-pressed'],undefined);
});

test('stopping a preview sound resolves that segment so the round can continue',async()=>{
 const speakerStart=source.indexOf('  function createSpeaker()');
 const speakerEnd=source.indexOf('\n  // iOS needs the capture analyser',speakerStart);
 let audioSource;
 class FakeAudioSource {
  constructor(){this.listeners={};this.stopped=0;this.buffer=null}
  connect(){}
  addEventListener(name,fn){this.listeners[name]=fn}
  start(){}
  stop(){this.stopped++;this.listeners.ended?.()}
 }
 class FakeAudioContext {
  constructor(){this.state='running';this.currentTime=0;this.destination={}}
  resume(){return Promise.resolve()}
  suspend(){return Promise.resolve()}
  close(){return Promise.resolve()}
  createBufferSource(){audioSource=new FakeAudioSource();return audioSource}
 }
 const speaker=vm.runInNewContext(source.slice(speakerStart,speakerEnd)+'\ncreateSpeaker()',{
  window:{AudioContext:FakeAudioContext,ShadowAudio:{decode:()=>Promise.resolve({duration:2})}},src:'/audio/test',
  BEEP_MS:120,setInterval:()=>1,clearInterval(){},setTimeout,clearTimeout,
 });
 await speaker.ready();
 const segment=speaker.play();await Promise.resolve();await Promise.resolve();await Promise.resolve();
 assert.equal(speaker.stopCurrent(),true);await segment;
 assert.equal(audioSource.stopped,1);assert.equal(speaker.stopCurrent(),false);
});
