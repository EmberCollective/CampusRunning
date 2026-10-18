// Leaflet 地图适配器（经典/新版/卫星三档瓦片，无 Key）
// 由 map_engine.js 加载使用；[lat,lng] 顺序转换仅限本文件内部，外部统一 {lat,lng}

// 轨迹覆盖物主题色：地图覆盖物无法读取 CSS 变量，改用 JS 常量集中定义；
// 本文件先于 map_adapter_amap.js 加载，两适配器共用此常量。换主题时与 style.css 的 --accent 同步修改。
const TRACK_ACCENT = '#3B5BD7';

class LeafletAdapter {
    // containerId: 地图容器元素 id
    // opts.interactive === false 时创建只读地图（生成器预览卡）：禁用全部交互，
    // 且不注册 click/mousedown（_handlers 恒为 null，事件即使触发也无处可去）
    constructor(containerId, opts = {}) {
        const interactive = opts.interactive !== false;
        // zoomControl 关闭：默认缩放按钮位于左上角，会与搜索框重叠；缩放用滚轮/双击或「适配视野」
        const mapOptions = { center: [26.4205, 106.6713], zoom: 17, minZoom: 3, maxZoom: 20, zoomControl: false };
        if (!interactive) {
            Object.assign(mapOptions, { dragging: false, scrollWheelZoom: false, doubleClickZoom: false, boxZoom: false, keyboard: false, touchZoom: false });
        }
        this.map = L.map(containerId, mapOptions);

        // 三档瓦片源预定义（高德瓦片直连免 Key；不立即全部 add，由 setBaseMode 决定挂载）
        // maxNativeZoom 18：高德瓦片仅部分区域有 z19/z20 数据，其余空白；超过 18 一律复用
        // z18 瓦片做插值放大（变模糊但无空白），地图仍可缩放到 maxZoom 20
        const tileOptions = { subdomains: ['1', '2', '3', '4'], maxNativeZoom: 18, maxZoom: 20, attribution: '© 高德地图' };
        this._tiles = {
            classic: L.tileLayer('https://webrd0{s}.is.autonavi.com/appmaptile?lang=zh_cn&size=1&scale=1&style=8&x={x}&y={y}&z={z}', tileOptions),
            fresh: L.tileLayer('https://wprd0{s}.is.autonavi.com/appmaptile?x={x}&y={y}&z={z}&lang=zh_cn&size=1&scl=1&style=7', tileOptions),
            satelliteBase: L.tileLayer('https://webst0{s}.is.autonavi.com/appmaptile?x={x}&y={y}&z={z}&style=6', tileOptions),
            satelliteLabel: L.tileLayer('https://webst0{s}.is.autonavi.com/appmaptile?x={x}&y={y}&z={z}&style=8', tileOptions)
        };

        // 覆盖物分层：顶点、主线（含闭合虚线）、中点
        this.vertexLayer = L.layerGroup().addTo(this.map);
        this.lineLayer = L.layerGroup().addTo(this.map);
        this.midpointLayer = L.layerGroup().addTo(this.map);

        this._handlers = null;     // renderTrack 注入的事件回调集
        this._currentBase = null;  // 当前已挂载的瓦片层数组
        this._onView = null;       // 图形层的视野钩子回调（具名引用，便于 off）
        this._onZoomStart = null;
        this._onZoomEnd = null;

        if (interactive) {
            this._bindEditorEvents();
        }
    }

    // 编辑器交互事件绑定（只读实例跳过：主页预览卡无画笔/拖点语义）
    _bindEditorEvents() {
        // 地图空白处点击 → onMapClick（顶点/中点点击不冒泡到 map）
        this.map.on('click', (e) => {
            if (this._handlers) {
                this._handlers.onMapClick({ lat: e.latlng.lat, lng: e.latlng.lng });
            }
        });

        // 左键按下 → onMapMouseDown：画笔加点走按下而非 click（click 在按下后拖动平移时被引擎抑制，会丢点）
        this.map.on('mousedown', (e) => {
            // 顶点/中点覆盖物上的按下有自己的交互（拖顶点/插点），不当作地图落笔；
            // 不依赖 Leaflet 的 propagatedFrom（layer 未把 map 注册为 event parent，不会带该标记）
            const t = e.originalEvent && e.originalEvent.target;
            if (t && t.closest && t.closest('.vertex-marker, .midpoint-handle')) return;
            if (e.originalEvent && e.originalEvent.button !== 0) return;  // 中/右键按下是拖动或菜单，不加点
            if (this._handlers && this._handlers.onMapMouseDown) {
                this._handlers.onMapMouseDown({ lat: e.latlng.lat, lng: e.latlng.lng });
            }
        });
    }

