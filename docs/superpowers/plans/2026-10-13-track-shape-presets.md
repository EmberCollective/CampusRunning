# 轨迹编辑器图形模板 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 给轨迹编辑器补上图形模板能力——侧边栏点选矩形/圆形/操场形，图形出现在地图上可按 Word 图片的方式拖动/缩放/旋转，轮廓上实时预打点（点数随尺寸变化），确认后一次性写入轨迹点。

**Architecture:** 三层。`shape_geometry.js` 是零依赖纯几何模块（图形模型、轮廓分解、按间距打点、手柄变换数学、米↔经纬度），浏览器与 Node 双用，全部单测覆盖。`shape_layer.js` 在 `.map-stage` 上叠一层 SVG，负责像素换算、视野同步与指针交互。`track_editor.js` 只做侧边栏接线。图形层是地图容器的兄弟节点，因此天然置顶，且其指针事件不会冒泡到地图容器。

**Tech Stack:** 原生 JavaScript（无构建步骤、无 npm 依赖）、Leaflet（已有 vendor 副本）、高德 JS API 2.0、SVG、Node 内置 `assert`（仅测试用）、pytest。

**Spec:** `docs/superpowers/specs/2026-10-13-track-shape-presets-design.md`

## Global Constraints

- **不新增任何运行时依赖**：无 npm、无 package.json、无构建步骤。前端一律用普通 `<script>` 全局脚本，保持仓库现有风格。
- **不改后端**：`web/routes.py`、`src/`、CLI、导出链路一行都不动。
- **不改 `renderTrack`**：两个适配器的 `renderTrack(points, handlers)` 与 `track_editor.js` 的 `points` 数据流保持原样。
- **常量取值（逐字照抄 spec §2.3）**：`EARTH_RADIUS_M = 6371000`、`M_PER_DEG_LAT = EARTH_RADIUS_M * Math.PI / 180`、`MIN_DIM_M = 5`、`MIN_SPACING = 3`、`MAX_SPACING = 100`、`MAX_POINTS = 500`。
- **默认尺寸（逐字照抄 spec §2.2）**：操场 `w = 157.39, h = 73`（= 直道 84.39 + 2×半径 36.5）；矩形 `w = 100, h = 60`；圆形 `w = h = 120`（R = 60）。默认间距 10 m。
- **坐标约定**：局部坐标系原点 = 图形中心，`+x` = 东，`+y` = 北，`rotation` 逆时针为正。像素空间 y 向下，转换公式 `px = cx + x·scale`、`py = cy − y·scale`。
- **脚本加载顺序**：`leaflet.js → map_adapter_leaflet.js → map_adapter_amap.js → map_engine.js → search_box.js → shape_geometry.js → shape_layer.js → track_editor.js`。
- **注释与用户可见文案一律中文**，与仓库现有风格一致。
- **主题色** `#3B5BD7`，前端复用已有全局常量 `TRACK_ACCENT`（定义在 `map_adapter_leaflet.js`，先于本次新增脚本加载，可直接引用）。
- **提交信息**用仓库 CLAUDE.md 的 type：本次全部为 `web` 前缀。

## Review Focus

以下 5 类输入/场景 spec 没有明说，但用户极可能撞上；每条都在对应任务的步骤里有验证动作。

1. **极端缩放下图形层是否仍贴合**（Leaflet z3 与 z20、AMap 官方档）：`metersPerPixel` 求法必须除零安全，手柄不能缩到抓不住。→ Task 7、Task 8。
2. **图形被拖到视口外**（部分或全部离开画布）：手柄是否还能抓回来，SVG 是否需要溢出裁剪。→ Task 9。
3. **多图形分开摆放**：两图形之间会连出一条跨越直线，用户必须在预览里提前看到，而不是生成后才发现。→ Task 8、Task 10。
4. **生成后立刻 Ctrl+Z**：轨迹点回到手画状态，且图形层仍在（图形编辑不进撤销栈）。→ Task 11。
5. **生成 500 点上限的轨迹后能否正常出数据**：下游 `TrackAnalyzer` / 导出器 / 生成器是否吃得下高点数轨迹。→ Task 12。

---

### Task 1: 几何模块骨架与单位换算

**Files:**
- Create: `web/static/js/shape_geometry.js`
- Create: `tests/js/test_shape_geometry.js`
- Create: `tests/test_shape_geometry.py`

**Interfaces:**
- Consumes: 无（本任务是一切的基础）
- Produces:
  - `EARTH_RADIUS_M: number` = 6371000
  - `M_PER_DEG_LAT: number` ≈ 111194.93
  - `haversineMeters(a: {lat,lng}, b: {lat,lng}) -> number`（米）
  - `mPerDegLng(lat: number) -> number`（米/度，`cos` 下限 0.01）
  - `projectLocal(shape: {rotation}, lx, ly) -> {x, y}`（旋转到「东/北」轴，单位米）
  - `unprojectLocal(shape: {rotation}, x, y) -> {lx, ly}`（逆旋转回局部轴）
  - `localToGeo(center: {lat,lng}, lx, ly, rotation: number) -> {lat, lng}`
  - `module.exports` 守卫，供 Node `require`

- [ ] **Step 1: 写测试脚手架（Node 断言运行器 + pytest 驱动器）**

创建 `tests/js/test_shape_geometry.js`：

```js
// 图形几何单测：无 DOM 依赖，Node 直接运行（零第三方依赖）
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

const { test, near, true_, section } = module.exports = {
    test, near, true_, section, G, passed: () => passed, failed: () => failed
};

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
```

创建 `tests/test_shape_geometry.py`：

```python
"""图形几何模块（web/static/js/shape_geometry.js）的单测驱动。

几何是纯 JS（无 DOM），用 Node 跑；CI 只装 Python，故无 Node 时整组跳过。
"""

import shutil
import subprocess
from pathlib import Path

import pytest

NODE = shutil.which("node")
JS_TEST = Path(__file__).parent / "js" / "test_shape_geometry.js"
GEOMETRY = Path(__file__).parent.parent / "web" / "static" / "js" / "shape_geometry.js"


@pytest.mark.skipif(NODE is None, reason="需要 Node.js 运行前端几何单测（CI 无 Node 时跳过）")
def test_shape_geometry_js_suite():
    assert GEOMETRY.exists(), f"几何模块不存在：{GEOMETRY}"
    result = subprocess.run(
        [NODE, str(JS_TEST)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
    )
    assert result.returncode == 0, f"Node 用例失败：\n{result.stdout}\n{result.stderr}"
```

- [ ] **Step 2: 运行测试，确认失败**

Run: `python -m pytest tests/test_shape_geometry.py -v`
Expected: FAIL —— `AssertionError: 几何模块不存在：...shape_geometry.js`（或 Node 报 `Cannot find module`）

- [ ] **Step 3: 写最小实现**

创建 `web/static/js/shape_geometry.js`：

```js
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
```

- [ ] **Step 4: 运行测试，确认通过**

Run: `python -m pytest tests/test_shape_geometry.py -v`
Expected: PASS（本机有 Node v24；终端里能看到 `9 个用例通过，0 个失败`。若用例数少于 9，说明某个用例抛在 `require` 阶段被静默跳过，必须先查）

- [ ] **Step 5: 提交**

```bash
git add web/static/js/shape_geometry.js tests/js/test_shape_geometry.js tests/test_shape_geometry.py
git commit -m "web: 新增图形几何模块骨架（常量、haversine、米↔经纬度）与 Node 单测脚手架"
```

---

### Task 2: 图形规范化与默认尺寸

**Files:**
- Modify: `web/static/js/shape_geometry.js`（追加函数 + 扩充 `module.exports`）
- Modify: `tests/js/test_shape_geometry.js`（追加用例）

