const {test}=require('node:test');const assert=require('node:assert/strict');const fs=require('node:fs'),vm=require('node:vm');
const source=fs.readFileSync('src/shadow/web/static/app.js','utf8');
const begin=source.indexOf('  document.addEventListener("keydown",',source.indexOf('// 一句从头到尾'));
const end=source.indexOf('\n  });',begin)+6;
function run(key,{step='drill',ready=true,repeat=false,typing=false,prevented=false}={}){
 let handler,continued=0,navigated=0,assigned=0;const continuation={hidden:!ready,disabled:false,click(){continued++}};
 const drill={hidden:step!=='drill',classList:{contains:name=>name==='graded'&&ready}};
 vm.runInNewContext(source.slice(begin,end),{recording:false,physicalKey:()=>key,listenStep:{hidden:true},
 document:{addEventListener:(_,fn)=>handler=fn,getElementById:id=>id==='practice-continue'?continuation:id==='step-drill'?drill:{hidden:step!=='record',classList:{contains:()=>false}},querySelectorAll:()=>[],querySelector:()=>({href:'/practice/1/2',click(){navigated++}})},window:{location:{assign(){assigned++}}}});
 handler({repeat,defaultPrevented:prevented,target:{closest:()=>typing?{}:null},preventDefault(){}});return {continued,navigated,assigned};
}
test('Enter continues from completed dictation only, never skips a sentence',()=>{
 assert.equal(run('Enter').continued,1);for(const options of [{ready:false},{step:'record'},{step:'listen'},{typing:true},{repeat:true},{prevented:true}])assert.equal(run('Enter',options).continued,0);
 assert.equal(run('Enter').navigated,0);
});
test('arrow navigation clicks the link so draft saving and guards also run',()=>{const state=run('ArrowRight');assert.equal(state.navigated,1);assert.equal(state.assigned,0)});
test('after dictation continue opens analysis without starting the microphone',()=>{
 const mobile=fs.readFileSync('src/shadow/web/static/mobile.js','utf8');const begin=mobile.indexOf("next.addEventListener('click'");const end=mobile.indexOf('\n',begin);
 for(const blocked of [false,true]){
  let click;const calls=[];vm.runInNewContext(mobile.slice(begin,end),{next:{addEventListener:(_,fn)=>click=fn},isBusy:()=>blocked,startControl:{disabled:false,click:()=>calls.push('start')},panels:[null,null,{classList:{contains:()=>false}}],show:()=>calls.push('record')});
  click();assert.deepEqual(calls,blocked?[]:['record']);
 }
});
test('space chooses the current phase action and never starts during prelisten or analysis',()=>{
 const begin=source.indexOf('  const spaceTarget = () => {'),end=source.indexOf('\n  };',begin)+5;
 for(const scenario of ['listen','drill','graded','ready','saved','recording','prelisten','analysis','pending']){
  const play={id:'play'},start={id:'start'},next={id:'next',hidden:false},stop={id:'stop',hidden:scenario==='prelisten'},both={id:'both'};
  const isRecord=['ready','saved','recording','prelisten','analysis','pending'].includes(scenario);
  const record={hidden:!isRecord,classList:{contains:()=>false}};
  const drill={hidden:isRecord||scenario==='listen',classList:{contains:n=>n==='graded'&&scenario==='graded'}};
  const context={recording:['recording','prelisten'].includes(scenario),root:{dataset:{answersRevealed:'true',submitting:String(scenario==='analysis'),pending:String(scenario==='pending')}},document:{getElementById:id=>({'step-record':record,'step-drill':drill,'start-record':start,'practice-continue':next,'stop-take':stop,'rec-result':{hidden:scenario!=='saved'}}[id]),querySelector:()=>scenario==='saved'?both:null,querySelectorAll:()=>[play]}};
  const target=vm.runInNewContext(source.slice(begin,end)+';spaceTarget()',context);
  const wanted={listen:play,drill:play,graded:next,ready:start,saved:both,recording:stop,prelisten:null,analysis:null,pending:null}[scenario];assert.equal(target,wanted,scenario);
 }
});
