// 轨迹预览卡片（生成器左栏迷你地图）
// 复用 map_adapter_leaflet.js 的 LeafletAdapter（只读实例），点击整卡跳转
// /track-editor?track=<id>，由编辑器侧自动加载该轨迹。
// 坐标按轨迹 id 缓存，切换回已看过的轨迹不再发请求。

const TrackPreview = (() => {
    let adapter = null;              // LeafletAdapter 只读实例，首次 show 时懒初始化
    const coordsCache = new Map();   // trackId -> [{lat,lng}]
    let pendingSeq = 0;              // 竞态守卫：快速切换轨迹时丢弃过期响应
    let currentId = null;            // 当前展示的轨迹（visibilitychange 静默刷新用）

    const els = {
        card: document.getElementById('track-preview-card'),
        name: document.getElementById('preview-name'),
        lap: document.getElementById('preview-lap'),
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
        adapter.map.invalidateSize();
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

    function renderPoints(points) {
        ensureMap();
        adapter.renderOutline(points);
        adapter.fitTrack(points, [14, 14]);
    }

    // 显示指定轨迹：meta 来自 /api/tracks 列表（name + lap_distance_km），坐标另行拉取
    async function show(trackId, meta) {
        currentId = trackId;
        els.card.href = `/track-editor?track=${encodeURIComponent(trackId)}`;
        // name 来自 JSON 文件的任意文本，只走 textContent 防存储型 XSS（与 app.js 轨迹下拉同约定）
        els.name.textContent = meta.name;
        els.lap.textContent = `${meta.lap_distance_km}km/圈`;

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
            renderPoints(points);
        } catch (error) {
            // 静默失败：保留现有画面（如轨迹已在别处删除），下次选中该轨迹走正常加载报错
            console.warn('轨迹预览静默刷新失败:', error);
        }
    }

    // 无可选轨迹时的空态
    function reset() {
        pendingSeq++;  // 作废可能在途的旧请求，避免过期轨迹画到空态卡片上
        currentId = null;
        els.card.href = '/track-editor';
        els.name.textContent = '—';
        els.lap.textContent = '';
        showOverlay('暂无轨迹');
    }

    return { show, reset };
})();
