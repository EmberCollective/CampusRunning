// 轨迹编辑器 - 前端逻辑（地图引擎无关：渲染/定位经 MapEngine 转发）
//
// 依赖（按页面加载顺序在其前）：
//   map_adapter_leaflet.js / map_adapter_amap.js（引擎适配器）
//   map_engine.js（MapEngine：模式切换/Key 管理）
//   search_box.js（initSearchBox，主 init 中调用）

// ===== 状态 =====
let points = [];                    // [{lat, lng}] 坐标唯一真源
let undoStack = [];                 // points 快照栈，上限 100
let redoStack = [];
let editingTrackId = null;          // 从磁盘加载的轨迹 id；null=新建
let activeCorrection = null;        // 保存时使用：新建→defaultCorrection；编辑→加载时的原值
let defaultCorrection = null;       // GET /api/defaults 的 default_coordinate_correction
let dragStartSnapshot = null;       // 顶点拖拽开始时的快照
let currentTool = 'pan';            // 当前工具：'pan' 拖动平移（默认）/ 'draw' 画笔加点 / 'erase' 橡皮擦删点

const UNDO_LIMIT = 100;

// 地图舞台元素（工具光标切换、中键临时态都要用）
const mapStageEl = document.querySelector('.map-stage');

// ===== 工具切换 =====
function applyToolButtons() {
    document.getElementById('tool-pan').classList.toggle('active', currentTool === 'pan');
    document.getElementById('tool-draw').classList.toggle('active', currentTool === 'draw');
    document.getElementById('tool-erase').classList.toggle('active', currentTool === 'erase');
}

function setTool(tool) {
    if (tool !== 'pan' && tool !== 'draw' && tool !== 'erase') return;
    currentTool = tool;
    applyToolButtons();
    // 地图光标反馈：画笔为十字，橡皮擦悬停顶点变红（CSS），拖动用地图默认（抓手）
    mapStageEl.classList.toggle('draw-mode', tool === 'draw');
    mapStageEl.classList.toggle('erase-mode', tool === 'erase');
}

// ===== 边界转换（{lat,lng} 与项目 JSON {longitude,latitude} 的唯一转换点）=====
const toGeoCoords = () => points.map(p => ({ longitude: p.lng, latitude: p.lat }));

// ===== 编辑事件处理（由地图适配器回调，只操作 points）=====
const HANDLERS = {
    onMapClick(pt) {
        // 仅画笔模式下点击才加点；拖动模式下点击仅用于平移（顶点/中点交互不受影响）
        if (currentTool !== 'draw') return;
        pushUndo();
        points.push({ lat: pt.lat, lng: pt.lng });
        renderTrack();
    },
    onVertexDragStart() {
        dragStartSnapshot = points.map(pt => ({ ...pt }));
    },
    onVertexDragEnd(i, pt) {
        commitSnapshot(dragStartSnapshot);
        dragStartSnapshot = null;
        points[i] = { lat: pt.lat, lng: pt.lng };
        renderTrack();
    },
    onVertexClick(i) {
        // 仅橡皮擦模式下点击顶点才删点，避免拖动/画笔模式下拖拽顶点时误触删除
        if (currentTool !== 'erase') return;
        pushUndo();
        points.splice(i, 1);
        renderTrack();
    },
    onMidpointClick(i, mid) {
        // 橡皮擦模式下点击中点不插点（该模式意图是删除，误触插点很反直觉）
        if (currentTool === 'erase') return;
        pushUndo();
        points.splice(i + 1, 0, { lat: mid.lat, lng: mid.lng });
        renderTrack();
    }
};

// ===== 渲染（转发到当前活跃引擎，全量重建）=====
function renderTrack() {
    MapEngine.renderTrack(points, HANDLERS);
    updateStats();
}

// ===== 撤销/重做 =====
function pushUndo() {
    commitSnapshot(points.map(p => ({ ...p })));
}

function commitSnapshot(snap) {
    undoStack.push(snap);
    if (undoStack.length > UNDO_LIMIT) undoStack.shift();
    redoStack = [];
    updateButtonStates();
}

function clearHistory() {
    undoStack = [];
    redoStack = [];
    updateButtonStates();
}

function undo() {
    if (!undoStack.length) return;
    redoStack.push(points.map(p => ({ ...p })));
    points = undoStack.pop();
    renderTrack();
    updateButtonStates();
}

function redo() {
    if (!redoStack.length) return;
    undoStack.push(points.map(p => ({ ...p })));
    points = redoStack.pop();
    renderTrack();
    updateButtonStates();
}

function updateButtonStates() {
    document.getElementById('undo-btn').disabled = undoStack.length === 0;
    document.getElementById('redo-btn').disabled = redoStack.length === 0;
}