    // 切换底图模式：'classic'|'fresh' 单层；'satellite' 卫星底图+路网标注两层叠加（标注层 zIndex 高）
    setBaseMode(mode) {
        (this._currentBase || []).forEach((layer) => layer.remove());
        this._currentBase = [];

        if (mode === 'classic') {
            this._currentBase.push(this._tiles.classic.addTo(this.map));
        } else if (mode === 'fresh') {
            this._currentBase.push(this._tiles.fresh.addTo(this.map));
        } else if (mode === 'satellite') {
            this._tiles.satelliteBase.setZIndex(1);
            this._tiles.satelliteLabel.setZIndex(2);  // 路网标注置于卫星底图之上
            this._currentBase.push(this._tiles.satelliteBase.addTo(this.map), this._tiles.satelliteLabel.addTo(this.map));
        }
    }

    // 激活地图：恢复视角并强制重算尺寸（容器由隐藏变可见后必须调用）
    activate(view) {
        this.map.setView([view.lat, view.lng], view.zoom);
        this.map.invalidateSize();
    }

    // 读取当前视角
    getView() {
        const c = this.map.getCenter();
        return { lat: c.lat, lng: c.lng, zoom: this.map.getZoom() };
    }

    // 拖动平移开关（画笔模式下禁用，避免按住左键移动被当成拖图）；
    // 同时切换双击缩放：画笔下双击应是连续落笔而非视角跳动
    setDragEnabled(enabled) {
        if (enabled) {
            this.map.dragging.enable();
            this.map.doubleClickZoom.enable();
        } else {
            this.map.dragging.disable();
            this.map.doubleClickZoom.disable();
        }
    }

    // 平滑飞行到指定位置
    flyTo(lat, lng, zoom) {
        this.map.flyTo([lat, lng], zoom);
    }

    // ===== 屏幕像素换算（图形层用：容器像素 ↔ 经纬度）=====
    // 容器像素原点 = #map-leaflet 左上角；#map-leaflet 与 #selection-layer 同为 inset:0，
    // 故这里返回的坐标可以直接当作 selection-layer 的坐标使用。
    latLngToContainer(lat, lng) {
        // latLngToContainerPoint 会取整；组变换需可逆的亚像素坐标，避免每次拖动累积舍入误差。
        const p = this.map.project([lat, lng]).subtract(this.map.getPixelOrigin())
            .subtract(this.map.containerPointToLayerPoint([0, 0]));
        return { x: p.x, y: p.y };
    }

    containerToLatLng(x, y) {
        const ll = this.map.containerPointToLatLng([x, y]);
        return { lat: ll.lat, lng: ll.lng };
    }

    // 视野变化钩子：平移/缩放重绘图形层；缩放动画期间要遮住图形层——
    // Leaflet 动画中 latLngToContainerPoint 仍返回旧 zoom 的值，不遮会先漂移再跳回
    //
    // 必须先摘上一轮再绑：MapEngine 每次切底图档位都会重绑，而 map 实例是构造时建好后
    // 长期复用的——只 on 不 off 的话，切 N 次档位就叠 N 层监听，每次平移触发 N 倍重绘。
    // 保留具名回调引用才 off 得掉，所以不能写成内联箭头函数。
    bindViewHooks(hooks) {
        this._unbindViewHooks();
        this._onView = () => hooks.onChange();
        this._onZoomStart = () => hooks.onZoomStart && hooks.onZoomStart();
        this._onZoomEnd = () => {
            if (hooks.onZoomEnd) hooks.onZoomEnd();
            hooks.onChange();
        };
        this.map.on('move zoom', this._onView);
        this.map.on('zoomstart', this._onZoomStart);
        this.map.on('zoomend', this._onZoomEnd);
    }

