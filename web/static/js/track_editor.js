// Coordinates stay in GCJ-02. MapEngine and SelectionLayer own projection and gestures.
let points = [], undoStack = [], redoStack = [], editingTrackId = null, activeCorrection = null;
let currentTool = 'pan', dragStartSnapshot = null, pendingShape = null;
const UNDO_LIMIT = 100;
const mapStageEl = document.querySelector('.map-stage');
const TrackEditor = (() => {
    let initialized = false, initializing = null, activeKey = null, loadSeq = 0, saving = false;
    const drafts = new Map();
    const editable = () => pendingShape ? pendingShape.points : points;
    const snapshot = rows => rows.map(p => ({ ...p }));
    const pixel = p => MapEngine.latLngToContainer(p.lat, p.lng);
    const geo = p => MapEngine.containerToLatLng(p.x, p.y);
    function fingerprint() {
        return JSON.stringify([points, $('track-id').value, $('track-name').value, $('track-description').value]);
    }
    let savedFingerprint = '';
    function changed() {
        $('editor-dirty').textContent = fingerprint() === savedFingerprint ? '已保存' : '未保存';
    }
    function storeDraft() {
        if (activeKey === null) return;
        drafts.set(activeKey, { points: snapshot(points), undo: undoStack.map(snapshot), redo: redoStack.map(snapshot),
            id: $('track-id').value, name: $('track-name').value, description: $('track-description').value,
            editingTrackId, activeCorrection, savedFingerprint });
    }
    function renderLibrary() {
        const list = $('track-library'); list.replaceChildren();
        const all = new Map(Generator.tracks().map(t => [t.id, { name: t.name, count: t.num_points }]));
        for (const [key, item] of drafts) all.set(key, { name: item.name || '未命名轨迹', count: item.points.length });
        for (const [key, item] of all) {
            const button = document.createElement('button');
            button.className = 'track-row'; button.setAttribute('aria-pressed', String(key === activeKey));
            const icon = document.createElementNS('http://www.w3.org/2000/svg', 'svg'); icon.setAttribute('class', 'icon'); icon.setAttribute('aria-hidden', 'true');
            const use = document.createElementNS('http://www.w3.org/2000/svg', 'use'); use.setAttribute('href', '#i-map'); icon.append(use);
            const text = document.createElement('span'), name = document.createElement('strong'), count = document.createElement('small');
            name.textContent = item.name; count.textContent = `${item.count} 节点`; text.append(name, count); button.append(icon, text);
            button.onclick = () => open(key); list.append(button);
        }
    }
    function activate(key, data) {
        cancelShape(); SelectionLayer.clear(); activeKey = key;
        points = snapshot(data.points); undoStack = (data.undo || []).map(snapshot); redoStack = (data.redo || []).map(snapshot);
        editingTrackId = data.editingTrackId ?? null; activeCorrection = data.activeCorrection ?? null;
        $('track-id').value = data.id || ''; $('track-name').value = data.name || ''; $('track-description').value = data.description || '';
        savedFingerprint = data.savedFingerprint ?? fingerprint();
        renderTrack(); updateButtonStates(); renderLibrary();
        if (points.length) MapEngine.fitTrack(points);
        if (activeCorrection) notify('旧版坐标修正已忽略，保存时会移除；轨迹仍按 GCJ-02 使用');
    }
    async function open(id) {
        if (saving) { notify('正在保存，请等待保存完成后切换轨迹'); return; }
        await init();
        if (!id || id === activeKey) return;
        const seq = ++loadSeq;
        storeDraft();
        if (drafts.has(id)) { activate(id, drafts.get(id)); return; }
        try {
            const data = await requestJSON('/api/tracks/' + encodeURIComponent(id) + '/coords');
            if (seq !== loadSeq) return;
            activate(id, { points: data.base_coordinates.map(p => ({ lat: p.latitude, lng: p.longitude })),
                id: data.id, name: data.name, description: data.description, editingTrackId: data.id, activeCorrection: data.coordinate_correction });
            storeDraft();
        } catch (error) { notify('轨迹未载入：' + error.message); }
    }
    function newTrack() {
        if (!initialized || saving) return;
        loadSeq++; storeDraft();
        const key = 'new:' + crypto.randomUUID();
        activate(key, { points: [], name: '未命名轨迹', id: 'track_' + Date.now().toString(36), savedFingerprint: '' });
        storeDraft(); setTool('draw'); $('track-name').focus();
    }
    function renderOriginal() {
        const svg = $('shape-background').firstElementChild; svg.replaceChildren();
        if (!pendingShape || points.length < 2 || !MapEngine.isReady()) return;
        const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
        path.setAttribute('d', 'M' + points.map(pixel).map(p => `${p.x},${p.y}`).join('L') + (points.length > 2 ? 'Z' : ''));
        svg.append(path);
    }
    function renderSelection(ids, frame) {
        $('selection-empty').hidden = !!ids.length;
        $('selection-properties').hidden = !ids.length;
        $('pending-actions').hidden = !pendingShape;
        $('selected-actions').hidden = !!pendingShape;
        $('selection-title').textContent = pendingShape ? '放置快捷图形' : '节点选区';
        if (frame) {
            const scale = metersPerPixel(frame);
            for (const [id, value] of [['selection-width', frame.width * scale], ['selection-height', frame.height * scale], ['selection-angle', frame.angle * 180 / Math.PI]])
                if (document.activeElement !== $(id)) $(id).value = id === 'selection-angle' ? String(Number(value.toFixed(1))) : value.toFixed(1);
            $('selection-width').disabled = frame.width < 1e-6;
            $('selection-height').disabled = frame.height < 1e-6;
        }
        if (pendingShape) {
            const canJoin = !!joinLoops(points.map(pixel), pendingShape.points.map(pixel));
            $('add-shape').disabled = !canJoin;
            $('pending-warning').textContent = canJoin ? '仅为放置预览；确认后加入轨迹，取消不改变原节点' : '与已有轨迹重叠或无法接入，请移动图形后再添加';
        }
    }
    function metersPerPixel(center) {
        return haversineMeters(geo(center), geo({ x: center.x + 50, y: center.y })) / 50;
    }
    function commit(snap) {
        if (pendingShape) return;
        undoStack.push(snap); if (undoStack.length > UNDO_LIMIT) undoStack.shift(); redoStack = [];
        updateButtonStates(); changed();
    }
    function startShape(type) {
        if (!initialized || saving) return;
        cancelShape(); SelectionLayer.cancelDrag();
        const previousSelection = SelectionLayer.indices(), previousTool = currentTool;
        const { width, height } = mapStageEl.getBoundingClientRect(), center = { x: width / 2, y: height / 2 };
        const scale = metersPerPixel(center);
        const shape = viewportShape(type, width * scale, height * scale);
        const generated = shapeToLocalLoop(shape, Number($('shape-spacing').value)).map(p => geo({ x: center.x + p.x / scale, y: center.y - p.y / scale }));
        if (!generated.every(SelectionGeometry.validGeo)) { notify('此地图范围无法放置图形，请放大地图后重试'); return; }
        pendingShape = { type, points: generated, previousSelection, previousTool };
        setTool('select'); renderTrack(); SelectionLayer.selectIndices(generated.map((_, i) => i));
        document.querySelectorAll('[data-shape]').forEach(button => button.setAttribute('aria-pressed', String(button.dataset.shape === type)));
    }
    function cancelShape() {
        if (!pendingShape) return;
        SelectionLayer.cancelDrag();
        const previous = pendingShape; pendingShape = null; SelectionLayer.clear();
        setTool(previous.previousTool);
        if (previous.previousTool === 'select') SelectionLayer.selectIndices(previous.previousSelection);
        document.querySelectorAll('[data-shape]').forEach(button => button.setAttribute('aria-pressed', 'false'));
        renderTrack();
    }
    function addShape() {
        if (!pendingShape) return;
        SelectionLayer.cancelDrag();
        const generated = snapshot(pendingShape.points), joined = joinLoops(points.map(pixel), generated.map(pixel));
        if (!joined) { notify('图形与原轨迹重叠，请移开后再添加'); return; }
        cancelShape();
        const start = joined.after + 1, before = snapshot(points);
        points.splice(start, 0, ...joined.order.map(i => generated[i])); commit(before); renderTrack();
        setTool('select');
        SelectionLayer.selectIndices(joined.order.map((_, i) => start + i)); notify('快捷图形已加入，可撤销恢复');
    }
    function transformField(id) {
        const frame = SelectionLayer.frame(); if (!frame) return;
        const input = $(id), value = Number(input.value);
        if (!input.checkValidity() || !Number.isFinite(value)) { SelectionLayer.render(); notify('请填写有效的选区尺寸或角度'); return; }
        const next = { ...frame };
        if (id === 'selection-angle') next.angle = value * Math.PI / 180;
        else next[id === 'selection-width' ? 'width' : 'height'] = value / metersPerPixel(frame);
        if (!SelectionLayer.transformTo(next)) notify('变换超出地图有效范围，已保留原轨迹');
    }
    function rotate(delta) {
        const frame = SelectionLayer.frame(); if (frame) SelectionLayer.transformTo({ ...frame, angle: frame.angle + delta * Math.PI / 180 });
    }
    function deleteSelected() {
        if (pendingShape) { cancelShape(); return; }
        SelectionLayer.cancelDrag(); const selected = new Set(SelectionLayer.indices());
        if (!selected.size) return;
        const before = snapshot(points); SelectionLayer.clear(); points = points.filter((_, i) => !selected.has(i));
        commit(before); renderTrack();
    }
    async function save() {
        if (saving) return false;
        if (pendingShape) { notify('请先确认添加或取消放置快捷图形'); return false; }
        SelectionLayer.cancelDrag();
        loadSeq++; // A late track fetch must not replace the geometry being saved.
        const id = $('track-id').value.trim(), name = $('track-name').value.trim();
        if (!/^[a-z0-9_-]+$/.test(id)) { notify('轨迹 ID 仅支持小写字母、数字、下划线和连字符'); $('track-id').focus(); return false; }
        if (!name) { notify('请填写轨迹名称'); $('track-name').focus(); return false; }
        if (points.length < 3) { notify('至少需要 3 个节点才能保存轨迹'); return false; }
        const payload = { id, name, description: $('track-description').value.trim(), coordinate_correction: null,
            base_coordinates: points.map(p => ({ longitude: p.lng, latitude: p.lat })), overwrite: id === editingTrackId };
        const sentFingerprint = fingerprint();
        saving = true; $('save-track').disabled = $('use-track').disabled = true; notify('正在保存轨迹…', 'loading');
        try {
            let data;
            try { data = await postJSON('/api/tracks', payload); }
            catch (error) {
                if (error.status !== 409 || !error.data.exists) throw error;
                if (!confirm(`轨迹 ${id} 已存在，覆盖保存？`)) { notify('已取消覆盖，当前编辑保留'); return false; }
                data = await postJSON('/api/tracks', { ...payload, overwrite: true });
            }
            editingTrackId = id; activeCorrection = null; savedFingerprint = sentFingerprint;
            const oldKey = activeKey; activeKey = id; drafts.delete(oldKey); storeDraft(); changed();
            if (Math.abs(data.distance_meters - totalLoopDistance(payload.base_coordinates.map(p => ({ lat: p.latitude, lng: p.longitude })))) >= .5)
                notify('轨迹已保存，但服务端与本页距离不一致，请重新载入核对');
            else notify('轨迹已保存到本地轨迹库');
            try { await Generator.refreshTracks(id); await TrackPreview.revalidate(); renderLibrary(); }
            catch { notify('轨迹已保存，但列表刷新失败；请恢复服务后刷新页面'); }
            return true;
        } catch (error) { notify('保存未完成，当前编辑保留：' + error.message); return false; }
        finally { saving = false; $('save-track').disabled = $('use-track').disabled = false; }
    }
    async function init() {
        if (initialized) return;
        if (initializing) return initializing;
        initializing = (async () => {
            await MapEngine.init();
            initSearchBox();
            SelectionLayer.init({ getPoints: editable,
                apply(next) { if (pendingShape) pendingShape.points = next; else points = next; renderTrack(); },
                commit, onChange: renderSelection });
            MapEngine.bindViewHooks({ onChange() { renderOriginal(); }, onZoomStart() {}, onZoomEnd() {} });
            new ResizeObserver(() => {
                if (currentPage() === 'tracks') MapEngine.activeAdapter().map.invalidateSize?.({ animate: false });
            }).observe(mapStageEl);
            initialized = true;
            document.querySelectorAll('[data-shape], button[data-tool]').forEach(b => { b.disabled = false; });
            renderTrack(); updateButtonStates();
        })();
        try { await initializing; } finally { initializing = null; }
    }
    async function show() {
        try {
            await init();
            const adapter = MapEngine.activeAdapter(); adapter.activate(adapter.getView());
            if (activeKey === null) {
                const queryId = new URLSearchParams(location.search).get('track');
                await open(queryId || $('track-choice').value || (await Generator.refreshTracks())[0]?.id);
            }
        } catch (error) { notify('地图未就绪：' + error.message); }
    }
    document.querySelectorAll('button[data-tool]').forEach(button => { button.disabled = true; button.onclick = () => setTool(button.dataset.tool); });
    document.querySelectorAll('[data-shape]').forEach(button => { button.disabled = true; button.onclick = () => startShape(button.dataset.shape); });
    $('shape-spacing').onchange = () => {
        const value = Number($('shape-spacing').value);
        $('shape-spacing').value = Number.isFinite(value) ? Math.max(MIN_SPACING, Math.min(MAX_SPACING, value)) : DEFAULT_SPACING;
    };
    $('new-track').onclick = $('new-track-inline').onclick = newTrack;
    $('save-track').onclick = save;
    $('use-track').onclick = async () => {
        if (pendingShape) { notify('请先确认或取消放置图形'); return; }
        if ((fingerprint() !== savedFingerprint || !editingTrackId) && !await save()) return;
        Generator.selectTrack(editingTrackId); location.hash = 'generate';
    };
    for (const id of ['track-name', 'track-id', 'track-description']) $(id).addEventListener('input', changed);
    $('select-all').onclick = () => { if (!initialized) return; setTool('select'); SelectionLayer.selectIndices(editable().map((_, i) => i)); };
    $('deselect').onclick = () => SelectionLayer.clear();
    $('delete-selection').onclick = deleteSelected;
    $('add-shape').onclick = addShape; $('cancel-shape').onclick = cancelShape;
    for (const id of ['selection-width', 'selection-height', 'selection-angle']) $(id).onchange = () => transformField(id);
    $('rotate-left').onclick = () => rotate(-15); $('rotate-right').onclick = () => rotate(15);
    $('editor-shortcuts').onclick = () => $('shortcuts-dialog').showModal();
    $('editor-focus').onclick = () => { $('editor-workspace').classList.toggle('focus-canvas'); $('editor-focus').setAttribute('aria-pressed', String($('editor-workspace').classList.contains('focus-canvas'))); };
    $('editor-fit').onclick = () => { if (initialized && editable().length) MapEngine.fitTrack(editable()); };
    $('zoom-in').onclick = () => zoom(1); $('zoom-out').onclick = () => zoom(-1);
    function zoom(delta) {
        if (!initialized) return;
        const adapter = MapEngine.activeAdapter(), view = adapter.getView(); adapter.flyTo(view.lat, view.lng, Math.max(3, Math.min(20, view.zoom + delta)));
    }
    $('map-style').onchange = () => { if (initialized) MapEngine.switchMode($('map-style').value); };
    $('map-search-form').onsubmit = event => { event.preventDefault(); if (initialized) doSearch($('search-input').value.trim()); };
    $('clear-track').onclick = () => { if (points.length || pendingShape) $('clear-dialog').showModal(); };
    $('confirm-clear').onclick = () => {
        cancelShape(); const before = snapshot(points); SelectionLayer.clear(); points = []; commit(before); renderTrack(); $('clear-dialog').close();
    };
    document.addEventListener('workbench:page', event => { if (event.detail === 'tracks') show(); });
    window.addEventListener('beforeunload', event => {
        if (!initialized) return;
        storeDraft();
        const dirty = pendingShape || [...drafts.values()].some(d => JSON.stringify([d.points, d.id, d.name, d.description]) !== d.savedFingerprint);
        if (dirty) { event.preventDefault(); event.returnValue = ''; }
    });
    document.addEventListener('keydown', event => {
        if (currentPage() !== 'tracks' || !initialized || document.querySelector('dialog[open]') || event.target.closest('input, textarea, select, [contenteditable]')) return;
        const key = event.key.toLowerCase(), modifier = event.ctrlKey || event.metaKey;
        if (modifier && key === 'a') { event.preventDefault(); $('select-all').click(); }
        else if (modifier && key === 'z') { event.preventDefault(); event.shiftKey ? redo() : undo(); }
        else if (modifier && key === 'y') { event.preventDefault(); redo(); }
        else if (modifier && key === 's') { event.preventDefault(); save(); }
        else if (!modifier && !event.altKey && ['h', 'p', 'e', 'v'].includes(key)) { event.preventDefault(); setTool({ h: 'pan', p: 'draw', e: 'erase', v: 'select' }[key]); }
        else if (event.key === 'Escape') { event.preventDefault(); pendingShape ? cancelShape() : SelectionLayer.clear(); }
        else if (event.key === 'Enter' && pendingShape) { event.preventDefault(); addShape(); }
        else if (['Delete', 'Backspace'].includes(event.key) && SelectionLayer.indices().length) { event.preventDefault(); deleteSelected(); }
        else if (key === 'f') { event.preventDefault(); $('editor-fit').click(); }
        else if (event.key.startsWith('Arrow') && SelectionLayer.indices().length) {
            event.preventDefault(); const frame = SelectionLayer.frame(), step = event.shiftKey ? 10 : 1;
            const delta = { ArrowLeft: [-step, 0], ArrowRight: [step, 0], ArrowUp: [0, -step], ArrowDown: [0, step] }[event.key];
            if (frame && delta) SelectionLayer.transformTo({ ...frame, x: frame.x + delta[0], y: frame.y + delta[1] });
        }
    });
    return { open, init, cancelShape, commit, changed, renderOriginal, updateSelection: renderSelection, editable,
        pending: () => !!pendingShape, isReady: () => initialized };
})();
function setTool(tool) {
    if (!MapEngine.isReady()) return;
    if (pendingShape && tool !== 'select') TrackEditor.cancelShape();
    SelectionLayer.setActive(tool === 'select'); currentTool = tool;
    document.querySelectorAll('button[data-tool]').forEach(button => button.setAttribute('aria-pressed', String(button.dataset.tool === tool)));
    MapEngine.setDragEnabled(tool !== 'draw' && tool !== 'select');
    for (const key of ['draw', 'erase', 'select']) mapStageEl.classList.toggle(key + '-mode', tool === key);
    $('canvas-tip').textContent = { pan: '拖动地图与节点，点击线段中点插入节点', draw: '点击地图添加节点；中键临时平移地图', erase: '点击节点删除，可以撤销恢复', select: '拖出矩形框选；选框内移动，边柄缩放，顶部柄旋转；Esc 取消' }[tool];
}
const HANDLERS = {
    onMapClick() {},
    onMapMouseDown(pt) {
        if (currentTool !== 'draw' || pendingShape) return;
        pushUndo(); points.push({ lat: pt.lat, lng: pt.lng }); renderTrack();
    },
    onVertexDragStart() { dragStartSnapshot = points.map(p => ({ ...p })); },
    onVertexDragEnd(i, pt) {
        if (pendingShape) return;
        TrackEditor.commit(dragStartSnapshot); dragStartSnapshot = null; points[i] = { lat: pt.lat, lng: pt.lng }; renderTrack();
    },
    onVertexClick(i) { if (currentTool === 'erase' && !pendingShape) { pushUndo(); points.splice(i, 1); renderTrack(); } },
    onMidpointClick(i, mid) { if (currentTool !== 'erase' && currentTool !== 'select' && !pendingShape) { pushUndo(); points.splice(i + 1, 0, { lat: mid.lat, lng: mid.lng }); renderTrack(); } }
};
function renderTrack() {
    if (!MapEngine.isReady()) return;
    MapEngine.renderTrack(TrackEditor.editable(), HANDLERS);
    $('editor-point-count').textContent = `${points.length} 节点`;
    $('editor-loop-distance').textContent = `${totalLoopDistance(points).toFixed(1)} m`;
    TrackEditor.renderOriginal(); TrackEditor.changed();
}
function totalLoopDistance(rows) {
    if (rows.length < 2) return 0;
    return rows.reduce((sum, p, i) => sum + haversineMeters(p, rows[(i + 1) % rows.length]), 0);
}
function pushUndo() { SelectionLayer.clear(); TrackEditor.commit(points.map(p => ({ ...p }))); }
function updateButtonStates() { $('editor-undo').disabled = !undoStack.length; $('editor-redo').disabled = !redoStack.length; }
function undo() {
    if (pendingShape) { TrackEditor.cancelShape(); return; }
    SelectionLayer.clear(); if (!undoStack.length) return;
    redoStack.push(points.map(p => ({ ...p }))); points = undoStack.pop(); renderTrack(); updateButtonStates();
}
function redo() {
    if (pendingShape) { TrackEditor.cancelShape(); return; }
    SelectionLayer.clear(); if (!redoStack.length) return;
    undoStack.push(points.map(p => ({ ...p }))); points = redoStack.pop(); renderTrack(); updateButtonStates();
}
$('editor-undo').onclick = undo; $('editor-redo').onclick = redo;
mapStageEl.addEventListener('mousedown', event => {
    if (event.button !== 1 || !MapEngine.isReady()) return;
    MapEngine.setDragEnabled(true); mapStageEl.classList.remove('draw-mode', 'erase-mode', 'select-mode');
}, true);
function restoreToolUI() {
    if (!MapEngine.isReady()) return;
    MapEngine.setDragEnabled(currentTool !== 'draw' && currentTool !== 'select');
    for (const key of ['draw', 'erase', 'select']) mapStageEl.classList.toggle(key + '-mode', currentTool === key);
}
window.addEventListener('mouseup', event => { if (event.button === 1) restoreToolUI(); }, true);
window.addEventListener('blur', restoreToolUI);
document.documentElement.addEventListener('mouseleave', restoreToolUI);
