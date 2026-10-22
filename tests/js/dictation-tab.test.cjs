const {test}=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const source=fs.readFileSync('src/shadow/web/static/app.js','utf8');
const ui=fs.readFileSync('src/shadow/web/static/ui.js','utf8');
const keyCode=ui.slice(ui.indexOf('function physicalKey('),ui.indexOf('// 快捷键不灵时的诊断'));
test('Tab is recognized by physical code even when IME reports Process',()=>{
 assert.equal(vm.runInNewContext(keyCode+';physicalKey({code:"Tab",key:"Process"})'),'Tab');
});
for(const composing of [false,true])test(`Tab replays without leaving dictation input, composing=${composing}`,()=>{
 let handler,played=0,focused=0,prevented=0;
 const begin=source.indexOf('  typed.addEventListener("keydown",'),end=source.indexOf('\n  // 在光标处',begin);
 vm.runInNewContext(keyCode+'\n'+source.slice(begin,end),{typed:{addEventListener:(_,fn)=>handler=fn,focus(){focused++}},drillStep:{querySelector:()=>({click(){played++}})}});
 handler({key:'Process',code:'Tab',isComposing:composing,preventDefault(){prevented++}});
 assert.equal(played,1);assert.equal(focused,1);assert.equal(prevented,1);
});
test('restoring saved dictation selection survives automatic status synchronization',()=>{
 const mobile=fs.readFileSync('src/shadow/web/static/mobile.js','utf8');
 const begin=mobile.indexOf("document.addEventListener('shadow:session-restored',");
 const end=mobile.indexOf(';',mobile.indexOf('});',begin))+1;
 const root={dataset:{activeStep:'drill'}};let handler,opened;
 vm.runInNewContext(mobile.slice(begin,end),{document:{addEventListener:(_,fn)=>handler=fn},root,sync(){root.dataset.activeStep='record'},show(id){opened=id}});
 handler();assert.equal(opened,'drill');
});
for(const shiftKey of [false,true])test(`Tab on dictation panel outside input, shift=${shiftKey}`,()=>{
 const begin=source.indexOf('  document.addEventListener("keydown",',source.indexOf('// 一句从头到尾')),end=source.indexOf('\n  });',begin)+6;
 let handler,played=0;const play={hidden:false,click(){played++}};
 const drill={hidden:false,classList:{contains:()=>false},querySelector:()=>play};
 vm.runInNewContext(source.slice(begin,end),{recording:false,physicalKey:()=> 'Tab',document:{addEventListener:(_,fn)=>handler=fn,getElementById:id=>id==='step-drill'?drill:{hidden:true,classList:{contains:()=>false},focus(){}},querySelectorAll:()=>[]}});
 handler({shiftKey,target:{closest:()=>null},preventDefault(){}});assert.equal(played,shiftKey?0:1);
});
test('late-loading controls retain the step already restored from storage',()=>{
 const mobile=fs.readFileSync('src/shadow/web/static/mobile.js','utf8');
 const begin=mobile.indexOf("const initial=root.dataset.activeStep||'listen';");
 const end=mobile.indexOf('\n',begin);
 const root={dataset:{activeStep:'drill'}};let opened;
 vm.runInNewContext(mobile.slice(begin,end),{root,sync(){root.dataset.activeStep='record'},show(id){opened=id}});
 assert.equal(opened,'drill');
});
test('Shift+Tab leaves the input normally without replaying',()=>{
 let handler,played=0;
 const begin=source.indexOf('  typed.addEventListener("keydown",'),end=source.indexOf('\n  // 在光标处',begin);
 vm.runInNewContext(keyCode+'\n'+source.slice(begin,end),{typed:{addEventListener:(_,fn)=>handler=fn},drillStep:{querySelector:()=>({click(){played++}})}});
 handler({key:'Tab',code:'Tab',shiftKey:true,preventDefault(){throw Error('normal focus navigation must remain available')}});
 assert.equal(played,0);
});
