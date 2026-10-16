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