**Interfaces:**
- Consumes: `MIN_DIM_M`（Task 1）
- Produces:
  - `lockDims(type: string, width: number, height: number) -> {width, height}` —— 夹紧尺寸并施加类型约束（圆锁定 `w = h`；操场保证 `w ≥ h`，即直道 `L ≥ 0`）
  - `normalizeShape(shape) -> shape` —— 返回新对象，`width`/`height` 已过夹紧
  - `makeDefaultShape(type: 'rect'|'circle'|'stadium', center: {lat,lng}, id: string) -> shape` —— 未知类型抛 `Error`

- [ ] **Step 1: 写失败测试**

在 `tests/js/test_shape_geometry.js` 的「汇总」块**之前**插入：

```js
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
    let threw = false;
    try {
        G.makeDefaultShape('triangle', { lat: 0, lng: 0 }, 'x');
    } catch (e) {
        threw = true;
    }
    true_(threw, '未知类型必须抛错');
});
```

- [ ] **Step 2: 运行测试，确认失败**

Run: `python -m pytest tests/test_shape_geometry.py -v`
Expected: FAIL —— `TypeError: G.lockDims is not a function`

- [ ] **Step 3: 写最小实现**

在 `web/static/js/shape_geometry.js` 的 `localToGeo` 之后、`module.exports` 之前插入：

```js
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
```

同时把 `module.exports` 改为：

```js
if (typeof module !== 'undefined' && module.exports) {
    module.exports = {
        EARTH_RADIUS_M, M_PER_DEG_LAT, MIN_DIM_M, MIN_SPACING, MAX_SPACING, MAX_POINTS,
        haversineMeters, mPerDegLng, projectLocal, unprojectLocal, localToGeo,
        lockDims, normalizeShape, makeDefaultShape
    };
}
```

- [ ] **Step 4: 运行测试，确认通过**

Run: `python -m pytest tests/test_shape_geometry.py -v`
Expected: PASS（`17 个用例通过，0 个失败`：Task 1 的 9 个 + 本任务 8 个）

- [ ] **Step 5: 提交**

```bash
git add web/static/js/shape_geometry.js tests/js/test_shape_geometry.js
git commit -m "web: 几何模块新增尺寸约束、规范化与默认图形尺寸"
```

---

### Task 3: 轮廓分解为路径基元

**Files:**
- Modify: `web/static/js/shape_geometry.js`
- Modify: `tests/js/test_shape_geometry.js`

**Interfaces:**
- Consumes: `normalizeShape`（Task 2）、`MIN_DIM_M`
- Produces:
  - 基元类型：`{kind:'line', from:{x,y}, to:{x,y}}` 或 `{kind:'arc', center:{x,y}, radius:number, startAngle:number, sweep:number}`（局部米坐标）
  - `shapeOutlines(shape) -> primitive[]` —— 逆时针、闭合（末基元终点 == 首基元起点）
  - `primitiveLength(p) -> number`（米）
  - `primitivePoint(p, t) -> {x, y}` —— `t ∈ [0,1]`，`t=0` 为基元起点
  - `shapePerimeter(shape) -> number`（米）

- [ ] **Step 1: 写失败测试**

在「汇总」块之前插入：

```js
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
```

- [ ] **Step 2: 运行测试，确认失败**

Run: `python -m pytest tests/test_shape_geometry.py -v`
Expected: FAIL —— `TypeError: G.shapeOutlines is not a function`

- [ ] **Step 3: 写最小实现**

在 `makeDefaultShape` 之后、`module.exports` 之前插入：

```js
// ===== 轮廓分解（局部米坐标，统一逆时针，首尾闭合）=====
//
// 基元结构：
//   { kind: 'line', from: {x,y}, to: {x,y} }
//   { kind: 'arc', center: {x,y}, radius, startAngle, sweep }   // 弧度，逆时针为正
//
// 三个图形的起点（即生成点列的第一个点，编辑器会把它标成「起点」）：
//   矩形  西南角 (-w/2, -h/2)
//   圆形  正东 (R, 0)
//   操场  左起下 (-L/2, -R)

const TWO_PI = Math.PI * 2;

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
        return [{
            kind: 'arc',
            center: { x: 0, y: 0 },
            radius: w / 2,
            startAngle: 0,
            sweep: TWO_PI
        }];
    }

    if (s.type === 'stadium') {
        const radius = h / 2;
        const straight = w - h;   // 直道长度；normalizeShape 已保证 >= 0
        return [
            { kind: 'line', from: { x: -straight / 2, y: -radius }, to: { x: straight / 2, y: -radius } },
            { kind: 'arc', center: { x: straight / 2, y: 0 }, radius, startAngle: -Math.PI / 2, sweep: Math.PI },
            { kind: 'line', from: { x: straight / 2, y: radius }, to: { x: -straight / 2, y: radius } },
            { kind: 'arc', center: { x: -straight / 2, y: 0 }, radius, startAngle: Math.PI / 2, sweep: Math.PI }
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
```

同时把 `module.exports` 改为（在上一版基础上追加 4 个名字）：

```js
if (typeof module !== 'undefined' && module.exports) {
    module.exports = {
        EARTH_RADIUS_M, M_PER_DEG_LAT, MIN_DIM_M, MIN_SPACING, MAX_SPACING, MAX_POINTS,
        haversineMeters, mPerDegLng, projectLocal, unprojectLocal, localToGeo,
        lockDims, normalizeShape, makeDefaultShape,
        shapeOutlines, primitiveLength, primitivePoint, shapePerimeter
    };
}
```

- [ ] **Step 4: 运行测试，确认通过**

Run: `python -m pytest tests/test_shape_geometry.py -v`
Expected: PASS（`26 个用例通过，0 个失败`：17 + 本任务 9 个）

- [ ] **Step 5: 提交**

```bash
git add web/static/js/shape_geometry.js tests/js/test_shape_geometry.js
git commit -m "web: 几何模块新增三种图形的轮廓分解与周长计算"
```

---

### Task 4: 按间距打点

**Files:**
- Modify: `web/static/js/shape_geometry.js`
- Modify: `tests/js/test_shape_geometry.js`

**Interfaces:**
- Consumes: `shapeOutlines`、`primitiveLength`、`primitivePoint`、`localToGeo`、`normalizeShape`、`MIN_SPACING`、`MAX_SPACING`、`MAX_POINTS`
- Produces: `shapeToLoop(shape, spacing: number) -> {lat,lng}[]` —— 闭合点列（不含与首点重复的末点），按图形自身顺时针/逆时针方向排列，逆时针

- [ ] **Step 1: 写失败测试**

在「汇总」块之前插入：

```js
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
```

- [ ] **Step 2: 运行测试，确认失败**

Run: `python -m pytest tests/test_shape_geometry.py -v`
Expected: FAIL —— `TypeError: G.shapeToLoop is not a function`

- [ ] **Step 3: 写最小实现**

在 `shapePerimeter` 之后、`module.exports` 之前插入：

```js
// 按目标间距把轮廓细分成闭合点列（设计文档 §3.2）
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
```

同时把 `module.exports` 改为：

```js
if (typeof module !== 'undefined' && module.exports) {
    module.exports = {
        EARTH_RADIUS_M, M_PER_DEG_LAT, MIN_DIM_M, MIN_SPACING, MAX_SPACING, MAX_POINTS,
        haversineMeters, mPerDegLng, projectLocal, unprojectLocal, localToGeo,
        lockDims, normalizeShape, makeDefaultShape,
        shapeOutlines, primitiveLength, primitivePoint, shapePerimeter,
        shapeToLoop
    };
}
```

- [ ] **Step 4: 运行测试，确认通过**

Run: `python -m pytest tests/test_shape_geometry.py -v`
Expected: PASS（`38 个用例通过，0 个失败`：26 + 本任务 12 个）

- [ ] **Step 5: 提交**

