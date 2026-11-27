// 地图引擎管理器 - 底图模式切换 / 双引擎适配 / 高德 Key 管理
//
// 依赖（按页面加载顺序在其后）：map_adapter_leaflet.js (LeafletAdapter)、map_adapter_amap.js (loadAmap/AmapAdapter)
// 被使用：track_editor.js（renderTrack/fitTrack 转发）、search_box.js（flyTo/loadAmap/Key 读取）
//
// 模式说明：
//   classic   经典瓦片（webrd style=8，无 Key）
//   fresh     新版瓦片（wprd style=7，无 Key）
//   satellite 卫星影像 + 路网标注（webst style=6/8，无 Key）
//   amap      官方高德 JS API 2.0 引擎（需页面配置 Key，懒加载）

// ===== Key 本地存储 =====
const AMAP_KEY_STORAGE = 'te_amap_key';
const AMAP_SCODE_STORAGE = 'te_amap_scode';

// 从服务器配置文件读取的 Key（优先级高于 localStorage）
let _serverAmapKey = '';
let _serverAmapScode = '';

// 初始化：从服务器加载高德 Key 配置
async function initAmapKeyFromServer() {
    try {
        const response = await fetch('/api/amap-key');
        if (response.ok) {
            const data = await response.json();
            _serverAmapKey = data.key || '';
            _serverAmapScode = data.securityJsCode || '';
        } else {
            throw new Error('无法读取地图配置');
        }
    } catch (e) {
        throw new Error('无法读取本地地图配置，请恢复服务后重试');
    }
}

function readMapStorage(key) {
    try { return localStorage.getItem(key); } catch { return ''; }
}

function getAmapKey() {
    // 优先使用服务器配置，其次使用 localStorage
    return _serverAmapKey || readMapStorage(AMAP_KEY_STORAGE) || '';
}

function getAmapScode() {
    // 优先使用服务器配置，其次使用 localStorage
    return _serverAmapScode || readMapStorage(AMAP_SCODE_STORAGE) || '';
}

function hasAmapKey() {
    return !!getAmapKey();
}

