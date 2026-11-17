'use strict';
const $ = id => document.getElementById(id);
let toastTimer;
function notify(message, type) {
    $('toast').textContent = message;
    $('toast').hidden = false;
    clearTimeout(toastTimer);
    if (type !== 'loading') toastTimer = setTimeout(() => { $('toast').hidden = true; }, 5000);
}
function showMessage(message, type) { notify(message, type); }
function timeLabel(value) {
    const seconds = Math.max(0, Math.round(value));
    return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, '0')}`;
}
async function requestJSON(url, options = {}) {
    const { timeout = 15000, ...init } = options;
    const response = await fetch(url, { ...init, signal: AbortSignal.timeout(timeout), cache: 'no-store' });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
        const error = new Error(data.error || `请求失败（${response.status}），请检查本地服务后重试`);
        error.status = response.status;
        error.data = data;
        throw error;
    }
    return data;
}
function postJSON(url, data, timeout) {
    return requestJSON(url, { method: 'POST', timeout, headers: {
        'Content-Type': 'application/json',
        ...(workbenchConfig.token ? { 'X-Watch-Token': workbenchConfig.token } : {})
    }, body: JSON.stringify(data) });
}
function showInfo(title, message) {
    $('feedback-title').textContent = title;
    $('feedback-copy').textContent = message;
    $('feedback-dialog').showModal();
}
function currentPage() {
    const hash = location.hash.slice(1);
    const page = ['generate', 'tracks', 'watch'].includes(hash) ? hash : workbenchConfig.page;
    return page === 'watch' && !workbenchConfig.watch ? 'generate' : page;
}
function navigate(focus = false) {
    const page = currentPage();
    const titles = { generate: '生成记录', tracks: '轨迹编辑', watch: '手表控制' };
    for (const key of Object.keys(titles)) {
        $('page-' + key).hidden = key !== page;
        const link = document.querySelector(`[data-nav="${key}"]`);
        if (key === page) link?.setAttribute('aria-current', 'page');
        else link?.removeAttribute('aria-current');
    }
    document.title = `${titles[page]} · CampusRunning`;
    $('status-context').textContent = { generate: '设置 → 生成结果 → 下载或载入',
        tracks: '编辑节点与图形 → 保存轨迹 → 用于生成', watch: '广播可用 → Keep 连接 → 文件接收 → 活动核对' }[page];
    if (focus) $(page === 'tracks' ? 'tracks-title' : page + '-title').focus({ preventScroll: true });
    document.dispatchEvent(new CustomEvent('workbench:page', { detail: page }));
}
let settingsTab = 'maps', connectionConfig = null, settingsBusy = false, settingsReady = false;
function selectSettingsTab(tab) {
    if (!workbenchConfig.watch) tab = 'maps';
    settingsTab = tab;
    for (const key of ['broadcast', 'compatibility', 'maps']) {
        $('setting-' + key).hidden = key !== tab;
        document.querySelector(`[data-setting-tab="${key}"]`).setAttribute('aria-pressed', String(key === tab));
    }
    $('clear-map-keys').hidden = tab !== 'maps';
    $('apply-settings').hidden = tab === 'compatibility';
    updateTransportFields();
}
async function openSettings(tab = 'maps') {
    selectSettingsTab(tab);
    settingsReady = false;
    updateTransportFields(false);
    $('settings-note').textContent = '正在读取本地配置…';
    $('apply-settings').disabled = true;
    $('settings-dialog').showModal();
    try {
        const [, connection] = await Promise.all([initAmapKeyFromServer(), workbenchConfig.watch ? requestJSON('/api/watch/config') : null]);
        $('map-key').value = getAmapKey();
        $('map-security-key').value = getAmapScode();
        $('map-provider').value = MapEngine.mode;
        connectionConfig = connection;
        $('transport-choice').value = connection?.transport || 'netsim';
        $('netsim-source').value = connection?.netsim_ini || '';
        $('netsim-state-path').value = connection?.netsim_state || '';
        $('windows-state-path').value = connection?.windows_state || '';
        $('connection-config-file').textContent = connection?.config_file || '当前面板未提供保存位置，请重新启动服务';
        $('connection-data-dir').textContent = connection?.data_dir || '—';
        $('windows-python').value = connection?.python || '';
        $('btvs-path').value = connection?.btvs || '';
        $('tshark-path').value = connection?.tshark || '';
        $('environment-result').textContent = '尚未检查本次配置';
        settingsReady = true;
        updateTransportFields();
    } catch {
        $('settings-note').textContent = '无法读取配置，请恢复本地服务后重新打开设置';
    }
}
async function saveMapSettings(clear = false) {
    if (settingsBusy || !settingsReady) return;
    const key = clear ? '' : $('map-key').value.trim();
    const scode = clear ? '' : $('map-security-key').value.trim();
    if (!clear && $('map-provider').value === 'amap' && !key) {
        selectSettingsTab('maps');
        $('settings-note').textContent = '官方高德需要 JS API Key，请先填写';
        $('map-key').focus();
        return;
    }
    settingsBusy = true; updateTransportFields();
    $('clear-map-keys').disabled = true;
    try {
        await postJSON('/api/amap-key', { key, securityJsCode: scode });
        const changed = key !== getAmapKey() || scode !== getAmapScode();
        _serverAmapKey = key;
        _serverAmapScode = scode;
        try { localStorage.removeItem(AMAP_KEY_STORAGE); localStorage.removeItem(AMAP_SCODE_STORAGE); } catch { /* Server config is authoritative. */ }
        if (changed) { placeSearch = null; searchSeq++; hideSearchResults(); }
        updateSearchState();
        const mode = clear ? 'classic' : $('map-provider').value;
        try { localStorage.setItem('map_mode', mode); } catch { /* Session still works without storage. */ }
        if (MapEngine.isReady()) MapEngine.switchMode(mode);
        $('map-style').value = mode;
        $('settings-dialog').close();
        notify(changed && MapEngine.adapters.amap ? '地图配置已保存；已加载的官方地图需刷新后使用新密钥' : clear ? '地图密钥已清除' : '设置已保存');
    } catch (error) {
        $('settings-note').textContent = '保存未完成：' + error.message;
    } finally {
        settingsBusy = false;
        $('clear-map-keys').disabled = false;
        updateTransportFields(false);
    }
}
function connectionValues() {
    return { transport: $('transport-choice').value, netsim_ini: $('netsim-source').value.trim(),
        netsim_state: $('netsim-state-path').value.trim(), windows_state: $('windows-state-path').value.trim(), python: $('windows-python').value.trim(),
        btvs: $('btvs-path').value.trim(), tshark: $('tshark-path').value.trim() };
}
async function saveConnectionSettings() {
    if (settingsBusy || !settingsReady || $('apply-settings').disabled) return;
    settingsBusy = true; updateTransportFields();
    try {
        connectionConfig = await postJSON('/api/watch/config', connectionValues());
        $('settings-dialog').close();
        document.dispatchEvent(new Event('workbench:connection'));
        notify('连接配置已保存；在手表控制页手动启动广播');
    } catch (error) {
        $('settings-note').textContent = '保存未完成：' + error.message;
    } finally { settingsBusy = false; updateTransportFields(false); }
}
function updateTransportFields(resetNote = true) {
    const value = $('transport-choice').value;
    for (const name of ['netsim', 'windows', 'other']) $(name + '-options').hidden = name !== value;
    const active = connectionConfig?.running || connectionConfig?.operation;
    const unavailable = value === 'other';
    $('apply-settings').disabled = !settingsReady || settingsBusy || (settingsTab === 'broadcast' && (active || unavailable));
    $('environment-check').disabled = !settingsReady || settingsBusy || unavailable;
    for (const id of ['transport-choice', 'netsim-source', 'netsim-state-path', 'windows-state-path', 'windows-python', 'btvs-path', 'tshark-path']) $(id).disabled = !settingsReady || settingsBusy || !!active;
    if (resetNote) $('settings-note').textContent = settingsTab === 'maps' ? '地图配置保存在本地' : settingsTab === 'compatibility' ? '手机联调与活动有效性需单独验收' :
        active ? '先停止广播并等待清理完成，再修改连接配置' : unavailable ? '该路线尚未接入，不能启用' : '保存仅更新配置，不启动广播';
}
document.querySelectorAll('[data-close-dialog]').forEach(button => button.addEventListener('click', () => button.closest('dialog').close()));
document.querySelectorAll('[data-dialog]').forEach(button => button.addEventListener('click', () => $(button.dataset.dialog).showModal()));
document.querySelectorAll('[data-setting-tab]').forEach(button => button.addEventListener('click', () => selectSettingsTab(button.dataset.settingTab)));
$('open-settings').onclick = () => openSettings(workbenchConfig.watch ? 'broadcast' : 'maps');
$('open-map-settings').onclick = () => openSettings('maps');
$('watch-settings').onclick = () => openSettings('broadcast');
$('apply-settings').onclick = () => settingsTab === 'broadcast' ? saveConnectionSettings() : saveMapSettings();
$('transport-choice').onchange = () => { $('environment-result').textContent = '尚未检查本次配置'; updateTransportFields(); };
for (const id of ['netsim-source', 'netsim-state-path', 'windows-state-path', 'windows-python', 'btvs-path', 'tshark-path']) $(id).oninput = () => { $('environment-result').textContent = '配置已修改，请重新检查'; };
$('clear-map-keys').onclick = () => {
    if (confirm('清除本地保存的高德地图密钥？地点搜索和官方高德将不可用。')) saveMapSettings(true);
};
$('settings-dialog').addEventListener('close', () => { $('map-key').value = ''; $('map-security-key').value = ''; });
$('environment-check').onclick = async () => {
    if (settingsBusy || !settingsReady) return;
    settingsBusy = true; updateTransportFields();
    $('environment-result').textContent = '正在读取本机能力，最长约 30 秒…';
    const labels = { python: 'Python 3.11', bless: 'Bless 0.3.0', administrator: '管理员权限', peripheral: '外设广播能力', radio_on: '蓝牙开启', netsim_ini: 'Netsim 配置文件' };
    try {
        const result = await postJSON('/api/watch/check', connectionValues(), 35000);
        const failed = Object.entries(result.checks).filter(([, ok]) => !ok).map(([key]) => labels[key] || key);
        const netsim = $('transport-choice').value === 'netsim';
        $('environment-result').textContent = result.ready ? '前置检查通过：' + Object.keys(result.checks).map(key => labels[key] || key).join('、') + (netsim ? '。仅确认文件存在，尚未验证模拟器连接' : '。尚未验证手机连接') :
            '未通过：' + failed.join('、') + (netsim ? '。请启动模拟器，核对配置文件位置后重试' : '。修正后重新检查；权限不足时请从管理员终端启动面板');
    } catch (error) { $('environment-result').textContent = '检查未完成：' + error.message; }
    finally { settingsBusy = false; updateTransportFields(); }
};
window.addEventListener('hashchange', () => navigate(true));
document.addEventListener('DOMContentLoaded', () => {
    navigate();
    requestJSON('/api/version').then(data => { $('app-version').textContent = `v${data.version}`; }).catch(() => { $('app-version').textContent = '本地工作台'; });
});
