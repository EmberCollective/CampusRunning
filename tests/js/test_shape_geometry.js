// 图形几何单测：无 DOM 依赖，Node 直接运行（零第三方依赖）
//
// 由 tests/test_shape_geometry.py 驱动（pytest 起 node 跑本文件并断言退出码）。
// 每个任务在自己的小节里追加用例；「汇总」块必须始终留在文件最后。
const G = require('../../web/static/js/shape_geometry.js');

let passed = 0;
let failed = 0;

// 极简用例运行器：失败不中断，末尾统一汇报，退出码反映总结果
function test(name, fn) {
    try {
        fn();
        passed++;
        console.log('  ✓ ' + name);
    } catch (error) {
        failed++;
        console.error('  ✗ ' + name);
        console.error('    ' + error.message);
    }
}

// 浮点比较：默认容差 1e-6
function near(actual, expected, tol = 1e-6, label = '') {
    if (!(Math.abs(actual - expected) <= tol)) {
        throw new Error(`${label} 期望 ${expected}，实际 ${actual}（容差 ${tol}）`);
    }
}

function true_(cond, label) {
    if (!cond) throw new Error(label + ' 不成立');
}

function section(title) {
    console.log('\n' + title);
}

// ===== 常量与单位换算 =====
section('常量与单位换算');

test('haversineMeters 对已知距离准确（纬度 1 度 ≈ 111194.93 m）', () => {
    near(G.haversineMeters({ lat: 0, lng: 0 }, { lat: 1, lng: 0 }), G.M_PER_DEG_LAT, 0.01, '1 度纬度');
});

test('haversineMeters 对同一点返回 0', () => {
    near(G.haversineMeters({ lat: 26.42, lng: 106.67 }, { lat: 26.42, lng: 106.67 }), 0, 1e-9, '同点');
});

test('mPerDegLng 随纬度收缩（赤道 > 中纬度）', () => {
    true_(G.mPerDegLng(0) > G.mPerDegLng(45), '经度方向米数应随纬度增大而减小');
    near(G.mPerDegLng(0), G.M_PER_DEG_LAT, 0.01, '赤道处等于 M_PER_DEG_LAT');
});

test('mPerDegLng 对极高纬度有下限保护，不返回 0 或负数', () => {
    true_(G.mPerDegLng(89.9999) > 0, '近距离极点的经度米数必须为正');
    true_(G.mPerDegLng(90) > 0, '恰好 90 度也必须为正');
});

test('projectLocal / unprojectLocal 互为逆运算', () => {
    const shape = { rotation: 0.7 };
    const p = G.projectLocal(shape, 30, -12);
    const back = G.unprojectLocal(shape, p.x, p.y);
    near(back.lx, 30, 1e-9, 'lx');
    near(back.ly, -12, 1e-9, 'ly');
});

test('projectLocal 在 rotation = 0 时是恒等', () => {
    const p = G.projectLocal({ rotation: 0 }, 30, -12);
    near(p.x, 30, 1e-12, 'x');
    near(p.y, -12, 1e-12, 'y');
});

test('projectLocal 旋转 90 度把东向转到北向', () => {
    const p = G.projectLocal({ rotation: Math.PI / 2 }, 100, 0);
    near(p.x, 0, 1e-9, 'x');
    near(p.y, 100, 1e-9, 'y');
});

test('localToGeo 到中心的距离等于局部偏移长度（误差 < 0.5%）', () => {
    const center = { lat: 26.4205, lng: 106.6713 };
    const cases = [[30, 0], [0, -40], [25, 25], [-60, 15]];
    cases.forEach(([lx, ly]) => {
        const geo = G.localToGeo(center, lx, ly, 0);
        const want = Math.hypot(lx, ly);
        const got = G.haversineMeters(center, geo);
        true_(Math.abs(got - want) / want < 0.005, `(${lx},${ly}) 期望 ≈${want}，实际 ${got}`);
    });
});

