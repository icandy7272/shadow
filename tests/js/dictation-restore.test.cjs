const {test}=require('node:test'),assert=require('node:assert/strict');
const fs=require('node:fs'),vm=require('node:vm');
test('restoring ungraded dictation clears stale recorder folding while preserving typed draft',()=>{
 const source=fs.readFileSync('src/shadow/web/static/app.js','utf8');
 const begin=source.indexOf('    restore:saved=>{');
 const end=source.indexOf('\n    }\n  });',begin);
 const makeStep=names=>{const values=new Set(names);return {values,classList:{contains:n=>values.has(n),add:n=>values.add(n),remove:(...ns)=>ns.forEach(n=>values.delete(n)),toggle:(n,on)=>on?values.add(n):values.delete(n)},querySelector:()=>({})}};
 const drill=makeStep([]),listen=makeStep([]),record=makeStep([]);
 const typed={value:''},root={dataset:{}};
 const saved={runId:4,rating:'3',typed:'my unfinished words',activeStep:'drill',steps:{listen:['complete'],record:['complete'],drill:['done','foldable','complete']},analysis:{run_id:4}};
 vm.runInNewContext(`const restore=${source.slice(begin,end).replace('    restore:','')}\n};restore(saved)`,{
  saved,root,typed,drillStep:drill,listenStep:{querySelectorAll:()=>[]},refreshCount(){},
  window:{ShadowSession:{validGrading:()=>false}},
  document:{getElementById:id=>({'step-listen':listen,'step-drill':drill,'step-record':record}[id])},
  setFolded(){throw new Error('ungraded draft must not remain foldable')},
 });
 assert.equal(drill.values.has('done'),false);assert.equal(drill.values.has('complete'),false);
 assert.equal(drill.values.has('foldable'),false);assert.equal(drill.values.has('locked'),false);
 assert.equal(typed.value,'my unfinished words');assert.equal(root.dataset.answersRevealed,'false');
});