```bash
git add web/static/js/shape_geometry.js tests/js/test_shape_geometry.js
git commit -m "web: 几何模块新增按间距打点，点数随图形尺寸自动变化"
```

---

### Task 5: 手柄几何与变换数学

**Files:**
- Modify: `web/static/js/shape_geometry.js`
- Modify: `tests/js/test_shape_geometry.js`

**Interfaces:**
- Consumes: `normalizeShape`、`lockDims`、`handlePositions` 内部依赖、`projectLocal`、`unprojectLocal`、`M_PER_DEG_LAT`、`mPerDegLng`、`MIN_DIM_M`
- Produces:
  - `HANDLE_KEYS: string[]` = `['nw','n','ne','e','se','s','sw','w']`
  - `HANDLE_OPPOSITE: {[key: string]: string}`
  - `ROTATE_HANDLE_ANGLE: number` = `Math.PI / 2`（旋转手柄在局部 +y / 正北方向）
  - `handlePositions(shape) -> {key, lx, ly}[]`（局部米坐标，8 个）
  - `rotationFromPointer(offsetX, offsetY) -> number`（指针相对中心的东西/北向偏移 → 新 rotation）
  - `resizeShape(snapshot, key, offsetX, offsetY) -> shape` —— 对角锚点固定；`offsetX/offsetY` 是**指针相对 `snapshot.center` 的东西/北向偏移（米）**

- [ ] **Step 1: 写失败测试**

在「汇总」块之前插入：

```js
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

test('向左下拖 se 手柄时，nw 角的地理位置保持不动（Word 锚点手感）', () => {
    const before = RECT();
    const anchorLocal = G.handlePositions(before).find((h) => h.key === 'nw');
    const anchorBefore = G.localToGeo(before.center, anchorLocal.lx, anchorLocal.ly, before.rotation);
    const after = G.resizeShape(before, 'se', 20, -10);   // 指针在中心东南 20/10 m
    const anchorLocalAfter = G.handlePositions(after).find((h) => h.key === 'nw');
    const anchorAfter = G.localToGeo(after.center, anchorLocalAfter.lx, anchorLocalAfter.ly, after.rotation);
    true_(G.haversineMeters(anchorBefore, anchorAfter) < 1e-6, '锚点应纹丝不动');
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

test('旋转不改变宽高与中心', () => {
    const before = RECT();
    const theta = G.rotationFromPointer(70, 70);
    const after = { ...before, rotation: theta };
    near(after.width, before.width, 1e-9, 'width');
    near(after.center.lat, before.center.lat, 1e-9, 'center.lat');
});

test('已旋转的图形仍能正确按锚点缩放', () => {
    const before = { ...RECT(), rotation: Math.PI / 4 };
    const anchorLocal = G.handlePositions(before).find((h) => h.key === 'sw');
    const anchorBefore = G.localToGeo(before.center, anchorLocal.lx, anchorLocal.ly, before.rotation);
    const after = G.resizeShape(before, 'ne', 40, 40);
    const anchorAfterLocal = G.handlePositions(after).find((h) => h.key === 'sw');
    const anchorAfter = G.localToGeo(after.center, anchorAfterLocal.lx, anchorAfterLocal.ly, after.rotation);
    true_(G.haversineMeters(anchorBefore, anchorAfter) < 1e-6, '旋转后锚点仍应固定');
});
```

- [ ] **Step 2: 运行测试，确认失败**

Run: `python -m pytest tests/test_shape_geometry.py -v`
Expected: FAIL —— `TypeError: G.handlePositions is not a function`

- [ ] **Step 3: 写最小实现**

在 `shapeToLoop` 之后、`module.exports` 之前插入：

```js
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

// 拖动手柄缩放。offsetX/offsetY 是指针相对 snapshot.center 的「东西/北向」偏移（米）。
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

    const raw = {
        width: hasX ? Math.abs(p.lx - ax) : s.width,
        height: hasY ? Math.abs(p.ly - ay) : s.height
    };
    const { width, height } = lockDims(s.type, raw.width, raw.height);

    const dirX = hasX ? (Math.sign(p.lx - ax) || 1) : 0;
    const dirY = hasY ? (Math.sign(p.ly - ay) || 1) : 0;
    const shift = projectLocal(s, hasX ? ax + dirX * width / 2 : 0, hasY ? ay + dirY * height / 2 : 0);

    const center = {
        lat: s.center.lat + shift.y / M_PER_DEG_LAT,
        lng: s.center.lng + shift.x / mPerDegLng(s.center.lat)
    };
    return normalizeShape({ ...s, width, height, center });
}
```

同时把 `module.exports` 改为：

```js
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
```

- [ ] **Step 4: 运行测试，确认通过**

Run: `python -m pytest tests/test_shape_geometry.py -v`
Expected: PASS（`55 个用例通过，0 个失败`：38 + 本任务 17 个）

- [ ] **Step 5: 提交**

```bash
git add web/static/js/shape_geometry.js tests/js/test_shape_geometry.js
git commit -m "web: 几何模块新增手柄布局与锚点缩放/旋转数学"
```

---

### Task 6: 加载脚本 + 收敛 haversine 副本

**Files:**
- Modify: `web/templates/track_editor.html:210-215`（脚本加载顺序）
- Modify: `web/static/js/track_editor.js:127-137`（删除本地 haversine 副本）

**Interfaces:**
- Consumes: `shape_geometry.js` 的 `haversineMeters`、`EARTH_RADIUS_M`（Task 1）
- Produces: 页面里 `haversineMeters` 只有一个实现；后续任务可直接用全局 `shape_geometry` 里的函数

- [ ] **Step 1: 在模板里插入脚本标签**

把 `web/templates/track_editor.html` 末尾的脚本块：

```html
    <!-- 脚本加载顺序：Leaflet → 两个地图适配器 → 引擎 → 搜索框 → 编辑器主逻辑 -->
    <script src="/static/vendor/leaflet/leaflet.js"></script>
    <script src="/static/js/map_adapter_leaflet.js"></script>
    <script src="/static/js/map_adapter_amap.js"></script>
    <script src="/static/js/map_engine.js"></script>
    <script src="/static/js/search_box.js"></script>
    <script src="/static/js/track_editor.js"></script>
```

改为：

```html
    <!-- 脚本加载顺序：Leaflet → 两个地图适配器 → 引擎 → 搜索框 → 图形几何 → 编辑器主逻辑 -->
    <!-- shape_geometry.js 必须在 track_editor.js 之前：它依赖其全局函数。
         shape_layer.js 的 <script> 由 Task 8 在本行之后再补（本任务时该文件尚不存在）。 -->
    <script src="/static/vendor/leaflet/leaflet.js"></script>
    <script src="/static/js/map_adapter_leaflet.js"></script>
    <script src="/static/js/map_adapter_amap.js"></script>
    <script src="/static/js/map_engine.js"></script>
    <script src="/static/js/search_box.js"></script>
    <script src="/static/js/shape_geometry.js"></script>
    <script src="/static/js/shape_layer.js"></script>
    <script src="/static/js/track_editor.js"></script>
```

同时把地图舞台里的图形层容器加上（放在 `#map-amap` 之后、`.search-box` 之前，与 CSS 的兄弟顺序一致）：

```html
                <!-- 高德官方 JS API 容器：仅「官方」档使用，初始隐藏 -->
                <div id="map-amap" style="display:none"></div>

                <!-- 图形模板覆盖层：SVG 由 shape_layer.js 在 init 时注入 -->
                <div id="shape-layer" class="shape-layer"></div>
```

- [ ] **Step 2: 删掉 track_editor.js 里的 haversine 副本**

把 `web/static/js/track_editor.js` 中这一段：

