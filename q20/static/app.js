'use strict';
const minInput=document.getElementById('minutes'),refreshButton=document.getElementById('refresh');
let minutes=1,timer=null,busy=false,lastRequest=0;
try{const n=Number(localStorage.getItem('q20.refreshMinutes'));if(Number.isInteger(n)&&n>=1&&n<=1440)minutes=n;}catch{}
minInput.value=minutes;
function intervalText(){document.getElementById('interval').textContent=`Refreshes every ${minutes} minute${minutes===1?'':'s'} while visible. Minimum: 1 minute.`;}
function schedule(){clearTimeout(timer);if(!document.hidden)timer=setTimeout(refresh,Math.max(60000,minutes*60000));}
async function refresh(){if(busy||document.hidden)return;if(lastRequest&&Date.now()-lastRequest<60000){schedule();return;}busy=true;lastRequest=Date.now();refreshButton.disabled=true;
try{const r=await fetch('/status',{cache:'no-store',signal:AbortSignal.timeout(15000)});if(!r.ok)throw Error('Status unavailable');const s=await r.json();document.getElementById('message').textContent=s.message||'Status unavailable';const grid=document.getElementById('cards');grid.replaceChildren();
for(const [label,value] of [['Network',s.network],['Node height',s.nodeHeight],['Index height',s.indexHeight],['Token definitions',s.tokens],['Messages examined',s.messages],['Bound outputs',s.boundOutputs]]){const card=document.createElement('div');card.className='card';const h=document.createElement('h2');h.textContent=label;const p=document.createElement('p');p.textContent=value??'Unavailable';card.append(h,p);grid.append(card);}}
catch{document.getElementById('message').textContent='Status unavailable. Retrying at the next refresh.';}
finally{busy=false;refreshButton.disabled=false;schedule();}}
document.getElementById('save').addEventListener('click',()=>{const n=Number(minInput.value);if(!Number.isInteger(n)||n<1||n>1440){minInput.setCustomValidity('Choose whole minutes, from 1 to 1440.');minInput.reportValidity();return;}minInput.setCustomValidity('');minutes=n;try{localStorage.setItem('q20.refreshMinutes',String(n));}catch{}intervalText();schedule();});
refreshButton.addEventListener('click',refresh);document.addEventListener('visibilitychange',()=>{clearTimeout(timer);if(!document.hidden){if(Date.now()-lastRequest>=minutes*60000)refresh();else schedule();}});intervalText();refresh();
