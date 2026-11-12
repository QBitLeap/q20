const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const test=require('node:test');

test('dashboard enforces minute minimum, pauses while hidden and never overlaps',async()=>{
  const elements=new Map();let requests=0,now=100000;const scheduled=new Map();let timerId=0;
  function element(){return {value:'1',disabled:false,children:[],handlers:{},textContent:'',
    append(...nodes){this.children.push(...nodes)},replaceChildren(){this.children=[]},
    addEventListener(k,fn){this.handlers[k]=fn},setCustomValidity(s){this.validation=s},reportValidity(){}};}
  const document={hidden:false,handlers:{},getElementById(id){if(!elements.has(id))elements.set(id,element());return elements.get(id)},createElement:element,addEventListener(k,fn){this.handlers[k]=fn}};
  const context={document,localStorage:{getItem(){return '0'},setItem(){}},
    Date:{now(){return now}},AbortSignal:{timeout(){return {}}},
    setTimeout(fn,ms){assert.ok(ms>=60000);scheduled.set(++timerId,{fn,ms});return timerId},clearTimeout(id){scheduled.delete(id)},
    async fetch(){requests++;return {ok:true,async json(){return {network:'mainnet',indexHeight:10,nodeHeight:10,message:'Ready'}}}}};
  vm.runInNewContext(fs.readFileSync('q20/static/app.js','utf8'),context);
  await new Promise(setImmediate);
  assert.equal(requests,1);assert.equal(elements.get('minutes').value,1);
  elements.get('refresh').handlers.click();elements.get('refresh').handlers.click();await new Promise(setImmediate);
  assert.equal(requests,1);
  elements.get('minutes').value='0';elements.get('save').handlers.click();assert.match(elements.get('minutes').validation,/whole minutes/);
  elements.get('minutes').value='2';elements.get('save').handlers.click();assert.match(elements.get('interval').textContent,/every 2 minutes/);
  document.hidden=true;document.handlers.visibilitychange();assert.equal(scheduled.size,0);
  now+=120001;document.hidden=false;document.handlers.visibilitychange();await new Promise(setImmediate);
  assert.equal(requests,2);assert.equal(elements.get('refresh').disabled,false);
  assert.equal(elements.get('cards').children.length,6);
});