```js
// ===== 统计（Haversine，与后端 TrackAnalyzer 同参：R=6371000，环线含闭合段）=====
const EARTH_RADIUS_M = 6371000;

function haversineMeters(a, b) {
    const toRad = (deg) => deg * Math.PI / 180;
    const dLat = toRad(b.lat - a.lat);
    const dLng = toRad(b.lng - a.lng);
    const s = Math.sin(dLat / 2) ** 2 +
        Math.cos(toRad(a.lat)) * Math.cos(toRad(b.lat)) * Math.sin(dLng / 2) ** 2;
    return 2 * EARTH_RADIUS_M * Math.asin(Math.sqrt(s));
}

function totalLoopDistance(pts) {
```

改为：

```js
// ===== 统计（Haversine 已收敛到 shape_geometry.js，唯一实现；与后端 TrackAnalyzer 同参：R=6371000，环线含闭合段）=====
function totalLoopDistance(pts) {
```

（`haversineMeters` 现在由先加载的 `shape_geometry.js` 提供全局函数，`totalLoopDistance` 的调用点不动。）

- [ ] **Step 3: 启动应用手验（统计读数必须一字不差）**

Run: `python app.py`

浏览器打开 `http://127.0.0.1:5000/editor?track=east_campus_stadium`

Expected:
- 页面正常渲染，地图与轨迹加载，控制台**没有** `haversineMeters is not defined`
- 右侧「环线总距离 LOOP」显示 **439.4 m**（该值是先前用同一公式离线算出的基准，去重后必须完全一致）
- 拖一个顶点，读数随之变化

- [ ] **Step 4: 跑一遍 Python 测试确认没波及后端**

Run: `python -m pytest -q`
Expected: PASS（全绿）

- [ ] **Step 5: 提交**

```bash
git add web/templates/track_editor.html web/static/js/track_editor.js
git commit -m "web: 编辑器加载图形模块脚本，haversine 副本收敛为唯一实现"
```

---

### Task 7: 适配器坐标换算与视野钩子

**Files:**
- Modify: `web/static/js/map_adapter_leaflet.js`（在 `getView()` 之后插入）
- Modify: `web/static/js/map_adapter_amap.js`（在 `getView()` 之后插入）
- Modify: `web/static/js/map_engine.js`（`getView` 转发附近 + `switchMode` 内重绑）

**Interfaces:**
- Consumes: 无（用引擎自带 API）
- Produces（两个适配器与 `MapEngine` 同名同签名）：
  - `latLngToContainer(lat: number, lng: number) -> {x: number, y: number}` —— 相对地图容器左上角的像素
  - `containerToLatLng(x: number, y: number) -> {lat: number, lng: number}`
  - `bindViewHooks(hooks: {onChange, onZoomStart, onZoomEnd}) -> void`
- `MapEngine.bindViewHooks(hooks)` 记录 hooks，并在 `switchMode` 成功切换到新适配器后对新适配器重新绑定并主动调用一次 `onChange`

- [ ] **Step 1: 给 LeafletAdapter 加三个方法**

在 `web/static/js/map_adapter_leaflet.js` 的 `fitTrack` 之前插入：

```js
    // ===== 屏幕像素换算（图形层用：容器像素 ↔ 经纬度）=====
    // 容器像素原点 = #map-leaflet 左上角；#map-leaflet 与 #shape-layer 同为 inset:0，
    // 故这里返回的坐标可以直接当作 shape-layer 的坐标使用。
    latLngToContainer(lat, lng) {
        const p = this.map.latLngToContainerPoint([lat, lng]);
        return { x: p.x, y: p.y };
    }

    containerToLatLng(x, y) {
        const ll = this.map.containerPointToLatLng([x, y]);
        return { lat: ll.lat, lng: ll.lng };
    }

    // 视野变化钩子：平移/缩放重绘图形层；缩放动画期间要遮住图形层——
    // Leaflet 动画中 latLngToContainerPoint 仍返回旧 zoom 的值，不遮会先漂移再跳回
    bindViewHooks(hooks) {
        this.map.on('move zoom', () => hooks.onChange());
        this.map.on('zoomstart', () => hooks.onZoomStart && hooks.onZoomStart());
        this.map.on('zoomend', () => {
            if (hooks.onZoomEnd) hooks.onZoomEnd();
            hooks.onChange();
        });
    }
```

- [ ] **Step 2: 给 AmapAdapter 加三个方法**

在 `web/static/js/map_adapter_amap.js` 的 `fitTrack` 之前插入：

```js
    // ===== 屏幕像素换算（图形层用：容器像素 ↔ 经纬度）=====
    // 容器像素原点 = #map-amap 左上角；与 #shape-layer 同为 inset:0，坐标可直接共用。
    latLngToContainer(lat, lng) {
        const p = this.map.lngLatToContainer([lng, lat]);
        return { x: p.getX(), y: p.getY() };
    }

    containerToLatLng(x, y) {
        const ll = this.map.containerToLngLat(new this._AMap.Pixel(x, y));
        return { lat: ll.getLat(), lng: ll.getLng() };
    }

    // 视野变化钩子：AMap 缩放是瞬时切换、没有动画漂移，故不需要遮挡，
    // onZoomStart / onZoomEnd 由 MapEngine 传空实现。
    bindViewHooks(hooks) {
        this.map.on('mapmove', () => hooks.onChange());
        this.map.on('zoomchange', () => hooks.onChange());
        this.map.on('viewchange', () => hooks.onChange());
    }
```

- [ ] **Step 3: MapEngine 转发 + 切档重绑**

在 `web/static/js/map_engine.js` 的 `setDragEnabled` 之后插入：

```js
    // ===== 图形层用的像素换算与视野钩子（转发到当前活跃引擎）=====
    // 钩子只注册一次，切换到新适配器时必须重新绑定，否则切档后图形不再跟随视野；
    // 重绑后立刻补一次 onChange，让图形在新引擎下重新定位。
    bindViewHooks(hooks) {
        this._viewHooks = hooks;
        this._bindViewHooksToActive();
    },

    _bindViewHooksToActive() {
        if (!this._viewHooks) return;
        this.activeAdapter().bindViewHooks(this._viewHooks);
        this._viewHooks.onChange();
    },

    latLngToContainer(lat, lng) {
        return this.activeAdapter().latLngToContainer(lat, lng);
    },

    containerToLatLng(x, y) {
        return this.activeAdapter().containerToLatLng(x, y);
    },
```

在 `MapEngine` 对象字面量的 `_dragEnabled: true,` 之后补一个字段：

```js
    _viewHooks: null,           // 图形层注册的视野钩子（切档时重绑）
```

然后在 `switchMode(mode)` 里，Leaflet 三档互切的收尾处（`renderTrack();  // 后台引擎覆盖物不维护，切换后必须重渲染` 之后）加上：

```js
        this._bindViewHooksToActive();   // 图形层跟随新引擎重新定位
```

在 `_switchToAmap()` 的两条成功路径里（`renderTrack();` 之后）同样各加一行：

```js
            this._bindViewHooksToActive();
```

- [ ] **Step 4: 浏览器控制台验证（含极端缩放）**

Run: `python app.py`，打开 `http://127.0.0.1:5000/editor`，F12 控制台：

```js
// 1) 坐标换算自洽：容器任意点 → 经纬度 → 回容器点，应回到原处（±1 px）
const p = { x: 400, y: 300 };
const ll = MapEngine.containerToLatLng(p.x, p.y);
MapEngine.latLngToContainer(ll.lat, ll.lng);         // 期望 {x: 400±1, y: 300±1}

// 2) 视野钩子：拖动地图时持续打印
MapEngine.bindViewHooks({ onChange: () => console.log('view changed'), onZoomStart: () => {}, onZoomEnd: () => {} });
```

