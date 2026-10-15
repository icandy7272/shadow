const test=require('node:test'),assert=require('node:assert/strict');
const {sectionFor,retainedURL,readViewState}=require('../../src/shadow/web/static/navigation.js');
test('only app sections are retained, never recorder or external routes',()=>{
 assert.equal(sectionFor('/sources/12'),'library');assert.equal(sectionFor('/vocab'),'library');
 assert.equal(sectionFor('/talk'),'start');assert.equal(sectionFor('/practice/1/2'),null);
 assert.equal(retainedURL('https://evil.test/sources','library','https://shadow.test'),null);
 assert.equal(retainedURL('/records?range=month','records','https://shadow.test'),'/records?range=month');
 assert.equal(retainedURL('/practice/1/2','start','https://shadow.test'),null);
 assert.equal(retainedURL('/records','library','https://shadow.test'),null);
});
test('retained input and scroll are bounded and malformed storage falls back safely',()=>{
 assert.deepEqual(readViewState('{broken'),null);
 assert.deepEqual(readViewState(JSON.stringify({scroll:-20,search:'test'})),{scroll:0,search:'test',filter:'all'});
 assert.equal(readViewState(JSON.stringify({scroll:Infinity,search:12})).scroll,0);
 assert.equal(readViewState(JSON.stringify({scroll:100,search:'x'.repeat(5000)})).search.length,500);
});

test('cached documents refresh tab destinations after another page changes section state',()=>{
 const vm=require('node:vm'),fs=require('node:fs');const events={},listeners={};
 const data=new Map([['shadow.navigation.v1:section:records','/records?range=week']]);
 let href='https://shadow.test/records';
 const link={get href(){return new URL(href,'https://shadow.test').href},set href(value){href=value},addEventListener(name,fn){listeners[name]=fn}};
 const document={body:{style:{}},querySelector(){return null},querySelectorAll(){return [link]}};
 const window={scrollY:0,addEventListener(name,fn){events[name]=fn}};
 const sessionStorage={getItem:key=>data.get(key)||null,setItem:(key,value)=>data.set(key,value)};
 vm.runInNewContext(fs.readFileSync(require.resolve('../../src/shadow/web/static/navigation.js'),'utf8'),{document,window,sessionStorage,URL,location:{origin:'https://shadow.test',pathname:'/today',search:''},performance:{getEntriesByType:()=>[]}});
 assert.equal(link.href,'https://shadow.test/records?range=week');
 data.set('shadow.navigation.v1:section:records','/records?range=month');
 events.pageshow?.({persisted:true});
 assert.equal(link.href,'https://shadow.test/records?range=month');
 data.set('shadow.navigation.v1:section:records','https://evil.test/records');
 events.pageshow?.({persisted:true});
 assert.equal(link.href,'https://shadow.test/records');
});
