const test=require('node:test');const assert=require('node:assert/strict');
const {clampNumber,canDismissDrag,finishState}=require('../../src/shadow/web/static/native-ui.js');
test('numeric controls clamp at business bounds',()=>{assert.equal(clampNumber('',1,6,3),3);assert.equal(clampNumber(99,1,6,3),6);assert.equal(clampNumber(-1,0,20,4),0)});
test('sheet drag only accepts deliberate downward grabber movement',()=>{assert.equal(canDismissDrag(95,0,800),true);assert.equal(canDismissDrag(40,2,50),true);assert.equal(canDismissDrag(10,100,20),false);assert.equal(canDismissDrag(-100,0,50),false)});
test('completion requires no active or unsaved recording',()=>{assert.equal(finishState({recording:true,pending:[],analysis:{}}),'recording');assert.equal(finishState({pending:[{}],analysis:{}}),'pending');assert.equal(finishState({pending:[],analysis:{}}),'saved');assert.equal(finishState({pending:[],analysis:null}),'draft')});

test('inflight submission cannot be discarded',()=>assert.equal(finishState({submitting:true,pending:[{}],analysis:{}}),'submitting'));

test('busy control synchronization does not retrigger identical disabled mutations',()=>{const {setDisabledIfChanged}=require('../../src/shadow/web/static/native-ui.js');let value=false,writes=0;const control={get disabled(){return value},set disabled(next){value=next;writes++}};setDisabledIfChanged(control,true);setDisabledIfChanged(control,true);assert.equal(writes,1);setDisabledIfChanged(control,false);assert.equal(writes,2)});