Expected:
- 第 1 步返回的坐标与 `{x:400, y:300}` 相差不超过 1 px
- 第 2 步注册后，拖动地图与滚轮缩放时控制台持续打印 `view changed`
- **极端缩放**：滚轮缩到最近（约 z20）与最远（约 z3），重复第 1 步，两次都必须同样自洽（这一步专门验 `metersPerPixel` 的除零安全，Task 8 会真正用到）
- 切到「新版」「卫星」档，再重复第 2 步，拖动仍持续打印（验证切档重绑）

- [ ] **Step 5: 提交**

```bash
git add web/static/js/map_adapter_leaflet.js web/static/js/map_adapter_amap.js web/static/js/map_engine.js
git commit -m "web: 地图适配器新增容器像素换算与视野变化钩子，MapEngine 转发并支持切档重绑"
```

---

### Task 8: 图形层骨架——渲染、视野同步、选中

**Files:**
- Create: `web/static/js/shape_layer.js`
- Modify: `web/templates/track_editor.html`（补上 `shape_layer.js` 的 `<script>`，插在上一行 `shape_geometry.js` 之后）
- Modify: `web/static/css/track_editor.css`（追加图形层样式）
- Modify: `web/static/js/track_editor.js`（init 里调用 `ShapeLayer.init()`）

**Interfaces:**
- Consumes: `shape_geometry.js` 全家（全局函数）、`MapEngine.latLngToContainer` / `containerToLatLng` / `bindViewHooks`、全局常量 `TRACK_ACCENT`
- Produces 全局对象 `ShapeLayer`：
  - `init() -> void` —— 注入 SVG、注册视野钩子与键盘，必须在 `MapEngine.init()` 之后调用
  - `add(type) -> string` —— 在当前地图中心放置默认图形，返回新 id，并选中它
  - `addAt(type, center) -> string`
  - `remove(id) -> void`
  - `clear() -> void`
  - `select(id) -> void`（传 `null` 取消选中）
  - `selectedId() -> string|null`
  - `shapes() -> shape[]`（副本）
  - `spacing() -> number` / `setSpacing(meters) -> void`
  - `generatePoints() -> {lat,lng}[]` —— 各图形依次 `shapeToLoop` 拼接
  - `redraw() -> void`
  - `onChange(cb) -> void` —— 图形集合或选中项变化时回调（侧边栏 chip 列表同步用）

- [ ] **Step 1: 写 CSS**

在 `web/static/css/track_editor.css` 末尾追加：

```css
/* ============================================================
   图形模板覆盖层 —— .map-stage 的兄弟图层，天然盖住两个地图容器
   pointer-events 默认穿透，只有图形本体与手柄自己开启
   ============================================================ */
.shape-layer {
    position: absolute;
    inset: 0;
    z-index: 500;              /* 高于两个地图容器，低于 .search-box / .basemap-switch 的 1000 */
    pointer-events: none;
    overflow: hidden;          /* 图形被拖出视口时不撑出滚动条 */
}
.shape-layer svg { display: block; }
.shape-layer.is-hidden { opacity: 0; }   /* Leaflet 缩放动画期间遮挡，见 shape_layer.js */

.shape-outline {
    fill: rgba(59, 91, 215, .06);
    stroke: var(--accent);
    stroke-width: 2;
    stroke-dasharray: none;
    vector-effect: non-scaling-stroke;
    pointer-events: auto;
    cursor: move;
}
.shape-outline.selected {
    stroke-width: 2.5;
    fill: rgba(59, 91, 215, .1);
}
.shape-frame {
    fill: none;
    stroke: var(--accent);
    stroke-width: 1;
    stroke-dasharray: 4 4;
    opacity: .55;
    pointer-events: none;
}

.shape-preview-line {
    fill: none;
    stroke: rgba(59, 91, 215, .35);
    stroke-width: 1.5;
    stroke-dasharray: 5 5;
    pointer-events: none;
}
.shape-preview-dot {
    fill: #fff;
    stroke: var(--accent);
    stroke-width: 2;
    pointer-events: none;
}
.shape-preview-start {
    fill: var(--accent);
    stroke: #fff;
    stroke-width: 2;
    pointer-events: none;
}

.shape-handle {
    fill: #fff;
    stroke: var(--accent);
    stroke-width: 2;
    pointer-events: auto;
}
.shape-handle-rot {
    fill: #fff;
    stroke: var(--accent);
    stroke-width: 2;
    pointer-events: auto;
    cursor: grab;
}
.shape-handle-rot:active { cursor: grabbing; }
.shape-rot-line {
    stroke: var(--accent);
    stroke-width: 1.5;
    pointer-events: none;
}
```

- [ ] **Step 2: 写图形层骨架**

创建 `web/static/js/shape_layer.js`：

```js
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
    const ROTATE_HANDLE_PX = 28;    // 旋转手柄距离包围盒上边的像素距离（缩放不变）

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

    // 舞台像素 → 相对图形中心的「东西/北向」偏移（米）
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

    // ---------- 渲染 ----------

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

    function buildOutline(g, shape, centerPx) {
        const prims = shapeOutlines(shape);
        const pts = [];
        prims.forEach((p) => {
            pts.push(localToStage(shape, centerPx, p.from.x, p.from.y));
        });
        // 用折线逼近圆弧：圆弧按每 5 度采样，视觉上足够平滑
        prims.forEach((p) => {
            if (p.kind !== 'arc') return;
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

    // 8 方向缩放手柄光标，按屏幕角度每 45 度一档
    const RESIZE_CURSORS = ['e-resize', 'se-resize', 's-resize', 'sw-resize',
        'w-resize', 'nw-resize', 'n-resize', 'ne-resize'];

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
        },

        add(type) {
            const c = MapEngine.containerToLatLng(stageCenterPx().x, stageCenterPx().y);
            return this.addAt(type, c);
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
```

- [ ] **Step 3: 补上脚本标签并在 init 里挂上**

把 `web/templates/track_editor.html` 里的：

```html
    <script src="/static/js/shape_geometry.js"></script>
    <script src="/static/js/track_editor.js"></script>
```

改为：

```html
    <script src="/static/js/shape_geometry.js"></script>
    <script src="/static/js/shape_layer.js"></script>
    <script src="/static/js/track_editor.js"></script>
```

在 `web/static/js/track_editor.js` 的 init 中，`initSearchBox();` 之后加一行：

```js
    initSearchBox();
    ShapeLayer.init();   // 图形覆盖层：必须在 MapEngine.init() 之后（依赖活跃适配器的像素换算）
```

- [ ] **Step 4: 浏览器控制台验证渲染与视野同步**

Run: `python app.py`，打开 `http://127.0.0.1:5000/editor?track=east_campus_stadium`，F12 控制台：

```js
// 1) 放一个操场，应看到轮廓 + 一圈预览点 + 8 个方块手柄 + 旋转手柄
ShapeLayer.add('stadium');

// 2) 默认操场点数应为 38
ShapeLayer.generatePoints().length;

// 3) 放一个矩形，两个图形之间应出现一条跨越的连接虚线
ShapeLayer.add('rect');
ShapeLayer.generatePoints().length;      // 期望 38 + 32 = 70

// 4) 选中第二个图形，手柄只画在它身上
ShapeLayer.select(ShapeLayer.shapes()[1].id);
```

Expected:
- 图形轮廓是主题色描边 + 淡蓝填充，预览点是白底蓝圈的小圆，**第一个点是实心蓝点**（起点标记）
- 两个图形之间有一条虚线连接段（多图形拼接的可见反馈）
- 手柄是 8 个白色小方块 + 上方的旋转圆点与引线
- **拖动地图**：图形跟着地图一起移动，且不闪烁、不抖动
- **滚轮缩放**：图形跟手缩放；缩放动画的 250 ms 内图形层短暂消失，动画结束立刻回来（不能出现「先漂移再跳回」）
- **缩到最近 z20 与最远 z3**：图形定位都正确，手柄仍是同样大小（不随缩放变大变小）——这一步验证 `computeScale()` 没有除零、`vector-effect` 生效
- 切到「新版」「卫星」档：图形仍在正确位置（不漂移）