// ===== 统计（Haversine，与后端 TrackAnalyzer 同参：R=6371000，环线含闭合段）=====
const EARTH_RADIUS_M = 6371000;

function haversineMeters(a, b) {
    const toRad = (deg) => deg * Math.PI / 180;
    const dLat = toRad(b.lat - a.lat);
    const dLng = toRad(b.lng - a.lng);
    const s = Math.sin(dLat / 2) ** 2 +
        Math.cos(toRad(a.lat)) * Math.cos(toRad(b.lat)) * Math.sin(dLng / 2) ** 2;
    return 2 * EARTH_RADIUS_M * Math.asin(Math.sqrt(s));
}

function totalLoopDistance(pts) {
    if (pts.length < 2) return 0;
    let total = 0;
    for (let i = 0; i < pts.length; i++) {
        total += haversineMeters(pts[i], pts[(i + 1) % pts.length]);
    }
    return total;
}

function updateStats() {
    document.getElementById('stat-points').textContent = points.length;
    document.getElementById('stat-distance').textContent = `${totalLoopDistance(points).toFixed(1)} m`;
}

// ===== 轨迹列表 =====
async function refreshTrackSelect() {
    try {
        const response = await fetch('/api/tracks');
        if (!response.ok) throw new Error(`HTTP ${response.status}`);

        const tracks = await response.json();
        const select = document.getElementById('load-track-select');
        // 用 DOM API 构建（name 来自 JSON 文件的任意文本，禁止拼入 innerHTML 防存储型 XSS）
        select.replaceChildren(new Option('选择轨迹...', ''));
        tracks.forEach(t => select.add(new Option(`${t.name} (${t.lap_distance_km} km/圈)`, t.id)));
        if (editingTrackId) select.value = editingTrackId;
    } catch (error) {
        showMessage('加载轨迹列表失败: ' + error.message, 'error');
    }
}

// ===== 加载轨迹 =====
async function handleLoad() {
    const id = document.getElementById('load-track-select').value;
    if (!id) {
        showMessage('请先选择一个轨迹', 'error');
        return;
    }

    try {
        const response = await fetch(`/api/tracks/${id}/coords`);
        if (!response.ok) {
            const err = await response.json().catch(() => ({}));
            showMessage(err.error || `加载失败 (${response.status})`, 'error');
            return;
        }

        const data = await response.json();
        points = data.base_coordinates.map(p => ({ lat: p.latitude, lng: p.longitude }));
        editingTrackId = data.id || id;
        activeCorrection = data.coordinate_correction ?? null;

        document.getElementById('track-id').value = editingTrackId;
        document.getElementById('track-name').value = data.name || '';
        document.getElementById('track-desc').value = data.description || '';

        clearHistory();
        renderTrack();
        if (points.length > 0) {
            MapEngine.fitTrack(points);
        }
        updateCorrectionNote();
        showMessage(`已加载轨迹: ${data.name || id}`, 'success');
    } catch (error) {
        showMessage('网络错误：无法连接服务器', 'error');
    }
}

// ===== 新建空白 =====
function handleNew() {
    points = [];
    editingTrackId = null;
    activeCorrection = defaultCorrection;
    document.getElementById('track-id').value = '';
    document.getElementById('track-name').value = '';
    document.getElementById('track-desc').value = '';
    clearHistory();
    renderTrack();
    updateCorrectionNote();
}

// ===== 坐标修正提示 =====
function updateCorrectionNote() {
    const note = document.getElementById('correction-note');
    if (editingTrackId === null) {
        note.textContent = defaultCorrection
            ? '保存时将应用默认坐标偏移修正'
            : '无默认坐标修正配置（保存时不添加）';
    } else if (activeCorrection) {
        note.textContent = '保留该轨迹原有坐标修正配置';
    } else {
        note.textContent = '该轨迹无坐标修正（保存时不添加）';
    }
    note.classList.remove('hidden');
}

// ===== 保存 =====
function handleSaveSubmit(e) {
    e.preventDefault();
    const id = document.getElementById('track-id').value.trim();
    const name = document.getElementById('track-name').value.trim();
    const description = document.getElementById('track-desc').value.trim();

    if (!/^[a-z0-9_-]+$/.test(id)) {
        showMessage('轨迹ID仅能包含小写字母、数字、下划线、连字符', 'error');
        return;
    }
    if (!name) {
        showMessage('名称不能为空', 'error');
        return;
    }
    if (points.length < 3) {
        showMessage('至少需要 3 个轨迹点才能保存', 'error');
        return;
    }

    doSave({
        id,
        name,
        description,
        base_coordinates: toGeoCoords(),
        coordinate_correction: activeCorrection,
        overwrite: id === editingTrackId
    });
}

