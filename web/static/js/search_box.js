// 地址搜索 - 高德 PlaceSearch（需页面配置 Key，坐标 GCJ-02 直用）
//
// 依赖：map_adapter_amap.js (loadAmap/createPlaceSearch)、map_engine.js (MapEngine.flyTo/Key 读取)

let placeSearch = null;      // 懒建：首次搜索时初始化
let searchTimer = null;      // 输入防抖
let searchSeq = 0;           // 请求序号（丢弃过期响应）

// ===== 初始化 =====
function initSearchBox() {
    const input = document.getElementById('search-input');
    const box = document.querySelector('.search-box');

    input.addEventListener('input', () => {
        clearTimeout(searchTimer);
        const kw = input.value.trim();
        if (!kw) {
            hideSearchResults();
            return;
        }
        searchTimer = setTimeout(() => doSearch(kw), 300);
    });

    input.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') {
            // 回车选首条
            const first = document.querySelector('#search-results li[data-idx]');
            if (first) first.click();
        } else if (e.key === 'Escape') {
            hideSearchResults();
        }
    });

    // 未配置 Key 时点击搜索框引导到设置弹层
    box.addEventListener('click', () => {
        if (!hasAmapKey()) openSettings();
    });

    // 点击其他区域收起下拉
    document.addEventListener('click', (e) => {
        if (!box.contains(e.target)) hideSearchResults();
    });

    updateSearchState();
}

// ===== 启用/禁用态（Key 配置变化时刷新）=====
function updateSearchState() {
    const input = document.getElementById('search-input');
    if (hasAmapKey()) {
        input.disabled = false;
        input.placeholder = '搜索地点，如：贵州大学';
        input.title = '';
    } else {
        input.disabled = true;
        input.placeholder = '配置高德 Key 后可用搜索';
        input.title = '点击配置高德 Key';
    }
}

// ===== 搜索 =====
async function doSearch(kw) {
    if (!hasAmapKey()) {
        openSettings();
        return;
    }

    // 首次搜索：加载 JS API 并创建搜索服务
    if (!placeSearch) {
        showSearchMessage('初始化搜索服务…');
        try {
            await loadAmap(getAmapKey(), getAmapScode());
            placeSearch = createPlaceSearch();
        } catch (error) {
            showSearchMessage('搜索服务初始化失败：' + (error && error.message ? error.message : error));
            return;
        }
    }

    const seq = ++searchSeq;
    placeSearch.search(kw, (status, result) => {
        if (seq !== searchSeq) return;  // 过期响应丢弃
        if (status === 'complete' && result.poiList && result.poiList.pois.length) {
            renderSearchResults(result.poiList.pois);
        } else if (status === 'no_data') {
            showSearchMessage('无结果');
        } else {
            // error：常见为 Key/安全密钥校验失败
            showSearchMessage('搜索失败：请检查 Key/安全密钥（齿轮设置）');
        }
    });
}

// ===== 下拉渲染 =====
function renderSearchResults(pois) {
    const ul = document.getElementById('search-results');
    ul.innerHTML = '';
    pois.forEach((poi, idx) => {
        const li = document.createElement('li');
        li.dataset.idx = idx;

        const name = document.createElement('div');
        name.className = 'poi-name';
        name.textContent = poi.name || '未命名地点';

        const addr = document.createElement('div');
        addr.className = 'poi-addr';
        addr.textContent = poi.address || poi.district || '';

        li.appendChild(name);
        li.appendChild(addr);
        li.addEventListener('click', () => selectPoi(poi));
        ul.appendChild(li);
    });
    ul.style.display = '';
}

function showSearchMessage(text) {
    const ul = document.getElementById('search-results');
    ul.innerHTML = '';
    const li = document.createElement('li');
    li.className = 'poi-empty';
    li.textContent = text;
    ul.appendChild(li);
    ul.style.display = '';
}

function hideSearchResults() {
    const ul = document.getElementById('search-results');
    ul.style.display = 'none';
}

// ===== 选中 → 飞行定位（GCJ-02 坐标直接使用）=====
function selectPoi(poi) {
    if (poi.location && typeof poi.location.getLng === 'function') {
        const lng = poi.location.getLng();
        const lat = poi.location.getLat();
        MapEngine.flyTo(lat, lng, 16);
        document.getElementById('search-input').value = poi.name || '';
    }
    hideSearchResults();
}