test('localToGeo 在旋转下保持距离不变', () => {
    const center = { lat: 26.4205, lng: 106.6713 };
    const geo = G.localToGeo(center, 80, 0, Math.PI / 3);
    const got = G.haversineMeters(center, geo);
    true_(Math.abs(got - 80) / 80 < 0.005, `期望 ≈80，实际 ${got}`);
});

// ===== 图形规范化与默认尺寸 =====
section('图形规范化与默认尺寸');

test('lockDims 把过小尺寸夹紧到 MIN_DIM_M', () => {
    const d = G.lockDims('rect', 1, 1);
    near(d.width, G.MIN_DIM_M, 1e-9, 'width');
    near(d.height, G.MIN_DIM_M, 1e-9, 'height');
});

test('lockDims 对圆形锁定宽高相等（取较大者）', () => {
    const d = G.lockDims('circle', 100, 40);
    near(d.width, 100, 1e-9, 'width');
    near(d.height, 100, 1e-9, 'height');
});

test('lockDims 对操场保证 w >= h（直道不为负）', () => {
    const d = G.lockDims('stadium', 60, 100);
    true_(d.width >= d.height, '操场必须 w >= h');
    near(d.width, 100, 1e-9, 'width 抬到 height');
});

test('lockDims 对矩形不施加比例约束', () => {
    const d = G.lockDims('rect', 300, 20);
    near(d.width, 300, 1e-9, 'width');
    near(d.height, 20, 1e-9, 'height');
});

test('normalizeShape 夹紧 rect(1,1) 到 5x5 并返回新对象', () => {
    const src = { id: 'a', type: 'rect', center: { lat: 1, lng: 2 }, width: 1, height: 1, rotation: 0 };
    const out = G.normalizeShape(src);
    near(out.width, 5, 1e-9, 'width');
    near(out.height, 5, 1e-9, 'height');
    true_(out !== src, '必须返回新对象，不原地修改');
    near(src.width, 1, 1e-9, '原对象不得被改动');
});

test('normalizeShape 保留 id/type/center/rotation', () => {
    const src = { id: 'x9', type: 'circle', center: { lat: 26.4, lng: 106.6 }, width: 200, height: 50, rotation: 0.3 };
    const out = G.normalizeShape(src);
    true_(out.id === 'x9' && out.type === 'circle', 'id/type 保留');
    near(out.rotation, 0.3, 1e-12, 'rotation 保留');
    near(out.center.lat, 26.4, 1e-12, 'center 保留');
});

test('makeDefaultShape 默认周长落在现有轨迹区间（320–400 m）', () => {
    const center = { lat: 26.4205, lng: 106.6713 };
    ['rect', 'circle', 'stadium'].forEach((type) => {
        const s = G.makeDefaultShape(type, center, 'd1');
        true_(s.type === type, type + ' 类型正确');
        true_(s.id === 'd1', type + ' id 正确');
        near(s.center.lat, center.lat, 1e-9, type + ' center.lat');
        near(s.rotation, 0, 1e-9, type + ' 初始 rotation');
    });
    // 周长按几何定义直接算，不依赖 Task 3 才有的 shapePerimeter
    const rect = G.makeDefaultShape('rect', center, 'r');
    near(2 * (rect.width + rect.height), 320, 0.01, '矩形周长');
    const circle = G.makeDefaultShape('circle', center, 'c');
    near(Math.PI * circle.width, Math.PI * 120, 0.01, '圆形周长');
    const stadium = G.makeDefaultShape('stadium', center, 's');
    // 操场周长 = 2L + πh，其中 L = w - h
    near(2 * (stadium.width - stadium.height) + Math.PI * stadium.height, 2 * 84.39 + Math.PI * 73, 0.01, '操场周长');
});

test('makeDefaultShape 对未知类型抛错', () => {
    // 必须匹配错误信息：若只判断「抛了没」，函数根本不存在时 TypeError 也会让用例假通过
    let message = '';
    try {
        G.makeDefaultShape('triangle', { lat: 0, lng: 0 }, 'x');
    } catch (e) {
        message = e.message;
    }
    true_(/未知图形类型/.test(message), `应以「未知图形类型」拒绝，实际抛出：${message || '(没有抛错)'}`);
});