    _unbindViewHooks() {
        if (!this._onView) return;
        this.map.off('move zoom', this._onView);
        this.map.off('zoomstart', this._onZoomStart);
        this.map.off('zoomend', this._onZoomEnd);
        this._onView = null;
        this._onZoomStart = null;
        this._onZoomEnd = null;
    }

    // 缩放至轨迹范围（无点时不动作）；padding 可配——小尺寸地图（预览卡）需更小的内边距
    fitTrack(points, padding = [30, 30]) {
        if (points.length > 0) {
            this.map.fitBounds(L.latLngBounds(points.map((p) => [p.lat, p.lng])), { padding: padding });
        }
    }

    // 轨迹渲染（全量重建），handlers 提供 onMapClick/onVertexDragStart/onVertexDragEnd/onVertexClick/onMidpointClick
    renderTrack(points, handlers) {
        this._handlers = handlers;
        this.vertexLayer.clearLayers();
        this.lineLayer.clearLayers();
        this.midpointLayer.clearLayers();

        const n = points.length;

        // 主线
        if (n >= 2) {
            L.polyline(points.map((p) => [p.lat, p.lng]), { color: TRACK_ACCENT, weight: 3 }).addTo(this.lineLayer);
        }

        // 闭合虚线（末点→首点）
        if (n >= 3) {
            L.polyline([points[n - 1], points[0]], { color: TRACK_ACCENT, weight: 2, dashArray: '6 6', opacity: 0.6 }).addTo(this.lineLayer);
        }

        // 顶点（可拖拽调整、点击删除）
        points.forEach((p, i) => {
            const marker = L.marker([p.lat, p.lng], {
                draggable: true,
                icon: L.divIcon({
                    className: 'vertex-marker',
                    iconSize: [12, 12],
                    iconAnchor: [6, 6]  // 中心对准坐标点，避免视觉偏移
                })
            });
            marker.on('dragstart', () => handlers.onVertexDragStart(i));
            marker.on('dragend', () => {
                const ll = marker.getLatLng();
                handlers.onVertexDragEnd(i, { lat: ll.lat, lng: ll.lng });
            });
            marker.on('click', () => handlers.onVertexClick(i));
            this.vertexLayer.addLayer(marker);
        });

        // 中点插入手柄（相邻段 + 闭合段，闭合段仅当点数>=3）
        if (n >= 2) {
            for (let i = 0; i < n; i++) {
                if (i === n - 1 && n < 3) break;
                const a = points[i];
                const b = points[(i + 1) % n];
                const mid = { lat: (a.lat + b.lat) / 2, lng: (a.lng + b.lng) / 2 };
                const handle = L.circleMarker([mid.lat, mid.lng], {
                    radius: 5,
                    className: 'midpoint-handle',
                    color: TRACK_ACCENT,
                    fillOpacity: 0.8,
                    bubblingMouseEvents: false  // 阻断 click 冒泡到 map，避免插中点同时误加点（对齐 AMap 侧防冒泡）
                });
                handle.on('click', () => handlers.onMidpointClick(i, mid));
                this.midpointLayer.addLayer(handle);
            }
        }
    }

    // 只读轨迹轮廓渲染（生成器预览卡）：只画主线 + 闭合虚线 + 起点圆点，
    // 不画顶点/中点、不注入 _handlers；起点 interactive:false 保证点击穿透到外层链接
    renderOutline(points) {
        this.vertexLayer.clearLayers();
        this.lineLayer.clearLayers();
        this.midpointLayer.clearLayers();

        const n = points.length;

        if (n >= 2) {
            L.polyline(points.map((p) => [p.lat, p.lng]), { color: TRACK_ACCENT, weight: 3, interactive: false }).addTo(this.lineLayer);
        }

        // 闭合虚线（末点→首点），与 renderTrack 保持同一视觉语言
        if (n >= 3) {
            L.polyline([points[n - 1], points[0]], { color: TRACK_ACCENT, weight: 2, dashArray: '6 6', opacity: 0.6, interactive: false }).addTo(this.lineLayer);
        }

        // 起点标记：白边 + 主题色填充
        if (n >= 1) {
            L.circleMarker([points[0].lat, points[0].lng], {
                radius: 4,
                color: '#fff',
                weight: 2,
                fillColor: TRACK_ACCENT,
                fillOpacity: 1,
                interactive: false
            }).addTo(this.vertexLayer);
        }
    }
}
