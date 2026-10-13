# 轨迹编辑器图形模板设计文档

- 日期：2026-10-13
- 分支：`feat/track-shape-presets`（基于 `main` @ `e9df749`）
- 状态：待用户审阅

## 背景

轨迹编辑器（`/editor`）目前只能靠画笔逐点点击或从磁盘加载已有轨迹来产生一条环线。画一个标准的操场跑道需要点 40 次，且很难画得圆；画矩形/圆形更是几乎不可能画准。

需要给编辑器补一个**图形模板**能力：侧边栏点选现成图形（矩形 / 圆形 / 操场形），图形出现在地图上并可按 Word 图片的方式拖动、缩放、旋转，调整过程中实时显示将要生成的点，确认后一次性写入轨迹。

## 目标

- 侧边栏提供 矩形 / 圆形 / 操场形 三种模板，点击即在地图中心放置
- 图形可拖动、缩放、旋转，手柄手感对齐 Word 图片调整
- 图形轮廓上实时预打点，**点数随图形尺寸自动变化**
- 图形层始终位于两个地图引擎与全部地图 UI 之上
- 生成的轨迹点与手画点无差别，密度对齐现有轨迹（9–18 m/点）

## 非目标

- 不做吸附、对齐、等距阵列
- 不做旋转角度的数值输入框（只用鼠标手柄）
- 不做图形的落盘持久化（图形仅是编辑期辅助，不写入轨迹 JSON）
- 不做椭圆、多边形、折线等更多图形
- 不改 `renderTrack`、顶点编辑、导出链路、后端与 CLI

## 已确认决策

| # | 决策 | 结论 |
|---|---|---|
| 1 | 图形与轨迹点的关系 | **独立对象 + 生成按钮**：图形可叠加多个，点「生成轨迹点」才写入 `points` |
| 2 | 点密度规则 | **按周长/间距**，默认 10 m，侧边栏可调（3–100 m） |
| 3 | 已有手画点时的生成行为 | **替换**，先 `confirm`，替换前 `pushUndo()`，可 Ctrl+Z |
| 4 | 渲染方式 | **DOM/SVG 覆盖层**，两个引擎共用一套几何与交互代码 |
| 5 | 图形可用范围 | 新建与编辑已有轨迹时都可用 |
| 6 | 「预加载」的含义 | 侧边栏提供三种现成图形；**不是**「新建空白」后自动放置图形 |

## 一、模块结构

```
web/static/js/shape_geometry.js   新增  纯函数，无 DOM / 无地图依赖，可在 Node 下单测
web/static/js/shape_layer.js      新增  SVG 覆盖层：渲染、手柄、拖动/缩放/旋转、视野同步
web/static/js/track_editor.js     修改  侧边栏接线、生成轨迹点、生命周期清理
web/templates/track_editor.html   修改  侧边栏新区块 + script 标签
web/static/css/track_editor.css   修改  图形层、手柄、侧边栏 chip 样式
web/static/js/map_engine.js       修改  转发坐标换算 + bindViewHooks + 切档重绘
web/static/js/map_adapter_leaflet.js  修改  3 个方法
web/static/js/map_adapter_amap.js     修改  3 个方法
tests/js/test_shape_geometry.js   新增  Node 单测用例
tests/test_shape_geometry.py      新增  pytest 驱动 Node（无 Node 时跳过）
```

分层原则：**几何与打点全部在 `shape_geometry.js`（纯函数，可测）；DOM 与指针交互全部在 `shape_layer.js`；`track_editor.js` 只做接线**，不出现图形数学。