// ===== 轮廓分解 =====
section('轮廓分解');

test('矩形分解为 4 条直线段，长度依次为 100/60/100/60', () => {
    const s = { id: 'r', type: 'rect', center: { lat: 26.42, lng: 106.67 }, width: 100, height: 60, rotation: 0 };
    const prims = G.shapeOutlines(s);
    true_(prims.length === 4, '基元数应为 4，实际 ' + prims.length);
    const lens = prims.map(G.primitiveLength);
    [100, 60, 100, 60].forEach((want, i) => near(lens[i], want, 1e-9, `第 ${i} 段长`));
    true_(prims.every((p) => p.kind === 'line'), '应全为直线段');
});

test('矩形的起点是西南角，且首尾闭合', () => {
    const s = { id: 'r', type: 'rect', center: { lat: 26.42, lng: 106.67 }, width: 100, height: 60, rotation: 0 };
    const prims = G.shapeOutlines(s);
    near(prims[0].from.x, -50, 1e-9, '起点 x');
    near(prims[0].from.y, -30, 1e-9, '起点 y');
    const last = prims[prims.length - 1];
    near(last.to.x, prims[0].from.x, 1e-9, '闭合点 x');
    near(last.to.y, prims[0].from.y, 1e-9, '闭合点 y');
});

test('矩形四角都落在基元端点上（不会被切角）', () => {
    const s = { id: 'r', type: 'rect', center: { lat: 26.42, lng: 106.67 }, width: 100, height: 60, rotation: 0 };
    const pts = [];
    G.shapeOutlines(s).forEach((p) => { pts.push(p.from); pts.push(p.to); });
    [[-50, -30], [50, -30], [50, 30], [-50, 30]].forEach(([x, y]) => {
        const hit = pts.some((q) => Math.hypot(q.x - x, q.y - y) < 1e-6);
        true_(hit, `角点 (${x},${y}) 应在基元端点上`);
    });
});

test('圆形分解为 1 个整圆弧，半径 60，弧长 2πR', () => {
    const s = { id: 'c', type: 'circle', center: { lat: 26.42, lng: 106.67 }, width: 120, height: 120, rotation: 0 };
    const prims = G.shapeOutlines(s);
    true_(prims.length === 1 && prims[0].kind === 'arc', '应为单个圆弧');
    near(prims[0].radius, 60, 1e-9, '半径');
    near(G.primitiveLength(prims[0]), 2 * Math.PI * 60, 1e-6, '弧长');
    near(G.primitivePoint(prims[0], 0).x, 60, 1e-9, '起点在正东');
    near(G.primitivePoint(prims[0], 0).y, 0, 1e-9, '起点在正东');
});

test('操场分解为 直线-半圆-直线-半圆，直道 84.39、半径 36.5', () => {
    const s = { id: 's', type: 'stadium', center: { lat: 26.42, lng: 106.67 }, width: 157.39, height: 73, rotation: 0 };
    const prims = G.shapeOutlines(s);
    const kinds = prims.map((p) => p.kind).join(',');
    true_(kinds === 'line,arc,line,arc', '基元顺序应为 line,arc,line,arc，实际 ' + kinds);
    near(G.primitiveLength(prims[0]), 84.39, 1e-6, '底边直道');
    near(G.primitiveLength(prims[1]), Math.PI * 36.5, 1e-6, '右半圆弧长');
    near(prims[1].radius, 36.5, 1e-9, '半径');
    near(G.primitiveLength(prims[2]), 84.39, 1e-6, '顶边直道');
    near(G.primitiveLength(prims[3]), Math.PI * 36.5, 1e-6, '左半圆弧长');
});

