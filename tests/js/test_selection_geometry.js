const assert = require('node:assert/strict');
const G = require('../../web/static/js/selection_geometry.js');
let count = 0;
const test = (name, fn) => { fn(); count++; console.log('PASS ' + name); };
const near = (a, b) => assert.ok(Math.abs(a - b) < 1e-8, `${a} != ${b}`);
const f = { x: 100, y: 80, width: 60, height: 40, angle: 0 };
test('中心命中包含边界，反向拉框相同，半径相交但中心在外不选', () => {
    const a = { x: 0, y: 0 }, b = { x: 20, y: 30 };
    assert.ok(G.inside(a, b, a));
    assert.ok(G.inside(b, a, b));
    assert.ok(!G.inside(a, b, { x: -1, y: 15 }));
    assert.equal(G.bounds([]), null);
});
test('平移所有点位移相同', () => {
    const to = G.transform(f, 'move', { x: 2, y: 5 }, { x: 12, y: 20 });
    assert.deepEqual(G.point({ x: 70, y: 60 }, f, to), { x: 80, y: 75 });
});
for (const [key, [hx, hy]] of Object.entries(G.handles)) {
    test(`${key} 缩放固定对侧，边柄只改变单轴，角柄改变双轴`, () => {
        const start = G.world(f, hx * f.width / 2, hy * f.height / 2);
        const end = { x: start.x + hx * 12, y: start.y + hy * 8 };
        const to = G.transform(f, key, start, end);
        near(to.width, f.width + (hx ? 12 : 0));
        near(to.height, f.height + (hy ? 8 : 0));
        const anchor = G.world(f, -hx * f.width / 2, -hy * f.height / 2);
        const after = G.point(anchor, f, to);
        near(anchor.x, after.x); near(anchor.y, after.y);
        const crossed = G.transform(f, key, start,
            { x: start.x - hx * 1000, y: start.y - hy * 1000 });
        assert.ok(crossed.width > 0 && crossed.height > 0);
        near(crossed.width, hx ? 1 : f.width);
        near(crossed.height, hy ? 1 : f.height);
    });
}
test('旋转围绕中心且保持距离；旋转后的边柄沿局部轴变换', () => {
    const to = G.transform(f, 'rotate', { x: 100, y: 30 }, { x: 150, y: 80 });
    const p = G.point({ x: 130, y: 80 }, f, to);
    near(p.x, 100); near(p.y, 110); near(to.angle, Math.PI / 2);
    const edge = G.world(to, to.width / 2, 0);
    const resized = G.transform(to, 'e', edge, { x: edge.x, y: edge.y + 20 });
    near(resized.width, 80); near(resized.height, 40);
    near(resized.x, 100); near(resized.y, 90);
});
test('零宽、零高与单点保持有限坐标；退化轴不可扩展', () => {
    for (const points of [[{ x: 5, y: 5 }], [{ x: 5, y: 5 }, { x: 5, y: 20 }],
        [{ x: 5, y: 5 }, { x: 20, y: 5 }]]) {
        const from = G.bounds(points);
        for (const key of Object.keys(G.handles)) {
            const to = G.transform(from, key, { x: 0, y: 0 }, { x: 30, y: 40 });
            if (!from.width) near(to.width, 0);
            if (!from.height) near(to.height, 0);
            points.forEach(p => assert.ok(Object.values(G.point(p, from, to)).every(Number.isFinite)));
        }
    }
});
test('非法经纬度、NaN、Infinity 与投影极点拒绝', () => {
    for (const p of [{ lat: NaN, lng: 0 }, { lat: 0, lng: Infinity },
        { lat: 90, lng: 0 }, { lat: -91, lng: 0 }, { lat: 20, lng: 181 }]) assert.ok(!G.validGeo(p));
    assert.ok(G.validGeo({ lat: 26.42, lng: 106.67 }));
});
console.log(`${count} selection geometry tests passed`);
