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

function getAmapKey() {
    return localStorage.getItem(AMAP_KEY_STORAGE) || '';
}

function getAmapScode() {
    return localStorage.getItem(AMAP_SCODE_STORAGE) || '';
}

function hasAmapKey() {
    return !!getAmapKey();
}

// ===== 引擎管理 =====
const MapEngine = {
    mode: 'classic',               // 当前底图模式
    adapters: { leaflet: null, amap: null },  // amap 懒建（需 Key + 在线加载）
    loading: false,                // 官方引擎加载防重入

    init() {
        this.adapters.leaflet = new LeafletAdapter('map-leaflet');
        this.adapters.leaflet.setBaseMode('classic');
        this._bindSwitchButtons();
        this._bindSettingsModal();
        this._updateSwitchStates();
    },

    // ===== 模式切换 =====
    switchMode(mode) {
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
        this.mode = mode;
        this._updateSwitchStates();
        renderTrack();  // 后台引擎覆盖物不维护，切换后必须重渲染
    },

    async _switchToAmap() {
        if (!hasAmapKey()) {
            // 未配置 Key：引导到设置弹层，停留当前档
            openSettings();
            return;
        }

        // 已建实例：仅做视图迁移与容器切换
        if (this.adapters.amap) {
            const view = this.adapters.leaflet.getView();
            document.getElementById('map-leaflet').style.display = 'none';
            document.getElementById('map-amap').style.display = '';
            this.adapters.amap.activate(view);
            this.mode = 'amap';
            this._updateSwitchStates();
            renderTrack();
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
            this.mode = 'amap';
            this._updateSwitchStates();
            renderTrack();
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
        this.activeAdapter().fitTrack(points);
    },

    flyTo(lat, lng, zoom) {
        this.activeAdapter().flyTo(lat, lng, zoom);
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

    // ===== Key 设置弹层 =====
    _bindSettingsModal() {
        document.getElementById('settings-btn').addEventListener('click', openSettings);
        document.getElementById('settings-close-btn').addEventListener('click', closeSettings);
        document.getElementById('settings-save-btn').addEventListener('click', () => this._saveKeys());
        document.getElementById('settings-clear-btn').addEventListener('click', () => this._clearKeys());
        // 点击遮罩关闭
        document.getElementById('settings-modal').addEventListener('click', (e) => {
            if (e.target.id === 'settings-modal') closeSettings();
        });
    },

    _saveKeys() {
        const key = document.getElementById('amap-key-input').value.trim();
        const scode = document.getElementById('amap-scode-input').value.trim();
        const note = document.getElementById('settings-note');

        if (!key) {
            note.textContent = 'Key 不能为空';
            return;
        }

        const keyChanged = key !== getAmapKey() || scode !== getAmapScode();
        localStorage.setItem(AMAP_KEY_STORAGE, key);
        if (scode) {
            localStorage.setItem(AMAP_SCODE_STORAGE, scode);
        } else {
            localStorage.removeItem(AMAP_SCODE_STORAGE);
        }

        // 引擎已加载后凭据变更不热重载（loader 不重复请求）
        if (this.adapters.amap && keyChanged) {
            note.textContent = '已保存。检测到 Key 变更，刷新页面后生效。';
        } else {
            note.textContent = '已保存。';
        }
        this._updateSwitchStates();
        if (typeof updateSearchState === 'function') updateSearchState();
    },

    _clearKeys() {
        localStorage.removeItem(AMAP_KEY_STORAGE);
        localStorage.removeItem(AMAP_SCODE_STORAGE);
        document.getElementById('amap-key-input').value = '';
        document.getElementById('amap-scode-input').value = '';
        document.getElementById('settings-note').textContent = '已清除。';

        // 若正处于官方档，切回经典档
        if (this.mode === 'amap') {
            this.switchMode('classic');
        }
        this._updateSwitchStates();
        if (typeof updateSearchState === 'function') updateSearchState();
    },
};

// ===== 弹层与遮罩开关 =====
function openSettings() {
    document.getElementById('amap-key-input').value = getAmapKey();
    document.getElementById('amap-scode-input').value = getAmapScode();
    document.getElementById('settings-note').textContent = '';
    document.getElementById('settings-modal').style.display = '';
}

function closeSettings() {
    document.getElementById('settings-modal').style.display = 'none';
}

function showMapLoading(text) {
    document.getElementById('map-loading-text').textContent = text || '加载中…';
    document.getElementById('map-loading').style.display = '';
}

function hideMapLoading() {
    document.getElementById('map-loading').style.display = 'none';
}
