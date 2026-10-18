// 图形模板纯几何：无 DOM、无地图依赖，浏览器与 Node 双用
//
// 坐标约定（设计文档 §2.4）：
//   局部坐标系原点 = 图形中心；+x = 东，+y = 北；rotation 逆时针为正
//   projectLocal / unprojectLocal 在这一层工作（东向上、北向上）
//   编辑器按当前视野将局部米坐标换成像素，再通过 MapEngine 反投影
//
// 常量口径与 track_editor.js 的环线统计一致（R = 6371000），
// 保证图形生成的距离与右下角「环线总距离」读数完全对齐。

const EARTH_RADIUS_M = 6371000;
const M_PER_DEG_LAT = EARTH_RADIUS_M * Math.PI / 180;   // ≈ 111194.93 m

const MIN_DIM_M = 5;      // 宽/高（圆为直径）下限
const MIN_SPACING = 3;    // 点间距下限（米）
const MAX_SPACING = 100;  // 点间距上限（米）
const DEFAULT_SPACING = 10;  // 编辑器默认点间距（米），也是非有限输入的回退值
const MAX_POINTS = 500;   // 单个图形的点数上限（多图形拼接后总数可超过它）

// 两点球面距离（米）。原 track_editor.js 的本地副本已收敛到此处，唯一实现。
function haversineMeters(a, b) {
    const toRad = (deg) => deg * Math.PI / 180;
    const dLat = toRad(b.lat - a.lat);
    const dLng = toRad(b.lng - a.lng);
    const s = Math.sin(dLat / 2) ** 2 +
        Math.cos(toRad(a.lat)) * Math.cos(toRad(b.lat)) * Math.sin(dLng / 2) ** 2;
    return 2 * EARTH_RADIUS_M * Math.asin(Math.sqrt(s));
}

// 经度方向每度对应的米数（随纬度收缩）。下限 0.01 是纯防御：极点附近 cos → 0，
// 会让米→度换算爆炸；本项目只用国内坐标，正常路径取不到下限。
function mPerDegLng(lat) {
    return M_PER_DEG_LAT * Math.max(Math.cos(lat * Math.PI / 180), 0.01);
}

// 局部坐标 → 旋转后的「东/北」偏移（米）
function projectLocal(shape, lx, ly) {
    const c = Math.cos(shape.rotation);
    const s = Math.sin(shape.rotation);
    return { x: lx * c - ly * s, y: lx * s + ly * c };
}

// 框选沿用相同的旋转数学，逆投影仍是共享几何。
function unprojectLocal(shape, x, y) {
    const c = Math.cos(shape.rotation), s = Math.sin(shape.rotation);
    return { lx: x * c + y * s, ly: -x * s + y * c };
}

// 局部坐标（米）+ 旋转 → 经纬度（中心点切平面近似，图形量级 ~100 m 足够）
function localToGeo(center, lx, ly, rotation) {
    const p = projectLocal({ rotation }, lx, ly);
    return {
        lat: center.lat + p.y / M_PER_DEG_LAT,
        lng: center.lng + p.x / mPerDegLng(center.lat)
    };
}

// ===== 图形模型与尺寸约束 =====
//
// 默认尺寸（设计文档 §2.2）：周长刻意落在现有轨迹 320–400 m 区间
//   操场 w = L + 2R = 84.39 + 73 = 157.39，h = 2R = 73  → 周长 398.1 m（标准 400 m 内道）
//   矩形 100 × 60                                        → 周长 320 m
//   圆形 w = h = 120（R = 60）                           → 周长 377.0 m
const DEFAULT_SIZES = {
    rect: { width: 100, height: 60 },
    circle: { width: 120, height: 120 },
    stadium: { width: 157.39, height: 73 }
};

// 尺寸约束：先夹紧下限，再按类型锁比例
//   圆：正圆，宽高强制相等
//   操场：w = L + h，故 w >= h 等价于直道 L >= 0（w == h 时退化为圆）
//
function lockDims(type, width, height) {
    let w = Math.max(width, MIN_DIM_M);
    let h = Math.max(height, MIN_DIM_M);
    if (type === 'circle') {
        const d = Math.max(w, h);
        w = d;
        h = d;
    } else if (type === 'stadium' && h > w) {
        w = h;
    }
    return { width: w, height: h };
}