test('操场起点在左起下，基元首尾闭合', () => {
    const s = { id: 's', type: 'stadium', center: { lat: 26.42, lng: 106.67 }, width: 157.39, height: 73, rotation: 0 };
    const prims = G.shapeOutlines(s);
    near(prims[0].from.x, -84.39 / 2, 1e-9, '起点 x');
    near(prims[0].from.y, -36.5, 1e-9, '起点 y');
    const last = prims[prims.length - 1];
    near(last.to.x, prims[0].from.x, 1e-9, '闭合点 x');
    near(last.to.y, prims[0].from.y, 1e-9, '闭合点 y');
});

test('操场基元端点全部落在轮廓上（距中心符合几何定义）', () => {
    const s = { id: 's', type: 'stadium', center: { lat: 26.42, lng: 106.67 }, width: 157.39, height: 73, rotation: 0 };
    const prims = G.shapeOutlines(s);
    // 所有端点要么在直道（|y| == R 且 |x| <= L/2），要么在弯道（到某个圆心距离 == R）
    const R = 36.5;
    const L = 84.39;
    const pts = [];
    prims.forEach((p) => { pts.push(p.from); pts.push(p.to); });
    pts.forEach((q) => {
        const onStraight = Math.abs(Math.abs(q.y) - R) < 1e-6 && Math.abs(q.x) <= L / 2 + 1e-6;
        const dRight = Math.hypot(q.x - L / 2, q.y);
        const dLeft = Math.hypot(q.x + L / 2, q.y);
        const onArc = Math.abs(dRight - R) < 1e-6 || Math.abs(dLeft - R) < 1e-6;
        true_(onStraight || onArc, `端点 (${q.x},${q.y}) 应落在操场轮廓上`);
    });
});

test('shapePerimeter 对三种默认图形给出已知周长', () => {
    const center = { lat: 26.4205, lng: 106.6713 };
    near(G.shapePerimeter(G.makeDefaultShape('rect', center, 'r')), 320, 1e-6, '矩形周长 2(100+60)');
    near(G.shapePerimeter(G.makeDefaultShape('circle', center, 'c')), Math.PI * 120, 1e-6, '圆形周长 120π');
    near(G.shapePerimeter(G.makeDefaultShape('stadium', center, 's')), 2 * 84.39 + Math.PI * 73, 1e-6, '操场周长 2L+πh');
});

test('shapeOutlines 对未规范化的图形自动夹紧', () => {
    const s = { id: 'r', type: 'rect', center: { lat: 26.42, lng: 106.67 }, width: 1, height: 1, rotation: 0 };
    near(G.primitiveLength(G.shapeOutlines(s)[0]), G.MIN_DIM_M, 1e-9, '夹紧后底边长');
});

// ===== 打点 =====
section('按间距打点');

const RECT = () => ({ id: 'r', type: 'rect', center: { lat: 26.4205, lng: 106.6713 }, width: 100, height: 60, rotation: 0 });
const CIRCLE = () => ({ id: 'c', type: 'circle', center: { lat: 26.4205, lng: 106.6713 }, width: 120, height: 120, rotation: 0 });
const STADIUM = () => ({ id: 's', type: 'stadium', center: { lat: 26.4205, lng: 106.6713 }, width: 157.39, height: 73, rotation: 0 });

test('矩形 100x60 @ 10 m 生成 32 点（10+6+10+6）', () => {
    near(G.shapeToLoop(RECT(), 10).length, 32, 0, '点数');
});

test('矩形四角都在点集内', () => {
    const loop = G.shapeToLoop(RECT(), 10);
    const corners = G.shapeOutlines(RECT()).map((p) => p.from);
    corners.forEach((c) => {
        const want = G.localToGeo(RECT().center, c.x, c.y, 0);
        const hit = loop.some((p) => G.haversineMeters(p, want) < 0.01);
        true_(hit, `角点 (${c.x},${c.y}) 应在生成点集内`);
    });
});

