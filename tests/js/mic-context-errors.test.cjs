const {test}=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
for(const where of ['analyser','source'])test(`microphone ${where} construction failure closes its owned context`,async()=>{const source=fs.readFileSync('src/shadow/web/static/app.js','utf8'),a=source.indexOf('  async function listenTo('),b=source.indexOf('  // 手机不让出声时',a);let closed=0;class Context{constructor(){this.state='running'}resume(){return Promise.resolve()}close(){closed++;return Promise.resolve()}createAnalyser(){if(where==='analyser')throw Error('analyser unavailable');return {getFloatTimeDomainData(){}}}createMediaStreamSource(){throw Error('source unavailable')}}const ctx={window:{AudioContext:Context},Float32Array};vm.runInNewContext(source.slice(a,b),ctx);await assert.rejects(ctx.listenTo({},null));assert.equal(closed,1)});
test('capture analyser keeps the post-microphone iOS context and never monitors to speaker',async()=>{
 const source=fs.readFileSync('src/shadow/web/static/app.js','utf8'),a=source.indexOf('  async function listenTo('),b=source.indexOf('  // 手机不让出声时',a);let created=0,disconnected=0,closed=0;
 const analyser={getFloatTimeDomainData(){},disconnect(){disconnected++}};
 class Context{constructor(){created++;this.state='running'}resume(){return Promise.resolve()}createAnalyser(){return analyser}createMediaStreamSource(){return {connect(target){assert.equal(target,analyser)},disconnect(){disconnected++}}}close(){closed++;return Promise.resolve()}}
 const context={window:{AudioContext:Context},Float32Array};vm.runInNewContext(source.slice(a,b),context);const ear=await context.listenTo({},{close(){throw Error('must not close playback')}});ear.close();assert.equal(created,1);assert.equal(disconnected,2);assert.equal(closed,1);
});
test('audio session is selected before capture and restored after release',()=>{
 const source=fs.readFileSync('src/shadow/web/static/ui.js','utf8');const context={};vm.runInNewContext(source.slice(source.indexOf('function captureAudioSession(')),context);
 const nav={audioSession:{type:'auto'}};const restore=context.captureAudioSession(nav);assert.equal(nav.audioSession.type,'play-and-record');restore();assert.equal(nav.audioSession.type,'auto');assert.doesNotThrow(()=>context.captureAudioSession({})());
 const release=context.captureAudioSession(nav);nav.audioSession.type='playback';release();assert.equal(nav.audioSession.type,'playback');
});