// 采样前规范化临时形状尺寸
function normalizeShape(shape) {
    const { width, height } = lockDims(shape.type, shape.width, shape.height);
    return { ...shape, width, height };
}

// 新建默认图形；center 取当前地图中心
function makeDefaultShape(type, center, id) {
    const size = DEFAULT_SIZES[type];
    if (!size) throw new Error('未知图形类型: ' + type);
    return {
        id,
        type,
        center: { lat: center.lat, lng: center.lng },
        width: size.width,
        height: size.height,
        rotation: 0
    };
}

// ===== 轮廓分解（局部米坐标，统一逆时针，首尾闭合）=====
//
// 基元结构（设计文档 §3.1）：
//   { kind: 'line', from: {x,y}, to: {x,y} }
//   { kind: 'arc', from: {x,y}, to: {x,y}, center: {x,y}, radius, startAngle, sweep }   // 弧度，逆时针为正
//
// from/to 是**所有**基元的通用字段（圆弧的 from/to 由圆心半径与起止角推出），
// 这样遍历端点、拼闭合多边形、判断首尾相接都不需要按 kind 分支。
//
// 三个图形的起点（即生成点列的第一个点，编辑器会把它标成「起点」）：
//   矩形  西南角 (-w/2, -h/2)
//   圆形  正东 (R, 0)
//   操场  左起下 (-L/2, -R)

const TWO_PI = Math.PI * 2;

// 按圆心、半径、起始角、扫角造一个圆弧基元，并补出 from/to
function arcPrimitive(center, radius, startAngle, sweep) {
    return {
        kind: 'arc',
        center,
        radius,
        startAngle,
        sweep,
        from: {
            x: center.x + radius * Math.cos(startAngle),
            y: center.y + radius * Math.sin(startAngle)
        },
        to: {
            x: center.x + radius * Math.cos(startAngle + sweep),
            y: center.y + radius * Math.sin(startAngle + sweep)
        }
    };
}

function shapeOutlines(shape) {
    const s = normalizeShape(shape);
    const w = s.width;
    const h = s.height;

    if (s.type === 'rect') {
        const x = w / 2;
        const y = h / 2;
        return [
            { kind: 'line', from: { x: -x, y: -y }, to: { x: x, y: -y } },
            { kind: 'line', from: { x: x, y: -y }, to: { x: x, y: y } },
            { kind: 'line', from: { x: x, y: y }, to: { x: -x, y: y } },
            { kind: 'line', from: { x: -x, y: y }, to: { x: -x, y: -y } }
        ];
    }

    if (s.type === 'circle') {
        return [arcPrimitive({ x: 0, y: 0 }, w / 2, 0, TWO_PI)];
    }

    if (s.type === 'stadium') {
        const radius = h / 2;
        const straight = w - h;   // 直道长度；normalizeShape 已保证 >= 0
        return [
            { kind: 'line', from: { x: -straight / 2, y: -radius }, to: { x: straight / 2, y: -radius } },
            arcPrimitive({ x: straight / 2, y: 0 }, radius, -Math.PI / 2, Math.PI),
            { kind: 'line', from: { x: straight / 2, y: radius }, to: { x: -straight / 2, y: radius } },
            arcPrimitive({ x: -straight / 2, y: 0 }, radius, Math.PI / 2, Math.PI)
        ];
    }

    throw new Error('未知图形类型: ' + s.type);
}

function primitiveLength(p) {
    if (p.kind === 'line') {
        return Math.hypot(p.to.x - p.from.x, p.to.y - p.from.y);
    }
    return Math.abs(p.radius * p.sweep);
}

// t ∈ [0,1]：直线按线性插值，圆弧按角度插值（因此采样点严格落在弧上）
function primitivePoint(p, t) {
    if (p.kind === 'line') {
        return {
            x: p.from.x + (p.to.x - p.from.x) * t,
            y: p.from.y + (p.to.y - p.from.y) * t
        };
    }
    const a = p.startAngle + p.sweep * t;
    return { x: p.center.x + p.radius * Math.cos(a), y: p.center.y + p.radius * Math.sin(a) };
}