// ===== 引擎管理 =====
const MapEngine = {
    mode: 'classic',               // 当前底图模式
    adapters: { leaflet: null, amap: null },  // amap 懒建（需 Key + 在线加载）
    loading: false,                // 官方引擎加载防重入
    _dragEnabled: true,            // 拖动平移状态（画笔工具禁用），切换档位后需重放
    _viewHooks: [],                // 覆盖层的视野钩子（切档时统一重绑）

    async init() {
        // 先从服务器加载高德 Key 配置
        await initAmapKeyFromServer();

        this.adapters.leaflet = new LeafletAdapter('map-leaflet');
        this.adapters.leaflet.setBaseMode('classic');
        this._bindSwitchButtons();
        this._updateSwitchStates();
        this.switchMode(readMapStorage('map_mode') || 'classic');
    },

    // ===== 模式切换 =====
    switchMode(mode) {
        if (!['classic', 'fresh', 'satellite', 'amap'].includes(mode)) return;
        if (mode === this.mode || this.loading) return;

        if (mode === 'amap') {
            this._switchToAmap();
            return;
        }

        // Leaflet 三档互切（含从官方档切回）
        if (this.mode === 'amap' && this.adapters.amap) {
            const view = this.adapters.amap.getView();
            document.getElementById('map-amap').style.display = 'none';
            document.getElementById('map-leaflet').style.display = '';
            this.adapters.leaflet.activate(view);
        }
        this.adapters.leaflet.setBaseMode(mode);
        this.adapters.leaflet.setDragEnabled(this._dragEnabled);
        this.mode = mode;
        this._updateSwitchStates();
        renderTrack();  // 后台引擎覆盖物不维护，切换后必须重渲染
        this._bindViewHooksToActive();   // 图形层跟随新引擎重新定位
    },

    async _switchToAmap() {
        if (!hasAmapKey()) {
            // 未配置 Key：引导到设置弹层，停留当前档
            openSettings('maps');
            return;
        }

        // 已建实例：仅做视图迁移与容器切换
        if (this.adapters.amap) {
            const view = this.adapters.leaflet.getView();
            document.getElementById('map-leaflet').style.display = 'none';
            document.getElementById('map-amap').style.display = '';
            this.adapters.amap.activate(view);
            this.adapters.amap.setDragEnabled(this._dragEnabled);
            this.mode = 'amap';
            this._updateSwitchStates();
            renderTrack();
            this._bindViewHooksToActive();
            return;
        }

        // 首次：动态加载官方 JS API
        this.loading = true;
        showMapLoading('加载高德地图…');
        try {
            const AMap = await loadAmap(getAmapKey(), getAmapScode());
            const view = this.adapters.leaflet.getView();
            document.getElementById('map-leaflet').style.display = 'none';
            document.getElementById('map-amap').style.display = '';  // 容器必须先可见再建实例
            this.adapters.amap = new AmapAdapter(AMap, 'map-amap', view);
            this.adapters.amap.setDragEnabled(this._dragEnabled);
            this.mode = 'amap';
            this._updateSwitchStates();
            renderTrack();
            this._bindViewHooksToActive();
        } catch (error) {
            showMessage('官方地图加载失败：' + (error && error.message ? error.message : error), 'error');
            this._updateSwitchStates();
        } finally {
            this.loading = false;
            hideMapLoading();
        }
    },

    // ===== 转发到当前活跃引擎 =====
    activeAdapter() {
        return this.mode === 'amap' ? this.adapters.amap : this.adapters.leaflet;
    },

    renderTrack(points, handlers) {
        this.activeAdapter().renderTrack(points, handlers);
    },

    fitTrack(points) {
        this.activeAdapter().fitTrack(points, [60, 60]); // Leave room for the rotation handle and map controls.
    },

    flyTo(lat, lng, zoom) {
        this.activeAdapter().flyTo(lat, lng, zoom);
    },

    // 拖动平移开关（画笔工具禁用）：存值并转发当前活跃引擎，切换档位后重放
    setDragEnabled(enabled) {
        this._dragEnabled = enabled;
        this.activeAdapter().setDragEnabled(enabled);
    },

    // ===== 图形层用的像素换算与视野钩子（转发到当前活跃引擎）=====
    // 钩子只注册一次，切换到新适配器时必须重新绑定，否则切档后图形不再跟随视野；
    // 重绑后立刻补一次 onChange，让图形在新引擎下重新定位。
    bindViewHooks(hooks) {
        this._viewHooks.push(hooks);
        this._bindViewHooksToActive();
    },

    _bindViewHooksToActive() {
        const notify = key => this._viewHooks.forEach(h => { if (h[key]) h[key](); });
        this.activeAdapter().bindViewHooks({
            onChange: () => notify('onChange'),
            onZoomStart: () => notify('onZoomStart'),
            onZoomEnd: () => notify('onZoomEnd')
        });
        notify('onChange');
    },

    latLngToContainer(lat, lng) {
        return this.activeAdapter().latLngToContainer(lat, lng);
    },

    // 当前活跃引擎是否已就绪。init() 是异步的（开头要拉一次高德 Key 配置），
    // 在那之前 activeAdapter() 返回 null —— 而侧边栏的图形按钮在脚本加载时就绑好了 click，
    // 用户在 init 完成前点到，会一路走到上面的坐标换算上抛
    // 「Cannot read properties of null」。调用方先问这里再动手。
    isReady() {
        return !!this.activeAdapter();
    },

    containerToLatLng(x, y) {
        return this.activeAdapter().containerToLatLng(x, y);
    },

    // 覆盖层放在活跃地图内，让滚轮和中键沿原生事件路径交给地图引擎。
    mountOverlay(element) {
        const container = this.activeAdapter().map.getContainer();
        if (element.parentNode !== container) container.appendChild(element);
    },

    // ===== 切换按钮 =====
    _bindSwitchButtons() {
        ['classic', 'fresh', 'satellite', 'amap'].forEach((mode) => {
            const btn = document.getElementById('mode-' + mode);
            if (!btn) return;
            btn.removeAttribute('disabled');  // 用 .disabled 类控制视觉，保留 click 引导
            btn.addEventListener('click', () => this.switchMode(mode));
        });
    },

    _updateSwitchStates() {
        document.getElementById('map-style').value = this.mode;
        ['classic', 'fresh', 'satellite', 'amap'].forEach((mode) => {
            const btn = document.getElementById('mode-' + mode);
            if (!btn) return;
            btn.classList.toggle('active', this.mode === mode);
            if (mode === 'amap') {
                const unavailable = !hasAmapKey() && this.adapters.amap === null;
                btn.classList.toggle('disabled', unavailable);
                btn.title = unavailable ? '官方高德地图（需先配置 Key，点击设置）' : '官方高德地图';
            }
        });
    },

};

function showMapLoading(text) {
    document.getElementById('map-loading-text').textContent = text || '加载中…';
    document.getElementById('map-loading').style.display = '';
}

function hideMapLoading() {
    document.getElementById('map-loading').style.display = 'none';
}