test('圆形 R=60 @ 10 m 生成 38 点，且每点距中心 60 m', () => {
    const loop = G.shapeToLoop(CIRCLE(), 10);
    near(loop.length, 38, 0, '点数');
    loop.forEach((p, i) => {
        const d = G.haversineMeters(CIRCLE().center, p);
        true_(Math.abs(d - 60) <= 0.5, `第 ${i} 点距中心 ${d}，应 ≈60`);
    });
});

test('操场 84.39/36.5 @ 10 m 生成 38 点（8+11+8+11）', () => {
    near(G.shapeToLoop(STADIUM(), 10).length, 38, 0, '点数');
});

test('点数随尺寸单调增长', () => {
    const small = G.shapeToLoop(RECT(), 10).length;
    const big = G.shapeToLoop({ ...RECT(), width: 200, height: 120 }, 10).length;
    true_(big > small, `放大后点数应增加：小 ${small} 大 ${big}`);
});

test('间距减半则点数约翻倍', () => {
    const a = G.shapeToLoop(CIRCLE(), 10).length;
    const b = G.shapeToLoop(CIRCLE(), 5).length;
    true_(b >= a * 1.9 && b <= a * 2.1, `期望约 ${a * 2}，实际 ${b}`);
});

test('超大图形自动抬高间距，点数封顶 MAX_POINTS', () => {
    const loop = G.shapeToLoop({ ...RECT(), width: 5000, height: 5000 }, 3);
    true_(loop.length <= G.MAX_POINTS, `点数 ${loop.length} 应 <= ${G.MAX_POINTS}`);
    near(loop.length, G.MAX_POINTS, 0, '应按周长平分到恰好上限');
});

test('间距被夹紧到 [MIN_SPACING, MAX_SPACING]', () => {
    near(G.shapeToLoop(CIRCLE(), 0.001).length, G.shapeToLoop(CIRCLE(), G.MIN_SPACING).length, 0, '过小间距夹到下限');
    near(G.shapeToLoop(CIRCLE(), 9999).length, G.shapeToLoop(CIRCLE(), G.MAX_SPACING).length, 0, '过大间距夹到上限');
});

test('末点与首点之间没有缺口（矩形 @ 10 m 应为 10 m）', () => {
    const loop = G.shapeToLoop(RECT(), 10);
    const gap = G.haversineMeters(loop[loop.length - 1], loop[0]);
    true_(Math.abs(gap - 10) < 0.2, `缺口 ${gap}，应 ≈10`);
});

test('旋转 90 度后经纬跨度互换', () => {
    const loop = G.shapeToLoop({ ...RECT(), rotation: Math.PI / 2 }, 10);
    const lats = loop.map((p) => p.lat);
    const lngs = loop.map((p) => p.lng);
    const latSpan = (Math.max(...lats) - Math.min(...lats)) * G.M_PER_DEG_LAT;
    const lngSpan = (Math.max(...lngs) - Math.min(...lngs)) * G.mPerDegLng(RECT().center.lat);
    true_(Math.abs(latSpan - 100) < 1, `南北跨度 ${latSpan}，应 ≈100`);
    true_(Math.abs(lngSpan - 60) < 1, `东西跨度 ${lngSpan}，应 ≈60`);
});

test('旋转不改变点数', () => {
    near(G.shapeToLoop({ ...RECT(), rotation: 1.1 }, 10).length, G.shapeToLoop(RECT(), 10).length, 0, '点数');
});

test('未规范化的过小图形也能正常打点', () => {
    const loop = G.shapeToLoop({ ...RECT(), width: 1, height: 1 }, 10);
    true_(loop.length >= 3, `至少 3 点，实际 ${loop.length}`);
});

// ===== 手柄几何与变换 =====
section('手柄几何与变换');