`shape_geometry.js` 对浏览器与 Node 双用：对外挂全局对象（供 `shape_layer.js` / `track_editor.js` 以 `<script>` 顺序引用），末尾加 `if (typeof module !== 'undefined') module.exports = {...}` 守卫（供 Node 单测 require）。导出：`EARTH_RADIUS_M`、`M_PER_DEG_LAT`、`MIN_DIM_M`、`MIN_SPACING`、`MAX_SPACING`、`MAX_POINTS`、`haversineMeters`、`mPerDegLng`、`projectLocal`、`unprojectLocal`、`localToGeo`、`lockDims`、`normalizeShape`、`makeDefaultShape`、`primitiveLength`、`primitivePoint`、`shapeOutlines`、`shapePerimeter`、`shapeToLoop`、`handlePositions`、`HANDLE_OPPOSITE`、`ROTATE_HANDLE_ANGLE`、`rotationFromPointer`、`resizeShape`。

**手柄几何也在本模块**（`handlePositions` / `resizeShape` / `rotationFromPointer`）——它们是纯 2D 数学，不碰 DOM，因此同样走 Node 单测；`shape_layer.js` 只负责像素换算与指针事件接线。

## 二、几何模型

### 2.1 数据模型

三种图形统一成一个模型，存于 `shape_layer.js` 的模块级数组 `shapes[]`：

```js
{
  id: string,                    // 唯一 id（放置时生成）
  type: 'rect' | 'circle' | 'stadium',
  center: { lat, lng },          // 地理锚点，唯一真源
  width: number,                 // 米，局部包围盒 x 向
  height: number,                // 米，局部包围盒 y 向
  rotation: number               // 弧度，逆时针为正，0 = 局部 +x 指向正东
}
```

- **矩形**：`w × h` 两轴自由。轮廓即包围盒。
- **圆形**：锁定 `w = h = 2R`（正圆，非椭圆），包围盒内切。
- **操场**：`w = L + 2R`，`h = 2R`，`L` = 直道长，`R` = 弯道半径。即「左右两个半圆 + 中间矩形」。`L` 夹紧到 ≥ 0（`L = 0` 时退化为圆）。

### 2.2 默认尺寸

默认值刻意对齐真实场地，周长落在现有轨迹 363–440 m 区间内：

| 图形 | 默认尺寸 | 周长 |
|---|---|---|
| 操场 | 直道 `L = 84.39 m`，半径 `R = 36.5 m` | **398.1 m**（标准 400 m 田径场内道） |
| 矩形 | `100 m × 60 m` | 320 m |
| 圆形 | `R = 60 m` | 377.0 m |

> 设计讨论中曾口头给出「操场 ≈ 40 点」，按 §3.2 的分段取整公式实际为 **38 点**（8 + 11 + 8 + 11）。以公式为准。

### 2.3 常量与单位换算

```js
EARTH_RADIUS_M = 6371000                                  // 与 track_editor.js 的环线统计算口径一致
M_PER_DEG_LAT  = EARTH_RADIUS_M * Math.PI / 180           // ≈ 111194.93 m，常量
// 经度方向随纬度收缩，按图形中心纬度求值（非常量）
mPerDegLng(centerLat) = M_PER_DEG_LAT * max(cos(centerLat), 0.01)

MIN_DIM_M   = 5      // 宽/高（圆为直径）下限
MIN_SPACING = 3      // 间距下限（米）
MAX_SPACING = 100    // 间距上限（米）
MAX_POINTS  = 500    // 单个图形的点数上限（不是整条轨迹：多图形拼接后总数可以超过它）
```

局部坐标 → 经纬度用中心点切平面近似（图形量级 ~100 m，误差可忽略），并复用编辑器既有的 `R = 6371000`，保证生成结果与右下角「环线总距离」读数一致：

```
dLat = ly / M_PER_DEG_LAT
dLng = lx / mPerDegLng(centerLat)
```

### 2.4 局部坐标约定

- 局部原点 = 图形中心；局部 `+x` = 东，局部 `+y` = 北（纬度增大方向）
- `rotation` 逆时针为正
- 旋转：`rx = lx·cosθ − ly·sinθ`，`ry = lx·sinθ + ly·cosθ`
- SVG 像素空间 y 轴朝下，故 `py = centerPx.y − ry·scale`，`scale = 1 / metersPerPixel`
- 指针 → 局部分量（先按像素 y 翻转，再逆旋转）：
  `ux = px − centerPx.x`，`uy = −(py − centerPx.y)`；
  `lx = (ux·cosθ + uy·sinθ) / scale`，`ly = (−ux·sinθ + uy·cosθ) / scale`

