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
function runTakeArrow(key,{selected=1,revealed=true,hidden=false,activeStep='record'}={}){
 let handler,prevented=false;const rows=[0,1,2].map(index=>({chosen:index===selected,focused:false,classList:{contains(name){return name==='chosen'&&rows[index].chosen}},click(){rows.forEach((row,i)=>row.chosen=i===index)},focus(){this.focused=true}}));
 const result={hidden,querySelectorAll:()=>rows};const root={dataset:{answersRevealed:String(revealed),activeStep}};
 vm.runInNewContext(source.slice(begin,end),{recording:false,root,physicalKey:()=>key,listenStep:{hidden:true},document:{addEventListener:(_,fn)=>handler=fn,getElementById:id=>id==='rec-result'?result:{hidden:true,classList:{contains:()=>false}},querySelectorAll:()=>[],querySelector:()=>null}});
 handler({repeat:false,defaultPrevented:false,target:{closest:()=>null},preventDefault(){prevented=true}});return {rows,prevented};
}
test('up and down select the previous and next take after results appear',()=>{
 const down=runTakeArrow('ArrowDown');assert.equal(down.rows[2].chosen,true);assert.equal(down.rows[2].focused,true);assert.equal(down.prevented,true);
 const up=runTakeArrow('ArrowUp');assert.equal(up.rows[0].chosen,true);assert.equal(up.rows[0].focused,true);
});
test('take selection does not wrap or steal arrows before results are available',()=>{
 const top=runTakeArrow('ArrowUp',{selected:0});assert.equal(top.rows[0].chosen,true);assert.equal(top.prevented,false);
 const locked=runTakeArrow('ArrowDown',{revealed:false});assert.equal(locked.rows[1].chosen,true);assert.equal(locked.prevented,false);
 const hidden=runTakeArrow('ArrowDown',{hidden:true});assert.equal(hidden.rows[1].chosen,true);assert.equal(hidden.prevented,false);
 const otherStep=runTakeArrow('ArrowDown',{activeStep:'drill'});assert.equal(otherStep.rows[1].chosen,true);assert.equal(otherStep.prevented,false);
});
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
for(const key of ['o','m'])for(const revealed of [false,true])test(`${key} analysis playback obeys reveal=${revealed}`,()=>{
 let handler,played=0;
 const control={hidden:false,click(){played++}};
 vm.runInNewContext(source.slice(begin,end),{recording:false,root:{dataset:{answersRevealed:String(revealed)}},physicalKey:()=>key,
 document:{addEventListener:(_,fn)=>handler=fn,getElementById:()=>({hidden:false,classList:{contains:()=>false}}),querySelectorAll:()=>[control,control,control]}});
 handler({target:{closest:()=>null},preventDefault(){}});assert.equal(played,revealed?1:0);
});
