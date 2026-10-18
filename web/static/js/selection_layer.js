// 临时节点选择覆盖层：仅持有索引与选框，坐标仍由编辑器 points 保存。
// 每次手势相对按下快照计算；松手提交一次，取消/失焦/视野改变则回滚。
const SelectionLayer = (() => {
    const G = SelectionGeometry;
    let host, svg, api, active = false, indices = [], frameGeo = null, drag = null;
    const stage = document.querySelector('.map-stage');
    const pixel = p => MapEngine.latLngToContainer(p.lat, p.lng);
    const geo = p => MapEngine.containerToLatLng(p.x, p.y);
    const same = (a, b) => a.every((p, i) => Math.abs(p.lat - b[i].lat) < 1e-12
        && Math.abs(p.lng - b[i].lng) < 1e-12);
    function node(tag, attrs, cls) {
        const el = document.createElementNS('http://www.w3.org/2000/svg', tag);
        Object.entries(attrs).forEach(([key, value]) => el.setAttribute(key, value));
        if (cls) el.setAttribute('class', cls);
        return el;
    }
    function position(e) {
        const r = stage.getBoundingClientRect();
        return { x: e.clientX - r.left, y: e.clientY - r.top };
    }
    function rememberFrame(f) {
        frameGeo = f ? [[-1, -1], [1, -1], [1, 1], [-1, 1]]
            .map(([x, y]) => geo(G.world(f, x * f.width / 2, y * f.height / 2))) : null;
    }
    function frame() {
        if (!frameGeo) return null;
        const [a, b, c, d] = frameGeo.map(pixel);
        const width = Math.hypot(b.x - a.x, b.y - a.y);
        const height = Math.hypot(d.x - a.x, d.y - a.y);
        return { x: (a.x + c.x) / 2, y: (a.y + c.y) / 2, width, height,
            angle: width > 1e-6 ? Math.atan2(b.y - a.y, b.x - a.x)
                : height > 1e-6 ? Math.atan2(d.y - a.y, d.x - a.x) - Math.PI / 2 : 0 };
    }
    function render() {
        if (!svg) return;
        svg.replaceChildren();
        svg.setAttribute('width', stage.clientWidth);
        svg.setAttribute('height', stage.clientHeight);
        host.classList.toggle('is-active', active);
        const status = document.getElementById('selection-status');
        status.hidden = !active;
        document.getElementById('delete-selection-btn').disabled = !active || !indices.length;
        status.textContent = indices.length ? `已选 ${indices.length} 个节点 · Delete 删除 · Esc 取消选择`
            : '拖出矩形框选节点 · 中键平移地图';
        if (!active) return;
        indices.forEach(i => {
            const p = pixel(api.getPoints()[i]);
            svg.appendChild(node('circle', { cx: p.x, cy: p.y, r: 8, 'data-index': i }, 'selection-node'));
        });
        if (drag && drag.key === 'marquee') {
            const a = drag.start, b = drag.last;
            svg.appendChild(node('rect', { x: Math.min(a.x, b.x), y: Math.min(a.y, b.y),
                width: Math.abs(a.x - b.x), height: Math.abs(a.y - b.y) }, 'selection-marquee'));
            return;
        }
        const f = frame();
        if (!f) return;
        // 小选区留出可拖动的内部空间，避免禁用的边柄在单点中心重叠抢走移动手势。
        const w = Math.max(24, f.width), h = Math.max(24, f.height);
        const group = node('g', { transform: `translate(${f.x} ${f.y}) rotate(${f.angle * 180 / Math.PI})` });
        group.appendChild(node('rect', { x: -w / 2, y: -h / 2, width: w, height: h,
            'data-selection-key': 'move' }, 'selection-frame'));
        Object.entries(G.handles).forEach(([key, [x, y]]) => {
            const disabled = !(x && f.width > 1e-6 || y && f.height > 1e-6);
            const handle = node('circle', { cx: x * w / 2, cy: y * h / 2, r: 5,
                'data-selection-key': key, 'data-disabled': disabled }, 'shape-handle selection-handle');
            const cursors = ['e', 'se', 's', 'sw', 'w', 'nw', 'n', 'ne'];
            const angle = Math.atan2(y, x) + f.angle + 2 * Math.PI;
            handle.style.cursor = disabled ? 'not-allowed' : cursors[Math.round(angle / (Math.PI / 4)) % 8] + '-resize';
            group.appendChild(handle);
        });
        group.appendChild(node('line', { x1: 0, y1: -h / 2, x2: 0, y2: -h / 2 - 28 }, 'shape-rot-line'));
        group.appendChild(node('circle', { cx: 0, cy: -h / 2 - 28, r: 6,
            'data-selection-key': 'rotate' }, 'shape-handle-rot'));
        svg.appendChild(group);
    }
    function release(id) {
        if (host.hasPointerCapture(id)) host.releasePointerCapture(id);
    }
    function finish(cancel = false) {
        if (!drag) return;
        const previous = drag;
        drag = null;
        if (previous.key === 'marquee') {
            if (cancel) indices = [];
            rememberFrame(G.bounds(indices.map(i => pixel(api.getPoints()[i]))));
        } else if (cancel) {
            frameGeo = previous.frameGeo;
            api.apply(previous.snapshot);
        } else if (!same(previous.snapshot, api.getPoints())) {
            api.commit(previous.snapshot);
        }
        release(previous.id);
        render();
    }
    function clear() {
        finish(true);
        indices = [];
        frameGeo = null;
        render();
    }
    function begin(e) {
        if (!active) return;
        if (e.button !== 0) { if (e.button === 1) finish(true); return; }
        if (drag) return;
        e.preventDefault();
        e.stopPropagation();
        if (host.classList.contains('is-hidden')) return;
        const target = e.target.closest('[data-selection-key]');
        if (target && target.dataset.disabled === 'true') return;
        const start = position(e);
        const key = target ? target.dataset.selectionKey : 'marquee';
        if (key === 'marquee') { indices = []; frameGeo = null; }
        drag = { id: e.pointerId, key, start, last: start, frame: frame(), frameGeo,
            snapshot: api.getPoints().map(p => ({ ...p })),
            pixels: indices.map(i => ({ i, ...pixel(api.getPoints()[i]) })) };
        host.setPointerCapture(e.pointerId);
        render();
    }
    function update(e) {
        if (!drag || e.pointerId !== drag.id) return;
        if (!(e.buttons & 1)) { finish(true); return; }
        const end = position(e);
        drag.last = end;
        if (drag.key === 'marquee') {
            indices = api.getPoints().flatMap((p, i) => G.inside(drag.start, end, pixel(p)) ? [i] : []);
        } else {
            const nextFrame = G.transform(drag.frame, drag.key, drag.start, end);
            const next = drag.snapshot.map(p => ({ ...p }));
            // 返回起点保持原坐标，避免空手势产生投影舍入误差及无意义撤销。
            if (Math.hypot(end.x - drag.start.x, end.y - drag.start.y) > 1e-6) {
                for (const p of drag.pixels) {
                    const q = G.point(p, drag.frame, nextFrame), ll = geo(q);
                    const back = G.validGeo(ll) ? pixel(ll) : null;
                    // 拒绝越过地理边界/投影饱和的整帧，保留上一合法状态。
                    if (!back || Math.hypot(back.x - q.x, back.y - q.y) > 0.1) return;
                    next[p.i] = { ...next[p.i], ...ll };
                }
            }
            api.apply(next);
            rememberFrame(nextFrame);
        }
        e.preventDefault();
        render();
    }
    return {
        init(callbacks) {
            api = callbacks;
            host = document.getElementById('selection-layer');
            svg = node('svg', {}, 'selection-svg');
            host.appendChild(svg);
            host.addEventListener('pointerdown', begin);
            host.addEventListener('pointermove', update);
            host.addEventListener('pointerup', e => { if (drag && e.pointerId === drag.id && e.button === 0) finish(); });
            ['pointercancel', 'lostpointercapture'].forEach(type => host.addEventListener(type, () => finish(true)));
            ['mousedown', 'click', 'dblclick'].forEach(type => host.addEventListener(type, e => {
                if (active && e.button === 0) e.stopPropagation();
            }));
            window.addEventListener('blur', () => finish(true));
            document.addEventListener('keydown', e => {
                if (active && e.key === 'Escape') { clear(); e.preventDefault(); }
            });
            MapEngine.bindViewHooks({
                onChange() { finish(true); MapEngine.mountOverlay(host); render(); },
                onZoomStart() { finish(true); host.classList.add('is-hidden'); },
                onZoomEnd() { host.classList.remove('is-hidden'); render(); }
            });
            new ResizeObserver(() => { finish(true); render(); }).observe(stage);
            render();
        },
        setActive(value) { clear(); active = value; render(); },
        selectIndices(next) {
            clear();
            indices = [...new Set(next)].filter(i => Number.isInteger(i) && i >= 0 && i < api.getPoints().length);
            rememberFrame(G.bounds(indices.map(i => pixel(api.getPoints()[i]))));
            render();
        },
        clear,
        cancelDrag: () => finish(true),
        indices: () => indices.slice()
    };
})();