## 三、打点规则

### 3.1 轮廓分解为路径基元

三种图形统一按**逆时针**方向分解，各自起点如下表（起点即生成点列的第一个点，被编辑器标记为「起点」）：

| 图形 | 起点 | 基元序列（逆时针） |
|---|---|---|
| 矩形 | `(−w/2, −h/2)`（西南角） | 底边 `(−w/2,−h/2) → (w/2,−h/2)` → 右边 `(w/2,−h/2) → (w/2,h/2)` → 顶边 `(w/2,h/2) → (−w/2,h/2)` → 左边 `(−w/2,h/2) → (−w/2,−h/2)`，共 4 条直线段 |
| 圆形 | `(R, 0)`（正东） | 单个整圆弧，半径 `R`，逆时针扫 `2π` |
| 操场 | `(−L/2, −R)`（左起下） | 底边 `(−L/2,−R) → (L/2,−R)` → 右半圆（圆心 `(L/2,0)`，−90°→+90°） → 顶边 `(L/2,R) → (−L/2,R)` → 左半圆（圆心 `(−L/2,0)`，90°→270°） |

基元结构：`{ kind: 'line' | 'arc', from, to, center?, radius?, startAngle?, sweep? }`。

### 3.2 细分

```
每段：
  len = 直线段长 / 圆弧弧长（= R · |sweep|）
  n   = max(1, round(len / spacing))
  采样参数 t = 0, 1/n, 2/n, …, (n−1)/n   （取 n 个点，不含 t = 1，避免与下一段首点重复）
总点数 N = Σn
```

要点：

- **顶点与切点必然落在点上** —— 矩形四角精确、操场直道与弯道的切点精确，不会切角
- **点数严格随尺寸线性增长**（用户需求「根据图像大小调整点的数量」）
- 每段至少 1 个采样点，`n = 0` 不会出现

### 3.3 点数封顶

```
perimeter = Σ 段长
if (perimeter / spacing > MAX_POINTS):
    spacing = perimeter / MAX_POINTS      // 自动抬高实际间距
```

防止手滑拖出极大图形（或把间距拉到 3 m）导致生成上万点。

### 3.4 多图形拼接

`shapes[]` 按放置顺序拼接成一条闭合点列；**只有单个图形时即为该图形的完整环线**。多个图形之间由预览折线自动连出连接段——预览显示的就是最终结果，图形分开放置会看到一条跨越直线，据此可自行调整位置。预览折线统一绘制整个生成点列（含连接段），不做特例处理。

## 四、覆盖层架构

### 4.1 图层定位与事件隔离

```
.map-stage  (position: relative)
 ├─ #map-leaflet      引擎自身 pane 层级
 ├─ #map-amap
 ├─ .shape-layer      ← 新增，position:absolute; inset:0; z-index:500; pointer-events:none
 ├─ .search-box       z-index:1000
 └─ .basemap-switch / .map-hint / .map-loading
```

- 图形层是地图容器的**兄弟节点**，DOM 层级上天然盖住两个引擎 → 直接满足「调整时位于最顶层」，无需自定义 pane 或 zIndex 调优
- `pointer-events: none` 置于图层，仅图形本体与手柄自身设 `auto`
- **关键收益**：图形上的鼠标事件不会冒泡到 `#map-leaflet` / `#map-amap`，因此拖手柄**不会被画笔工具误判成加点**，也无需改动 `renderTrack` 现有的 `mousedown` 命中检测
- 坐标系对齐不变量：`#map-leaflet`、`#map-amap`、`.shape-layer` 三者均为 `inset: 0`，故适配器返回的容器像素坐标可直接当作图层坐标使用

### 4.2 适配器接口新增

