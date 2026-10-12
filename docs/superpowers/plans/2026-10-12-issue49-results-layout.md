# Issue #49 生成结果布局重构 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将生成结果板块移到「开始生成」按钮正下方（右栏 param-main 内），结果表格限高内部滚动 + sticky 表头。

**Architecture:** 纯前端三处小改：index.html 移动 DOM 位置并重结构；style.css 把独立 panel 样式改为右栏内嵌卡片 + 新增滚动容器；app.js 在 `showResults()` 中重置滚动位置并平滑滚入视野。后端 API 与结果数据结构不动。

**Tech Stack:** Flask + Jinja2 模板、原生 CSS/JS（无构建步骤、无 JS 测试基建）

**Spec:** `docs/superpowers/specs/2026-10-12-issue49-results-layout-design.md`

## Global Constraints

- 不改后端路由 / API / 结果数据结构
- 不动左栏（数据源 / 生成模式）与状态条
- 不做分页、虚拟滚动（YAGNI）
- 结果隐藏机制保持 `#results-section` + `.show` class 切换（app.js 既有约定）
- 滚动限高 `40vh`；sticky 表头背景必须不透明（`var(--surface)`）
- 提交信息格式遵循项目 CLAUDE.md commit 规范，结尾加 `Co-Authored-By: Claude Code <noreply@anthropic.com>`

---

### Task 1: index.html — 移动结果板块到右栏按钮下方

**Files:**
- Modify: `web/templates/index.html:346-375`

**Interfaces:**
- Consumes: 既有 `#results-section` / `#results-body` / `#download-btn` ID（app.js 依赖，不得改名）
- Produces: `.results-head`（标题行）、`.results-scroll`（滚动容器，包裹 `results-table`）——Task 2 的 CSS、Task 3 的 JS 均按此 class 名引用

- [ ] **Step 1: 移动并重写结果区块**

将现有的（index.html 末段，workbench 闭合之后）：

```html
            </main>
        </div>

        <!-- 输出区 -->
        <section id="results-section" class="panel output-sec results-section">
            <div class="section-head">
                <span class="group-label" style="margin:0;"><span class="step-no">03</span>生成结果 OUTPUT</span>
                <span class="mono-tag" style="margin-left:auto;">FIT / TCX EXPORT</span>
                <button id="download-btn" class="btn btn-primary btn-sm" disabled>下载文件</button>
            </div>
            <div class="section-body">
                <table class="results-table">
                    <thead>
                        <tr>
                            <th>日期</th>
                            <th>距离</th>
                            <th>配速</th>
                            <th>时长</th>
                            <th>卡路里</th>
                        </tr>
                    </thead>
                    <tbody id="results-body">
                    </tbody>
                </table>
            </div>
        </section>
```

改为（结果块移入 `<main>`，紧跟 `#message` 所在 section-body 之后）：

```html
                <!-- 消息提示：紧跟执行区，生成中/结果反馈显示于此 -->
                <div class="section-body" style="padding-top:0;">
                    <div id="message" class="message"></div>
                </div>

                <!-- 生成结果：按钮正下方，超限内部滚动 (#49) -->
                <div class="section-body" style="padding-top:0;">
                    <section id="results-section" class="results-section">
                        <div class="results-head">
                            <span class="group-label" style="margin:0;"><span class="step-no">03</span>生成结果 OUTPUT</span>
                            <span class="mono-tag">FIT / TCX EXPORT</span>
                            <button id="download-btn" class="btn btn-primary btn-sm" disabled>下载文件</button>
                        </div>
                        <div class="results-scroll">
                            <table class="results-table">
                                <thead>
                                    <tr>
                                        <th>日期</th>
                                        <th>距离</th>
                                        <th>配速</th>
                                        <th>时长</th>
                                        <th>卡路里</th>
                                    </tr>
                                </thead>
                                <tbody id="results-body">
                                </tbody>
                            </table>
                        </div>
                    </section>
                </div>
            </main>
        </div>
```

要点：
- `class="panel output-sec results-section"` → `class="results-section"`（不再独立 panel）
- 表格外层包 `.results-scroll`；标题行改用 `.results-head`（不用 `.section-head`，那是 panel 顶部专用样式）
- 三个 ID（`results-section` / `results-body` / `download-btn`）原样保留

- [ ] **Step 2: 页面仍可正常加载**

Run: `curl -s http://127.0.0.1:5057/ | grep -c "results-section"`
（若服务未启动，先后台启动：`python -c "from web.routes import create_app; create_app().run(host='127.0.0.1', port=5057, use_reloader=False)"`）
Expected: 出现 2 次（元素本身 + 无 `.show` 时浏览器加载后 app.js 才加 class；grep 到开标签即可，`>0`）

- [ ] **Step 3: Commit**

