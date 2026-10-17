const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
class Node {
 constructor(tag,cls='',text=''){this.tagName=tag;this.children=[];this.parentNode=null;this.attrs={};this.style={};this.listeners={};this.text=text;this.classes=new Set((cls||'').split(' ').filter(Boolean));this.classList={toggle:(c,on)=>on?this.classes.add(c):this.classes.delete(c),contains:c=>this.classes.has(c),add:c=>this.classes.add(c),remove:c=>this.classes.delete(c)};}
 append(...nodes){for(const n of nodes){n.remove();this.children.push(n);n.parentNode=this;}}
 remove(){if(this.parentNode)this.parentNode.children=this.parentNode.children.filter(n=>n!==this);this.parentNode=null;}
 replaceChildren(...nodes){this.children.forEach(n=>n.parentNode=null);this.children=[];this.append(...nodes);}
 set textContent(v){this.replaceChildren();this.text=v;}
 setAttribute(k,v){this.attrs[k]=v;}
 addEventListener(k,fn){(this.listeners[k]??=[]).push(fn);}
 click(){(this.listeners.click||[]).forEach(fn=>fn({}));}
 close(){this.open=false;(this.listeners.close||[]).forEach(fn=>fn());}
 querySelectorAll(cls){return this.children.flatMap(n=>[...(n.classes.has(cls.slice(1))?[n]:[]),...n.querySelectorAll(cls)]);}
}
function setup(){const dialogs=[],takes=[];const body=new Node('body');const context=vm.createContext({el:(...args)=>new Node(...args),window:{ShadowSheets:{open:d=>{d.open=true;dialogs.push(d);}}},document:{body},loops:new Set()});let source=fs.readFileSync('src/shadow/web/static/figures.js','utf8');source=source.slice(source.indexOf('function renderFigures('));vm.runInContext(source,context);context.renderTake=()=>{const node=new Node('div','take-figures'),bar=new Node('div');const take={node,bar,stops:0,stop(){this.stops++;},listen(side){this.side=side;}};takes.push(take);return take;};const take={accuracy:95,speech:1,pause:null,problems:[]};const result=context.renderFigures({takes:[take,take],chosen:1});return {result,dialogs,takes,body};}
test('take selection exposes pressed and representative states without nested action buttons',()=>{const {result}=setup();const rows=result.controls.querySelectorAll('.take-row');assert.equal(rows[1].attrs['aria-pressed'],'true');assert.equal(rows[0].attrs['aria-pressed'],'false');assert.equal(rows[1].querySelectorAll('.take-menu').length,0);assert.equal(result.controls.querySelectorAll('.take-menu').length,2);rows[0].click();assert.equal(rows[0].attrs['aria-pressed'],'true');assert.ok(rows[1].classes.has('representative'));});
test('take menu delegates source playback and viewer moves and restores the same graph',()=>{const {result,dialogs,takes}=setup();result.controls.querySelectorAll('.take-menu')[0].click();const menu=dialogs.at(-1);menu.querySelectorAll('.take-action-source')[0].click();assert.equal(takes.at(-1).side,'ref');result.controls.querySelectorAll('.take-menu')[0].click();dialogs.at(-1).querySelectorAll('.take-action-enlarge')[0].click();const viewer=dialogs.at(-1),take=takes.at(-1);assert.equal(viewer.querySelectorAll('.take-figures')[0],take.node);viewer.close();assert.equal(result.figures.querySelectorAll('.take-figures')[0],take.node);assert.ok(take.stops>0);});
test('switch and dispose close the viewer safely',()=>{const {result,dialogs}=setup();result.controls.querySelectorAll('.take-menu')[1].click();dialogs.at(-1).querySelectorAll('.take-action-enlarge')[0].click();const viewer=dialogs.at(-1);result.controls.querySelectorAll('.take-row')[0].click();assert.equal(viewer.open,false);assert.equal(result.figures.querySelectorAll('.take-figures').length,1);result.dispose();assert.equal(result.figures.querySelectorAll('.take-figures').length,1);});
test('late viewer close event cannot restore a stale take after switching',()=>{const {result,dialogs,takes}=setup();result.controls.querySelectorAll('.take-menu')[1].click();dialogs.at(-1).querySelectorAll('.take-action-enlarge')[0].click();const viewer=dialogs.at(-1),old=takes.at(-1);let deliver;viewer.close=()=>{viewer.open=false;deliver=()=>viewer.listeners.close.forEach(fn=>fn());};result.controls.querySelectorAll('.take-row')[0].click();const active=takes.at(-1);deliver();assert.equal(result.figures.querySelectorAll('.take-figures')[0],active.node);assert.notEqual(active.node,old.node);});
test('mine action and view action select their take without creating extra playback',()=>{const {result,dialogs,takes}=setup();result.controls.querySelectorAll('.take-menu')[0].click();dialogs.at(-1).querySelectorAll('.take-action-mine')[0].click();assert.equal(takes.at(-1).side,'usr');const selected=takes.at(-1);result.controls.querySelectorAll('.take-menu')[0].click();dialogs.at(-1).querySelectorAll('.take-action-view')[0].click();assert.equal(takes.at(-1),selected);});

test('fullscreen moves the same playback bar and restores it on closing',()=>{const {result,dialogs,takes}=setup();result.controls.querySelectorAll('.take-menu')[1].click();dialogs.at(-1).querySelectorAll('.take-action-enlarge')[0].click();const viewer=dialogs.at(-1),take=takes.at(-1);assert.equal(take.bar.parentNode,viewer);assert.equal(result.controls.querySelectorAll('.playbar-slot')[0].children.length,0);const stops=take.stops;viewer.close();assert.equal(take.bar.parentNode,result.controls.querySelectorAll('.playbar-slot')[0]);assert.ok(take.stops>stops);});
test('take action sheet uses one padded header with close action and a separate action list',()=>{
 const {result,dialogs}=setup();result.controls.querySelectorAll('.take-menu')[0].click();const menu=dialogs.at(-1);
 const header=menu.querySelectorAll('.sheet-header')[0],body=menu.querySelectorAll('.action-list')[0];
 assert.ok(header);assert.ok(body);assert.equal(header.querySelectorAll('.take-action-close').length,1);
 assert.equal(body.querySelectorAll('.grouped-row').length,4);assert.equal(body.querySelectorAll('.take-action-close').length,0);
});
