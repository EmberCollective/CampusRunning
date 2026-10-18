// 框选的屏幕空间仿射变换。复用图形模板的旋转/逆旋转；缩放禁止翻转。
const SelectionGeometry = (() => {
    const projection = typeof module !== 'undefined' && module.exports
        ? require('./shape_geometry.js') : { projectLocal, unprojectLocal };
    const handles = { nw: [-1, -1], n: [0, -1], ne: [1, -1], e: [1, 0],
        se: [1, 1], s: [0, 1], sw: [-1, 1], w: [-1, 0] };
    const local = (f, p) => projection.unprojectLocal({ rotation: f.angle }, p.x - f.x, p.y - f.y);
    function world(f, x, y) {
        const q = projection.projectLocal({ rotation: f.angle }, x, y);
        return { x: f.x + q.x, y: f.y + q.y };
    }
    function bounds(pixels) {
        if (!pixels.length) return null;
        const xs = pixels.map(p => p.x), ys = pixels.map(p => p.y);
        const left = Math.min(...xs), right = Math.max(...xs);
        const top = Math.min(...ys), bottom = Math.max(...ys);
        return { x: (left + right) / 2, y: (top + bottom) / 2,
            width: right - left, height: bottom - top, angle: 0 };
    }
    function inside(a, b, p) {
        return p.x >= Math.min(a.x, b.x) && p.x <= Math.max(a.x, b.x)
            && p.y >= Math.min(a.y, b.y) && p.y <= Math.max(a.y, b.y);
    }
    function transform(f, key, start, end) {
        if (key === 'move') return { ...f, x: f.x + end.x - start.x, y: f.y + end.y - start.y };
        if (key === 'rotate') {
            if (Math.hypot(end.x - f.x, end.y - f.y) < 1) return f;
            return { ...f, angle: f.angle + Math.atan2(end.y - f.y, end.x - f.x)
                - Math.atan2(start.y - f.y, start.x - f.x) };
        }
        const [hx, hy] = handles[key];
        const a = local(f, start), b = local(f, end);
        // 退化轴不能除零；越过对侧锚点时停在最小正尺寸，不交换点序或翻转。
        const width = hx && f.width > 1e-6
            ? Math.max(Math.min(1, f.width), f.width + hx * (b.lx - a.lx)) : f.width;
        const height = hy && f.height > 1e-6
            ? Math.max(Math.min(1, f.height), f.height + hy * (b.ly - a.ly)) : f.height;
        const center = world(f, hx * (width - f.width) / 2, hy * (height - f.height) / 2);
        return { ...f, ...center, width, height };
    }
    function point(p, from, to) {
        const q = local(from, p);
        return world(to, q.lx * (from.width > 1e-6 ? to.width / from.width : 1),
            q.ly * (from.height > 1e-6 ? to.height / from.height : 1));
    }
    const validGeo = p => Number.isFinite(p.lat) && Number.isFinite(p.lng)
        && Math.abs(p.lat) < 90 && Math.abs(p.lng) <= 180;
    return { handles, local, world, bounds, inside, transform, point, validGeo };
})();
if (typeof module !== 'undefined' && module.exports) module.exports = SelectionGeometry;
