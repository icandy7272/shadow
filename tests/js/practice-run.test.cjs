const {test}=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
test('concurrent dictation and upload reserve only one shared practice round',async()=>{
 const source=fs.readFileSync('src/shadow/web/static/app.js','utf8');
 const begin=source.indexOf('let reservingRun = null;'),end=source.indexOf('if (root) {',begin);
 let requests=0,respond;
 const c={runId:null,root:{dataset:{segment:'1',unit:'2'}},fetch:()=>{requests++;return new Promise(resolve=>respond=resolve)}};
 c.keepRun=data=>{c.runId=data.run_id};vm.runInNewContext(source.slice(begin,end),c);
 const first=c.ensurePracticeRun(),second=c.ensurePracticeRun();assert.equal(requests,1);
 respond({ok:true,json:async()=>({run_id:9})});assert.equal(await first,9);assert.equal(await second,9);assert.equal(c.runId,9);
 assert.equal(await c.ensurePracticeRun(),9);assert.equal(requests,1);
});
