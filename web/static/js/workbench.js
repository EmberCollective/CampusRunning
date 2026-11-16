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
function selectSettingsTab(tab) {
    if (!workbenchConfig.watch) tab = 'maps';
    for (const key of ['broadcast', 'compatibility', 'maps']) {
        $('setting-' + key).hidden = key !== tab;
        document.querySelector(`[data-setting-tab="${key}"]`).setAttribute('aria-pressed', String(key === tab));
    }
    $('clear-map-keys').hidden = tab !== 'maps';
}
async function openSettings(tab = 'maps') {
    selectSettingsTab(tab);
    $('settings-note').textContent = '正在读取本地配置…';
    $('apply-settings').disabled = true;
    $('settings-dialog').showModal();
    try {
        await initAmapKeyFromServer();
        $('map-key').value = getAmapKey();
        $('map-security-key').value = getAmapScode();
        $('map-provider').value = MapEngine.mode;
        $('transport-choice').value = 'netsim';
        updateTransportFields();
        $('settings-note').textContent = '地图配置保存在本地；未接入路线不可启用';
        $('apply-settings').disabled = false;
    } catch {
        $('settings-note').textContent = '无法读取配置，请恢复本地服务后重新打开设置';
    }
}
async function saveMapSettings(clear = false) {
    if (!clear && $('transport-choice').value !== 'netsim') return;
    const key = clear ? '' : $('map-key').value.trim();
    const scode = clear ? '' : $('map-security-key').value.trim();
    if (!clear && $('map-provider').value === 'amap' && !key) {
        selectSettingsTab('maps');
        $('settings-note').textContent = '官方高德需要 JS API Key，请先填写';
        $('map-key').focus();
        return;
    }
    $('apply-settings').disabled = $('clear-map-keys').disabled = true;
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
        $('apply-settings').disabled = $('clear-map-keys').disabled = false;
    }
}
function updateTransportFields() {
    const value = $('transport-choice').value;
    for (const name of ['netsim', 'windows', 'other']) $(name + '-options').hidden = name !== value;
    $('apply-settings').disabled = value !== 'netsim';
    $('settings-note').textContent = value === 'netsim' ? '地图配置保存在本地；未接入路线不可启用' : '当前仅查看配置位置；该路线尚未接入，不能保存或启用';
}
document.querySelectorAll('[data-close-dialog]').forEach(button => button.addEventListener('click', () => button.closest('dialog').close()));
document.querySelectorAll('[data-dialog]').forEach(button => button.addEventListener('click', () => $(button.dataset.dialog).showModal()));
document.querySelectorAll('[data-setting-tab]').forEach(button => button.addEventListener('click', () => selectSettingsTab(button.dataset.settingTab)));
$('open-settings').onclick = () => openSettings(workbenchConfig.watch ? 'broadcast' : 'maps');
$('open-map-settings').onclick = () => openSettings('maps');
$('watch-settings').onclick = () => openSettings('broadcast');
$('apply-settings').onclick = () => saveMapSettings();
$('transport-choice').onchange = updateTransportFields;
$('clear-map-keys').onclick = () => {
    if (confirm('清除本地保存的高德地图密钥？地点搜索和官方高德将不可用。')) saveMapSettings(true);
};
$('settings-dialog').addEventListener('close', () => { $('map-key').value = ''; $('map-security-key').value = ''; });
$('environment-check').onclick = () => {
    showInfo('环境检查范围', '当前仅能读取面板的广播、连接及文件状态，尚未提供系统兼容检查。API 35 / Keep 9.1.120 是仓库已测基线，不代表本机已检测通过；多模拟器隔离和 iOS 尚未验收。');
};
window.addEventListener('hashchange', () => navigate(true));
document.addEventListener('DOMContentLoaded', () => {
    navigate();
    requestJSON('/api/version').then(data => { $('app-version').textContent = `v${data.version}`; }).catch(() => { $('app-version').textContent = '本地工作台'; });
});