- [ ] **Step 5: 跑测试并提交**

Run: `python -m pytest -q`
Expected: PASS

```bash
git add web/static/js/shape_layer.js web/static/css/track_editor.css web/static/js/track_editor.js web/templates/track_editor.html
git commit -m "web: 新增图形覆盖层，渲染轮廓/预览点/变换手柄并跟随地图视野"
```

---

### Task 9: 指针交互——移动、缩放、旋转

**Files:**
- Modify: `web/static/js/shape_layer.js`（新增交互模块，并在 `init()` 里绑定）

**Interfaces:**
- Consumes: `resizeShape`、`rotationFromPointer`、`unprojectLocal`、`projectLocal`、`M_PER_DEG_LAT`、`mPerDegLng`（shape_geometry.js）；本文件的 `stageToOffset`、`shapeCenterPx`、`localToStage`、`rebuild`
- Produces: 无新公开 API（纯交互增强）。行为契约：拖图形本体 = 移动；拖 8 个方块 = 按锚点缩放；拖旋转圆点 = 旋转；点图形 = 选中；点地图空白 = 取消选中；`Esc` 取消选中；`Delete`/`Backspace` 删除选中图形

- [ ] **Step 1: 加入交互状态与指针处理**

在 `web/static/js/shape_layer.js` 里，`// ---------- 渲染 ----------` 之前插入：

```js
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

        if (key === 'rotate') {
            // 记下按下瞬间的指针方位：用户可能抓在旋转圆点的任意位置，
            // 用它作为基准才能保证按下不跳转（rotationFromPointer 的第三个参数）
            drag = {
                mode: 'rotate', shapeId: id, key, snapshot: { ...shape, center: { ...shape.center } },
                grabLocal: null, grabBearing: Math.atan2(offset.y, offset.x) - shape.rotation
            };
        } else if (key) {
            drag = {
                mode: 'resize', shapeId: id, key, snapshot: { ...shape, center: { ...shape.center } },
                grabLocal: null, grabBearing: null
            };
        } else {
            drag = {
                mode: 'move', shapeId: id, key: null, snapshot: { ...shape, center: { ...shape.center } },
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
            try { evt.target.releasePointerCapture(evt.pointerId); } catch (e) { /* 指针已释放，忽略 */ }
        }
    }

    // 点地图空白取消选中：ShapeLayer 自身的 SVG 只覆盖有图形的区域，
    // 点在空白处时事件落到地图容器上，由 track_editor.js 的 onMapClick 转达
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
```

- [ ] **Step 2: 在 init 里绑定这些处理器**

把 `init()` 改为：

```js
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
```

- [ ] **Step 3: 把它接到「点空白取消选中」的回调上**

在 `web/static/js/track_editor.js` 里把 `HANDLERS.onMapClick` 的空实现改为：

```js
    onMapClick() {
        // 加点已改由 onMapMouseDown 承担：click 在按下后移动（地图拖动平移）时被引擎抑制，
        // 会导致"按住左键稍一动点就丢"；这里保留空实现避免适配器侧再加一条加点路径
        //
        // 借这个已在两个适配器接好的回调做「点地图空白取消选中图形」：
        // 图形层 SVG 只在有图形的地方开启 pointer-events，点空白处事件落到地图容器上
        ShapeLayer.select(null);
    },
```

- [ ] **Step 4: 浏览器逐项手验交互**

Run: `python app.py`，打开 `http://127.0.0.1:5000/editor`，F12 控制台 `ShapeLayer.add('stadium')` 后逐项操作：

Expected:
- **移动**：按住轮廓拖动，图形跟手平移，预览点同步重排；松手后手柄框贴合轮廓
- **锚点缩放**：拖右下角方块向右下 → **左上角位置纹丝不动**，图形向右下长大。这是 Word 手感的核心，必须逐向验一遍（8 个手柄各拖一次）
- **拖过锚点**：把右边中点一路拖到左边界之外 → 图形翻转，宽高不为负，不崩
- **尺寸下限**：把图形拖到极小 → 停在下限（肉眼约 5 m，即缩放到 z19 时约 100 px），不会塌成一点或消失
- **圆形锁定**：放一个圆形，任意拖一个手柄 → 始终是正圆，不会变椭圆
- **操场退化**：把操场纵向拉到很高 → 直道收成 0，退化成圆，不出现负直道
- **旋转**：拖旋转圆点绕中心转，图形与手柄一起转，**按下瞬间不跳**；转到任意角度后再拖缩放，锚点仍然固定
- **旋转后光标方向正确**：把图形转到 90° 左右，再把鼠标依次悬停到 8 个手柄上——光标方向应跟着图形一起转（原来指东的手柄现在显示南北向光标），不是永远指同一边
- **选中**：点第一个图形 → 手柄移到它身上；点第二个图形 → 手柄跟过去
- **取消选中**：点地图空白处 → 手柄消失；`Esc` 同样
- **删除**：选中后按 `Delete` → 图形消失，预览点同步减少
- **画笔不冲突**：切到「画笔」模式，拖动手柄与轮廓 → **不会加点**；在地图空白处点击 → 正常加点
- **拖到视口外**：把图形拖到画布外（一半或全部出界）→ 不出现滚动条、不撑破布局；再把露出的部分拖回视口内能救回来（若全部出界无法救回，用 `Esc` + `ShapeLayer.clear()` 重置，属于可接受的已知限制）

- [ ] **Step 5: 跑测试并提交**

Run: `python -m pytest -q`
Expected: PASS

```bash
git add web/static/js/shape_layer.js web/static/js/track_editor.js
git commit -m "web: 图形层支持拖动、锚点缩放与旋转，键盘删除与空白取消选中"
```

---

### Task 10: 侧边栏图形模板区块

**Files:**
- Modify: `web/templates/track_editor.html:124-140`（右面板「加载轨迹」区块之后插入新区块）
- Modify: `web/static/css/track_editor.css`（追加区块样式）
- Modify: `web/static/js/track_editor.js`（放置按钮、chip 列表、间距输入接线）

**Interfaces:**
- Consumes: `ShapeLayer.add/remove/select/shapes/selectedId/onChange/spacing/setSpacing`（Task 8）、`showMessage`（track_editor.js 已有）
- Produces: DOM id 契约，供后续任务与手验使用：`shape-btn-rect`、`shape-btn-circle`、`shape-btn-stadium`、`shape-list`、`shape-spacing`、`shape-generate-btn`、`shape-clear-btn`

- [ ] **Step 1: 插入侧边栏区块**

在 `web/templates/track_editor.html` 的「加载轨迹」`</section>` 之后、「统计」`<section>` 之前插入：

