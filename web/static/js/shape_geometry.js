// 图形模板纯几何：无 DOM、无地图依赖，浏览器与 Node 双用
//
// 坐标约定（设计文档 §2.4）：
//   局部坐标系原点 = 图形中心；+x = 东，+y = 北；rotation 逆时针为正
//   projectLocal / unprojectLocal 在这一层工作（东向上、北向上）
//   像素空间 y 向下，由 shape_layer.js 负责 scale 与 y 轴翻转
//
// 常量口径与 track_editor.js 的环线统计一致（R = 6371000），
// 保证图形生成的距离与右下角「环线总距离」读数完全对齐。

const EARTH_RADIUS_M = 6371000;
const M_PER_DEG_LAT = EARTH_RADIUS_M * Math.PI / 180;   // ≈ 111194.93 m

const MIN_DIM_M = 5;      // 宽/高（圆为直径）下限
const MIN_SPACING = 3;    // 点间距下限（米）
const MAX_SPACING = 100;  // 点间距上限（米）
const MAX_POINTS = 500;   // 单条轨迹点总数上限

const NS = 'http://www.w3.org/2000/svg';

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

// 「东/北」偏移（米）→ 局部坐标（projectLocal 的逆）
function unprojectLocal(shape, x, y) {
    const c = Math.cos(shape.rotation);
    const s = Math.sin(shape.rotation);
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
//   圆：正圆，宽高强制相等（取较大者）
//   操场：w = L + h，故 w >= h 等价于直道 L >= 0（w == h 时退化为圆）
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

// 返回规范化后的新对象；调用方（shape_layer）在每次编辑后都要过一遍
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
//   每段采样数 n = max(1, round(段长 / 间距))，取 t = 0, 1/n, …, (n-1)/n
//   取 n 个点而不含 t = 1，避免与下一段的首点重复
//
// 这个式子保证：① 顶点与切点必然落在点上（矩形四角、操场直道与弯道切点都是某段的 t = 0）；
// ② 点数严格随尺寸线性增长；③ 每段至少 1 点，不会出现空段。
//
// 点数封顶：先夹紧间距到 [MIN_SPACING, MAX_SPACING]，再按周长抬高间距，
// 保证手滑拖出极大图形（或把间距拉到 3 m）也不会生成上万点。
function shapeToLoop(shape, spacing) {
    const s = normalizeShape(shape);
    const prims = shapeOutlines(s);
    const perimeter = prims.reduce((sum, p) => sum + primitiveLength(p), 0);

    let effective = Math.min(Math.max(spacing, MIN_SPACING), MAX_SPACING);
    if (perimeter > 0 && perimeter / effective > MAX_POINTS) {
        effective = perimeter / MAX_POINTS;
    }

    const loop = [];
    prims.forEach((p) => {
        const len = primitiveLength(p);
        const n = Math.max(1, Math.round(len / effective));
        for (let i = 0; i < n; i++) {
            const local = primitivePoint(p, i / n);
            loop.push(localToGeo(s.center, local.x, local.y, s.rotation));
        }
    });
    return loop;
}

// ===== 手柄几何与变换（设计文档 §5.1）=====
//
// 8 个缩放手柄固定按图形**包围盒**分布——圆形也不例外，与 Word 对图片画的矩形选择框一致。
// 旋转手柄不在这 8 个之内：它位于局部 +y（正北）方向、包围盒之外 28 px 处，
// 28 px 需要 scale 才能换算成米，故由 shape_layer.js 负责定位；本模块只提供角度常量。

const HANDLE_KEYS = ['nw', 'n', 'ne', 'e', 'se', 's', 'sw', 'w'];

// 对角手柄：拖动时以它为锚点（Word 手感），它的地理位置保持不动
const HANDLE_OPPOSITE = {
    nw: 'se', n: 's', ne: 'sw', e: 'w',
    se: 'nw', s: 'n', sw: 'ne', w: 'e'
};

const ROTATE_HANDLE_ANGLE = Math.PI / 2;   // 旋转手柄在正北方向

function handlePositions(shape) {
    const s = normalizeShape(shape);
    const x = s.width / 2;
    const y = s.height / 2;
    return [
        { key: 'nw', lx: -x, ly: y },
        { key: 'n', lx: 0, ly: y },
        { key: 'ne', lx: x, ly: y },
        { key: 'e', lx: x, ly: 0 },
        { key: 'se', lx: x, ly: -y },
        { key: 's', lx: 0, ly: -y },
        { key: 'sw', lx: -x, ly: -y },
        { key: 'w', lx: -x, ly: 0 }
    ];
}

// 指针方位 → 新 rotation。
//
// grabBearing 是「按下瞬间指针的方位角」，默认值即旋转手柄自身的固定方位（正北）。
// 用户可能抓在旋转圆点的任意位置，传入实际抓取方位才能在按下瞬间不跳转；
// 只抓在正上方时用默认值即可。
function rotationFromPointer(offsetX, offsetY, grabBearing = ROTATE_HANDLE_ANGLE) {
    return Math.atan2(offsetY, offsetX) - grabBearing;
}

// 拖动手柄缩放。offsetX/offsetY 是指针相对 snapshot.center 的「东/北」偏移（米）。
//
// 算法（顺序很重要）：
//   1. 把指针偏移逆旋转到快照局部坐标系
//   2. 以对角手柄为锚点，算出裁剪前的宽高
//   3. 施加类型尺寸约束（圆锁定、操场 w >= h）
//   4. 用**约束后**的宽高反算中心偏移，锚点才真的不动
// 第 4 步若用约束前的宽高，圆形/操场的锚点会漂——这是本函数唯一的坑。
function resizeShape(snapshot, key, offsetX, offsetY) {
    const s = normalizeShape(snapshot);
    const hasX = key === 'e' || key === 'w' || key.length === 2;
    const hasY = key === 'n' || key === 's' || key.length === 2;

    const anchor = handlePositions(s).find((h) => h.key === HANDLE_OPPOSITE[key]);
    if (!anchor) throw new Error('未知手柄: ' + key);

    const p = unprojectLocal(s, offsetX, offsetY);
    const ax = hasX ? anchor.lx : 0;
    const ay = hasY ? anchor.ly : 0;

    const { width, height } = lockDims(
        s.type,
        hasX ? Math.abs(p.lx - ax) : s.width,
        hasY ? Math.abs(p.ly - ay) : s.height
    );

    const dirX = hasX ? (Math.sign(p.lx - ax) || 1) : 0;
    const dirY = hasY ? (Math.sign(p.ly - ay) || 1) : 0;
    const shift = projectLocal(s, hasX ? ax + dirX * width / 2 : 0, hasY ? ay + dirY * height / 2 : 0);

    const center = {
        lat: s.center.lat + shift.y / M_PER_DEG_LAT,
        lng: s.center.lng + shift.x / mPerDegLng(s.center.lat)
    };
    return normalizeShape({ ...s, width, height, center });
}

// Node 单测入口（浏览器下 module 未定义，整块跳过）
if (typeof module !== 'undefined' && module.exports) {
    module.exports = {
        EARTH_RADIUS_M, M_PER_DEG_LAT, MIN_DIM_M, MIN_SPACING, MAX_SPACING, MAX_POINTS,
        haversineMeters, mPerDegLng, projectLocal, unprojectLocal, localToGeo,
        lockDims, normalizeShape, makeDefaultShape,
        shapeOutlines, primitiveLength, primitivePoint, shapePerimeter, shapeToLoop,
        HANDLE_KEYS, HANDLE_OPPOSITE, ROTATE_HANDLE_ANGLE,
        handlePositions, rotationFromPointer, resizeShape
    };
}
