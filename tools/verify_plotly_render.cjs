/* Real bundled Plotly with an emulated SVG DOM. No browser automation or UI.
 * Geometry shims supply text/canvas measurements only; Plotly calc/diff/render
 * and the dashboard's actual change handler are exercised without adapters.
 */
'use strict';
const fs=require('node:fs'),assert=require('node:assert/strict');
const {JSDOM,VirtualConsole}=require('../.qa/node_modules/jsdom');
const filename=process.argv[2]||'output/ib_U5157275_audit/allocation_dashboard.html';
const source=fs.readFileSync(filename,'utf8');
const scripts=[...source.matchAll(/<script(?:\s[^>]*)?>([\s\S]*?)<\/script>/g)];
const errors=[];
const vc=new VirtualConsole();vc.on('jsdomError',error=>errors.push(String(error)));
const dom=new JSDOM(source.replace(/<script(?:\s[^>]*)?>[\s\S]*?<\/script>/g,''),{runScripts:'outside-only',pretendToBeVisual:true,url:'http://localhost/',virtualConsole:vc});
const w=dom.window;
w.TextDecoder=TextDecoder;w.TextEncoder=TextEncoder;
w.URL.createObjectURL=()=> 'blob:fixture';w.URL.revokeObjectURL=()=>{};
w.HTMLCanvasElement.prototype.getContext=function(){return {measureText:text=>({width:String(text).length*7}),createLinearGradient:()=>({addColorStop(){}})};};
w.SVGElement.prototype.getBBox=function(){return {x:0,y:0,width:(this.textContent||'').length*7,height:14};};
w.Element.prototype.getBoundingClientRect=function(){const chart=this.closest?.('#chart');return {x:0,y:0,left:0,top:0,width:this.id==='chart'||chart?1100:800,height:this.id==='chart'||chart?620:135,right:1100,bottom:620};};
Object.defineProperty(w.HTMLElement.prototype,'clientWidth',{get(){return 1100;}});
Object.defineProperty(w.HTMLElement.prototype,'clientHeight',{get(){return this.id==='chart'?620:135;}});
let pending,lastError,reactCalls=0;
const payload=w.document.createElement('script');payload.id='portfolio-data';payload.type='application/json';payload.textContent=scripts[1][1];w.document.body.append(payload);
async function main(){
 w.eval(scripts[0][1]);
 const originalReact=w.Plotly.react.bind(w.Plotly);
 w.Plotly.react=(...args)=>{reactCalls++;const start=performance.now();pending=originalReact(...args);pending.then(()=>console.log('Plotly.react',args[1].length,'traces',Math.round(performance.now()-start)+'ms'),error=>{lastError=error;console.error(error);});return pending;};
 w.eval(scripts.at(-1)[1]);await w.portfolioDashboard.ready;await w.portfolioDashboard.profitReady;
 const gd=w.document.getElementById('chart'),mode=w.document.getElementById('mode');
 // Exercise the real currency control and chart, including the native KZT view.
 const currencyApp=w.portfolioDashboard,currencySelect=w.document.getElementById('profitCurrency');
 const sourceBefore=JSON.stringify(currencyApp.data.states),profitBefore=JSON.stringify(currencyApp.data.profit.states);
 for(const currency of currencyApp.data.profit.currencies){
  currencySelect.value=currency;await currencySelect.onchange();
  const graph=w.document.getElementById('profitChart');
  const profitStates=currencyApp.data.profit.states.filter(s=>s.events.length);
  assert.deepEqual(Array.from(graph.data[0].x),Array.from(profitStates,s=>s.timestamp));
  assert.deepEqual(Array.from(graph.data[0].y),Array.from(profitStates,s=>s.by_currency[currency].cumulative_realized));
  assert(graph.data.filter(t=>t.uid.endsWith('_continuation')).every(t=>t.hoverinfo==='skip'&&!t.showlegend));
  if(currencyApp.data.metadata.input_name==='ib_U5157275_audit.xlsx'){
   assert(!graph.data[0].x.some(x=>x.startsWith('2025-10-20')));
   const repayment=graph.data[0].x.findIndex(x=>x.startsWith('2022-07-28'));
   assert(repayment>=0);
   assert(graph.data[0].customdata[repayment][2].includes('Валютный заём'));
   const state=profitStates[repayment],loss=state.events.filter(e=>e.category==='Currency borrowing').reduce((sum,e)=>sum+e.realized_pnl_native,0);
   assert(Math.abs(loss+18801.233805412943)<1e-6);
  }
  assert(graph.layout.yaxis.title.text.includes(currency));
  assert(w.document.getElementById('profitAmountHeader').textContent.includes(currency));
  assert(currencyApp.exportProfitRows().includes(currency));
  assert(graph.data[0].hovertemplate.includes('%{customdata[2]}'));
  assert(!graph.data[0].hovertemplate.includes('customdata[0]'));
  assert(!graph.data[0].hovertemplate.includes('customdata[1]'));
  const daySummaries=new Map();
  for(const [i,state] of profitStates.entries()){
   const operation=graph.data[0].customdata[i][2];
   assert(!operation.includes('<br>')&&!operation.includes('FIFO')&&!operation.includes('&quot;'));
   const day=state.timestamp.slice(0,10);
   if(daySummaries.has(day))assert.equal(operation,daySummaries.get(day));
   daySummaries.set(day,operation);
   const dailyCategories=new Set(currencyApp.data.profit.states.filter(s=>s.timestamp.startsWith(day)).flatMap(s=>s.events.map(e=>e.category)));
   if(dailyCategories.size)assert.equal(operation.split(', ').length,dailyCategories.size);
  }
  const eventIndex=profitStates.findIndex(s=>s.by_currency[currency].complete);
  w.Plotly.Fx.hover(graph,[{curveNumber:0,pointNumber:eventIndex}]);
  assert(graph.querySelector('.hoverlayer').textContent.includes('Накоплено:'));
  assert(graph.querySelector('.hoverlayer').textContent.includes(graph.data[0].customdata[eventIndex][2].replace(/<[^>]*>/g,' ').trim().split(/\s+/)[0]));
  w.Plotly.Fx.unhover(graph);
  assert.equal(JSON.stringify(currencyApp.data.states),sourceBefore);
  assert.equal(JSON.stringify(currencyApp.data.profit.states),profitBefore);
 }
 currencySelect.value=currencyApp.data.profit.default_currency;await currencySelect.onchange();
 if(w.portfolioDashboard.data.metadata.input_name==='halyk_1028197847_audit.xlsx'){
  const app=w.portfolioDashboard;
  assert.equal(gd._fullData.length,16);
  assert(app.data.states.every(s=>s.valid&&Object.values(s.quantities).every(q=>q>=0)));
  assert(app.data.reconciliation.some(r=>r.category==='cash_funding_history_missing'));
  assert(w.document.getElementById('quality').textContent.includes('not verified broker borrowing'));
  assert.equal(w.document.getElementById('borrowingLabel').textContent,'Negative reconstructed cash (USD)');
  mode.value='classes';await mode.onchange();assert.equal(gd._fullData.length,5);
  mode.value='individual';await mode.onchange();assert.equal(gd._fullData.length,16);
  assert.equal(w.document.getElementById('chartError').hidden,true);
  if(errors.length)throw new Error(errors.join('\n'));
  console.log('Halyk Plotly verified: 16/5 traces, no false security shorts, complete rates, funding gap disclosed.');
  dom.window.close();return;
 }
 if(w.portfolioDashboard.data.metadata.input_name==='tsifra_1432280_audit.xlsx'){
  const app=w.portfolioDashboard,profitGraph=w.document.getElementById('profitChart');
  assert.equal(gd._fullData.length,35);
  assert.equal(profitGraph._fullData.filter(t=>!t.uid.endsWith('_continuation')).length,1);
  assert.equal(app.data.profit.states.at(-1).complete,true);
  assert(Object.hasOwn(app.data.profit.states.at(-1).cumulative_by_category,'Taxes'));
  assert(w.document.getElementById('profitBreakdown').textContent.includes('\u041d\u0430\u043b\u043e\u0433\u0438'));
  assert(w.document.getElementById('quality').classList.contains('error'));
  assert(app.data.states.every(s=>s.valid&&Object.values(s.weights).every(v=>v!==null)));
  assert(app.data.states[0].amounts.RU0007288411>6000);
  assert.equal(app.data.states[0].quantities.RU0009029524,30000);
  assert(gd._fullLayout.legend.y>1,'Legend must stay above the chart and date slider');
  assert(gd.data.every(t=>t.y.every(v=>v!==null)), 'Complete data must have no empty allocation bands');
  mode.value='classes';await mode.onchange();
  assert.equal(gd._fullData.length,3);
  mode.value='individual';await mode.onchange();
  assert.equal(gd._fullData.length,35);
  assert.equal(w.document.getElementById('chartError').hidden,true);
  if(errors.length)throw new Error(errors.join('\n'));
  console.log('Tsifra Plotly rendering verified: 35/3 traces, 274 complete states, split transferred lots, tax breakdown, complete profit, legend above chart.');
  dom.window.close();return;
 }
 assert.equal(gd._fullData.length,73);assert(gd.querySelectorAll('.scatterlayer path.js-fill').length>0);
 const profitGraph=w.document.getElementById('profitChart'),profitData=w.portfolioDashboard.data.profit;
 assert.equal(profitGraph._fullData.filter(t=>!t.uid.endsWith('_continuation')).length,1);
 assert(profitGraph.querySelector('.scatterlayer path.js-line'));
 assert.equal(profitGraph.data[0].line.shape,'hv');
 assert.equal(profitGraph.data[0].y[0],profitData.states.find(s=>s.events.length).cumulative_realized_usd);
 assert.equal(profitGraph.data[0].y.at(-1),profitData.states.at(-1).cumulative_realized_usd);
 const originalProfit=JSON.stringify(profitGraph.data[0].y);
 profitGraph.emit('plotly_click',{points:[{x:'2025-02-03T12:32:07'}]});
 assert.equal(w.portfolioDashboard.data.states[w.portfolioDashboard.getIndex()].timestamp,'2025-02-03T12:32:07');
 assert(w.document.getElementById('profitBreakdown').textContent.includes('Опционы'));
 assert(w.document.getElementById('profitSelected').textContent.includes('2025-02-03'));
 for(let cycle=0;cycle<3;cycle++){
  mode.value='classes';mode.dispatchEvent(new w.Event('change'));await pending;
  if(lastError)throw lastError;
  assert.equal(gd._fullData.length,7);
  assert.equal(gd.querySelectorAll('.legend .traces').length,7);
  assert.equal(w.document.getElementById('chartError').hidden,true);
  assert(gd._fullData.every(t=>/^[a-zA-Z][a-zA-Z0-9_]*$/.test(t.uid)));
  for(let ix=0;ix<w.portfolioDashboard.data.states.length;ix++)assert(Math.abs(gd.data.reduce((sum,t)=>sum+t.y[ix],0)-100)<1e-6);
  mode.value='individual';mode.dispatchEvent(new w.Event('change'));await pending;
  assert.equal(gd._fullData.length,73);
  assert.equal(gd.querySelectorAll('.legend .traces').length,73);
  assert.equal(JSON.stringify(profitGraph.data[0].y),originalProfit);
 }
 // Exercise the actual header buttons and DOM rows, not a parallel sort helper.
 const app=w.portfolioDashboard,body=w.document.getElementById('allocationTable');
 const rows=()=>Array.from(body.rows,row=>row.dataset.key);
 const state=()=>app.data.states[app.getIndex()];
 const columnValues={instrument:k=>app.data.instruments[k]?.name||'Cash',isin:k=>app.data.instruments[k]?.isin||'',
  class:k=>k==='Cash'?'Cash':state().quantities[k]<0&&app.data.instruments[k].is_option?'Short-option collateral':app.data.instruments[k].asset_class,
  quantity:k=>k==='Cash'?null:state().quantities[k],capital:k=>state().amounts[k],weight:k=>state().weights[k],status:k=>state().basis_status[k]};
 function assertSorted(column,direction){let missingSeen=false,previous;const numeric=['quantity','capital','weight'].includes(column);
  for(const key of rows()){const value=columnValues[column](key);if(value==null||value===''){missingSeen=true;continue;}
   assert(!missingSeen,'Missing values must stay at the end');
   if(previous!==undefined){const diff=numeric?value-previous:String(value).localeCompare(String(previous),'en',{numeric:true,sensitivity:'base'});assert(direction==='ascending'?diff>=0:diff<=0,column+' '+direction);}
   previous=value;
  }
 }
 assertSorted('capital','descending');
 const beforeSortPlotCalls=reactCalls,ledgerBefore=JSON.stringify(app.data.states);
 for(const column of Object.keys(columnValues)){
  const button=w.document.getElementById('sort-'+column),header=w.document.getElementById('sort-header-'+column);
  button.click();const first=header.getAttribute('aria-sort');assertSorted(column,first);
  button.click();const second=header.getAttribute('aria-sort');assert.notEqual(second,first);assertSorted(column,second);
  assert.equal(Array.from(w.document.querySelectorAll('th[aria-sort]')).filter(th=>th.getAttribute('aria-sort')!=='none').length,1);
  assert.equal(w.document.getElementById('sort-arrow-'+column).textContent,second==='ascending'?'↑':'↓');
 }
 assert.equal(reactCalls,beforeSortPlotCalls,'Sorting must not redraw Plotly');
 // Persist numeric ascending order through date, mode, and filter changes.
 const quantityButton=w.document.getElementById('sort-quantity'),quantityHeader=w.document.getElementById('sort-header-quantity');
 quantityButton.click();if(quantityHeader.getAttribute('aria-sort')!=='ascending')quantityButton.click();
 assertSorted('quantity','ascending');assert.equal(rows().at(-1),'Cash');
 const calendar=w.document.getElementById('date');calendar.value='2025-01-16';calendar.dispatchEvent(new w.Event('change'));
 assertSorted('quantity','ascending');assert.equal(state().quantities[rows()[0]],-1);
 mode.value='classes';await mode.onchange();assertSorted('quantity','ascending');
 mode.value='individual';await mode.onchange();assertSorted('quantity','ascending');
 assert.equal(JSON.stringify(app.data.states),ledgerBefore);
 console.log('Sortable table verified: seven columns, numeric/text ordering, both directions, missing-last, preserved date/mode order, no accounting changes.');
 // Removing an option trace used to fail even without changing display mode.
 const put=Object.keys(w.portfolioDashboard.data.instruments).find(k=>w.portfolioDashboard.data.instruments[k].name==='GLD 07FEB25 251 P');
 w.portfolioDashboard.selected.delete(put);await mode.onchange();
 assert.equal(gd._fullData.length,72);
 assertSorted('quantity','ascending');
 w.portfolioDashboard.selected.clear();w.portfolioDashboard.selected.add(put);await mode.onchange();
 assert.equal(gd._fullData.length,1);
 mode.value='classes';await mode.onchange();
 const stateIndex=w.portfolioDashboard.data.states.findIndex(s=>s.timestamp==='2025-01-16T12:38:12');
 assert.equal(gd.data.reduce((sum,t)=>sum+t.y[stateIndex],0),w.portfolioDashboard.data.states[stateIndex].weights[put]);
 assert(gd.data.reduce((sum,t)=>sum+t.y[stateIndex],0)<100);
 assert.equal(w.document.getElementById('chartError').hidden,true);
 assert.equal(JSON.stringify(profitGraph.data[0].y),originalProfit);
 if(errors.length)throw new Error(errors.join('\n'));
 console.log('Real Plotly SVG rendering verified: three round trips, 73/7 traces, option filtering, complete-portfolio denominator.');
 dom.window.close();
}
main().catch(error=>{console.error(error.name,error.message,error.stack);dom.window.close();process.exitCode=1;});
