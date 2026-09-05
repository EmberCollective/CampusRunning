// 高德地图适配器（JS API 2.0，需页面配置 Key，官方 loader 在线加载，禁止本地转存）
// 由 map_engine.js 加载使用；[lng,lat] 顺序转换仅限本文件内部，外部统一 {lat,lng}

// ===== 模块级缓存 =====
let _loadPromise = null;          // SDK 加载 Promise 缓存（防重复加载；失败后置 null 允许重试）
let _loaderScriptAdded = false;   // loader.js <script> 是否已注入页面

// ===== SDK 加载 =====
// 加载高德 JS API 2.0，返回 Promise<AMap>；key/securityJsCode 由页面配置传入
function loadAmap(key, securityJsCode) {
    if (_loadPromise) return _loadPromise;

    _loadPromise = new Promise((resolve, reject) => {
        // 安全密钥必须先于 SDK 加载写入全局
        window._AMapSecurityConfig = { securityJsCode: securityJsCode };

        // loader 就绪后拉取 SDK，10 秒超时保护
        const startLoad = () => {
            if (!window.AMapLoader) {
                _loadPromise = null;
                _loaderScriptAdded = false;  // 加载器丢失，允许下次重新注入
                reject(new Error('无法连接高德服务'));
                return;
            }
            Promise.race([
                window.AMapLoader.load({ key: key, version: '2.0', plugins: ['AMap.PlaceSearch'] }),
                new Promise((_, timeout) => setTimeout(() => timeout(new Error('加载高德地图超时')), 10000))
            ]).then(resolve, (error) => {
                _loadPromise = null;  // 失败清缓存，允许重试
                reject(error);
            });
        };

        if (!_loaderScriptAdded) {
            const script = document.createElement('script');
            script.src = 'https://webapi.amap.com/loader.js';
            // loader.js 注入同样加 15 秒超时：请求悬挂（无 onload/onerror）时不能永久锁死引擎
            const scriptTimeout = setTimeout(() => {
                _loadPromise = null;
                _loaderScriptAdded = false;
                reject(new Error('连接高德服务超时'));
            }, 15000);
            const clearScriptTimeout = () => clearTimeout(scriptTimeout);
            script.onload = () => { clearScriptTimeout(); startLoad(); };
            script.onerror = () => {
                clearScriptTimeout();
                _loadPromise = null;
                _loaderScriptAdded = false;  // 注入失败允许重试
                reject(new Error('无法连接高德服务'));
            };
            document.head.appendChild(script);
            _loaderScriptAdded = true;
        } else {
            startLoad();  // script 已注入过（仅重试路径走到这里）
        }
    });

    return _loadPromise;
}

// ===== 适配器 =====
class AmapAdapter {
    // AMap: loadAmap resolve 的 SDK 对象；containerId: 容器 id；view: 初始视角 {lat, lng, zoom}
    // 注意：容器必须已可见后才能 new（隐藏容器 WebGL 尺寸为 0，会渲染空白）
    constructor(AMap, containerId, view) {
        this._AMap = AMap;
        this._handlers = null;      // renderTrack 注入的事件回调集
        this.overlays = [];         // 当前轨迹覆盖物集合（renderTrack 全量重建）
        this._defaultView = view;   // fitTrack 无覆盖物时的回退视角

        // 不传 layers → 默认标准底图
        this.map = new AMap.Map(containerId, {
            center: [view.lng, view.lat],
            zoom: view.zoom,
            viewMode: '2D',
            resizeEnable: true
        });

        this.map.on('click', (e) => {
            if (e.target && e.target !== this.map) return;  // 防覆盖物点击冒泡到地图
            if (this._handlers) {
                this._handlers.onMapClick({ lat: e.lnglat.getLat(), lng: e.lnglat.getLng() });
            }
        });

        // 左键按下 → onMapMouseDown：画笔加点走按下而非 click（click 在按下后拖动平移时被引擎抑制，会丢点）
        this.map.on('mousedown', (e) => {
            if (e.target && e.target !== this.map) return;  // 防覆盖物按下冒泡到地图
            const oe = e.originEvent || {};
            // 顶点/中点覆盖物上的按下有自己的交互（拖顶点/插点），不当作地图落笔（DOM 级命中检测，双引擎一致）
            const t = oe.target;
            if (t && t.closest && t.closest('.vertex-marker, .midpoint-handle')) return;
            if (!oe || oe.button !== 0) return;  // 仅左键；事件缺按钮信息时保守拒绝（与 Leaflet 侧一致）
            if (this._handlers && this._handlers.onMapMouseDown) {
                this._handlers.onMapMouseDown({ lat: e.lnglat.getLat(), lng: e.lnglat.getLng() });
            }
        });

        this._setupMiddleDrag();
    }

