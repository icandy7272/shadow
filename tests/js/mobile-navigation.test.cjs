const {test}=require('node:test'),assert=require('node:assert/strict');const {nextPracticeStep}=require('../../src/shadow/web/static/mobile.js');
test('rating advances, grading stays for feedback, skip advances',()=>{assert.equal(nextPracticeStep('listen',{listen:true,drill:false}),'drill');assert.equal(nextPracticeStep('drill',{listen:true,drill:true,skipped:false}),'drill');assert.equal(nextPracticeStep('drill',{listen:true,drill:true,skipped:true}),'record')});
test('revisiting unlocked steps does not jump to results',()=>{assert.equal(nextPracticeStep('listen',{listen:true,drill:true}),'listen');assert.equal(nextPracticeStep('record',{listen:true,drill:true}),'record')});

test('mastered dictation auto-skip opens recording immediately',()=>{assert.equal(nextPracticeStep('listen',{listen:true,drill:true,skipped:true}),'record')});
