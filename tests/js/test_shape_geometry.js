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

// ===== 汇总 =====
console.log(`\n${passed} 个用例通过，${failed} 个失败`);
if (failed > 0) process.exitCode = 1;
