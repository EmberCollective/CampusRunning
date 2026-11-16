'use strict';
const $ = id => document.getElementById(id);
const names = {generate:'生成记录',tracks:'轨迹编辑',watch:'手表控制'};
const sampleRecords = [
  {date:'2026-11-13',time:'07:18',km:3.6,seconds:1620,received:false},
  {date:'2026-11-12',time:'06:42',km:4.2,seconds:1890,received:false},
  {date:'2026-11-11',time:'07:06',km:2.8,seconds:1260,received:false},
  {date:'2026-11-10',time:'07:24',km:3.5,seconds:1575,received:true},
  {date:'2026-11-09',time:'06:36',km:4.1,seconds:1845,received:true},
  {date:'2026-11-08',time:'07:12',km:2.6,seconds:1170,received:true},
  {date:'2026-11-07',time:'06:54',km:3.4,seconds:1530,received:true},
  {date:'2026-11-06',time:'07:32',km:3.2,seconds:1440,received:true}
];
let records=sampleRecords.map(r=>({...r})), watchState='waiting', filter='all', mode='daily', draftRecords=[], candidateRecords=null, generatedFormat='b5', resultsStale=false, toastTimer;
let calendarMonth='2026-11';
const selectedDates=new Set(['2026-11-13','2026-11-14','2026-11-15']);
const settings={transport:'netsim',btvs:'',tshark:'',map:0};
const cloneRecords=rows=>rows.map(r=>({...r}));
function notify(message){$('toast').textContent=message;$('toast').hidden=false;clearTimeout(toastTimer);toastTimer=setTimeout(()=>{$('toast').hidden=true;},4500);}
function showInfo(title,message){$('feedback-title').textContent=title;$('feedback-copy').textContent=message;$('feedback-dialog').showModal();}
function timeLabel(seconds){return `${Math.floor(seconds/60)}:${String(seconds%60).padStart(2,'0')}`;}
function navigate(){
  const page=Object.hasOwn(names,location.hash.slice(1))?location.hash.slice(1):'watch';
  for(const key of Object.keys(names)){ $('page-'+key).hidden=key!==page;const link=document.querySelector(`[data-nav="${key}"]`);if(key===page)link.setAttribute('aria-current','page');else link.removeAttribute('aria-current'); }
  document.title=`${names[page]} · CampusRunning 界面草稿`;
  $('status-context').textContent=page==='tracks'?'节点编辑与模板变换仅保留在本页':page==='generate'?'设置 → 预览结果 → 下载或载入':'广播可用 → Keep 连接 → 文件接收 → 活动核对';
  if(page==='generate')renderRoutePreview();
}
function resetFilter(){filter='all';document.querySelectorAll('[data-filter]').forEach(button=>button.setAttribute('aria-pressed',String(button.dataset.filter==='all')));}
function renderRecords(){
  const visible=records.filter(r=>filter==='all'||(filter==='received'?r.received:!r.received));
  $('watch-records').replaceChildren();
  for(const record of visible){
    const row=document.createElement('tr'),date=document.createElement('td');date.textContent=record.date;
    const time=document.createElement('span');time.className='date-time num';time.textContent=record.time;date.append(time);row.append(date);
    for(const value of [record.km.toFixed(2),timeLabel(record.seconds)]){const cell=document.createElement('td');cell.className='num';cell.textContent=value;row.append(cell);}
    const status=document.createElement('td'),label=document.createElement('span');label.className='pill'+(record.received?' positive':'');label.textContent=record.received?'已接收':'待接收';status.append(label);row.append(status);$('watch-records').append(row);
  }
  const pending=records.filter(r=>!r.received).length,received=records.length-pending;
  for(const [id,value] of Object.entries({'all-count':records.length,'pending-count':pending,'received-count':received,'tab-pending':pending,'tab-received':received,'total-km':records.reduce((sum,r)=>sum+r.km,0).toFixed(2),'visible-record-count':`${visible.length} 条记录`}))$(id).textContent=value;
  $('empty-records').hidden=visible.length>0;$('empty-action').hidden=records.length>0;
  $('empty-title').textContent=records.length?'这个分类没有记录':'还没有载入记录';$('empty-copy').textContent=records.length?'切换到“全部”查看本批记录':'先生成 B5 手表记录，再载入这里';
  $('candidate').hidden=!candidateRecords;$('candidate-count').textContent=candidateRecords?.length||0;
  const blocked=pending>0||watchState==='error'||watchState==='unsupported';
  $('load-candidate').disabled=blocked;$('load-blocked').hidden=!blocked;
  $('load-blocked').textContent=pending?'当前还有待接收记录，完成后再载入下一批':watchState==='unsupported'?'当前连接路线尚未接入手表面板':'状态未知，恢复本地服务后重新检查';
  $('step-load').className='step'+(records.length?' done':' current');$('step-load-title').textContent=records.length?'记录已载入':'先生成并载入记录';$('step-loaded').textContent=records.length?`${records.length} 条记录，源文件保留`:'空目录可以先连接，不会发送活动';
  $('step-receipt-copy').textContent=pending?`剩余 ${pending} 条，等待 Keep 读取`:records.length?'本批文件接收完成，请核对活动':'载入并连接后再接收';
}
function renderWatch(next){
  watchState=settings.transport==='netsim'?next:'unsupported';
  const states={
    waiting:['等待 Keep 连接','虚拟广播已开启，请在同一已准备好的模拟器里连接 B5','待连接'],
    connected:['已连接 Keep','连接已建立，等待 Keep 读取文件；是否接收以列表为准','已连接'],
    complete:['本批文件已接收','文件已接收，请在 Keep 对应日期核对活动来源、有效性和统计','已接收'],
    stopped:['广播已停止','记录和接收标记保留。重新启动后，再到 Keep 中检查连接','已停止'],
    empty:['等待 Keep 连接','当前为空目录，连接不会产生或发送运动活动','待连接'],
    error:['连接状态未知','无法读取本地服务。记录仍保留，重新检查前不显示为已连接','状态未知'],
    address:['广播地址未知','广播已启动，但本轮可填写地址尚未确认；不要填写旧地址','地址未知'],
    unsupported:['连接路线尚未接入','已预留所选环境的配置位置，当前面板还不能启动这条连接路线','待接入']
  };
  const [title,help,nav]=states[watchState];$('connection-text').textContent=title;$('connection-help').textContent=help;$('nav-status').textContent=nav;
  $('device-mode').textContent={netsim:'安卓模拟器 · 虚拟广播',windows:'Windows 实体蓝牙 · 待接入',other:'其他传输 / 兼容层 · 待接入'}[settings.transport];
  $('connection-pill').className='pill'+(['connected','complete'].includes(watchState)?' positive':['waiting','empty'].includes(watchState)?' waiting':'');
  const addressKnown=['waiting','connected','complete','empty'].includes(watchState);
  $('sample-mac').textContent=addressKnown?'C27A4D910B68':'—';$('dialog-mac').textContent=$('sample-mac').textContent;
  $('copy-address').disabled=!addressKnown;$('dialog-copy').disabled=!addressKnown;
  $('settings-binding-address').textContent=addressKnown?'C2:7A:4D:91:0B:68 · 虚拟':'未知 / 已失效';
  $('address-medium').textContent=addressKnown?'虚拟地址':settings.transport==='windows'?'实体地址待观察':'地址不可用';
  $('address-help').textContent=addressKnown?'附近实体手机看不到这个虚拟地址':'不使用设备身份或电脑永久地址代替';
  $('toggle-broadcast').disabled=['error','unsupported'].includes(watchState);$('toggle-broadcast').querySelector('span').textContent=watchState==='stopped'?'启动广播':'停止广播';$('toggle-broadcast').querySelector('use').setAttribute('href',watchState==='stopped'?'#i-play':'#i-stop');
  $('state-warning').hidden=watchState!=='error';
  $('step-connect').className='step'+(['connected','complete'].includes(watchState)?' done':records.length&&!['error','unsupported'].includes(watchState)?' current':'');
  $('step-connect-title').textContent=watchState==='stopped'?'先重新启动广播':watchState==='address'?'等待确认本轮地址':watchState==='unsupported'?'先完成该路线接入':watchState==='error'?'先恢复状态读取':['connected','complete'].includes(watchState)?'Keep 已连接':'在 Keep 里连接 B5';
  $('step-connect-copy').textContent=['connected','complete'].includes(watchState)?'连接与文件接收分开核对':'使用当前有效地址，避免复用过期地址';
  $('step-receipt').className='step'+(watchState==='connected'?' current':watchState==='complete'?' done':'');$('step-receipt-title').textContent=watchState==='complete'?'本批文件已接收':'等 Keep 接收文件';
  if(watchState!=='unsupported')$('preview-state').value=watchState;
  renderRecords();
}
function setScenario(state){records=state==='empty'?[]:sampleRecords.map(r=>({...r,received:state==='complete'||r.received}));resetFilter();renderWatch(state);}
function markStale(){if(!draftRecords.length)return;resultsStale=true;$('result-next').disabled=true;$('result-summary').textContent='参数已修改，重新预览后再下载或载入';}
function renderAdvanced(){const total=mode==='total',file=$('output-format').value!=='b5';for(const id of ['rest-days','weekend-factor']){$(id).parentElement.hidden=!total;$(id).disabled=!total;}$('output-directory').parentElement.hidden=!file;$('output-directory').disabled=!file;$('advanced-section').hidden=!total&&!file;}
function setMode(next){
  mode=next;document.querySelectorAll('[data-mode]').forEach(button=>button.setAttribute('aria-pressed',String(button.dataset.mode===mode)));
  $('start-date-field').hidden=mode==='dates';$('end-date-field').hidden=['single','dates'].includes(mode);$('calendar-field').hidden=mode!=='dates';$('distance-range-field').hidden=['single','total'].includes(mode);$('total-distance-field').hidden=mode!=='total';$('single-distance-field').hidden=mode!=='single';
  document.querySelector('label[for="start-date"]').textContent=mode==='single'?'运动日期':'开始日期';
  $('mode-heading').textContent={daily:'日期与每日里程',total:'日期与总里程',single:'单次运动',dates:'选择运动日期'}[mode];
  for(const id of ['start-date','end-date','min-distance','max-distance','total-distance','single-distance'])$(id).disabled=$(id).closest('.fields > div').hidden;
  renderAdvanced();updatePlanCount();markStale();
}
function isoDate(value){return value.toISOString().slice(0,10);}
function monthShift(month,delta){const date=new Date(month+'-01T12:00:00Z');date.setUTCMonth(date.getUTCMonth()+delta);return isoDate(date).slice(0,7);}
function renderCalendar(focusDate){
  $('calendar-month').value=calendarMonth;
  const grid=$('calendar');grid.replaceChildren();for(const text of ['一','二','三','四','五','六','日']){const day=document.createElement('span');day.className='weekday';day.textContent=text;grid.append(day);}
  const first=new Date(calendarMonth+'-01T12:00:00Z'),offset=(first.getUTCDay()+6)%7;
  const end=new Date(first);end.setUTCMonth(end.getUTCMonth()+1);end.setUTCDate(0);
  const count=Math.ceil((offset+end.getUTCDate())/7)*7;
  const focus=focusDate||[...selectedDates].sort().find(date=>date.startsWith(calendarMonth))||calendarMonth+'-01';
  for(let index=0;index<count;index++){
    const date=new Date(first);date.setUTCDate(1-offset+index);const iso=isoDate(date),button=document.createElement('button');
    button.type='button';button.className='day'+(!iso.startsWith(calendarMonth)?' other-month':'');button.textContent=date.getUTCDate();button.dataset.date=iso;button.disabled=iso<'2000-01-01'||iso>'2099-12-31';button.tabIndex=iso===focus?0:-1;button.setAttribute('aria-label',`${date.getUTCFullYear()} 年 ${date.getUTCMonth()+1} 月 ${date.getUTCDate()} 日`);button.setAttribute('aria-pressed',String(selectedDates.has(iso)));
    button.addEventListener('click',()=>{if(selectedDates.has(iso))selectedDates.delete(iso);else selectedDates.add(iso);if(iso.slice(0,7)!==calendarMonth)calendarMonth=iso.slice(0,7);renderCalendar(iso);grid.querySelector(`[data-date="${iso}"]`)?.focus();markStale();});
    button.addEventListener('keydown',event=>{const delta={ArrowLeft:-1,ArrowRight:1,ArrowUp:-7,ArrowDown:7}[event.key];if(delta===undefined)return;event.preventDefault();const next=new Date(iso+'T12:00:00Z');next.setUTCDate(next.getUTCDate()+delta);const target=isoDate(next);if(target<'2000-01-01'||target>'2099-12-31')return;calendarMonth=target.slice(0,7);renderCalendar(target);grid.querySelector(`[data-date="${target}"]`)?.focus();});
    grid.append(button);
  }
  $('previous-month').disabled=calendarMonth<='2000-01';$('next-month').disabled=calendarMonth>='2099-12';
  $('calendar-count').textContent=`已选 ${selectedDates.size} 天 · 本月 ${[...selectedDates].filter(date=>date.startsWith(calendarMonth)).length} 天`;
  $('selected-dates').replaceChildren();for(const date of [...selectedDates].sort()){const chip=document.createElement('span');chip.className='date-chip';chip.append(document.createTextNode(date));const remove=document.createElement('button');remove.type='button';remove.textContent='×';remove.setAttribute('aria-label',`移除 ${date}`);remove.addEventListener('click',()=>{selectedDates.delete(date);renderCalendar();markStale();$('calendar-month').focus();});chip.append(remove);$('selected-dates').append(chip);}
  updatePlanCount();
}
function dateList(){
  if(mode==='dates')return [...selectedDates].sort();
  const start=$('start-date').value,end=mode==='single'?start:$('end-date').value;if(!start||!end)throw new Error('请填写运动日期');if(start>end)throw new Error('结束日期不能早于开始日期');
  const cursor=new Date(start+'T12:00:00Z'),stop=new Date(end+'T12:00:00Z'),days=[];while(cursor<=stop&&days.length<=64){days.push(isoDate(cursor));cursor.setUTCDate(cursor.getUTCDate()+1);}return days;
}
function updatePlanCount(){try{const count=dateList().length;$('plan-count').textContent=count>64?'超过 64 天':`${count} 天`;}catch{$('plan-count').textContent='请检查日期';}}
function generationError(message,id){$('generation-error').textContent=message;$('generation-error').hidden=false;if(id)$(id).focus();notify(message);}
function generatePreview(event){
  event.preventDefault();let days;try{days=dateList();}catch(error){generationError(error.message,'end-date');return;}
  if(window.DraftEditor&&window.DraftEditor.get($('track-choice').value).points.length<3){generationError('所选轨迹至少需要 3 个节点，请先在轨迹编辑器中补全','track-choice');return;}
  if(!days.length){generationError('请至少选择一个运动日期','calendar-month');return;}if(days.length>64){generationError('草稿最多预览 64 条记录，请缩短日期范围');return;}
  if(['daily','dates'].includes(mode)&&Number($('min-distance').value)>Number($('max-distance').value)){generationError('最低公里数不能大于最高公里数','min-distance');return;}
  if(Number($('min-pace').value)>Number($('max-pace').value)){generationError('最快配速的用时不能大于最慢配速','min-pace');return;}
  if($('earliest-time').value>$('latest-time').value){generationError('最早开始时间不能晚于最晚开始时间','earliest-time');return;}
  const km=mode==='single'?Number($('single-distance').value):mode==='total'?Number($('total-distance').value)/days.length:(Number($('min-distance').value)+Number($('max-distance').value))/2,pace=(Number($('min-pace').value)+Number($('max-pace').value))/2;
  draftRecords=days.map(date=>({date,time:$('earliest-time').value,km,seconds:Math.round(km*pace*60),received:false}));generatedFormat=$('output-format').value;resultsStale=false;
  $('result-rows').replaceChildren();for(const record of draftRecords){const row=document.createElement('tr');for(const [index,value]of[record.date,record.km.toFixed(2),timeLabel(record.seconds),timeLabel(Math.round(pace*60))].entries()){const cell=document.createElement('td');cell.textContent=value;if(index===1||index===2)cell.className='num';row.append(cell);}$('result-rows').append(row);}
  $('result-summary').textContent=`${days.length} 条示例 · ${(km*days.length).toFixed(2)} km · ${generatedFormat==='b5'?'B5 手表':generatedFormat.toUpperCase()}`;$('result-count').textContent=`${days.length} 条`;$('result-next').firstChild.textContent=generatedFormat==='b5'?'载入手表':'下载文件';$('result-next').disabled=false;$('result-table').hidden=false;$('empty-results').hidden=true;$('generation-error').hidden=true;
  if(innerWidth<=760)$('generation-results').scrollIntoView({block:'nearest'});notify('已更新示例结果，未生成真实文件');
}
function renderRoutePreview(){
  if(!window.DraftEditor)return;const track=window.DraftEditor.get($('track-choice').value);$('preview-track-name').textContent=track.name||'未命名轨迹';$('preview-track-distance').textContent=`${(track.distance/1000).toFixed(2)} km`;$('preview-track-points').textContent=track.points.length;$('preview-track-direction').textContent=track.direction;
  $('generator-route').setAttribute('d',track.points.length?'M'+track.points.map(p=>`${p.x},${p.y}`).join('L')+(track.points.length>2?'Z':''):'');
  const preview=$('generator-route').ownerSVGElement,rect=preview.getBoundingClientRect(),bounds=SelectionGeometry.bounds(track.points);
  if(bounds&&rect.width&&rect.height){const aspect=rect.width/rect.height,height=Math.max(240,bounds.height*1.5,bounds.width*1.5/aspect),width=height*aspect;preview.setAttribute('viewBox',`${bounds.x-width/2} ${bounds.y-height/2} ${width} ${height}`);}
}
async function copyAddress(){if($('copy-address').disabled)return;try{await navigator.clipboard.writeText($('sample-mac').textContent);notify('示例地址已复制，请勿用于真实绑定');}catch{showInfo('请手动复制示例地址',`示例地址：${$('sample-mac').textContent}。浏览器未允许自动复制，可选择文字复制；请勿用于真实绑定。`);}}
function selectSettingsTab(tab){for(const key of ['broadcast','compatibility','maps']){$('setting-'+key).hidden=key!==tab;document.querySelector(`[data-setting-tab="${key}"]`).setAttribute('aria-pressed',String(key===tab));}}
function updateTransportFields(){for(const name of ['netsim','windows','other'])$(name+'-options').hidden=$('transport-choice').value!==name;}
function openSettings(tab='broadcast'){$('transport-choice').value=settings.transport;$('btvs-path').value=settings.btvs;$('tshark-path').value=settings.tshark;$('map-provider').selectedIndex=settings.map;updateTransportFields();selectSettingsTab(tab);$('settings-dialog').showModal();}
document.querySelectorAll('[data-close-dialog]').forEach(button=>button.addEventListener('click',()=>button.closest('dialog').close()));
document.querySelectorAll('[data-dialog]').forEach(button=>button.addEventListener('click',()=>$(button.dataset.dialog).showModal()));
document.querySelectorAll('[data-mode]').forEach(button=>button.addEventListener('click',()=>setMode(button.dataset.mode)));
document.querySelectorAll('[data-filter]').forEach(button=>button.addEventListener('click',()=>{filter=button.dataset.filter;document.querySelectorAll('[data-filter]').forEach(item=>item.setAttribute('aria-pressed',String(item===button)));renderRecords();}));
$('preview-state').addEventListener('change',event=>setScenario(event.target.value));$('toggle-broadcast').addEventListener('click',()=>{renderWatch(watchState==='stopped'?'waiting':'stopped');notify('已切换示例广播状态，未操作真实蓝牙');});$('retry-status').addEventListener('click',()=>{renderWatch('waiting');notify('已恢复等待连接示例，未检查真实服务');});
$('copy-address').addEventListener('click',copyAddress);$('dialog-copy').addEventListener('click',copyAddress);
$('generate-form').addEventListener('submit',generatePreview);$('generate-form').addEventListener('input',()=>{markStale();updatePlanCount();});$('generate-form').addEventListener('change',markStale);
$('output-format').addEventListener('change',()=>{$('format-note').textContent=$('output-format').value==='b5'?'先检查生成结果，再由你点击载入手表':$('output-format').value==='fit'?'下载文件后自行导入；此方式不会载入手表':'通用运动格式；现有 Keep 导入通道不解析其中的步频';renderAdvanced();});
$('result-next').addEventListener('click',()=>{if(resultsStale||!draftRecords.length)return;if(generatedFormat!=='b5'){showInfo('文件下载入口示意','正式界面在这里下载生成文件。草稿没有生成 FIT / TCX 文件，不会开始下载。');return;}candidateRecords=cloneRecords(draftRecords);renderRecords();location.hash='watch';});
$('load-candidate').addEventListener('click',()=>{if(!candidateRecords||records.some(r=>!r.received)||['error','unsupported'].includes(watchState))return;records=cloneRecords(candidateRecords);candidateRecords=null;resetFilter();renderWatch('waiting');notify('已预览新一批载入后的界面，未启动真实同步');});
$('save-template').addEventListener('click',()=>showInfo('导出参数模板','正式界面在这里命名并下载当前参数。草稿保留输入，不写入或下载文件。'));
$('template-choice').addEventListener('change',()=>{if($('template-choice').value==='morning'){for(const [id,value]of Object.entries({'min-distance':2,'max-distance':5,'min-pace':7,'max-pace':8,'earliest-time':'06:00','latest-time':'08:00'}))$(id).value=value;markStale();notify('已套用示例晨跑参数，可继续修改');}});
for(const [id,delta]of[['previous-month',-1],['next-month',1]])$(id).addEventListener('click',()=>{calendarMonth=monthShift(calendarMonth,delta);renderCalendar();});
$('calendar-month').addEventListener('change',()=>{if($('calendar-month').checkValidity()&&$('calendar-month').value){calendarMonth=$('calendar-month').value;renderCalendar();}});$('current-month').addEventListener('click',()=>{calendarMonth='2026-11';renderCalendar();});$('clear-dates').addEventListener('click',()=>{selectedDates.clear();renderCalendar();markStale();});
$('open-settings').addEventListener('click',()=>openSettings());$('watch-settings').addEventListener('click',()=>openSettings());$('open-map-settings').addEventListener('click',()=>openSettings('maps'));
document.querySelectorAll('[data-setting-tab]').forEach(button=>button.addEventListener('click',()=>selectSettingsTab(button.dataset.settingTab)));$('transport-choice').addEventListener('change',updateTransportFields);
$('apply-settings').addEventListener('click',()=>{const next=$('transport-choice').value,transportChanged=next!==settings.transport;if(transportChanged&&!['stopped','unsupported'].includes(watchState)){notify('先停止广播并确认状态，再切换连接路线；当前文件会保留');return;}settings.transport=next;settings.btvs=$('btvs-path').value;settings.tshark=$('tshark-path').value;settings.map=$('map-provider').selectedIndex;$('settings-dialog').close();if(transportChanged)renderWatch(next==='netsim'?'stopped':'unsupported');notify('设置已应用到页面草稿，未修改系统环境');});
$('settings-dialog').addEventListener('close',()=>{$('map-key').value='';$('map-security-key').value='';});$('preview-environment-check').addEventListener('click',()=>{notify('环境检查入口已预留；静态稿没有运行检测，不标记为通过');});
$('map-search-form').addEventListener('submit',event=>{event.preventDefault();showInfo('地点搜索入口预览','正式界面沿用已有地址搜索与地图配置。草稿未连接在线地图，不执行地点搜索；输入内容仍保留。');});
$('map-style').addEventListener('change',()=>notify('已预览底图选择控件；画布保持示意地图，未请求地图服务'));
window.addEventListener('hashchange',()=>{navigate();const page=location.hash.slice(1);if(Object.hasOwn(names,page))$(page==='watch'?'watch-title':page==='tracks'?'tracks-title':'generate-title').focus({preventScroll:true});});
new ResizeObserver(()=>renderRoutePreview()).observe($('generator-route').ownerSVGElement);
setMode('daily');renderCalendar();renderWatch('waiting');navigate();
