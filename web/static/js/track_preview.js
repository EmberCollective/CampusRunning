// 预览允许浏览地图；编辑仍由 TrackEditor 完成，坐标按轨迹 ID 缓存。

const TrackPreview = (() => {
    const preview = document.getElementById('preview-map');
    preview.tabIndex = 0;
    preview.setAttribute('role', 'link');
    preview.title = '滚轮缩放 · 拖动平移 · 单击编辑轨迹';
    preview.insertAdjacentHTML('afterend', `<div class="zoom-controls preview-controls" id="preview-controls" role="group" aria-label="轨迹预览地图工具">
        <button type="button" id="preview-zoom-in" aria-label="放大预览地图" title="放大" disabled>+</button>
        <button type="button" id="preview-zoom-out" aria-label="缩小预览地图" title="缩小" disabled>−</button>
        <button type="button" id="preview-fit" aria-label="适配整条轨迹" title="适配整条轨迹" disabled><svg class="icon" aria-hidden="true"><use href="#i-fit"/></svg></button>
    </div>`);
    let adapter = null, fitPending = false;
    const coordsCache = new Map();   // trackId -> [{lat,lng}]
    let pendingSeq = 0;              // 竞态守卫：快速切换轨迹时丢弃过期响应
    let currentId = null;            // 当前展示的轨迹（visibilitychange 静默刷新用）

    const els = {
        card: document.getElementById('edit-preview-track'),
        name: document.getElementById('preview-track-name'),
        lap: document.getElementById('preview-track-distance'),
        overlay: document.getElementById('preview-overlay'),
        overlayText: document.getElementById('preview-overlay-text')
    };

    // 跨标签页编辑流程（中键打开编辑器改完轨迹后切回本页）会让本地坐标缓存过期：
    // 页面重新可见时静默重拉当前轨迹，拉到新坐标后原地替换（不闪加载态、失败不打扰）
    document.addEventListener('visibilitychange', () => {
        if (!document.hidden) revalidate();
    });

    // 懒初始化迷你地图：容器在正常文档流中且已有确定高度，invalidateSize 兜底
    function ensureMap() {
        if (adapter) return;
        adapter = new LeafletAdapter('preview-map', { interactive: false });
        adapter.setBaseMode('classic');
        // attribution 默认前缀是 Leaflet 官网链接：<a> 套 <a> 非法且会劫持整卡点击，改为纯文本
        adapter.map.attributionControl.setPrefix('');
        adapter.map.dragging.enable();
        adapter.map.scrollWheelZoom.enable();
        adapter.map.touchZoom.enable();
        adapter.map.keyboard.enable();
        adapter.map.on('click', event => {
            if (!event.originalEvent.target.closest('.leaflet-control, button, a')) edit();
        });
        adapter.map.on('zoomend', updateControls);
        L.DomEvent.disableClickPropagation(document.getElementById('preview-controls'));
        adapter.map.invalidateSize();
        new ResizeObserver(() => resize()).observe(document.getElementById('preview-map'));
    }

    function showOverlay(text) {
        els.overlayText.textContent = text;
        els.overlay.hidden = false;
    }

    function hideOverlay() {
        els.overlay.hidden = true;
    }

    // 拉取并转换某轨迹的坐标点（{lat,lng}，与编辑器同构）
    async function fetchPoints(trackId) {
        const response = await fetch(`/api/tracks/${encodeURIComponent(trackId)}/coords`);
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const data = await response.json();
        return data.base_coordinates.map((p) => ({ lat: p.latitude, lng: p.longitude }));
    }

    function renderPoints(points, fit = true) {
        ensureMap();
        adapter.renderOutline(points);
        if (fit) fitPending = true;
        resize();
        updateControls();
    }

    // 显示指定轨迹：meta 来自 /api/tracks 列表（name + lap_distance_km），坐标另行拉取
    async function show(trackId, meta) {
        currentId = trackId;
        els.card.href = '/track-editor?track=' + encodeURIComponent(trackId);
        document.getElementById('preview-map').setAttribute('aria-label', `${meta.name}，滚轮缩放，单击或按回车进入轨迹编辑`);
        updateControls();
        // name 来自 JSON 文件的任意文本，只走 textContent 防存储型 XSS（与 app.js 轨迹下拉同约定）
        els.name.textContent = meta.name;
        els.lap.textContent = `${meta.lap_distance_km.toFixed(2)} km`;
        document.getElementById('preview-track-points').textContent = meta.num_points;
        document.getElementById('preview-track-direction').textContent = meta.is_clockwise ? '顺时针' : '逆时针';

        const cached = coordsCache.get(trackId);
        if (cached) {
            pendingSeq++;  // 作废可能在途的旧请求
            renderPoints(cached);
            hideOverlay();
            return;
        }

        showOverlay('加载中...');
        const seq = ++pendingSeq;
        try {
            const points = await fetchPoints(trackId);
            if (seq !== pendingSeq) return;  // 用户已切换到其他轨迹，丢弃过期结果

            coordsCache.set(trackId, points);
            renderPoints(points);
            hideOverlay();
        } catch (error) {
            if (seq !== pendingSeq) return;
            // 不缓存失败：重新选中同一轨迹时会重试
            showOverlay('预览加载失败');
            console.error('轨迹预览加载失败:', error);
        }
    }

    // 静默刷新当前轨迹：后台重拉坐标，仅成功且仍是当前轨迹时替换画面
    async function revalidate() {
        if (!currentId) return;
        coordsCache.delete(currentId);
        const seq = ++pendingSeq;
        try {
            const points = await fetchPoints(currentId);
            if (seq !== pendingSeq || currentId === null) return;
            coordsCache.set(currentId, points);
            renderPoints(points, false);
        } catch (error) {
            // 静默失败：保留现有画面（如轨迹已在别处删除），下次选中该轨迹走正常加载报错
            console.warn('轨迹预览静默刷新失败:', error);
        }
    }

    // 无可选轨迹时的空态
    function reset() {
        pendingSeq++;  // 作废可能在途的旧请求，避免过期轨迹画到空态卡片上
        currentId = null;
        els.card.href = '#tracks';
        els.name.textContent = '—';
        els.lap.textContent = '';
        document.getElementById('preview-track-points').textContent = '—';
        document.getElementById('preview-track-direction').textContent = '—';
        if (adapter) adapter.renderOutline([]);
        fitPending = false;
        updateControls();
        showOverlay('暂无轨迹');
    }

    function resize() {
        if (!adapter || !document.getElementById('preview-map').clientWidth) return;
        adapter.map.invalidateSize({ animate: false });
        const points = coordsCache.get(currentId);
        if (fitPending && points) {
            adapter.fitTrack(points, [30, 30]);
            fitPending = false;
        }
    }
    function updateControls() {
        const available = !!adapter && !!coordsCache.get(currentId)?.length;
        document.getElementById('preview-zoom-in').disabled = !available || adapter.map.getZoom() >= adapter.map.getMaxZoom();
        document.getElementById('preview-zoom-out').disabled = !available || adapter.map.getZoom() <= adapter.map.getMinZoom();
        document.getElementById('preview-fit').disabled = !available;
    }
    async function edit() {
        if (!currentId) return;
        location.hash = 'tracks';
        try { await TrackEditor.open(currentId); }
        catch (error) { notify('轨迹未载入：' + error.message); }
    }
    document.getElementById('preview-zoom-in').onclick = () => adapter?.map.zoomIn();
    document.getElementById('preview-zoom-out').onclick = () => adapter?.map.zoomOut();
    document.getElementById('preview-fit').onclick = () => { fitPending = true; resize(); };
    document.getElementById('preview-map').addEventListener('keydown', event => {
        if (event.target === event.currentTarget && ['Enter', ' '].includes(event.key)) { event.preventDefault(); edit(); }
    });
    return { show, reset, resize, revalidate, edit };
})();