test('handlePositions 返回 8 个手柄，矩形按包围盒分布', () => {
    const hs = G.handlePositions(RECT());
    true_(hs.length === 8, '应为 8 个手柄，实际 ' + hs.length);
    const byKey = Object.fromEntries(hs.map((h) => [h.key, h]));
    near(byKey.nw.lx, -50, 1e-9, 'nw.lx');
    near(byKey.nw.ly, 30, 1e-9, 'nw.ly');
    near(byKey.se.lx, 50, 1e-9, 'se.lx');
    near(byKey.se.ly, -30, 1e-9, 'se.ly');
    near(byKey.n.lx, 0, 1e-9, 'n.lx');
    near(byKey.n.ly, 30, 1e-9, 'n.ly');
    near(byKey.w.lx, -50, 1e-9, 'w.lx');
    near(byKey.w.ly, 0, 1e-9, 'w.ly');
});

test('圆形使用矩形包围盒手柄（与 Word 图片选择框一致）', () => {
    const byKey = Object.fromEntries(G.handlePositions(CIRCLE()).map((h) => [h.key, h]));
    near(byKey.nw.lx, -60, 1e-9, 'nw.lx');
    near(byKey.nw.ly, 60, 1e-9, 'nw.ly');
    near(byKey.e.lx, 60, 1e-9, 'e.lx');
});

test('HANDLE_OPPOSITE 覆盖全部 8 个手柄且互为逆', () => {
    G.HANDLE_KEYS.forEach((k) => {
        const opp = G.HANDLE_OPPOSITE[k];
        true_(!!opp, k + ' 应有对角手柄');
        true_(G.HANDLE_OPPOSITE[opp] === k, k + ' 与 ' + opp + ' 应互为逆');
    });
});

// 锚点容差 1 mm：经纬度是球面坐标，mPerDegLng 随纬度变化，
// 中心南北移动后用同一个局部偏移换算出的经度会有亚毫米级差异（实测 2.7e-5 m）。
// 纬度方向是精确固定的；经度方向的这点漂移在任何缩放下都不可见，属模型固有精度而非缺陷。
const ANCHOR_TOL_M = 1e-3;

test('拖 se 手柄时，nw 角的地理位置保持不动（Word 锚点手感）', () => {
    const before = RECT();
    const anchorLocal = G.handlePositions(before).find((h) => h.key === 'nw');
    const anchorBefore = G.localToGeo(before.center, anchorLocal.lx, anchorLocal.ly, before.rotation);
    const after = G.resizeShape(before, 'se', 20, -10);   // 指针在中心东南 20/10 m
    const anchorLocalAfter = G.handlePositions(after).find((h) => h.key === 'nw');
    const anchorAfter = G.localToGeo(after.center, anchorLocalAfter.lx, anchorLocalAfter.ly, after.rotation);
    const drift = G.haversineMeters(anchorBefore, anchorAfter);
    true_(drift < ANCHOR_TOL_M, `锚点应保持不动，实际漂移 ${drift} m`);
    // 纬度方向必须精确固定（中心南北位移不该影响锚点纬度）
    near(anchorAfter.lat, anchorBefore.lat, 1e-12, '锚点纬度');
});

test('向右下拖 se 手柄把宽高改成 2 倍偏移', () => {
    const after = G.resizeShape(RECT(), 'se', 80, -50);
    near(after.width, 130, 1e-6, 'width');    // |80 - (-50)| = 130
    near(after.height, 80, 1e-6, 'height');   // |-50 - 30| = 80
});

test('拖 e 手柄只改宽度，高度不变', () => {
    const after = G.resizeShape(RECT(), 'e', 90, 999);
    near(after.width, 140, 1e-6, 'width');
    near(after.height, 60, 1e-6, 'height 应保持不变');
});

test('拖 n 手柄只改高度，宽度不变', () => {
    const after = G.resizeShape(RECT(), 'n', 999, 60);
    near(after.width, 100, 1e-6, 'width 应保持不变');
    near(after.height, 90, 1e-6, 'height = |60 − (−30)| = 90');
});

test('拖过锚点时图形翻转（宽高仍为正）', () => {
    const after = G.resizeShape(RECT(), 'e', -70, 0);
    true_(after.width > 0 && after.height > 0, '宽高必须为正');
    near(after.width, 20, 1e-6, 'width');     // |-70 - (-50)| = 20
});