function shapePerimeter(shape) {
    return shapeOutlines(shape).reduce((sum, p) => sum + primitiveLength(p), 0);
}

// ===== 按间距打点（设计文档 §3.2 / §3.3）=====
//
//   非零段按 round(段长 / 间距) 采样，取 t = 0, 1/n, …, (n-1)/n
//   直线至少 1 点，半圆至少 2 点，整圆至少 3 点，避免闭环退化成点或直线。
//   取 n 个点而不含 t = 1，避免与下一段的首点重复
//
// 这个式子保证：① 顶点与切点必然落在点上（矩形四角、操场直道与弯道切点都是某段的 t = 0）；
// ② 点数按尺寸与目标间距增长；③ 零长直道不采样，避免退化操场的切点重复。
//
// 点数封顶：先夹紧间距到 [MIN_SPACING, MAX_SPACING]，再按周长抬高间距，
// 保证手滑拖出极大图形（或把间距拉到 3 m）也不会生成上万点。
//
// 非有限间距（NaN / undefined / 'abc' / ±Infinity）先回退到 DEFAULT_SPACING：
// NaN 会一路穿过 Math.max/Math.min 仍是 NaN，最后 `i < NaN` 一次都不进循环，
// 结果是**静默**返回 0 个点 —— 不报错、界面上什么都不发生，最难排查的那类失败。
function shapeToLocalLoop(shape, spacing) {
    const s = normalizeShape(shape);
    const prims = shapeOutlines(s).filter((p) => primitiveLength(p) > 0);
    const lengths = prims.map(primitiveLength);
    const perimeter = lengths.reduce((sum, length) => sum + length, 0);

    const raw = Number(spacing);
    const requested = Number.isFinite(raw) ? raw : DEFAULT_SPACING;
    let effective = Math.min(Math.max(requested, MIN_SPACING), MAX_SPACING);
    if (perimeter > 0 && perimeter / effective > MAX_POINTS) {
        effective = perimeter / MAX_POINTS;
    }

    const minimums = prims.map((p) => p.kind === 'arc'
        ? Math.ceil(Math.abs(p.sweep) / Math.PI) + 1 : 1);
    const targets = lengths.map((length) => length / effective);
    const counts = targets.map((target, i) => Math.max(minimums[i], Math.round(target)));
    // 各段独立四舍五入可能使总数超过 500。只回收超出预算的点，优先调整
    // 超过理想配额最多的段；保留每段起点及圆弧最低采样数，角点/切点不会丢失。
    let excess = counts.reduce((sum, count) => sum + count, 0) - MAX_POINTS;
    while (excess > 0) {
        let candidate = -1;
        counts.forEach((count, i) => {
            if (count > minimums[i] && (candidate < 0 ||
                count - targets[i] > counts[candidate] - targets[candidate])) candidate = i;
        });
        counts[candidate] -= 1;
        excess -= 1;
    }

    const loop = [];
    prims.forEach((p, index) => {
        const n = counts[index];
        for (let i = 0; i < n; i++) {
            const local = primitivePoint(p, i / n);
            loop.push(local);
        }
    });
    return loop;
}

// 保留地理采样入口供纯几何测试使用；编辑器用局部采样配合地图投影。
function shapeToLoop(shape, spacing) {
    return shapeToLocalLoop(shape, spacing)
        .map(p => localToGeo(shape.center, p.x, p.y, shape.rotation));
}

// 保持三种模板的轮廓比例，占当前可见地图宽高的一半，给选框手柄留出空间。
function viewportShape(type, visibleWidth, visibleHeight) {
    const shape = makeDefaultShape(type, { lat: 0, lng: 0 });
    const ratio = Math.min(visibleWidth * 0.5 / shape.width, visibleHeight * 0.5 / shape.height);
    return normalizeShape({ ...shape, width: shape.width * ratio, height: shape.height * ratio });
}