```html
                <!-- 图形模板：点选即在地图中心放置，可拖动/缩放/旋转，确认后生成轨迹点 -->
                <section class="panel-sec">
                    <div class="group-label">图形模板 SHAPES</div>
                    <div class="shape-picker">
                        <button type="button" id="shape-btn-rect" class="shape-btn" title="矩形：点一下在地图中心放置">
                            <svg viewBox="0 0 36 24" aria-hidden="true"><rect x="2" y="2" width="32" height="20" rx="1"></rect></svg>
                            <span>矩形</span>
                        </button>
                        <button type="button" id="shape-btn-circle" class="shape-btn" title="圆形：点一下在地图中心放置">
                            <svg viewBox="0 0 36 24" aria-hidden="true"><circle cx="18" cy="12" r="10"></circle></svg>
                            <span>圆形</span>
                        </button>
                        <button type="button" id="shape-btn-stadium" class="shape-btn" title="操场形：两边半圆中间矩形，点一下在地图中心放置">
                            <svg viewBox="0 0 36 24" aria-hidden="true"><path d="M10 2h16a10 10 0 0 1 0 20H10a10 10 0 0 1 0-20z"></path></svg>
                            <span>操场</span>
                        </button>
                    </div>
                    <ul id="shape-list" class="shape-list"></ul>
                    <div class="form-group">
                        <label for="shape-spacing">点间距（米）</label>
                        <input type="number" id="shape-spacing" value="10" min="3" max="100" step="1">
                    </div>
                    <div class="btn-group">
                        <button type="button" id="shape-generate-btn" class="btn btn-primary" disabled>生成轨迹点</button>
                        <button type="button" id="shape-clear-btn" class="btn btn-secondary" disabled>清空图形</button>
                    </div>
                    <p class="hint">点图形即在地图中心放置；拖动移动、拖手柄缩放、拖上方圆点旋转。调整到位后点「生成轨迹点」写入轨迹；多个图形会按放置顺序串成一条环线。</p>
                </section>
```

- [ ] **Step 2: 加了样式**

在 `web/static/css/track_editor.css` 末尾追加：

```css
/* ============================================================
   侧边栏图形模板区块
   ============================================================ */
.shape-picker {
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    gap: 6px;
    margin-bottom: 10px;
}
.shape-btn {
    display: flex; flex-direction: column; align-items: center; gap: 4px;
    padding: 8px 4px;
    background: var(--surface);
    border: 1px solid var(--border-2); border-radius: var(--radius-sm);
    color: var(--text-2);
    font-size: 11px;
    cursor: pointer;
    transition: border-color .12s, color .12s, background .12s;
}
.shape-btn svg { width: 100%; height: 24px; }
.shape-btn svg rect,
.shape-btn svg circle,
.shape-btn svg path {
    fill: rgba(59, 91, 215, .08);
    stroke: currentColor;
    stroke-width: 1.5;
}
.shape-btn:hover { border-color: var(--accent); color: var(--accent); background: var(--accent-dim); }
.shape-btn:active { background: var(--surface-2); }

.shape-list {
    list-style: none;
    display: flex; flex-wrap: wrap; gap: 4px;
    margin: 0 0 10px;
}
.shape-list:empty { display: none; }
.shape-chip {
    display: inline-flex; align-items: center; gap: 5px;
    padding: 3px 5px 3px 8px;
    background: var(--surface-2);
    border: 1px solid var(--border); border-radius: 999px;
    font-family: var(--mono); font-size: 10.5px;
    color: var(--text-2);
    cursor: pointer;
    transition: border-color .12s, color .12s;
}
.shape-chip:hover { border-color: var(--accent); color: var(--text); }
.shape-chip.active { border-color: var(--accent); color: var(--accent); background: var(--accent-dim); }
.shape-chip-del {
    display: flex; align-items: center; justify-content: center;
    width: 14px; height: 14px;
    border: none; border-radius: 50%;
    background: transparent;
    color: var(--text-3);
    font-size: 12px; line-height: 1;
    cursor: pointer;
    transition: background .12s, color .12s;
}
.shape-chip-del:hover { background: var(--danger); color: #fff; }
```

- [ ] **Step 3: 接线**

在 `web/static/js/track_editor.js` 里，`// ===== 保存 =====` 之前插入：

```js
// ===== 图形模板 =====
const SHAPE_TYPE_LABEL = { rect: '矩形', circle: '圆形', stadium: '操场' };

// chip 文案：矩形显示宽高，圆形显示半径，操场显示直道与半径
function shapeChipText(shape) {
    if (shape.type === 'rect') return `矩形 ${Math.round(shape.width)}×${Math.round(shape.height)}`;
    if (shape.type === 'circle') return `圆形 R${Math.round(shape.width / 2)}`;
    return `操场 直道${Math.round(shape.width - shape.height)}/R${Math.round(shape.height / 2)}`;
}

// 重建 chip 列表与按钮可用态（形状数量或选中项变化时调用）
function renderShapePanel() {
    const list = document.getElementById('shape-list');
    const shapes = ShapeLayer.shapes();
    const selectedId = ShapeLayer.selectedId();

    // 用 DOM API 构建，chip 文案不进 innerHTML
    list.replaceChildren();
    shapes.forEach((shape) => {
        const li = document.createElement('li');
        li.className = 'shape-chip' + (shape.id === selectedId ? ' active' : '');
        li.dataset.shapeId = shape.id;

        const label = document.createElement('span');
        label.textContent = shapeChipText(shape);
        li.appendChild(label);

        const del = document.createElement('button');
        del.type = 'button';
        del.className = 'shape-chip-del';
        del.dataset.shapeId = shape.id;
        del.title = '删除该图形';
        del.textContent = '×';
        li.appendChild(del);

        list.appendChild(li);
    });

    const hasShapes = shapes.length > 0;
    document.getElementById('shape-generate-btn').disabled = !hasShapes;
    document.getElementById('shape-clear-btn').disabled = !hasShapes;
}

function handleShapeGenerate() {
    const shapes = ShapeLayer.shapes();
    if (!shapes.length) return;
    const generated = ShapeLayer.generatePoints();

    if (points.length > 0) {
        const ok = window.confirm(
            `将从 ${shapes.length} 个图形生成 ${generated.length} 个轨迹点，替换当前 ${points.length} 个点？`);
        if (!ok) return;
    }
    pushUndo();
    points = generated.map((p) => ({ lat: p.lat, lng: p.lng }));
    renderTrack();
    showMessage(`已从 ${shapes.length} 个图形生成 ${points.length} 个轨迹点`, 'success');
}

// chip 列表事件委托：点 chip 选中，点 × 删除
document.getElementById('shape-list').addEventListener('click', (e) => {
    const del = e.target.closest('.shape-chip-del');
    if (del) {
        ShapeLayer.remove(del.dataset.shapeId);
        return;
    }
    const chip = e.target.closest('.shape-chip');
    if (chip) ShapeLayer.select(chip.dataset.shapeId);
});

['rect', 'circle', 'stadium'].forEach((type) => {
    document.getElementById('shape-btn-' + type).addEventListener('click', () => {
        ShapeLayer.add(type);
    });
});

document.getElementById('shape-spacing').addEventListener('change', (e) => {
    const raw = Number(e.target.value);
    ShapeLayer.setSpacing(raw);
    e.target.value = ShapeLayer.spacing();   // 回写被夹紧后的实际值
});

document.getElementById('shape-generate-btn').addEventListener('click', handleShapeGenerate);
document.getElementById('shape-clear-btn').addEventListener('click', () => ShapeLayer.clear());

ShapeLayer.onChange(renderShapePanel);
```

在 `web/static/js/track_editor.js` 的 `init()` 里，`ShapeLayer.init();` 之后加一行：

```js
    ShapeLayer.init();   // 图形覆盖层：必须在 MapEngine.init() 之后（依赖活跃适配器的像素换算）
    renderShapePanel();  // 初始化侧边栏图形区块的按钮可用态
```

- [ ] **Step 4: 浏览器手验侧边栏**

Run: `python app.py`，打开 `http://127.0.0.1:5000/editor`：

Expected:
- 右面板在「加载轨迹」与「统计」之间出现「图形模板 SHAPES」区块，三个按钮显示可辨认的矩形/圆形/操场缩略图
- 三个按钮初始不可用的「生成轨迹点」「清空图形」是灰的
- 点「操场」→ 地图中心出现操场并自动选中，chip 出现并高亮，两个按钮变可点
- 点「矩形」→ chip 出现第二个条目，两个图形串成一条环线（能看到中间连接虚线段）
- 点第一个 chip → 手柄跳到第一个图形上
- 点 chip 上的 × → 该图形消失，chip 消失，预览点同步减少
- 「点间距」改成 5 → 预览点立刻变密一倍；改成 0.5 → 回写成 3（夹紧下限）；改成 9999 → 回写成 100
- 「清空图形」→ 图形与 chip 全部清空，两个按钮回到禁用