```bash
git add web/templates/index.html
git commit -m "web: 生成结果板块移入右栏按钮正下方 (#49)

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 2: style.css — 内嵌卡片样式 + 限高滚动 + sticky 表头

**Files:**
- Modify: `web/static/css/style.css:285-307`（「输出区」整节）

**Interfaces:**
- Consumes: Task 1 产出的 `.results-section` / `.results-head` / `.results-scroll` 结构
- Produces: 视觉最终态；无代码接口产出

- [ ] **Step 1: 替换「输出区」样式节**

将 style.css 中现有的：

```css
/* ============================================================
   输出区
   ============================================================ */
.output-sec { margin-top: 14px; }
.results-section { display: none; }
.results-section.show { display: block; }
.results-table { width: 100%; border-collapse: collapse; }
.results-table th {
    font-family: var(--mono); font-size: 10px; font-weight: 600;
    letter-spacing: .08em; text-transform: uppercase;
    color: var(--text-3);
    text-align: left;
    padding: 6px 10px;
    border-bottom: 1px solid var(--border);
}
.results-table td {
    font-family: var(--mono); font-size: 12px;
    padding: 7px 10px;
    border-bottom: 1px solid var(--border);
}
.results-table tbody tr { transition: background .1s; }
.results-table tbody tr:hover { background: var(--surface-2); }
.results-table td:first-child { color: var(--text-2); }
```

整体替换为：

```css
/* ============================================================
   输出区（右栏内嵌卡片，按钮正下方；超限内部滚动 #49）
   ============================================================ */
.results-section {
    display: none;
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    padding: 14px;
}
.results-section.show { display: block; }

.results-head {
    display: flex; align-items: center; gap: 10px;
    margin-bottom: 10px;
}
.results-head .mono-tag { margin-left: auto; }

/* 限高滚动容器：表头 sticky，超出约半屏的行在容器内滚动 */
.results-scroll { max-height: 40vh; overflow-y: auto; }

.results-table { width: 100%; border-collapse: collapse; }
.results-table th {
    position: sticky; top: 0; z-index: 1;
    background: var(--surface);
    font-family: var(--mono); font-size: 10px; font-weight: 600;
    letter-spacing: .08em; text-transform: uppercase;
    color: var(--text-3);
    text-align: left;
    padding: 6px 10px;
    border-bottom: 1px solid var(--border);
}
.results-table td {
    font-family: var(--mono); font-size: 12px;
    padding: 7px 10px;
    border-bottom: 1px solid var(--border);
}
.results-table tbody tr { transition: background .1s; }
.results-table tbody tr:hover { background: var(--surface-2); }
.results-table td:first-child { color: var(--text-2); }
```

要点：
- 删除 `.output-sec`（全仓库唯一使用方已在 Task 1 移除该 class）
- `.results-section` 由「整宽独立 panel」变为「内嵌卡片」：边框 + 圆角 + 14px 内边距，隐藏/`.show` 机制不变
- sticky 表头背景 `var(--surface)`（#FFFFFF 不透明），否则滚动时行内容会从表头后面透出

- [ ] **Step 2: 确认无残留引用**

Run: `grep -rn "output-sec" web/ --include="*.html" --include="*.css" --include="*.js"`
Expected: 无输出（exit 1）

- [ ] **Step 3: Commit**

```bash
git add web/static/css/style.css
git commit -m "web: 生成结果改内嵌卡片样式，限高滚动+sticky表头 (#49)

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 3: app.js — 结果滚回顶部并带入视野

**Files:**
- Modify: `web/static/js/app.js:957-975`（`showResults` 函数）

**Interfaces:**
- Consumes: Task 1 产出的 `.results-scroll` 容器（`section.querySelector('.results-scroll')`）
- Produces: 无（末端交互函数）

- [ ] **Step 1: 修改 showResults**

将现有的：

```js
// 显示结果
function showResults(result) {
    const section = document.getElementById('results-section');
    const tbody = document.getElementById('results-body');
    const downloadBtn = document.getElementById('download-btn');

    tbody.innerHTML = result.files.map(f => `
        <tr>
            <td>${f.date}</td>
            <td>${f.distance_km.toFixed(2)} km</td>
            <td>${f.pace_min_per_km.toFixed(2)} min/km</td>
            <td>${formatDuration(f.duration_seconds)}</td>
            <td>${f.calories}</td>
        </tr>
    `).join('');

    section.classList.add('show');
    downloadBtn.disabled = false;
}
```

改为（末尾追加 4 行，其余不动）：