// 相交包括相切与重叠；用于避免模板追加时新增跨过已有轨迹的连接线。
function segmentsMeet(a, b, c, d) {
    const cross = (p, q, r) => (q.x - p.x) * (r.y - p.y) - (q.y - p.y) * (r.x - p.x);
    const on = (p, q, r) => Math.abs(cross(p, q, r)) < 1e-7
        && r.x >= Math.min(p.x, q.x) - 1e-7 && r.x <= Math.max(p.x, q.x) + 1e-7
        && r.y >= Math.min(p.y, q.y) - 1e-7 && r.y <= Math.max(p.y, q.y) + 1e-7;
    const abC = cross(a, b, c), abD = cross(a, b, d), cdA = cross(c, d, a), cdB = cross(c, d, b);
    return abC * abD < 0 && cdA * cdB < 0 || on(a, b, c) || on(a, b, d) || on(c, d, a) || on(c, d, b);
}

function segmentsConflict(a, b, c, d) {
    if (!segmentsMeet(a, b, c, d)) return false;
    const same = (p, q) => Math.hypot(p.x - q.x, p.y - q.y) < 1e-7;
    // 允许相邻边共用端点，但不允许从该端点沿同一方向重叠。
    for (const [p, q] of [[a, b], [b, a]]) {
        for (const [r, t] of [[c, d], [d, c]]) {
            if (same(p, r)) {
                const cross = (q.x - p.x) * (t.y - p.y) - (q.y - p.y) * (t.x - p.x);
                const dot = (q.x - p.x) * (t.x - p.x) + (q.y - p.y) * (t.y - p.y);
                return Math.abs(cross) < 1e-7 && dot > 1e-7;
            }
        }
    }
    return true;
}

// 单环线格式不支持独立子路径：各打开一条边，用两条不相交的短线接入。
// 仅返回插入位置和新点顺序，绝不移动/重排旧节点；整组删除可恢复原环线。
function joinLoops(existing, added) {
    const n = existing.length, m = added.length;
    if (!n) return { after: -1, order: added.map((_, i) => i) };
    const edges = loop => loop.map((p, i) => [p, loop[(i + 1) % loop.length]]);
    const oldEdges = edges(existing), newEdges = edges(added);
    // 重叠轮廓不能无损接入；失败时由 UI 提示平移视野，不改历史或旧点。
    if (oldEdges.some(([a, b]) => newEdges.some(([c, d]) => segmentsMeet(a, b, c, d)))) return null;
    const distance = (a, b) => Math.hypot(a.x - b.x, a.y - b.y);
    let best = null, bestCost = Infinity;
    oldEdges.forEach(([a, b], i) => {
        newEdges.forEach(([c, d], j) => {
            for (const reverse of [false, true]) {
                const first = reverse ? c : d, last = reverse ? d : c;
                const cost = distance(a, first) + distance(last, b) - distance(a, b) - distance(c, d);
                if (cost >= bestCost) continue;
                const bridges = [[a, first], [last, b]];
                if (segmentsConflict(...bridges[0], ...bridges[1])) continue;
                if (bridges.some(([p, q]) => oldEdges.some(([r, t], k) => k !== i && segmentsConflict(p, q, r, t))
                    || newEdges.some(([r, t], k) => k !== j && segmentsConflict(p, q, r, t)))) continue;
                const order = Array.from({ length: m }, (_, k) => (j + (reverse ? -k : 1 + k) + m) % m);
                best = { after: i, order };
                bestCost = cost;
            }
        });
    });
    return best;
}

// Node 单测入口（浏览器下 module 未定义，整块跳过）
if (typeof module !== 'undefined' && module.exports) {
    module.exports = {
        EARTH_RADIUS_M, M_PER_DEG_LAT, MIN_DIM_M, MIN_SPACING, MAX_SPACING, MAX_POINTS,
        DEFAULT_SPACING,
        haversineMeters, mPerDegLng, projectLocal, unprojectLocal, localToGeo,
        lockDims, normalizeShape, makeDefaultShape,
        shapeOutlines, primitiveLength, primitivePoint, shapePerimeter, shapeToLocalLoop, shapeToLoop,
        viewportShape, segmentsMeet, segmentsConflict, joinLoops
    };
}
