const {test}=require('node:test'),assert=require('node:assert/strict');
const {nextPracticeStep,answersRevealed}=require('../../src/shadow/web/static/mobile.js');
test('rating advances to blind shadowing before dictation',()=>{
 assert.equal(nextPracticeStep('listen',{listen:true,record:false,drill:false}),'record');
});
test('saved shadowing advances to dictation until answers are revealed',()=>{
 assert.equal(nextPracticeStep('record',{listen:true,record:true,drill:false}),'drill');
 assert.equal(nextPracticeStep('record',{listen:true,record:true,drill:true}),'record');
});
test('revisiting completed listening does not jump',()=>{
 assert.equal(nextPracticeStep('listen',{listen:true,record:true,drill:true}),'listen');
});
test('only grading or explicit skip reveals answers, including restored sessions',()=>{
 assert.equal(answersRevealed({graded:false,skipped:false}),false);
 assert.equal(answersRevealed({graded:true,skipped:false}),true);
 assert.equal(answersRevealed({graded:false,skipped:true}),true);
});