```js
// LeafletAdapter
latLngToContainer(lat, lng) → { x, y }        // map.latLngToContainerPoint
containerToLatLng(x, y)     → { lat, lng }    // map.containerPointToLatLng

// AmapAdapter
latLngToContainer(lat, lng) → { x, y }        // map.lngLatToContainer
containerToLatLng(x, y)     → { lat, lng }    // map.containerToLngLat

// 两者共有：视野变化钩子
bindViewHooks({ onChange, onZoomStart, onZoomEnd })
```

- Leaflet：`map.on('move zoom', onChange)`；`zoomstart → onZoomStart`，`zoomend → onZoomEnd`
- AMap：`map.on('mapmove zoomchange viewchange', onChange)`；`onZoomStart` / `onZoomEnd` 传空实现（AMap 缩放为瞬时切换，无动画遮挡需求）

```js
// MapEngine 转发
latLngToContainer(lat, lng)
containerToLatLng(x, y)
bindViewHooks(hooks)     // 记录 hooks；switchMode 时对新活跃适配器重新绑定并调用一次 onChange
```

### 4.3 视野同步

图形层在 `onChange` 时全量重绘：取图形中心 → `latLngToContainer` 得中心像素 → 反算 `metersPerPixel` → 求 `scale = 1 / metersPerPixel` → 重绘 SVG。

`metersPerPixel` 的求法（避免低缩放下偏移量不足 1 px 导致除零）：

```
a = containerToLatLng(cx, cy)          // 屏幕中心
b = containerToLatLng(cx, cy − 50)     // 屏幕中心以北 50 px
metersPerPixel = haversineMeters(a, b) / 50
```

以 **50 px** 为基准直接反算，任何缩放下都稳定；不需要按 zoom 做自适应偏移。

`haversineMeters` 与 `EARTH_RADIUS_M` 统一由 `shape_geometry.js` 导出，`track_editor.js` 删除本地同名副本改为引用 —— 公式与常量完全一致（R = 6371000，环线含闭合段），是纯去重，不改变「环线总距离」读数。

### 4.4 缩放动画遮挡

Leaflet 滚轮/双击缩放有约 250 ms 动画，动画期间 `latLngToContainerPoint` 仍返回旧 zoom 的值，图形会先漂移再跳回。处理：`onZoomStart` 给 `.shape-layer` 加 `is-hidden`（`opacity: 0`），`onZoomEnd` 移除。用 opacity 而非 `display`，避免重排抖动。

## 五、交互规格

### 5.1 手柄布局

统一 8 个缩放手柄 + 1 个旋转手柄：

| 手柄 | 局部位置 | 行为 |
|---|---|---|
| 4 个角 | `(±w/2, ±h/2)` | 矩形双轴自由；圆形统一改 `R`；操场双轴（`L` 与 `R` 同时变） |
| 4 个边中点 | `(0, ±h/2)`、`(±w/2, 0)` | 单轴：横轴改 `w`，纵轴改 `h` |
| 旋转 | 像素空间，包围盒上边中点沿本地 `+y` 外移 28 px，带引线 | 绕中心旋转 |

按类型换算回尺寸参数：

- 矩形：`w = 2·|lx|`，`h = 2·|ly|`
- 圆形：与矩形/操场统一走**对角锚点 + 包围盒**缩放，再锁定 `w = h`（取较大者）。即拖动时对角手柄固定，圆直径等于约束后的包围盒边长。
  （早先版本的此处写成 `R = √(lx² + ly²)`「圆过指针」，与下方刚加入的锚点语义直接冲突，已废弃：锚点是「像 Word」这一用户可见要求的直接体现，公式版会让对角手柄漂移。）
- 操场：`R = h/2`，`L = w − h`，夹紧 `L ≥ 0`

所有尺寸最后统一夹紧到 `MIN_DIM_M`。

