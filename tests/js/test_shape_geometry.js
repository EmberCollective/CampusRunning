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

// ===== 汇总 =====
console.log(`\n${passed} 个用例通过，${failed} 个失败`);
if (failed > 0) process.exitCode = 1;
