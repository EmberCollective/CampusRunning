// 图形模板覆盖层：在 .map-stage 上叠一层 SVG，绘制图形轮廓、预览点与变换手柄
//
// 依赖（脚本顺序在前）：shape_geometry.js（纯几何，全局函数）、map_engine.js（MapEngine 像素换算）
// 坐标约定：几何一律在「米」空间算（shape_geometry 的局部坐标系）；
//           本文件负责 米 → 像素（scale）与 y 轴翻转：px = cx + x·scale，py = cy − y·scale
//
// 平移优化：视口平移时所有元素位移量相同，故只更新最外层 <g> 的 translate，
// 不重建节点——AMap 的 mapmove 事件频率接近 60 fps，逐帧重建 500 个预览点会卡顿。

const ShapeLayer = (function () {
    const NS = 'http://www.w3.org/2000/svg';
    const ROTATE_HANDLE_PX = 28;    // 旋转手柄距离包围盒上边的像素距离（缩放不变，故用像素）
    // 8 方向缩放手柄光标，按屏幕角度每 45 度一档
    const RESIZE_CURSORS = ['e-resize', 'se-resize', 's-resize', 'sw-resize',
        'w-resize', 'nw-resize', 'n-resize', 'ne-resize'];

    const mapStageEl = document.querySelector('.map-stage');

    let svgEl = null;
    let rootG = null;               // 平移偏移容器：只改它的 transform
    let shapes = [];
    let selected = null;            // 选中图形的 id
    let pointSpacing = 10;          // 点间距（米）
    let scale = 1;                  // 像素 / 米
    let originPx = null;            // 上次全量重建时 shapes[0] 中心的像素坐标（平移偏移的基准）
    let changeCallbacks = [];
    let seq = 0;                    // id 自增序号

    // ---------- 工具 ----------

    function stageSize() {
        const rect = mapStageEl.getBoundingClientRect();
        return { w: rect.width, h: rect.height };
    }

    function stageCenterPx() {
        const { w, h } = stageSize();
        return { x: w / 2, y: h / 2 };
    }

    // 当前缩放下「1 米 = 多少像素」。用屏幕中心与其以北 50 px 两点反算：
    // 以固定像素基准求，任何 zoom 都安全；不能用固定经纬度偏移，
    // 低缩放下那点偏移不足 1 px 会除零。
    function computeScale() {
        const c = stageCenterPx();
        const a = MapEngine.containerToLatLng(c.x, c.y);
        const b = MapEngine.containerToLatLng(c.x, c.y - 50);
        const meters = haversineMeters(a, b);
        return meters > 0 ? 50 / meters : 1;
    }

    function shapeCenterPx(shape) {
        return MapEngine.latLngToContainer(shape.center.lat, shape.center.lng);
    }

    // 局部米坐标 → 舞台像素（重建基准下的坐标，不含平移偏移）
    function localToStage(shape, centerPx, lx, ly) {
        const p = projectLocal(shape, lx, ly);
        return { x: centerPx.x + p.x * scale, y: centerPx.y - p.y * scale };
    }

    // 舞台像素 → 相对图形中心的「东/北」偏移（米）
    function stageToOffset(centerPx, px, py) {
        return { x: (px - centerPx.x) / scale, y: -(py - centerPx.y) / scale };
    }

    function el(tag, attrs, className) {
        const node = document.createElementNS(NS, tag);
        if (className) node.setAttribute('class', className);
        Object.keys(attrs || {}).forEach((k) => node.setAttribute(k, attrs[k]));
        return node;
    }

    function notify() {
        changeCallbacks.forEach((cb) => cb());
    }

    function findShape(id) {
        return shapes.find((s) => s.id === id) || null;
    }

    // 全部图形依次打点、拼接 → 舞台像素点列（多图形间的连接段自然包含在内）
    function previewPixels() {
        const pts = [];
        shapes.forEach((shape) => {
            shapeToLoop(shape, pointSpacing).forEach((geo) => {
                pts.push(MapEngine.latLngToContainer(geo.lat, geo.lng));
            });
        });
        return pts;
    }

    // ---------- 指针交互 ----------
    //
    // 一次拖拽的完整状态：drag 为 null 表示未在拖拽。
    // 所有几何计算都在拖拽开始时对 snapshot 做，指针移动只重算「相对 snapshot」的结果，
    // 避免逐帧累积误差（连续 apply 会让浮点误差滚雪球）。
    let drag = null;
    // drag = {
    //   mode: 'move' | 'resize' | 'rotate',
    //   shapeId, key, snapshot,          // snapshot 是拖拽开始时的图形快照
    //   grabLocal: {lx, ly} | null,      // move 模式：抓取点相对中心的局部坐标（米）
    //   grabBearing: number | null       // rotate 模式：按下瞬间的指针方位角，用于去除起始抖动
    // }

    function pointerStagePos(evt) {
        const rect = mapStageEl.getBoundingClientRect();
        return { x: evt.clientX - rect.left, y: evt.clientY - rect.top };
    }

    function beginDrag(evt) {
        const handleEl = evt.target.closest ? evt.target.closest('[data-handle-key]') : null;
        const outlineEl = evt.target.closest ? evt.target.closest('[data-shape-id]') : null;
        const id = (handleEl && handleEl.dataset.shapeId) || (outlineEl && outlineEl.dataset.shapeId);
        if (!id) return;
        const shape = findShape(id);
        if (!shape) return;

        // 命中图形即选中（含点未选中图形直接开拖的场景）
        if (selected !== id) {
            selected = id;
            rebuild();
            notify();
        }

        const pos = pointerStagePos(evt);
        const centerPx = shapeCenterPx(shape);
        const offset = stageToOffset(centerPx, pos.x, pos.y);
        const key = handleEl ? handleEl.dataset.handleKey : null;
        const snapshot = { ...shape, center: { ...shape.center } };

        if (key === 'rotate') {
            // 记下按下瞬间的指针方位：用户可能抓在旋转圆点的任意位置，
            // 用它作为基准才能保证按下不跳转（rotationFromPointer 的第三个参数）
            drag = {
                mode: 'rotate', shapeId: id, key, snapshot,
                grabLocal: null, grabBearing: Math.atan2(offset.y, offset.x) - shape.rotation
            };
        } else if (key) {
            drag = { mode: 'resize', shapeId: id, key, snapshot, grabLocal: null, grabBearing: null };
        } else {
            drag = {
                mode: 'move', shapeId: id, key: null, snapshot,
                grabLocal: unprojectLocal(shape, offset.x, offset.y), grabBearing: null
            };
        }

        evt.preventDefault();
        evt.stopPropagation();
        if (evt.target.setPointerCapture) evt.target.setPointerCapture(evt.pointerId);
    }

    function updateDrag(evt) {
        if (!drag) return;
        const pos = pointerStagePos(evt);
        const snap = drag.snapshot;
        let next = null;

        if (drag.mode === 'move') {
            const geo = MapEngine.containerToLatLng(pos.x, pos.y);
            // 新中心 = 指针地理坐标 − 抓取点相对中心的旋转后偏移
            const shift = projectLocal(snap, drag.grabLocal.lx, drag.grabLocal.ly);
            next = {
                ...snap,
                center: {
                    lat: geo.lat - shift.y / M_PER_DEG_LAT,
                    lng: geo.lng - shift.x / mPerDegLng(geo.lat)
                }
            };
        } else if (drag.mode === 'resize') {
            const centerPx = shapeCenterPx(snap);
            const offset = stageToOffset(centerPx, pos.x, pos.y);
            next = resizeShape(snap, drag.key, offset.x, offset.y);
        } else {
            const centerPx = shapeCenterPx(snap);
            const offset = stageToOffset(centerPx, pos.x, pos.y);
            // 第三参数传抓取时的方位，避免按下瞬间图形「跳」到指针方向
            next = { ...snap, rotation: rotationFromPointer(offset.x, offset.y, drag.grabBearing) };
        }

        shapes = shapes.map((s) => (s.id === drag.shapeId ? normalizeShape(next) : s));
        rebuild();
        evt.preventDefault();
    }

    function endDrag(evt) {
        if (!drag) return;
        drag = null;
        rebuild();
        notify();
        if (evt && evt.target && evt.target.releasePointerCapture && evt.pointerId !== undefined) {
            try {
                evt.target.releasePointerCapture(evt.pointerId);
            } catch (e) {
                // 指针已释放，忽略
            }
        }
    }

    // 键盘：Esc 取消选中，Delete/Backspace 删除选中图形
    // （点地图空白取消选中走的不是这里——图形层 SVG 只在有图形处开启 pointer-events，
    //   点空白时事件落到地图容器上，由 track_editor.js 的 onMapClick 转达）
    function handleKeydown(evt) {
        if (evt.target.closest && evt.target.closest('input, textarea, select')) return;
        if (evt.key === 'Escape') {
            if (selected) {
                selected = null;
                rebuild();
                notify();
            }
            return;
        }
        if (evt.key === 'Delete' || evt.key === 'Backspace') {
            if (!selected) return;
            evt.preventDefault();
            const id = selected;
            shapes = shapes.filter((s) => s.id !== id);
            selected = null;
            rebuild();
            notify();
        }
    }

    // ---------- 渲染 ----------

    // 轮廓多边形。必须**单趟按基元顺序**取点：分两趟（先取所有基元的端点、再补圆弧采样）
    // 会把两条弯道的采样点全堆到直道之后，操场轮廓自交。
    function buildOutline(g, shape, centerPx) {
        const pts = [];
        shapeOutlines(shape).forEach((p) => {
            if (p.kind === 'line') {
                pts.push(localToStage(shape, centerPx, p.from.x, p.from.y));
                return;
            }
            // 圆弧按约 5 度一档采样，视觉上足够平滑
            const steps = Math.max(8, Math.round(Math.abs(p.sweep) / (Math.PI / 36)));
            for (let i = 0; i <= steps; i++) {
                const q = primitivePoint(p, i / steps);
                pts.push(localToStage(shape, centerPx, q.x, q.y));
            }
        });
        const outline = el('polygon', {
            points: pts.map((q) => `${q.x},${q.y}`).join(' ')
        }, 'shape-outline' + (shape.id === selected ? ' selected' : ''));
        outline.dataset.shapeId = shape.id;
        g.appendChild(outline);
    }

    // 手柄光标随图形旋转就近切换：取手柄相对中心在**屏幕坐标**下的角度后分档。
    // 屏幕 y 向下、旋转逆时针为正，故这里直接用屏幕坐标算即可，无需额外取反。
    function handleCursor(shape, centerPx, h) {
        const q = localToStage(shape, centerPx, h.lx, h.ly);
        let a = Math.atan2(q.y - centerPx.y, q.x - centerPx.x);
        if (a < 0) a += Math.PI * 2;
        return RESIZE_CURSORS[Math.round(a / (Math.PI / 4)) % 8];
    }

    function buildHandles(g, shape, centerPx) {
        // 选中虚线框
        const corners = [
            localToStage(shape, centerPx, -shape.width / 2, -shape.height / 2),
            localToStage(shape, centerPx, shape.width / 2, -shape.height / 2),
            localToStage(shape, centerPx, shape.width / 2, shape.height / 2),
            localToStage(shape, centerPx, -shape.width / 2, shape.height / 2)
        ];
        g.appendChild(el('polygon', {
            points: corners.map((q) => `${q.x},${q.y}`).join(' ')
        }, 'shape-frame'));

        handlePositions(shape).forEach((h) => {
            const q = localToStage(shape, centerPx, h.lx, h.ly);
            const node = el('rect', {
                x: q.x - 4, y: q.y - 4, width: 8, height: 8
            }, 'shape-handle');
            node.dataset.handleKey = h.key;
            node.dataset.shapeId = shape.id;
            node.setAttribute('vector-effect', 'non-scaling-stroke');
            node.style.cursor = handleCursor(shape, centerPx, h);
            g.appendChild(node);
        });

        // 旋转手柄：包围盒上边中点沿局部 +y 外移 ROTATE_HANDLE_PX 像素
        const topMid = localToStage(shape, centerPx, 0, shape.height / 2);
        const knob = localToStage(shape, centerPx, 0, shape.height / 2 + ROTATE_HANDLE_PX / scale);
        g.appendChild(el('line', {
            x1: topMid.x, y1: topMid.y, x2: knob.x, y2: knob.y
        }, 'shape-rot-line'));
        const rot = el('circle', { cx: knob.x, cy: knob.y, r: 6 }, 'shape-handle-rot');
        rot.dataset.handleKey = 'rotate';
        rot.dataset.shapeId = shape.id;
        rot.setAttribute('vector-effect', 'non-scaling-stroke');
        g.appendChild(rot);
    }

    // 全量重建：缩放变化、图形增删改、间距变化时调用
    function rebuild() {
        if (!svgEl) return;
        const { w, h } = stageSize();
        svgEl.setAttribute('width', w);
        svgEl.setAttribute('height', h);
        scale = computeScale();
        originPx = shapes.length ? shapeCenterPx(shapes[0]) : null;

        rootG = el('g', {}, 'shape-root');

        // 1) 预览折线：整条生成点列（多图形之间自动连出连接段，所见即所得）
        const pixels = previewPixels();
        if (pixels.length >= 2) {
            const loopPts = pixels.concat([pixels[0]]);
            rootG.appendChild(el('polyline', {
                points: loopPts.map((q) => `${q.x},${q.y}`).join(' ')
            }, 'shape-preview-line'));
        }

        // 2) 轮廓（在预览点之下，避免遮挡）
        shapes.forEach((shape) => buildOutline(rootG, shape, shapeCenterPx(shape)));

        // 3) 预览点：起点更大且实心，便于识别环路方向
        pixels.forEach((q, i) => {
            rootG.appendChild(i === 0
                ? el('circle', { cx: q.x, cy: q.y, r: 5 }, 'shape-preview-start')
                : el('circle', { cx: q.x, cy: q.y, r: 3.5 }, 'shape-preview-dot'));
        });

        // 4) 手柄最后画 → 位于图形层最顶
        const sel = findShape(selected);
        if (sel) buildHandles(rootG, sel, shapeCenterPx(sel));

        svgEl.replaceChildren(rootG);
    }

    // 视野变化：缩放没变就只平移（便宜），变了才全量重建
    function onViewChange() {
        if (!svgEl) return;
        const next = shapes.length ? shapeCenterPx(shapes[0]) : null;
        const nextScale = computeScale();
        if (next && originPx && Math.abs(nextScale - scale) < 1e-9) {
            rootG.setAttribute('transform',
                `translate(${next.x - originPx.x}, ${next.y - originPx.y})`);
            return;
        }
        rebuild();
    }

    function setZoomHidden(hidden) {
        if (svgEl) svgEl.parentNode.classList.toggle('is-hidden', hidden);
    }

    // ---------- 公开 API ----------

    return {
        init() {
            if (svgEl) return;
            const host = document.getElementById('shape-layer');
            svgEl = el('svg', {}, 'shape-svg');
            host.appendChild(svgEl);
            rebuild();
            MapEngine.bindViewHooks({
                onChange: onViewChange,
                onZoomStart: () => setZoomHidden(true),
                onZoomEnd: () => setZoomHidden(false)
            });
            // 指针事件绑在宿主 div 上：SVG 内元素只负责提供 data-* 命中信息
            host.addEventListener('pointerdown', beginDrag);
            host.addEventListener('pointermove', updateDrag);
            host.addEventListener('pointerup', endDrag);
            host.addEventListener('pointercancel', endDrag);
            document.addEventListener('keydown', handleKeydown);
        },

        add(type) {
            const c = stageCenterPx();
            return this.addAt(type, MapEngine.containerToLatLng(c.x, c.y));
        },

        addAt(type, center) {
            seq += 1;
            const id = `shape-${Date.now()}-${seq}`;
            shapes.push(normalizeShape(makeDefaultShape(type, center, id)));
            selected = id;
            rebuild();
            notify();
            return id;
        },

        remove(id) {
            shapes = shapes.filter((s) => s.id !== id);
            if (selected === id) selected = null;
            rebuild();
            notify();
        },

        clear() {
            if (!shapes.length) return;
            shapes = [];
            selected = null;
            rebuild();
            notify();
        },

        select(id) {
            if (selected === id) return;
            selected = id;
            rebuild();
            notify();
        },

        selectedId() {
            return selected;
        },

        shapes() {
            return shapes.map((s) => ({ ...s, center: { ...s.center } }));
        },

        spacing() {
            return pointSpacing;
        },

        setSpacing(meters) {
            const next = Math.min(Math.max(Number(meters) || 10, MIN_SPACING), MAX_SPACING);
            if (next === pointSpacing) return;
            pointSpacing = next;
            rebuild();
        },

        generatePoints() {
            const out = [];
            shapes.forEach((shape) => {
                shapeToLoop(shape, pointSpacing).forEach((p) => out.push(p));
            });
            return out;
        },

        redraw() {
            rebuild();
        },

        onChange(cb) {
            changeCallbacks.push(cb);
        }
    };
})();