- [ ] **Step 5: 跑测试并提交**

Run: `python -m pytest -q`
Expected: PASS

```bash
git add web/templates/track_editor.html web/static/css/track_editor.css web/static/js/track_editor.js
git commit -m "web: 侧边栏新增图形模板区块（三种图形、图形列表、点间距、生成/清空）"
```

---

### Task 11: 生成轨迹点与生命周期清理

**Files:**
- Modify: `web/static/js/track_editor.js`（`handleNew` / `loadTrackById` 清空图形；顶栏与提示文案）

**Interfaces:**
- Consumes: `ShapeLayer.clear()`（Task 8）、`handleShapeGenerate`/`pushUndo`/`points`/`renderTrack`（track_editor.js 已有）
- Produces: 无新 API。行为契约：`新建空白` 与 `加载到地图` 都会清空图形层；生成不改变 `editingTrackId` 与 `activeCorrection`

- [ ] **Step 1: 在两条入口处清空图形**

把 `web/static/js/track_editor.js` 的 `handleNew()` 改为：

```js
// ===== 新建空白 =====
function handleNew() {
    points = [];
    editingTrackId = null;
    activeCorrection = defaultCorrection;
    document.getElementById('track-id').value = '';
    document.getElementById('track-name').value = '';
    document.getElementById('track-desc').value = '';
    ShapeLayer.clear();   // 清掉残留的图形层，避免"空白画布上还浮着一个操场"
    clearHistory();
    renderTrack();
    updateCorrectionNote();
}
```

在 `loadTrackById(id)` 的成功分支里，`clearHistory();` 之前加一行：

```js
        ShapeLayer.clear();   // 换轨迹时清掉上一个轨迹留下的图形层
        clearHistory();
```

- [ ] **Step 2: 更新地图左下角操作提示**

把 `.map-hint` 那段文案：

```html
                <div class="map-hint">默认<b>拖动</b>平移；「<b>画笔</b>」点击加点（地图锁定，平移请切回拖动）；「<b>橡皮擦</b>」点击顶点删点；顶点可拖动；线段中点小圆插点</div>
```

改为：

```html
                <div class="map-hint">默认<b>拖动</b>平移；「<b>画笔</b>」点击加点（地图锁定，平移请切回拖动）；「<b>橡皮擦</b>」点击顶点删点；顶点可拖动；线段中点小圆插点；右栏可放<b>图形模板</b></div>
```

- [ ] **Step 3: 浏览器手验生成与生命周期**

Run: `python app.py`，打开 `http://127.0.0.1:5000/editor`：

Expected:
- 点「操场」→ 拖到合适位置与大小 → 点「生成轨迹点」→ 轨迹点出现在地图上（与预览点同位置），「点数 POINTS」显示 38，「环线总距离 LOOP」显示约 **398 m**
- 生成后图形层**仍然存在**（手柄、轮廓、预览点都还在），便于继续微调后再生成一次
- **用画笔手画几个点，再点「生成轨迹点」** → 弹出确认框，文案形如「将从 1 个图形生成 38 个轨迹点，替换当前 4 个点？」→ 取消则什么都不变；确认则整体替换
- 生成后立刻 `Ctrl+Z` → **轨迹点回到替换前的手画点，且图形层仍在**（图形编辑不进撤销栈）
- 再 `Ctrl+Shift+Z` → 回到生成结果
- 点「新建空白」→ 图形层与 chip 全部清空，画布与右栏一起回到空态
- 先放一个图形，再从下拉框「加载到地图」加载 `east_campus_stadium` → 图形层清空、轨迹加载、距离读数 439.4 m
- **切底图档位**（经典/新版/卫星）→ 图形层位置不漂移、手柄仍在

- **生成不动保存目标**（spec §6）：先「加载到地图」加载 `east_campus_stadium`，再用图形重画并「生成轨迹点」，然后直接点「保存轨迹」——应提示「轨迹 east_campus_stadium 已存在，覆盖保存？」，即 `editingTrackId` 仍指向被加载的轨迹，没有被生成动作清成「新建」。取消保存，避免真的覆盖仓库里的示例轨迹。

- [ ] **Step 4: 跑测试并提交**

Run: `python -m pytest -q`
Expected: PASS

```bash
git add web/static/js/track_editor.js web/templates/track_editor.html
git commit -m "web: 新建/加载轨迹时清空图形层，补全操作提示"
```

---

### Task 12: 端到端验收

**Files:**
- 无代码改动（纯验收）

**Interfaces:**
- Consumes: 前 11 个任务的全部产出
- Produces: 验收结论；若发现缺陷则回到对应任务修复后重跑本任务

- [ ] **Step 1: 全量测试**

Run: `python -m pytest -q`
Expected: PASS，全绿；若本机有 Node，几何用例数应为 55（无 Node 时该组自动跳过，其余用例仍须全绿）

- [ ] **Step 2: 存一条图形轨迹并检验下游吃不吃得下**

Run: `python app.py`，浏览器打开 `http://127.0.0.1:5000/editor`：

1. 点「操场」，把「点间距」调到 **3**（最小值，逼近上限）
2. 反复点「操场」放 12 个图形（每个默认周长 398 m / 间距 3 m → 每图形约 133 点，合计约 1600 点；封顶是逐图形各 500 点，故这里不会触发）
3. 把 ID 填 `shape_smoke`、名称填 `图形模板冒烟`，点「保存轨迹」

Expected:
- 保存成功，提示形如 `已保存 .../config/tracks/shape_smoke.json（环线 ... km）`
- 侧边栏不卡死（生成与保存都在 2 秒内完成）

- [ ] **Step 3: 用 CLI 跑通下游链路**

Run（`single` 子命令 `--date` 与 `--distance` 都是必填；输出目录用 gitignore 覆盖的 `output/`）：

```bash
python main.py single --track shape_smoke --date 2026-10-13 --distance 3 --output-dir output/shape_smoke
ls output/shape_smoke
```

Expected:
- `single` 正常完成，不报错
- 输出目录里有生成的 FIT 文件（默认格式）
- 这一步专门验证高点数图形轨迹能被 `TrackAnalyzer`、生成器与导出器正常处理（Review Focus 第 5 条）

- [ ] **Step 4: 清理冒烟产物**

Run:

```bash
rm -f config/tracks/shape_smoke.json
rm -rf output/shape_smoke
git status --short
```

Expected: `git status --short` 只剩本次功能改动的文件，没有 `shape_smoke.json` 等临时产物（`output/` 已被 .gitignore 覆盖）

- [ ] **Step 5: 对照 spec §十 逐条验收**

打开 `docs/superpowers/specs/2026-10-13-track-shape-presets-design.md` 的「十、验收口径」，逐条在浏览器里现场确认：

1. 三种图形都能一键放置，并能拖动 / 8 向缩放 / 旋转
2. 图形层始终盖在底图与轨迹之上；拖手柄不会误加点
3. 调整图形大小时预览点数随之变化，密度约 10 m 一点
4. 操场默认尺寸生成 ≈ 400 m 环线（实为 398.1 m / 38 点），与右下角距离读数一致
5. 生成轨迹点后保存的 JSON 与手画轨迹结构完全一致，可直接用于生成跑步数据（Step 3 已验证）
6. 切底图四档、缩放、平移时图形与地图贴合无漂移

Expected: 六条全部通过。任何一条不通过 → 记录复现步骤，回到对应任务修复并重跑本任务。

- [ ] **Step 6: 提交（若验收中发现并修复了问题）**

```bash
git status --short
# 若无改动则跳过本步
git add -A
git commit -m "web: 图形模板端到端验收修复"
```
