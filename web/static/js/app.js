'use strict';
const Generator = (() => {
let mode='daily', result=null, generatedFormat='fit', resultsStale=false, busy=false, revision=0, templateSeq=0;
let tracks=[], templates=[], localTemplates={};
let calendarMonth=new Date().toISOString().slice(0,7);
const selectedDates=new Set();
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
function dayCount() {
    if (mode === 'dates') return selectedDates.size;
    const start = $('start-date').value, end = mode === 'single' ? start : $('end-date').value;
    if (!start || !end || start > end) throw new Error('结束日期不能早于开始日期');
    return Math.round((Date.parse(end + 'T12:00:00Z') - Date.parse(start + 'T12:00:00Z')) / 86400000) + 1;
}
function updatePlanCount() {
    try { $('plan-count').textContent = `${dayCount()} 天`; }
    catch { $('plan-count').textContent = '请检查日期'; }
}
function markStale() {
    revision++;
    if (!result) return;
    resultsStale = true;
    $('result-next').disabled = true;
    $('result-summary').textContent = '参数已修改，重新生成后再下载或载入';
}
function renderAdvanced() {
    renderPaceOptions();
    const b5 = $('output-format').value === 'b5';
    for (const id of ['rest-days', 'weekend-factor', 'min-daily', 'max-daily']) {
        $(id).parentElement.hidden = mode !== 'total';
        $(id).disabled = mode !== 'total';
    }
    $('output-directory').parentElement.hidden = b5;
    $('output-directory').disabled = b5;
    $('advanced-section').hidden = b5 && mode !== 'total';
    for (const id of ['include-track', 'apply-correction', 'enable-cadence']) {
        if (b5) $(id).checked = true;
        $(id).disabled = b5;
    }
    $('b5-required').hidden = !b5;
    $('format-note').textContent = b5 ? '先检查生成结果，再由你点击载入手表' :
        $('output-format').value === 'fit' ? '下载文件后自行导入；此方式不会载入手表' : '通用运动格式；Keep 文件导入不解析其中的步频';
}
function setMode(next) {
    mode = next;
    document.querySelectorAll('[data-mode]').forEach(button => button.setAttribute('aria-pressed', String(button.dataset.mode === mode)));
    $('start-date-field').hidden = mode === 'dates';
    $('end-date-field').hidden = mode === 'single' || mode === 'dates';
    $('calendar-field').hidden = mode !== 'dates';
    $('distance-range-field').hidden = mode === 'single' || mode === 'total';
    $('total-distance-field').hidden = mode !== 'total';
    $('single-distance-field').hidden = mode !== 'single';
    document.querySelector('label[for="start-date"]').textContent = mode === 'single' ? '运动日期' : '开始日期';
    $('mode-heading').textContent = { daily: '日期与每日里程', total: '日期与总里程', single: '单次运动', dates: '选择运动日期' }[mode];
    for (const id of ['start-date', 'end-date', 'min-distance', 'max-distance', 'total-distance', 'single-distance'])
        $(id).disabled = $(id).closest('.fields > div').hidden;
    renderAdvanced(); updatePlanCount(); markStale();
}
async function refreshTracks(selected) {
    const list = await requestJSON('/api/tracks');
    tracks = list;
    const chosen = selected || $('track-choice').value;
    $('track-choice').replaceChildren(...list.map(t => new Option(t.name, t.id)));
    if (list.some(t => t.id === chosen)) $('track-choice').value = chosen;
    if (!list.length) $('track-choice').add(new Option('轨迹库为空，请先创建轨迹', ''));
    updatePreview();
    if (result) markStale();
    return list;
}
function updatePreview() {
    const track = tracks.find(t => t.id === $('track-choice').value);
    if (!track) { TrackPreview.reset(); return; }
    TrackPreview.show(track.id, track);
}
function collect() {
    const value = id => Number($(id).value);
    const data = { track_id: $('track-choice').value, min_pace: value('min-pace'), max_pace: value('max-pace'),
        start_time_min: $('earliest-time').value, start_time_max: $('latest-time').value,
        output_format: $('output-format').value, output_dir: $('output-directory').value || 'output',
        include_track: $('include-track').checked, apply_correction: $('apply-correction').checked,
        enable_pace_fluctuation: $('pace-fluctuation').checked, enable_cadence: $('enable-cadence').checked,
        pace_algorithm: $('pace-algorithm').value, pace_intensity: value('pace-intensity') };
    if (mode === 'dates') Object.assign(data, { dates: [...selectedDates].sort(), min_km: value('min-distance'), max_km: value('max-distance') });
    else if (mode === 'single') Object.assign(data, { date: $('start-date').value, distance: value('single-distance') });
    else {
        Object.assign(data, { start_date: $('start-date').value, end_date: $('end-date').value });
        if (mode === 'daily') Object.assign(data, { min_km: value('min-distance'), max_km: value('max-distance') });
        else Object.assign(data, { total_km: value('total-distance'), min_daily_km: value('min-daily'),
            max_daily_km: value('max-daily'), weekend_factor: value('weekend-factor'), rest_days_per_week: value('rest-days') });
    }
    return data;
}
function generationError(message) {
    $('generation-error').textContent = message;
    $('generation-error').hidden = false;
    notify(message);
}
function validate(data) {
    const count = dayCount();
    if (!count) throw new Error('请至少选择一个运动日期');
    if (!data.track_id) throw new Error('请先选择一条轨迹');
    if (data.output_format === 'b5' && count > 64) throw new Error('B5 每批最多 64 天，请缩短日期范围');
    if (data.min_km > data.max_km) throw new Error('最低公里数不能大于最高公里数');
    if (data.min_daily_km > data.max_daily_km) throw new Error('每日最低公里数不能大于最高公里数');
    if (data.min_pace > data.max_pace) throw new Error('最快配速的用时不能大于最慢配速');
    if (data.start_time_min > data.start_time_max) throw new Error('最早开始不能晚于最晚开始');
}
function renderResults() {
    $('result-rows').replaceChildren();
    for (const record of result.files) {
        const row = document.createElement('tr');
        [record.date, record.distance_km.toFixed(2), timeLabel(record.duration_seconds), timeLabel(record.pace_min_per_km * 60)].forEach((value, index) => {
            const cell = document.createElement('td'); cell.textContent = value;
            if (index === 1 || index === 2) cell.className = 'num'; row.append(cell);
        });
        $('result-rows').append(row);
    }
    $('result-table').hidden = false; $('empty-results').hidden = true;
    $('result-summary').textContent = `${result.files.length} 条记录 · ${result.files.reduce((sum, r) => sum + r.distance_km, 0).toFixed(2)} km · ${generatedFormat === 'b5' ? 'B5 手表' : generatedFormat.toUpperCase()}`;
    $('result-count').textContent = `${result.files.length} 条`;
    $('result-next').firstChild.textContent = generatedFormat === 'b5' ? '载入手表' : '下载文件';
    $('result-next').disabled = !result.files.length || resultsStale;
    $('result-table').closest('.table-scroll').scrollTop = 0;
}
async function generate(event) {
    event.preventDefault();
    if (busy) return;
    const data = collect();
    try { validate(data); } catch (error) { generationError(error.message); return; }
    const startRevision = revision;
    busy = true; result = null; resultsStale = true;
    $('generate-button').disabled = true; $('result-next').disabled = true; $('generation-error').hidden = true;
    $('generate-button').firstChild.textContent = '正在生成…';
    notify('正在生成本地文件，完成前请保留此页面', 'loading');
    try {
        result = await postJSON('/api/generate/' + mode, data, 180000);
        generatedFormat = data.output_format; resultsStale = false;
        renderResults();
        if (startRevision !== revision) markStale();
        notify(`已生成 ${result.files.length} 条记录，尚未载入手表`);
        if (innerWidth <= 760) $('generation-results').scrollIntoView({ block: 'nearest' });
    } catch (error) {
        result = null;
        generationError(error.name === 'TimeoutError' ? '生成等待超时，文件结果未知；请先检查输出目录再重试' : '生成未完成：' + error.message);
        $('result-summary').textContent = '本次生成未完成，检查参数后重试';
    } finally {
        busy = false; $('generate-button').disabled = false; $('generate-button').firstChild.textContent = '生成并查看结果';
    }
}
async function nextResult() {
    if (!result || resultsStale) return;
    if (generatedFormat === 'b5') {
        WatchPanel.setCandidate({ id: result.job_id, count: result.files.length,
            km: result.files.reduce((sum, row) => sum + row.distance_km, 0) });
        location.hash = 'watch';
        return;
    }
    $('result-next').disabled = true;
    try {
        const response = await fetch('/api/download/' + encodeURIComponent(result.job_id), { signal: AbortSignal.timeout(60000) });
        if (!response.ok) throw new Error((await response.json()).error || '文件下载失败');
        const blob = await response.blob();
        downloadBlob(blob, result.files.length === 1 ? result.files[0].filename : result.job_id + '.zip');
        notify('下载已开始');
    } catch (error) { notify('下载未完成：' + error.message); }
    finally { $('result-next').disabled = resultsStale; }
}
function downloadBlob(blob, filename) {
    const url = URL.createObjectURL(blob), link = document.createElement('a');
    link.href = url; link.download = filename; link.click(); setTimeout(() => URL.revokeObjectURL(url), 10000);
}
function cacheTemplate(template) {
    localTemplates = { ...localTemplates, [template.id]: template };
    try { localStorage.setItem('template_cache', JSON.stringify(localTemplates)); }
    catch { notify('模板已在本页导入；浏览器无法保留模板，请保管下载的 JSON'); }
}
function renderTemplates(selected = '') {
    const select = $('template-choice');
    select.replaceChildren(new Option('自定义参数', ''), new Option('导入模板…', '__upload__'));
    for (const group of [{ label: '预设模板', rows: templates, prefix: 'server:' }, { label: '本地模板', rows: Object.values(localTemplates), prefix: 'local:' }]) {
        if (!group.rows.length) continue;
        const el = document.createElement('optgroup'); el.label = group.label;
        for (const template of group.rows) el.append(new Option(template.name, group.prefix + template.id));
        select.append(el);
    }
    select.value = selected;
}
function applyTemplate(template) {
    if (!template || typeof template !== 'object' || Array.isArray(template)) throw new Error('模板必须是 JSON 对象');
    const next = ['daily', 'total', 'single', 'dates'].find(key => template[key + '_config'] && Object.keys(template[key + '_config']).length);
    if (next) setMode(next);
    const config = template[mode + '_config'] || template.generation_config || {};
    if (config.pace_algorithm && ![...$('pace-algorithm').options].some(o => o.value === config.pace_algorithm))
        throw new Error('模板中的配速算法尚未注册，请先在本机注册该算法');
    $('pace-algorithm').value = config.pace_algorithm || 'natural';
    $('pace-intensity').value = config.pace_intensity ?? .15;
    const fields = { min_pace: 'min-pace', max_pace: 'max-pace', start_time_min: 'earliest-time', start_time_max: 'latest-time',
        start_date: 'start-date', end_date: 'end-date', date: 'start-date', distance: 'single-distance',
        min_km: 'min-distance', max_km: 'max-distance', total_km: 'total-distance', min_daily_km: 'min-daily',
        max_daily_km: 'max-daily', rest_days_per_week: 'rest-days', weekend_factor: 'weekend-factor', output_dir: 'output-directory' };
    for (const [key, id] of Object.entries(fields)) if (['number', 'string'].includes(typeof config[key])) $(id).value = config[key];
    if (config.pace !== undefined) $('min-pace').value = $('max-pace').value = config.pace;
    for (const [key, id] of [['start_hour_min', 'earliest-time'], ['start_hour_max', 'latest-time']])
        if (config[key] !== undefined && Number.isInteger(config[key]) && config[key] >= 0 && config[key] < 24) $(id).value = `${String(config[key]).padStart(2, '0')}:00`;
    for (const [key, id] of [['include_track', 'include-track'], ['apply_correction', 'apply-correction'], ['enable_pace_fluctuation', 'pace-fluctuation'], ['enable_cadence', 'enable-cadence']])
        if (typeof config[key] === 'boolean') $(id).checked = config[key];
    if ([...$('output-format').options].some(o => o.value === config.output_format)) $('output-format').value = config.output_format;
    const trackId = template.track_id || config.track_id;
    if (tracks.some(t => t.id === trackId)) $('track-choice').value = trackId;
    if (Array.isArray(config.dates)) {
        selectedDates.clear();
        for (const date of config.dates) if (typeof date === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(date) && date >= '2000-01-01' && date <= '2099-12-31' && isoDate(new Date(date + 'T12:00:00Z')) === date) selectedDates.add(date);
        if (selectedDates.size) calendarMonth = [...selectedDates].sort()[0].slice(0, 7);
    }
    renderAdvanced(); renderCalendar(); updatePreview(); markStale();
}
async function chooseTemplate() {
    const value = $('template-choice').value, seq = ++templateSeq;
    if (value === '__upload__') { $('template-choice').value = ''; $('template-upload').click(); return; }
    if (!value) return;
    try {
        const template = value.startsWith('local:') ? localTemplates[value.slice(6)] : await requestJSON('/api/template/' + encodeURIComponent(value.slice(7)));
        if (seq !== templateSeq) return;
        applyTemplate(template); notify('参数模板已应用，可继续修改');
    } catch (error) { notify('模板未应用：' + error.message); }
}
async function init() {
    const now = new Date(), today = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(now.getDate()).padStart(2, '0')}`;
    $('start-date').value = today.slice(0, 7) + '-01'; $('end-date').value = today;
    calendarMonth = today.slice(0, 7); selectedDates.add(today);
    try {
        const stored = JSON.parse(localStorage.getItem('template_cache') || '{}');
        if (stored && typeof stored === 'object' && !Array.isArray(stored))
            localTemplates = Object.fromEntries(Object.entries(stored).filter(([, value]) => value && typeof value.id === 'string' && typeof value.name === 'string'));
    } catch { localTemplates = {}; }
    const loaded = await Promise.allSettled([refreshTracks(), requestJSON('/api/templates'), requestJSON('/api/defaults'), requestJSON('/api/pace/algorithms')]);
    if (loaded[3].status === 'fulfilled') {
        $('pace-algorithm').replaceChildren(...loaded[3].value.map(a => {
            const option = new Option(a.name, a.id); option.dataset.description = a.description; return option;
        }));
    } else notify('配速算法列表读取失败，当前可使用自然慢跑；刷新页面后重试');
    if (loaded[0].status === 'rejected') generationError('无法读取轨迹库，请恢复服务后刷新页面');
    if (loaded[1].status === 'fulfilled') templates = loaded[1].value;
    else notify('预设模板读取失败，本地模板仍可使用');
    if (loaded[2].status === 'fulfilled') {
        const d = loaded[2].value;
        if ([...$('pace-algorithm').options].some(o => o.value === d.pace_algorithm)) $('pace-algorithm').value = d.pace_algorithm;
        $('pace-intensity').value = d.pace_intensity ?? .15;
        if (d.default_pace_range) [$('min-pace').value, $('max-pace').value] = d.default_pace_range;
        if (d.default_start_time_range) [$('earliest-time').value, $('latest-time').value] = d.default_start_time_range;
        if (tracks.some(t => t.id === d.default_track_id)) $('track-choice').value = d.default_track_id;
        for (const [key, id] of [['weekend_factor', 'weekend-factor'], ['rest_days_per_week', 'rest-days'], ['min_daily_km', 'min-daily'], ['max_daily_km', 'max-daily']]) if (d[key] !== undefined) $(id).value = d[key];
        if (!workbenchConfig.watch && ['fit', 'tcx'].includes(d.output_format)) $('output-format').value = d.output_format;
        updatePreview();
    }
    renderTemplates(); setMode(mode); renderCalendar();
}
document.querySelectorAll('[data-mode]').forEach(button => button.onclick = () => setMode(button.dataset.mode));
$('generate-form').addEventListener('submit', generate);
$('generate-form').addEventListener('input', () => { markStale(); updatePlanCount(); });
$('generate-form').addEventListener('change', markStale);
function renderPaceOptions() {
    for (const id of ['pace-algorithm', 'pace-intensity']) $(id).disabled = !$('pace-fluctuation').checked;
    $('pace-description').textContent = $('pace-fluctuation').checked
        ? $('pace-algorithm').selectedOptions[0]?.dataset.description || '缓慢进入状态，途中连续起伏。'
        : '配速波动已关闭，将按距离分配时间以保持匀速。';
}
$('pace-fluctuation').addEventListener('change', renderPaceOptions);
$('pace-algorithm').addEventListener('change', renderPaceOptions);
$('preview-pace').onclick = () => {
    const data = collect();
    if (!$('min-pace').reportValidity() || !$('max-pace').reportValidity() || !$('pace-intensity').reportValidity()) return;
    if (data.min_pace > data.max_pace) { generationError('最快配速的用时不能大于最慢配速'); return; }
    const distance = mode === 'single' ? data.distance : mode === 'total' ? (data.min_daily_km+data.max_daily_km)/2 : (data.min_km+data.max_km)/2;
    PacePreview.open(data, distance);
};
$('output-format').addEventListener('change', renderAdvanced);
$('track-choice').addEventListener('change', updatePreview);
$('result-next').onclick = nextResult;
$('template-choice').onchange = chooseTemplate;
$('template-upload').onchange = async event => {
    const file = event.target.files[0]; if (!file) return;
    try {
        if (file.size > 1024 * 1024) throw new Error('模板文件不能超过 1 MiB');
        const template = JSON.parse(await file.text());
        if (!template || typeof template !== 'object' || Array.isArray(template) || typeof template.name !== 'string') throw new Error('缺少模板名称或格式不正确');
        if (typeof template.id !== 'string' || !template.id) template.id = 'custom_' + crypto.randomUUID();
        applyTemplate(template); cacheTemplate(template); renderTemplates('local:' + template.id);
        notify('模板已导入');
    } catch (error) { notify('模板导入失败：' + error.message); }
    event.target.value = '';
};
$('save-template').onclick = () => { $('template-name').value = ''; $('template-dialog').showModal(); };
$('template-form').onsubmit = event => {
    event.preventDefault();
    const template = { id: 'custom_' + crypto.randomUUID(), name: $('template-name').value.trim(), description: '', track_id: $('track-choice').value, [mode + '_config']: collect() };
    if (!template.name) return;
    downloadBlob(new Blob([JSON.stringify(template, null, 2)], { type: 'application/json' }), template.name.replace(/[<>:"/\\|?*\x00-\x1f]/g, '_') + '.json');
    cacheTemplate(template); renderTemplates('local:' + template.id); $('template-dialog').close(); notify('参数模板已导出');
};
for (const [id, delta] of [['previous-month', -1], ['next-month', 1]]) $(id).onclick = () => { calendarMonth = monthShift(calendarMonth, delta); renderCalendar(); };
$('calendar-month').onchange = () => { if ($('calendar-month').checkValidity() && $('calendar-month').value) { calendarMonth = $('calendar-month').value; renderCalendar(); } };
$('current-month').onclick = () => { const d = new Date(); calendarMonth = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`; renderCalendar(); };
$('clear-dates').onclick = () => { selectedDates.clear(); renderCalendar(); markStale(); };
$('edit-preview-track').onclick = event => {
    if (event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
    event.preventDefault(); TrackPreview.edit();
};
document.addEventListener('workbench:page', event => { if (event.detail === 'generate') TrackPreview.resize(); });
document.addEventListener('DOMContentLoaded', init);
return { refreshTracks, markStale, selectTrack(id) { $('track-choice').value = id; updatePreview(); markStale(); }, tracks: () => tracks };
})();