    // 中键拖动：高德内置拖动只认左键（setStatus dragEnable 不作用于中键手势），
    // 画笔锁定时的中键拖图在 Leaflet 档由引擎天然支持，官方档需手动实现。
    // 用容器像素换算 setCenter（中心向鼠标位移反方向移动 = 地图内容跟手），不依赖 panBy 方向语义。
    _setupMiddleDrag() {
        const container = this.map.getContainer();
        let lastX = 0;
        let lastY = 0;
        let dragging = false;

        container.addEventListener('mousedown', (e) => {
            if (e.button !== 1) return;
            e.preventDefault();  // 阻止中键自动滚动
            dragging = true;
            lastX = e.clientX;
            lastY = e.clientY;
        });

        window.addEventListener('mousemove', (e) => {
            if (!dragging) return;
            const dx = e.clientX - lastX;
            const dy = e.clientY - lastY;
            lastX = e.clientX;
            lastY = e.clientY;
            const centerPx = this.map.lngLatToContainer(this.map.getCenter());
            const next = this.map.containerToLngLat(
                new this._AMap.Pixel(centerPx.getX() - dx, centerPx.getY() - dy));
            this.map.setCenter(next);
        });

        const stop = () => { dragging = false; };
        window.addEventListener('mouseup', stop);
        window.addEventListener('blur', stop);  // 切窗丢 mouseup 时终止，避免回窗后粘滞拖动
    }

    // 激活地图：恢复视角（AMap zoom 仅支持整数）
    activate(view) {
        this.map.setZoomAndCenter(Math.round(view.zoom), [view.lng, view.lat]);
    }

    // 读取当前视角
    getView() {
        const c = this.map.getCenter();
        return { lat: c.getLat(), lng: c.getLng(), zoom: this.map.getZoom() };
    }

    // 拖动平移开关（画笔模式下禁用，避免按住左键移动被当成拖图）；
    // 同时切换双击缩放：画笔下双击应是连续落笔而非视角跳动
    setDragEnabled(enabled) {
        this.map.setStatus({ dragEnable: enabled, doubleClickZoom: enabled });
    }

    // 定位到指定位置
    flyTo(lat, lng, zoom) {
        this.map.setZoomAndCenter(zoom, [lng, lat]);
    }

    // 缩放至轨迹覆盖物范围；无覆盖物时回默认中心
    fitTrack(points) {
        if (this.overlays.length > 0) {
            this.map.setFitView(this.overlays, false, [60, 60, 60, 60], 18);
        } else {
            const v = this._defaultView;
            this.map.setZoomAndCenter(v.zoom, [v.lng, v.lat]);
        }
    }

    // 轨迹渲染（全量重建），handlers 提供 onMapClick/onVertexDragStart/onVertexDragEnd/onVertexClick/onMidpointClick
    renderTrack(points, handlers) {
        this._handlers = handlers;
        this.map.remove(this.overlays);
        this.overlays = [];

        const n = points.length;

        // 主线
        if (n >= 2) {
            this.overlays.push(new this._AMap.Polyline({
                path: points.map((p) => [p.lng, p.lat]),
                strokeColor: TRACK_ACCENT,
                strokeWeight: 3,
                strokeOpacity: 1,
                lineJoin: 'round',
                map: this.map
            }));
        }

        // 闭合虚线（末点→首点）
        if (n >= 3) {
            this.overlays.push(new this._AMap.Polyline({
                path: [[points[n - 1].lng, points[n - 1].lat], [points[0].lng, points[0].lat]],
                strokeColor: TRACK_ACCENT,
                strokeWeight: 2,
                strokeOpacity: 0.6,
                strokeStyle: 'dashed',    // 虚线生效必须同时声明 strokeStyle
                strokeDasharray: [6, 6],  // 注意小写 a（AMap 2.0 拼写）
                map: this.map
            }));
        }

        // 顶点（可拖拽调整、点击删除）
        points.forEach((p, i) => {
            const marker = new this._AMap.Marker({
                content: '<div class="vertex-marker"></div>',
                position: [p.lng, p.lat],
                offset: new this._AMap.Pixel(-6, -6),  // 12x12 标记中心对准坐标点
                draggable: true,
                cursor: 'move',
                map: this.map
            });
            marker.on('dragstart', () => handlers.onVertexDragStart(i));
            marker.on('dragend', () => {
                const pos = marker.getPosition();
                handlers.onVertexDragEnd(i, { lat: pos.getLat(), lng: pos.getLng() });
            });
            marker.on('click', () => handlers.onVertexClick(i));
            this.overlays.push(marker);
        });

        // 中点插入手柄（相邻段 + 闭合段，闭合段仅当点数>=3，同 Leaflet 边界规则）
        if (n >= 2) {
            for (let i = 0; i < n; i++) {
                if (i === n - 1 && n < 3) break;
                const a = points[i];
                const b = points[(i + 1) % n];
                const mid = { lat: (a.lat + b.lat) / 2, lng: (a.lng + b.lng) / 2 };
                const handle = new this._AMap.CircleMarker({
                    center: [mid.lng, mid.lat],
                    radius: 5,
                    strokeColor: TRACK_ACCENT,
                    strokeWeight: 2,
                    fillColor: TRACK_ACCENT,
                    fillOpacity: 0.35,
                    cursor: 'pointer',
                    map: this.map
                });
                handle.on('click', () => handlers.onMidpointClick(i, mid));
                this.overlays.push(handle);
            }
        }
    }
}

// ===== POI 搜索 =====
// 创建地点搜索实例（不传 map/panel/autoFitView，纯数据回调用法）
function createPlaceSearch() {
    return new window.AMap.PlaceSearch({ pageSize: 8 });
}
