const profitLabels={'Closed trades':'Закрытые сделки','Redemptions':'Погашения и выкупы','Options':'Опционы','Dividends':'Дивиденды','Coupons':'Купоны и НКД','Interest':'Проценты','Currency borrowing':'Валютный заём','Currency trades':'Валютные сделки','Corporate actions':'Корпоративные выплаты','Fees / adjustments':'Комиссии и корректировки','Taxes':'Налоги и возвраты налогов'};
let profitReady=false,profitCurrency=P.profit?.default_currency||'USD';
const profitMoney=(value,currency=profitCurrency)=>value==null?'Недоступно':new Intl.NumberFormat('ru-RU',{style:'currency',currency,maximumFractionDigits:2}).format(value);
const profitView=state=>state.by_currency[profitCurrency];
const profitNative=state=>Object.entries(state.native_cumulative).filter(([,value])=>value!==0).map(([c,value])=>profitMoney(value,c)).join('; ')||'0';
const profitOperations=events=>[...new Set(events.map(event=>profitLabels[event.category]||event.category))].map(esc).join(', ');

function showProfitDate(i){const state=P.profit?.states[i];if(!state)return;
 const view=profitView(state);
 byId('profitSelected').textContent=`На ${state.timestamp.replace('T',' ')}: ${view.complete?profitMoney(view.cumulative_realized):'полный итог недоступен; известная часть '+profitMoney(view.known_subtotal)}. Дата пересчёта: ${state.valuation_timestamp.slice(0,10)}.`;
 byId('profitNative').textContent='Накоплено в исходных валютах: '+profitNative(state)+'.';
 byId('profitBreakdown').innerHTML=Object.entries(view.categories).map(([category,value])=>`<tr><td>${esc(profitLabels[category]||category)}</td><td class="num">${profitMoney(value)}</td></tr>`).join('');
 byId('profitAmountHeader').textContent='Накоплено, '+profitCurrency;
 byId('profitEvents').textContent=state.events.length?state.events.map(e=>`${profitLabels[e.category]||e.category}: ${profitMoney(e.realized_pnl_native,e.currency)}\n${e.details}\n${e.sources}`).join('\n\n'):'Новых доходов или расходов нет. Между событиями накопленный график не меняется.';
 byId('profitRates').textContent=Object.entries(view.fx_used).map(([c,rate])=>`${c}/USD: ${rate.rate}; дата курса ${rate.rate_date}; ${rate.source}\n${rate.url||''}`).join('\n\n')||'Перевод валют не требуется.';
 if(profitReady)Plotly.relayout('profitChart',{'shapes[0].x0':state.timestamp,'shapes[0].x1':state.timestamp});
}

function exportProfitRows(){const columns=['timestamp','valuation_timestamp','display_currency','cumulative_realized','known_subtotal','native_cumulative','fx_used'];
 const rows=P.profit.states.map(s=>{const v=profitView(s);return [s.timestamp,s.valuation_timestamp,profitCurrency,v.cumulative_realized,v.known_subtotal,JSON.stringify(s.native_cumulative),JSON.stringify(v.fx_used)];});
 return '\uFEFF'+[columns,...rows].map(row=>row.map(csvCell).join(',')).join('\r\n');
}