```js
// 显示结果
function showResults(result) {
    const section = document.getElementById('results-section');
    const tbody = document.getElementById('results-body');
    const downloadBtn = document.getElementById('download-btn');

    tbody.innerHTML = result.files.map(f => `
        <tr>
            <td>${f.date}</td>
            <td>${f.distance_km.toFixed(2)} km</td>
            <td>${f.pace_min_per_km.toFixed(2)} min/km</td>
            <td>${formatDuration(f.duration_seconds)}</td>
            <td>${f.calories}</td>
        </tr>
    `).join('');

    section.classList.add('show');
    downloadBtn.disabled = false;

    // 新一轮结果从顶部展示，并将结果块平滑带入视野 (#49)
    const scrollBox = section.querySelector('.results-scroll');
    if (scrollBox) scrollBox.scrollTop = 0;
    section.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
}
```

- [ ] **Step 2: 语法自检**

Run: `node --check web/static/js/app.js 2>/dev/null || python3 -c "print('node 不可用，跳过语法检查')"`
Expected: 无输出（node 可用时 exit 0）

- [ ] **Step 3: Commit**

```bash
git add web/static/js/app.js
git commit -m "web: 生成完成后结果滚回顶部并平滑进入视野 (#49)

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 4: 浏览器全量验证 + CHANGELOG

**Files:**
- Modify: `CHANGELOG.md`（`## [未发布]` 节）

**Interfaces:**
- Consumes: Task 1-3 的全部产出
- Produces: 无

- [ ] **Step 1: 启动开发服务器**

后台运行（Bash run_in_background）：

```bash
python -c "from web.routes import create_app; create_app().run(host='127.0.0.1', port=5057, use_reloader=False)"
```

Run: `sleep 2 && curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:5057/`
Expected: `200`

- [ ] **Step 2: Chrome DevTools MCP 桌面端验证（1600×1000）**

1. 打开 `http://127.0.0.1:5057/`，确认无 console 错误、结果区隐藏
2. **单个文件模式**：选日期、距离 3.0，点「开始生成」→ 结果卡片出现在右栏「开始生成」按钮正下方（`#message` 之下），非整宽
3. **每日模式**（多行滚动验证）：开始日期 `2026-09-01`、结束日期 `2026-10-10`、最低 2.0 / 最高 5.0 → 生成 ~35 行 → 卡片高度封顶（`max-height: 40vh`），容器内出现滚动条；用 JS 滚动 `.results-scroll`（`el.scrollTop = 200`）后截图确认表头仍固定在容器顶部
4. **总公里数模式**：任选一周、总 20 km → 生成 → 结果正常显示在按钮下方
5. **指定日期模式**：选 3 个日期 → 批量生成 → 结果正常
6. 二次生成（每日模式再跑一次）→ 结果从滚动顶部重新展示，页面平滑滚到结果区

每步用 `take_screenshot` 留证；用 `evaluate_script` 断言：

```js
() => {
  const sec = document.getElementById('results-section');
  const scrollBox = sec.querySelector('.results-scroll');
  const rect = sec.getBoundingClientRect();
  const btn = document.querySelector('#daily-form button[type="submit"]').getBoundingClientRect();
  return {
    insideMain: sec.closest('main.param-main') !== null,
    belowButton: rect.top > btn.bottom,
    scrollCapped: scrollBox.scrollHeight >= scrollBox.clientHeight,
    clientHeight: scrollBox.clientHeight,
    rows: document.querySelectorAll('#results-body tr').length
  };
}
```

Expected: `insideMain: true`、`belowButton: true`、每日模式 `rows > 20` 且 `scrollCapped: true`

- [ ] **Step 3: 窄屏验证（≤960px）**

`resize_page` 到 900×900 → 重新生成一次每日模式 → 截图确认：workbench 单列、结果在按钮下方、表格仍限高滚动。

- [ ] **Step 4: Python 测试保持绿色**

Run: `python -m pytest tests/ -q`
Expected: `78 passed`

- [ ] **Step 5: CHANGELOG 未发布节记录**

在 `CHANGELOG.md` 的 `## [未发布]` 下新增（保持与既有条目一致的编号引用格式）：

```markdown
### 变更

- 生成结果板块移至「开始生成」按钮正下方（右栏内嵌卡片），超出约半屏的结果在卡片内滚动且表头固定，页面不再被长结果撑高 (#49)
```

- [ ] **Step 6: Commit**

```bash
git add CHANGELOG.md
git commit -m "docs: CHANGELOG 未发布节记录 #49 布局调整

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

## Self-Review 记录

- **Spec 覆盖**：位置（Task 1）、内嵌样式+滚动+sticky（Task 2）、滚回顶部+带入视野（Task 3）、4 模式与双宽度验证（Task 4）✓；`.output-sec` 清理（Task 2 Step 2）✓
- **占位符**：无 TBD/TODO，所有代码块完整可抄
- **一致性**：`.results-head` / `.results-scroll` 命名在 Task 1（HTML）、Task 2（CSS）、Task 3（querySelector）三处一致；`#results-section` / `#results-body` / `#download-btn` ID 未动，app.js 其余部分零影响