**锚点语义（Word 手感）**：拖动任一手柄时，**对角手柄的地理位置保持不动**，图形向拖动方向生长/收缩（拖过锚点则翻转）。实现为 `resizeShape(snapshot, key, offsetX, offsetY)`：先按锚点求出裁剪前的宽高，再施加类型的尺寸约束（圆锁定、操场 `w ≥ h`），最后用**约束后的**宽高反算中心偏移，保证锚点真的不动。圆形沿用矩形包围盒的 8 个手柄（Word 对圆形图片也是画矩形选择框），不做「手柄落在圆周上」的特例。

手柄与轮廓一起旋转（全部在局部坐标系里算完再旋转平移回像素）。光标按旋转后的方向就近映射到 8 种 resize 光标，旋转手柄用 `grab`。

### 5.2 指针交互

- 拖动图形本体 = 移动（改 `center`，由 `containerToLatLng` 反算）
- 拖动缩放手柄 = 缩放（改 `width` / `height`）
- 拖动旋转手柄 = 旋转（`rotation = atan2(指针相对中心)`，不做角度吸附）
- 拖动中实时重绘预览点
- 单击图形本体 = 选中
- 点地图空白处 = 取消选中。挂载点用 `track_editor.js` 现有的 `HANDLERS.onMapClick`（当前是空实现），在其中调用取消选中；该回调在两个适配器都已接好，无需新增事件通道
- `Esc` 取消选中；`Delete` / `Backspace` 删除选中图形

### 5.3 视觉

- 轮廓：描边 2 px `#3B5BD7`（复用适配器已有的 `TRACK_ACCENT`），填充 `rgba(59,91,215,.06)`
- 选中：轮廓加粗至 2.5 px + 虚拟边框虚线 + 显示手柄；未选中只显示轮廓，无手柄
- 预览点：半径 3.5 px，白底 + 主题色描边的小圆，与轨迹顶点同一视觉语言；起点用实心主题色且半径 5 px 以示区分
- 预览折线：`rgba(59,91,215,.35)` 细线，绘制完整生成点列（含多图形间的连接段）
- 手柄：8 × 8 px 白色方块 + 主题色边框；旋转手柄为半径 6 px 圆形 + 引线

### 5.4 撤销栈边界

**图形编辑不进轨迹撤销栈。** `undoStack` / `redoStack` 仍只存 `points` 快照（语义不变）。「生成轨迹点」时压一次快照，因此 Ctrl+Z 可整体撤销一次生成。图形自身的拖动/缩放/旋转不可撤销。

## 六、侧边栏 UI

置于右侧属性面板「加载轨迹」之后、「统计」之前 —— 即 `新建空白` 之后顺手可用：

```
图形模板 SHAPES
  [▭ 矩形]  [◯ 圆形]  [⬭ 操场]     ← 带 SVG 缩略图的按钮，点击在地图中心放置
  已放置  ▭ 矩形 100×60  [×]        ← chip 列表，点选/删除；支持叠加多个
  点间距  [ 10 ] m                  ← number input，3–100
  [ 生成轨迹点 ]   [ 清空图形 ]
```

- 「生成轨迹点」：若 `points.length > 0`，先 `window.confirm('将从 N 个图形生成 M 个轨迹点，替换当前 K 个点？')`；确认后 `pushUndo()`，再把 `points` 整体替换为生成的点列，最后 `renderTrack()`
- 「生成轨迹点」在无图形时禁用；「清空图形」在无图形时禁用
- 「生成轨迹点」只改 `points`，**不动 `editingTrackId` / `activeCorrection`** —— 加载已有轨迹后用图形重画，保存仍覆盖原轨迹，与编辑器既有语义一致（坐标修正是轨迹属性，保存时统一应用）
- 消息提示复用现有 `showMessage()`

## 七、生命周期与边界