test('缩放夹紧到 MIN_DIM_M，不塌成一点', () => {
    // 指针几乎贴在锚点 nw(-50, 30) 上：raw 宽高只有 0.1 m，必须被夹到 5 m
    const after = G.resizeShape(RECT(), 'se', -49.9, 29.9);
    near(after.width, G.MIN_DIM_M, 1e-9, 'width');
    near(after.height, G.MIN_DIM_M, 1e-9, 'height');
});

test('圆形缩放后仍是正圆（宽高相等）', () => {
    const after = G.resizeShape(CIRCLE(), 'e', 100, 0);
    near(after.width, after.height, 1e-9, '宽高应相等');
    true_(after.width > 0, '直径为正');
});

test('操场纵向拉高超过宽度时退化为圆（直道为 0）', () => {
    const after = G.resizeShape(STADIUM(), 'n', 0, 200);
    near(after.width, after.height, 1e-6, '宽度应被抬到等于高度');
});

test('操场横向拖动改变直道长度，弯道半径不变', () => {
    // 锚点是西边界 x = −157.39/2 = −78.695，新宽 = 指针 x − 西边界 x = 120 + 78.695
    const after = G.resizeShape(STADIUM(), 'e', 120, 0);
    near(after.height, 73, 1e-6, '半径不变（高度不变）');
    near(after.width, 120 + 157.39 / 2, 1e-6, '总宽 = 指针 x − 西边界 x');
});

test('resizeShape 不修改入参快照', () => {
    const snapshot = RECT();
    G.resizeShape(snapshot, 'se', 80, -50);
    near(snapshot.width, 100, 1e-9, '快照 width 不得被改动');
    near(snapshot.height, 60, 1e-9, '快照 height 不得被改动');
});

test('rotationFromPointer：手柄正北时为 0，正西时为 +90 度，正南为 ±180 度', () => {
    near(G.rotationFromPointer(0, 100), 0, 1e-9, '正北');
    near(G.rotationFromPointer(-100, 0), Math.PI / 2, 1e-9, '正西');
    // 正南返回 -π（与 +π 等价，旋转本就是模 2π 的），故比较绝对值
    near(Math.abs(G.rotationFromPointer(0, -100)), Math.PI, 1e-9, '正南');
});

test('rotationFromPointer 接受自定义抓取方位，避免按下瞬间跳转', () => {
    // 用户抓在东北 45 度处：此时应保持 rotation 为 0，而不是跳到 -45 度
    const bearing = Math.PI / 4;
    near(G.rotationFromPointer(Math.cos(bearing) * 80, Math.sin(bearing) * 80, bearing), 0, 1e-9, '抓取方位自洽');
    // 指针再转到正北：相对抓取方位转过了 45 度
    near(G.rotationFromPointer(0, 80, bearing), Math.PI / 4, 1e-9, '转过 45 度');
});

test('旋转后手柄的东/北向偏移随之改变', () => {
    const before = RECT();
    const after = { ...before, rotation: G.rotationFromPointer(70, 70) };   // 转 -45 度
    const eastBefore = G.handlePositions(before).find((h) => h.key === 'e');
    const eastAfter = G.handlePositions(after).find((h) => h.key === 'e');
    // handlePositions 返回的局部坐标不含旋转，旋转体现在 projectLocal 上
    near(G.projectLocal(before, eastBefore.lx, eastBefore.ly).x, 50, 1e-9, '旋转前 e 的正东偏移');
    const rotated = G.projectLocal(after, eastAfter.lx, eastAfter.ly);
    near(rotated.x, 50 * Math.cos(-Math.PI / 4), 1e-6, '旋转后正东偏移被投影缩短');
    near(rotated.y, 50 * Math.sin(-Math.PI / 4), 1e-6, '旋转后出现南北分量');
});