async function doSave(payload) {
    showMessage('正在保存...', 'loading');
    disableButtons(true);

    try {
        const response = await fetch('/api/tracks', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });
        const data = await response.json().catch(() => ({}));

        // 已存在：确认后覆盖重发
        if (response.status === 409 && data.exists) {
            if (window.confirm(`轨迹 ${payload.id} 已存在，覆盖保存？`)) {
                return await doSave({ ...payload, overwrite: true });
            }
            showMessage('已取消保存', 'error');
            return;
        }

        if (response.status === 400) {
            showMessage(data.error || '保存失败 (400)', 'error');
            return;
        }

        if (!response.ok) {
            showMessage(`保存失败 (${response.status})`, 'error');
            return;
        }

        // 201 成功：校验服务端距离与本地计算一致
        editingTrackId = data.id;
        if (Math.abs(data.distance_meters - totalLoopDistance(points)) >= 0.5) {
            showMessage('警告：服务端距离与本地计算不一致', 'error');
        } else {
            showMessage(`已保存 ${data.filepath}（环线 ${(data.distance_meters / 1000).toFixed(3)} km）`, 'success');
        }
        await refreshTrackSelect();
    } catch (error) {
        showMessage('网络错误：无法连接服务器', 'error');
    } finally {
        disableButtons(false);
    }
}

// ===== 消息与按钮状态（对齐 app.js 模式）=====
function showMessage(text, type) {
    const msg = document.getElementById('message');
    msg.textContent = text;
    msg.className = `message ${type} show`;

    if (type !== 'loading') {
        setTimeout(() => {
            msg.classList.remove('show');
        }, 5000);
    }
}

function disableButtons(disabled) {
    document.querySelectorAll('button[type="submit"]').forEach(btn => {
        btn.disabled = disabled;
    });
}

// ===== 事件绑定 =====
document.addEventListener('keydown', (e) => {
    // 输入框内保留浏览器原生文本撤销，不劫持为轨迹 undo
    if (e.target.closest('input, textarea, select')) return;
    if (!(e.ctrlKey || e.metaKey)) return;
    const key = e.key.toLowerCase();
    const isUndo = key === 'z' && !e.shiftKey;
    const isRedo = (key === 'z' && e.shiftKey) || key === 'y';
    if (isUndo) {
        e.preventDefault();
        undo();
    } else if (isRedo) {
        e.preventDefault();
        redo();
    }
});

// 中键拖动地图时临时高亮「拖动」按钮并取消特殊光标，松开恢复当前工具态
function showTempPanUI() {
    document.getElementById('tool-pan').classList.add('active');
    document.getElementById('tool-draw').classList.remove('active');
    document.getElementById('tool-erase').classList.remove('active');
    mapStageEl.classList.remove('draw-mode');
    mapStageEl.classList.remove('erase-mode');
}

function restoreToolUI() {
    applyToolButtons();
    mapStageEl.classList.toggle('draw-mode', currentTool === 'draw');
    mapStageEl.classList.toggle('erase-mode', currentTool === 'erase');
}

window.addEventListener('mousedown', (e) => {
    if (e.button !== 1) return;
    showTempPanUI();
});
window.addEventListener('mouseup', (e) => {
    if (e.button !== 1) return;
    restoreToolUI();
});

document.getElementById('tool-pan').addEventListener('click', () => setTool('pan'));
document.getElementById('tool-draw').addEventListener('click', () => setTool('draw'));
document.getElementById('tool-erase').addEventListener('click', () => setTool('erase'));
document.getElementById('undo-btn').addEventListener('click', undo);
document.getElementById('redo-btn').addEventListener('click', redo);
document.getElementById('load-btn').addEventListener('click', handleLoad);
document.getElementById('new-btn').addEventListener('click', handleNew);
document.getElementById('fit-btn').addEventListener('click', () => {
    if (points.length > 0) {
        MapEngine.fitTrack(points);
    }
});
document.getElementById('clear-btn').addEventListener('click', () => {
    if (points.length === 0) return;
    pushUndo();
    points = [];
    renderTrack();
});
document.getElementById('save-form').addEventListener('submit', handleSaveSubmit);

// ===== 初始化 =====
(async function init() {
    // 地图引擎与搜索（同步初始化，Leaflet 立即可用）
    MapEngine.init();
    initSearchBox();

    try {
        const response = await fetch('/api/defaults');
        if (response.ok) {
            const d = await response.json();
            defaultCorrection = d.default_coordinate_correction ?? null;
        }
    } catch (error) {
        // defaults 拉取失败不阻塞编辑功能，保存时不添加修正
    }
    activeCorrection = defaultCorrection;

    await refreshTrackSelect();
    updateCorrectionNote();
    updateButtonStates();
    updateStats();
    renderTrack();  // 空渲染一次：向地图适配器注入事件回调，否则刷新后首次点击不会加点
})();