| 场景 | 行为 |
|---|---|
| 点图形按钮 | 在当前地图中心放置该图形，默认尺寸，自动选中 |
| `新建空白` | 清空 `shapes` 并重绘（避免残留图形层误导） |
| `加载到地图` | 清空 `shapes` 并重绘 |
| 切换底图档位 | 重绘（`MapEngine.switchMode` 内触发 `onChange`） |
| `MapEngine.init` 未完成 | 图形层不渲染（无活跃适配器可换算），init 完成后即可用 |
| 官方档无 Key / 未加载 | 图形层独立于引擎，Leaflet 三档照常可用 |
| 拖到尺寸下限 | 夹紧到 `MIN_DIM_M = 5 m`，不塌成一点 |
| 极多点数 | 自动抬高间距，把**单个图形**封顶在 `MAX_POINTS = 500`；多图形拼接后的总数不设上限（Task 12 已用 1584 点验证过下游链路） |
| 高纬度 `cos(lat) → 0` | `cos` 下限 0.01（纯防御，本项目仅国内坐标） |
| 页面刷新 | 图形不持久化，全部丢失（符合非目标） |

## 八、测试策略

纯几何部分（轮廓分解、细分、点数策略、旋转、米↔经纬度）无 DOM 依赖，用 Node 直接单测：

- `tests/js/test_shape_geometry.js`：用例本体，零依赖（Node 内置 `assert`）
- `tests/test_shape_geometry.py`：pytest 起 `node` 跑上述脚本并断言退出码；用 `@pytest.mark.skipif(shutil.which('node') is None)` 守卫 —— CI 的 `python -m pytest`（仅 Python 3.13，无 Node 步骤）自动跳过，**不引入新的 CI 依赖**；本机有 Node v24，可实跑
- `shape_geometry.js` 需带 `if (typeof module !== 'undefined') module.exports = {...}` 守卫，浏览器与 Node 双用

用例与精确期望值：

| # | 用例 | 期望 |
|---|---|---|
| 1 | `rect(100, 60)` @ 10 m | 32 点（10 + 6 + 10 + 6） |
| 2 | 同上，四角在点集内 | 与角点距离 < 1e-6 m |
| 3 | `circle(60)` @ 10 m | 38 点；每点到中心距离 = 60 ± 0.5 m |
| 4 | `stadium(L=84.39, R=36.5)` @ 10 m | 38 点（8 + 11 + 8 + 11） |
| 5 | 点数随尺寸单调 | `rect(100,60)` < `rect(200,120)` |
| 6 | 封顶 | `rect(5000,5000)` @ 3 m → 点数 ≤ 500 |
| 7 | 旋转 90° | `rect(100,60)` 旋转 `π/2` 后经度跨度 ≈ 60 m、纬度跨度 ≈ 100 m |
| 8 | 闭合无缺口 | `rect(100,60)` @ 10 m 的末点→首点距离 ≈ 10 m |
| 9 | 尺寸下限 | `rect(1,1)` 夹紧到 `5 × 5` |
| 10 | 米↔经纬度往返 | `localToGeo` 后用 haversine 回算的距离与本地坐标误差 < 0.5% |

DOM 交互层（拖手柄、旋转手感、缩放动画遮挡）不写自动化测试，手动跑 `python app.py` 逐项验收。

## 九、风险与回退

- **不改** `renderTrack` / `points` 数据流 / 导出链路 / 后端，新增代码全部是纯前端
- 回退方式：删除 `shape_geometry.js`、`shape_layer.js`、两个测试文件，并还原其余 6 个文件的改动 —— 即完全恢复原状
- 主要风险：Leaflet 缩放动画期间的坐标漂移（§4.4 已给出遮挡方案）；AMap 官方档的 `mapmove` 事件频率较高，重绘为轻量 SVG（< 500 个圆点），实测无性能问题则不改

## 十、验收口径

1. 三种图形都能一键放置，并能拖动 / 8 向缩放 / 旋转
2. 图形层始终盖在底图与轨迹之上；拖手柄不会误加点
3. 调整图形大小时预览点数随之变化，密度约 10 m 一点
4. 操场默认尺寸生成 ≈ 400 m 环线，与右下角距离读数一致
5. 生成轨迹点后保存的 JSON 与手画轨迹结构完全一致，可直接用于生成跑步数据
6. 切底图四档、缩放、平移时图形与地图贴合无漂移