async function drawProfit(){const data=P.profit;if(!data?.states.length){byId('profitPanel').hidden=true;return;}
 const last=data.states.at(-1),lastView=profitView(last);
 const warnings=data.issues.filter(i=>i.code!=='missing_profit_display_fx').map(i=>i.code==='fx_audit_pnl_excluded'?'Неподтверждённый валютный P/L из аудита исключён. Конвертация основной суммы валюты не считается доходом.':i.details);
 if(last.inferred_count)warnings.unshift('Часть результатов использует явно отмеченную оценённую себестоимость.');
 if(!lastView.complete)warnings.unshift('Не хватает себестоимости или курса отображения. Полный итог недоступен; известная часть отмечена пунктиром.');
 if(data.states.some(s=>!profitView(s).complete)&&lastView.complete)warnings.unshift('На отдельных датах нет курса отображения: график содержит пропуски. Исходные валютные суммы сохранены.');
 if(cashChecks.length)warnings.push('Сохраняются расхождения cash с брокерскими снимками. График показывает результат по имеющимся записям.');
 byId('profitTotal').textContent=lastView.complete?profitMoney(lastView.cumulative_realized):'Полный итог недоступен';
 byId('profitMethod').textContent='Прибыль сделки = выручка минус FIFO-себестоимость и комиссии в валюте инструмента. Доходы и расходы накапливаются в исходных валютах. В выбранную валюту переводится весь накопленный итог по курсу даты события. Учтены результаты фактических валютных сделок и погашения валютного займа; переоценка обычного денежного остатка не считается прибылью. '+(data.short_premium_policy==='closed'?'Премии коротких опционов учтены после закрытия или истечения.':'Премии коротких опционов учтены при получении.');
 byId('profitWarning').textContent=warnings.join(' ');byId('profitWarning').hidden=!warnings.length;
 const dailyEvents=new Map();
 for(const state of data.states){const day=state.timestamp.slice(0,10);dailyEvents.set(day,[...(dailyEvents.get(day)||[]),...state.events]);}
 const profitStates=data.states.filter(s=>s.events.length);
 const profitHoverData=profitStates.map(s=>[profitNative(s),s.valuation_timestamp.slice(0,10),profitOperations(dailyEvents.get(s.timestamp.slice(0,10)))]);
 const traces=[{type:'scatter',mode:'lines',name:'Накопленная прибыль',uid:'realized_profit_total',x:profitStates.map(s=>s.timestamp),y:profitStates.map(s=>profitView(s).cumulative_realized),line:{shape:'hv',width:2,color:'#176f63'},connectgaps:false,customdata:profitHoverData,hovertemplate:`%{x|%Y-%m-%d}<br><b>Накоплено: %{y:,.2f} ${profitCurrency}</b><br>%{customdata[2]}<extra></extra>`}];
 if(!lastView.complete)traces.push({type:'scatter',mode:'lines',name:'Только известная часть',uid:'realized_profit_known',x:profitStates.map(s=>s.timestamp),y:profitStates.map(s=>profitView(s).known_subtotal),line:{shape:'hv',dash:'dot',color:'#ac761d'},customdata:profitHoverData,hovertemplate:`%{x|%Y-%m-%d}<br>Известная часть: %{y:,.2f} ${profitCurrency}<br>%{customdata[2]}<extra></extra>`});
 // Extend the line to account boundaries without making synthetic hover events.
 const first=data.states[0],firstProfit=profitStates[0],lastProfit=profitStates.at(-1);
 const boundaryStates=profitStates.length?[...(first.timestamp!==firstProfit.timestamp?[first,firstProfit,null]:[]),...(lastProfit.timestamp!==last.timestamp?[lastProfit,last]:[])]:[first,last];
 if(boundaryStates.length)for(const trace of [...traces]){
  const field=trace.uid==='realized_profit_total'?'cumulative_realized':'known_subtotal';
  traces.push({type:'scatter',mode:'lines',uid:trace.uid+'_continuation',x:boundaryStates.map(s=>s?.timestamp??null),y:boundaryStates.map(s=>s?profitView(s)[field]:null),line:trace.line,connectgaps:false,hoverinfo:'skip',showlegend:false});
 }
 const graphLayout={margin:{l:85,r:20,t:20,b:65},font:{family:'system-ui',size:12,color:'#233b50'},xaxis:{type:'date',rangeslider:{visible:true,thickness:.1},range:range||undefined},yaxis:{title:{text:'Прибыль, '+profitCurrency},separatethousands:true,zeroline:true,zerolinecolor:'#a9bbc9'},hovermode:'closest',showlegend:!lastView.complete,shapes:[{type:'line',x0:S[index].timestamp,x1:S[index].timestamp,yref:'paper',y0:0,y1:1,line:{color:'#173f64',width:1,dash:'dot'}}]};
 if(profitReady)await Plotly.react('profitChart',traces,graphLayout,{responsive:true,displaylogo:false});
 else{await Plotly.newPlot('profitChart',traces,graphLayout,{responsive:true,displaylogo:false});profitReady=true;byId('profitChart').on('plotly_click',event=>{const at=indexAt(event.points?.[0]?.x);if(at>=0){index=at;showDate();}});}
 showProfitDate(index);
}

if(P.profit){for(const currency of P.profit.currencies){const option=document.createElement('option');option.value=currency;option.textContent=currency;byId('profitCurrency').append(option);}byId('profitCurrency').value=profitCurrency;}
byId('profitCurrency').onchange=async()=>{profitCurrency=byId('profitCurrency').value;await drawProfit();};
byId('exportProfit').onclick=()=>{const url=URL.createObjectURL(new Blob([exportProfitRows()],{type:'text/csv;charset=utf-8'})),a=document.createElement('a');a.href=url;a.download='realized_profit_'+profitCurrency+'.csv';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);};