test('已旋转的图形仍能正确按锚点缩放', () => {
    const before = { ...RECT(), rotation: Math.PI / 4 };
    const anchorLocal = G.handlePositions(before).find((h) => h.key === 'sw');
    const anchorBefore = G.localToGeo(before.center, anchorLocal.lx, anchorLocal.ly, before.rotation);
    const after = G.resizeShape(before, 'ne', 40, 40);
    const anchorAfterLocal = G.handlePositions(after).find((h) => h.key === 'sw');
    const anchorAfter = G.localToGeo(after.center, anchorAfterLocal.lx, anchorAfterLocal.ly, after.rotation);
    const drift = G.haversineMeters(anchorBefore, anchorAfter);
    true_(drift < ANCHOR_TOL_M, `旋转后锚点仍应固定，实际漂移 ${drift} m`);
    // 旋转 45 度后锚点不在正南北向，两轴都会有一点球面换算漂移，但量级仍须远小于 1 mm
    true_(drift < 1e-4, `旋转情形漂移应更小，实际 ${drift} m`);
});

// ===== 打点的健壮性（code review 发现 2）=====
section('打点健壮性：非有限间距');

test('DEFAULT_SPACING 与编辑器默认一致', () => {
    near(G.DEFAULT_SPACING, 10, 0, 'DEFAULT_SPACING');
});

test('非有限间距不静默返回 0 点', () => {
    [NaN, undefined, null, Infinity, -Infinity, 'abc', {}].forEach((s) => {
        const n = G.shapeToLoop(RECT(), s).length;
        true_(n >= 3, `spacing=${String(s)} 时点数 ${n}，绝不该静默产出 0 点`);
    });
});

test('非有限间距回退到默认 10 m', () => {
    // 写死 32（矩形 100×60 @10 m 的已知点数），不要拿 shapeToLoop 的两个返回值互比 ——
    // 出 bug 时两边会一起变成 0，断言就变成同义反复了。
    [NaN, undefined, 'abc'].forEach((s) => {
        near(G.shapeToLoop(RECT(), s).length, 32, 0, `spacing=${String(s)} 回退到 10 m`);
    });
});

// ===== 圆形边中点缩放（code review 发现 1）=====
section('圆形边中点手柄');

test('圆形的四个边中点手柄都能缩小它', () => {
    // 回归：lockDims 对圆取 max(w,h)，拖边中点时未驱动的那一轴会顶住结果，
    // 导致四个边手柄只能放大、永远缩不小（实测四个方向都停在 120）。
    const cases = [
        ['n', 0, 30], ['s', 0, -30], ['e', 30, 0], ['w', -30, 0]
    ];
    cases.forEach(([k, lx, ly]) => {
        const r = G.resizeShape(CIRCLE(), k, lx, ly);
        near(r.width, 90, 1e-6, `拖 ${k} 手柄的直径应为 |指针 − 对侧手柄| = 90`);
        near(r.height, 90, 1e-6, `拖 ${k} 手柄后仍应是正圆`);
    });
});

test('圆形边中点手柄仍能放大（别把缩小修成只能缩）', () => {
    const r = G.resizeShape(CIRCLE(), 'n', 0, 100);
    near(r.width, 160, 1e-6, '向外拖应变大到 160');
});

test('圆形边中点缩放时对侧手柄保持不动', () => {
    const before = CIRCLE();
    const anchorBefore = G.localToGeo(before.center, 0, -60, 0);        // 南侧手柄
    const after = G.resizeShape(before, 'n', 0, 30);
    const anchorAfter = G.localToGeo(after.center, 0, -after.height / 2, 0);
    const drift = G.haversineMeters(anchorBefore, anchorAfter);
    true_(drift < 1e-3, `南侧锚点应保持不动，实际漂移 ${drift} m`);
});

test('圆形角手柄仍取两轴较大者（两轴同时驱动）', () => {
    const r = G.resizeShape(CIRCLE(), 'se', 100, -100);
    near(r.width, 160, 1e-6, '角手柄向外 160');
});

// ===== 汇总 =====
console.log(`\n${passed} 个用例通过，${failed} 个失败`);
if (failed > 0) process.exitCode = 1;
