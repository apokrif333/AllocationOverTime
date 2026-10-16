/* Execute the actual dashboard controller with a minimal DOM and Plotly adapter.
 * This tests UI calculations/controls, not browser layout or Plotly rendering.
 */
'use strict';
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
async function main(){
const html=fs.readFileSync(process.argv[2]||'output/ib_U5157275_audit/allocation_dashboard.html','utf8');
const dataText=html.match(/<script id="portfolio-data" type="application\/json">([\s\S]*?)<\/script>/)[1];
const controller=html.slice(html.lastIndexOf('<script>')+8,html.lastIndexOf('</script>'));
const nodes=new Map();
function element(id){return {id,value:'',textContent:'',innerHTML:'',checked:false,hidden:true,style:{},handlers:{},children:[],classList:{toggle(){}},
 append(...items){this.children.push(...items);},replaceChildren(...items){this.children=items;},
 setAttribute(){},click(){this.clicked=true;},on(name,handler){this.handlers[name]=handler;},addEventListener(){},
 getBoundingClientRect(){return {left:0,top:0};},offsetWidth:280,offsetHeight:140,dataset:{}};}
function get(id){if(!nodes.has(id))nodes.set(id,element(id));return nodes.get(id);}
get('portfolio-data').textContent=dataText;get('mode').value='individual';get('severity').value='issues';
const plots=new Map(),rangeButtons=[6,12,'all'].map(v=>({dataset:{range:String(v)}}));
const sandbox={document:{getElementById:get,createElement:tag=>element(tag),querySelectorAll:()=>rangeButtons},
 Plotly:{react:(id,traces,layout)=>{get(id).data=traces;plots.set(id,{traces,layout});return Promise.resolve();},
         newPlot:(id,traces,layout)=>{plots.set(id,{traces,layout});return Promise.resolve();},relayout(){}},
 window:{innerWidth:1440,innerHeight:1000},Intl,Date,Map,Set,Blob,URL:{createObjectURL:()=>'',revokeObjectURL(){}},setTimeout:fn=>fn(),console};
vm.runInNewContext(controller,sandbox,{filename:'dashboard-controller.js'});
await sandbox.window.portfolioDashboard.ready;
await sandbox.window.portfolioDashboard.profitReady;
const dashboard=sandbox.window.portfolioDashboard,P=dashboard.data,S=P.states;
assert(S.length>0);
assert.equal(plots.get('chart').traces.length,Object.keys(P.instruments).length+1);
assert.equal(plots.get('chart').layout.yaxis.range[1],100);
assert(plots.get('chart').traces.every(t=>t.line.shape==='hv'&&!t.groupnorm));
assert(plots.get('chart').traces.every(t=>/^[a-zA-Z][a-zA-Z0-9_]*$/.test(t.uid)));
assert.equal(new Set(plots.get('chart').traces.map(t=>t.uid)).size,plots.get('chart').traces.length);
assert.equal(S[0].weights.Cash,100);
const profit=P.profit;
assert.equal(profit.states.length,S.length);
assert.equal(profit.states[0].cumulative_realized_usd,0);
assert.equal(plots.get('profitChart').traces[0].line.shape,'hv');
assert.equal(plots.get('profitChart').traces[0].y.at(-1),profit.states.at(-1).cumulative_realized_usd);
const profitBeforeFiltering=JSON.stringify(plots.get('profitChart').traces[0].y);
function sumAt(traces,index){return traces.reduce((sum,t)=>sum+(t.y[index]||0),0);}
for(let index=0;index<S.length;index++)if(S[index].valid)assert(Math.abs(sumAt(dashboard.traceSeries(),index)-100)<1e-6);
const id=Object.keys(P.instruments).find(k=>P.instruments[k].name==='GLD 07FEB25 251 P');
const opened=S.findIndex(s=>s.timestamp==='2025-01-16T12:38:12'),closed=S.findIndex(s=>s.timestamp==='2025-02-03T12:32:07');
assert.equal(S[opened].amounts[id],25100);assert.equal(S[closed].amounts[id],0);
get('search').value='GLD 07FEB25';get('search').oninput();get('matches').onclick();
assert.equal(dashboard.selected.size,1);assert(dashboard.selected.has(id));
assert.equal(dashboard.traceSeries()[0].y[opened],S[opened].weights[id]);
assert(dashboard.traceSeries()[0].y[opened]<100); // No filtering renormalization.
get('mode').value='classes';get('mode').onchange();
assert(plots.get('chart').traces.every(t=>/^[a-zA-Z][a-zA-Z0-9_]*$/.test(t.uid)));
assert.equal(sumAt(dashboard.traceSeries(),opened),S[opened].weights[id]);
get('all').onclick();
for(let index=0;index<S.length;index++)if(S[index].valid)assert(Math.abs(sumAt(dashboard.traceSeries(),index)-100)<1e-6);
get('highlight').value=id;get('highlight').onchange();
assert(dashboard.traceSeries().some(t=>t.opacity===.16));
get('date').value='2025-01-16';get('date').onchange({target:get('date')});
assert(get('reservedValue').textContent.includes('25,100'));
assert(get('allocationTable').innerHTML.includes('GLD 07FEB25 251 P'));
get('date').value='2025-02-03';get('date').onchange({target:get('date')});
assert.equal(get('reservedValue').textContent,'$0.00');
assert(get('profitSelected').textContent.includes('2025-02-03'));
assert(get('profitBreakdown').innerHTML.includes('Опционы'));
assert.equal(JSON.stringify(plots.get('profitChart').traces[0].y),profitBeforeFiltering);
get('dateSlider').oninput({target:{value:'0'}});assert.equal(get('cashValue').textContent,'$100,000.00');
get('severity').value='cash_balance';get('severity').onchange();
assert(get('reconTable').innerHTML.includes('161.4'));
assert(!get('reconTable').innerHTML.includes('source_audit:'));
const csv=dashboard.exportRows();
assert(csv.includes('accounting_denominator_usd'));assert(csv.includes('25100'));
assert.equal(csv.split('\r\n').length,1+S.length*(Object.keys(P.instruments).length+1));
assert(!html.match(/<script\s+[^>]*src\s*=/i),'Self-contained scripts expected');
assert(get('quality').textContent.includes('cash checkpoints'));

// Hover regression: MTNA was sold in 2025 and must never capture a 2026 tooltip.
get('mode').value='individual';get('mode').onchange();get('all').onclick();
const mtna='US03938LBF04',historical='2024-05-01T12:00:00',sold='2026-06-02T23:59:00';
function midpoint(id,time,traces){const ix=dashboard.indexAt(time);let base=0;for(const t of traces){if(t.visible===false||t.visible==='legendonly')continue;const weight=t.y[ix]||0;if(t.meta.key===id)return base+weight/2;base+=weight;}throw Error(id);}
let traces=dashboard.traceSeries();
let hit=dashboard.hoverAt(historical,midpoint(mtna,historical,traces),traces);
assert.equal(hit.trace.meta.key,mtna);assert.equal(hit.values[0],3104.55);
let markup=dashboard.hoverMarkup(hit);
assert(markup.includes('Вложено: $3,104.55'));
assert(markup.includes('Доля:'));
for(const technical of ['Cash (signed)','Borrowing','Full denominator','trade:','Trade:','documented'])assert(!markup.includes(technical));
const stepIndex=dashboard.indexAt(historical);
const middle=(Date.parse(S[stepIndex].timestamp+'Z')+Date.parse(S[stepIndex+1].timestamp+'Z'))/2;
assert.equal(dashboard.indexAt(middle),stepIndex); // Keep the preceding step, not nearest future event.
const soldIndex=dashboard.indexAt(sold);
assert.equal(S[soldIndex].amounts[mtna],0);
for(const trace of traces){if(!(trace.y[soldIndex]>0))continue;hit=dashboard.hoverAt(sold,midpoint(trace.meta.key,sold,traces),traces);assert.equal(hit.trace.meta.key,trace.meta.key);assert(hit.values[0]>0);assert.notEqual(hit.trace.meta.key,mtna);}
let cashTrace=traces.find(t=>t.meta.key==='Cash'),mtnaTrace=traces.find(t=>t.meta.key===mtna);
hit=dashboard.hoverAt(sold,cashTrace.y[soldIndex]/2,[mtnaTrace,cashTrace]);assert.equal(hit.trace.meta.key,'Cash');
assert.equal(dashboard.hoverAt(sold,50,[mtnaTrace,cashTrace]),null); // Empty filtered region.
assert.equal(dashboard.hoverAt(sold,50,[{...cashTrace,visible:'legendonly'},mtnaTrace]),null);
assert.equal(dashboard.hoverAt('2021-01-01',50,traces),null);
assert.equal(dashboard.hoverAt(sold,-1,traces),null);
const cashMid=midpoint('Cash',sold,traces);
get('chart').handlers.plotly_hover({points:[],xvals:[sold],yvals:[cashMid],xPixel:500,yPixel:300});
assert.equal(get('allocationHover').hidden,false);
assert(get('allocationHover').innerHTML.includes('Свободные деньги:'));
get('chart').handlers.plotly_unhover();assert.equal(get('allocationHover').hidden,true);
get('chart').handlers.plotly_click({points:[],xvals:[sold]});assert.equal(dashboard.getIndex(),soldIndex);
assert(plots.get('chart').layout.hoveranywhere&&plots.get('chart').layout.clickanywhere);
assert(traces.every(t=>t.hoverinfo==='skip'&&!t.hovertemplate));
console.log(JSON.stringify({states:S.length,instruments:Object.keys(P.instruments).length,
 controls_verified:['search','multiselect','modes','highlight','date','slider','reconciliation','CSV export','active-band hover','closed-position exclusion','compact USD tooltip'],
 denominator_preserved:true,weights_tolerance:1e-6,self_contained:true,
 limitation:'Controller tests only; real-browser visual review unavailable'},null,2));
}
main().catch(error=>{console.error(error);process.exitCode=1;});
