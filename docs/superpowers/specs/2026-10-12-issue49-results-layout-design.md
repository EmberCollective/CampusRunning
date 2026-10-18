# Issue #49 设计文档：生成结果板块移至按钮下方 + 溢出滚动

- 日期：2026-10-12
- 关联：[#49](https://github.com/EmberCollective/CampusRunning/issues/49)（enhancement）
- 状态：实现已随作者最终提交改为视口高度上限，待整合验收

## 背景

Issue 截图基于 v2 旧界面（配置左 / 结果右）。当前 v3 工作台布局中，`#results-section`
作为整宽 panel 铺在 workbench（左栏 + 右栏）下方：

- 结果与「开始生成」按钮之间隔着左栏（数据源 + 生成模式）的剩余高度，视觉动线断裂；
- 结果行数随生成文件数无限增长（如每日模式生成一个学期 ≈ 90+ 行），整页被撑长。

## 已确认的决策

1. **位置**：结果板块移入 `main.param-main`（右栏），紧跟 `#message` 反馈区之后，
   即「开始生成」按钮正下方；左栏不动。
2. **溢出处理**：内部滚动条（`max-height` + `overflow-y: auto` + sticky 表头），
   不做分页。
3. **高度上限**：沿用作者最后一次提交 `9c32ca3` 的视口计算。双栏和单列均使用
   视口高度减去 56px 顶栏避让及卡片标题、内边距、边框；可用高度不足 200px 时
   清除内联上限，回退到 CSS 的 `40vh`。不再与左栏底边对齐，也不按单列另设半屏上限。

## 目标

- 点击「开始生成」后，结果出现在按钮正下方，视觉动线连续
- 结果表格限高滚动，表头滚动时固定可见，页面不再被结果无限撑长
- 移动端单列布局下顺序保持：配置 → 按钮 → 结果

## 非目标

- 不做分页 / 虚拟滚动（当前结果规模用不上）
- 不改后端 API、不改结果数据结构
- 不动左栏（数据源 / 生成模式）与状态条

## 设计

### 1. 布局调整（`web/templates/index.html`）

- 将 `<section id="results-section">` 从 `.workbench` 之后移入 `<main class="panel param-main">`，
  置于 `#message` 所在 section-body 之后。
- class 由 `panel output-sec results-section` 改为 `results-section`：
  不再是独立 panel，改为右栏内嵌子面板（自带边框圆角，见样式）。
- 内部结构保留：`03 生成结果 OUTPUT` 标签 + 「下载文件」按钮的 header 行，
  表格外新增一层 `.results-scroll` 滚动容器。

### 2. 溢出样式（`web/static/css/style.css`）

```css
.results-section { /* 内嵌子面板：边框、圆角、背景 */ }

.results-scroll {
    max-height: 40vh;      /* JS 计算的可用高度不足 200px 时回退 */
    overflow-y: auto;      /* 复用全局自定义滚动条样式 */
}

.results-table thead th {
    position: sticky;
    top: 0;
    background: var(--surface); /* 不透明背景，遮住滚过的行 */
}
```

- 删除仅服务于旧整宽布局的 `.output-sec` 规则。
- 移动端无新增规则：workbench 折叠为单列时结果自然跟随按钮。
- 显示结果后由 `updateResultsScrollHeight()` 设置内联像素上限；窗口 resize、
  切换生成模式时重算，长表格内部滚动，少量结果按实际内容收缩。

### 3. 交互（`web/static/js/app.js`，`showResults()` 内）

- 填充表格后重置 `.results-scroll` 的 `scrollTop = 0`（新一轮结果从顶部展示）；
- 对结果块执行 `scrollIntoView({ behavior: 'smooth', block: 'nearest' })`，
  生成完成后将其平滑带入视野；`.results-section` 以 `scroll-margin-top: 56px`
  避让 sticky 顶栏，最近边缘对齐不保证卡片顶边固定在某一位置。

## 验证

- 浏览器实测（无 JS 测试基建）：4 种模式各生成一次；
  重点用每日模式生成 15+ 行验证滚动与 sticky 表头；
  桌面（1600px）与窄屏（≤960px，workbench 折叠为单列）两种宽度截图确认布局。
- 两种布局分别验证视口高度上限、resize 重算；可用高度不足 200px 时验证 `40vh` 回退。
- `pytest` 全量保持绿色。
