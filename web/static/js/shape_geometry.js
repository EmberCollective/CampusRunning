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

// Node 单测入口（浏览器下 module 未定义，整块跳过）
if (typeof module !== 'undefined' && module.exports) {
    module.exports = {
        EARTH_RADIUS_M, M_PER_DEG_LAT, MIN_DIM_M, MIN_SPACING, MAX_SPACING, MAX_POINTS,
        haversineMeters, mPerDegLng, projectLocal, unprojectLocal, localToGeo
    };
}
