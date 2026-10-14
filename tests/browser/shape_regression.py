"""Real-browser shape regressions against a running, isolated Flask instance.

Install Playwright in the test environment, start app.py, then run:
  python tests/browser/shape_regression.py --url http://127.0.0.1:5000 \
      --output /tmp/shape-regression --chromium /usr/bin/chromium
Screenshots, state assertions and a trace are saved outside the repository.
The server must use disposable test data; --save-id must not already exist.
"""

import argparse
import json
from pathlib import Path

from playwright.sync_api import sync_playwright


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', default='http://127.0.0.1:5000')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--chromium', default='/usr/bin/chromium')
    parser.add_argument('--save-id', default='pr51_fix_regression')
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    shots = args.output / 'screenshots'
    shots.mkdir(exist_ok=True)
    records, errors, network, dialogs = [], [], [], []
    answer = {'accept': True}
    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=args.chromium, headless=True,
                                     args=['--no-sandbox'])
        ctx = browser.new_context(viewport={'width': 1440, 'height': 1000}, accept_downloads=True)
        ctx.tracing.start(screenshots=True, snapshots=True, sources=True)
        page = ctx.new_page()
        page.on('pageerror', lambda e: errors.append(str(e)))
        page.on('requestfailed', lambda r: network.append({'url': r.url, 'failure': r.failure}))

        def dialog(d):
            dialogs.append({'step': len(records) + 1, 'type': d.type,
                            'message': d.message, 'accept': answer['accept']})
            d.accept() if answer['accept'] else d.dismiss()
        page.on('dialog', dialog)

        def state():
            return page.evaluate('''() => typeof ShapeLayer === 'undefined' ? ({
                url: location.href, downloadEnabled: !document.querySelector('#download-btn')?.disabled,
                preview: document.querySelector('#preview-name')?.textContent
            }) : ({points: points.length, coords: points,
                shapes: ShapeLayer.shapes(), selected: ShapeLayer.selectedId(),
                view: MapEngine.activeAdapter().getView(), tool: currentTool,
                undo: undoStack.length, redo: redoStack.length,
                hidden: document.querySelector('#shape-layer').classList.contains('is-editing-hidden'),
                preview: document.querySelectorAll('.shape-preview-start,.shape-preview-dot').length,
                svg: {w: +document.querySelector('.shape-svg').getAttribute('width'),
                      h: +document.querySelector('.shape-svg').getAttribute('height')},
                stage: {w: document.querySelector('.map-stage').clientWidth,
                        h: document.querySelector('.map-stage').clientHeight},
                message: document.querySelector('#message').textContent})''')

        def step(action, run, expected, check=lambda b, a: True):
            before = state() if records else {}
            result, detail, after = 'PASS', '', {}
            try:
                run()
                page.wait_for_timeout(450)
                after = state()
                assert check(before, after), '预期断言未满足'
            except Exception as exc:
                result, detail = 'FAIL', str(exc)
            ident = f'R{len(records) + 1:03}'
            page.screenshot(path=str(shots / f'{ident}.png'), full_page=True)
            records.append(dict(id=ident, action=action, precondition=before,
                                expected=expected, actual=after, result=result,
                                detail=detail, screenshot=f'screenshots/{ident}.png'))
            (args.output / 'results.json').write_text(json.dumps(records, ensure_ascii=False, indent=2))
            print(ident, result, action, detail, flush=True)
            if result != 'PASS':
                raise AssertionError(action + ': ' + detail)

        def click(selector):
            return lambda: page.locator(selector).click(timeout=5000)

        def fill(selector, value):
            page.locator(selector).fill(value)
            page.locator(selector).press('Tab')

        def drag(selector, dx, dy, button='left'):
            box = page.locator(selector).first.bounding_box()
            assert box, selector
            x, y = box['x'] + box['width']/2, box['y'] + box['height']/2
            page.mouse.move(x, y)
            page.mouse.down(button=button)
            page.mouse.move(x + dx, y + dy, steps=12)
            page.mouse.up(button=button)

        def wheel(delta):
            box = page.locator('.shape-outline').bounding_box()
            page.mouse.move(box['x'] + box['width']/2, box['y'] + box['height']/2)
            page.mouse.wheel(0, delta)
            page.wait_for_timeout(650)

        def vertex_click():
            box = page.locator('.vertex-marker').nth(2).bounding_box()
            page.mouse.click(box['x'] + box['width']/2, box['y'] + box['height']/2)

        def valid_loop(a):
            pts = a['coords']
            return len(pts) >= 3 and len({(p['lat'], p['lng']) for p in pts}) == len(pts)

        try:
            step('打开真实编辑器', lambda: page.goto(args.url + '/track-editor', wait_until='networkidle'),
                 '引擎ready，无点无模板', lambda b, a: a['points'] == 0 and not a['shapes'])
            # Refuse to overwrite any existing track, even in a test environment.
            assert args.save_id not in page.locator('#load-track-select option').evaluate_all('(es)=>es.map(e=>e.value)')
            step('放置矩形', click('#shape-btn-rect'), '32预览点', lambda b, a: a['preview'] == 32)
            step('缩小窗口', lambda: page.set_viewport_size({'width': 900, 'height': 700}),
                 'SVG与地图同尺寸', lambda b, a: a['svg'] == a['stage'])
            step('放大窗口', lambda: page.set_viewport_size({'width': 1800, 'height': 1000}),
                 'SVG扩大且模板仍可见', lambda b, a: a['svg'] == a['stage'] and page.locator('.shape-outline').is_visible())
            step('恢复窗口', lambda: page.set_viewport_size({'width': 1440, 'height': 1000}),
                 '尺寸一致', lambda b, a: a['svg'] == a['stage'])
            step('模板内滚轮放大', lambda: wheel(-120), 'zoom增加，模板坐标不变',
                 lambda b, a: a['view']['zoom'] > b['view']['zoom'] and a['shapes'] == b['shapes'])
            step('模板内滚轮缩小', lambda: wheel(120), 'zoom减小',
                 lambda b, a: a['view']['zoom'] < b['view']['zoom'])
            step('切换画笔', click('#tool-draw'), '画笔模式', lambda b, a: a['tool'] == 'draw')
            step('模板内中键平移', lambda: drag('.shape-outline', 60, 35, 'middle'),
                 '地图平移、模板地理坐标不变、不加点',
                 lambda b, a: a['view'] != b['view'] and a['shapes'] == b['shapes'] and a['points'] == 0)
            step('画笔下左键拖模板', lambda: drag('.shape-outline', 35, 25),
                 '只移动模板，不平移地图、不加点',
                 lambda b, a: a['shapes'] != b['shapes'] and a['view'] == b['view'] and a['points'] == 0)
            step('画笔下双击模板', lambda: page.locator('.shape-outline').dblclick(),
                 '不加点不缩放', lambda b, a: a['points'] == 0 and a['view'] == b['view'])
            for key, dx, dy in [('e', 20, 0), ('w', -20, 0), ('n', 0, -20), ('s', 0, 20),
                                ('ne', 15, -15), ('nw', -15, -15), ('se', 15, 15), ('sw', -15, 15)]:
                step('缩放手柄 ' + key, lambda k=key, x=dx, y=dy: drag('[data-handle-key="'+k+'"]', x, y),
                     '尺寸改变、画笔不加点', lambda b, a: a['shapes'] != b['shapes'] and a['points'] == 0)
            step('旋转模板', lambda: drag('[data-handle-key="rotate"]', 40, 30),
                 '角度改变、不加点', lambda b, a: a['shapes'][0]['rotation'] != b['shapes'][0]['rotation'] and a['points'] == 0)
            step('右键拖动模板', lambda: drag('.shape-outline', 25, 20, 'right'),
                 '模板保持', lambda b, a: a['shapes'] == b['shapes'])
            step('空白处画一点', lambda: page.mouse.click(200, 280), '新增1点', lambda b, a: a['points'] == 1)
            answer['accept'] = False
            step('取消替换确认', click('#shape-generate-btn'), '旧点保持，模板仍可编辑',
                 lambda b, a: a['coords'] == b['coords'] and not a['hidden'])
            answer['accept'] = True
            step('确认生成轨迹', click('#shape-generate-btn'), '点数与预览一致、退出模板编辑但模型保留',
                 lambda b, a: a['points'] == b['preview'] and a['hidden'] and len(a['shapes']) == 1)
            step('切橡皮擦', click('#tool-erase'), 'erase', lambda b, a: a['tool'] == 'erase')
            step('直接删除生成的顶点', vertex_click, '点数减1，无须清空模板', lambda b, a: a['points'] == b['points'] - 1)
            step('撤销删除', click('#undo-btn'), '点数恢复', lambda b, a: a['points'] == b['points'] + 1)
            step('撤销生成', click('#undo-btn'), '原有1点恢复', lambda b, a: a['points'] == 1)
            step('重做生成', click('#redo-btn'), '生成点恢复', lambda b, a: a['points'] > 3)
            step('通过列表恢复模板编辑', click('.shape-chip'), '模型仍在、覆盖可见',
                 lambda b, a: not a['hidden'] and a['selected'] is not None)
            step('切新版底图', click('#mode-fresh'), '切换后模板可编辑', lambda b, a: not a['hidden'])
            step('新版模板内滚轮放大', lambda: wheel(-120), 'zoom增加', lambda b, a: a['view']['zoom'] > b['view']['zoom'])
            step('切卫星底图', click('#mode-satellite'), '模板保留', lambda b, a: len(a['shapes']) == 1)
            step('卫星模板内中键平移', lambda: drag('.shape-outline', 30, 20, 'middle'),
                 '视角改变、不修改模板', lambda b, a: a['view'] != b['view'] and a['shapes'] == b['shapes'])
            step('新建空白', click('#new-btn'), '清空模板/轨迹/历史', lambda b, a: not a['shapes'] and a['points'] == 0 and a['undo'] == 0)
            step('放置圆', click('#shape-btn-circle'), '1圆', lambda b, a: len(a['shapes']) == 1)
            step('圆缩到最小直径', lambda: drag('[data-handle-key="e"]', -page.locator('.shape-outline').bounding_box()['width'] + 2, 0),
                 '直径5米', lambda b, a: a['shapes'][0]['width'] == 5)
            step('目标间距100米', lambda: fill('#shape-spacing', '100'), '仍至少3预览点', lambda b, a: a['preview'] >= 3)
            step('生成最小圆', click('#shape-generate-btn'), '至少3个唯一点', lambda b, a: valid_loop(a))
            step('填写隔离轨迹ID', lambda: fill('#track-id', args.save_id), '仅使用新ID')
            step('填写隔离轨迹名', lambda: fill('#track-name', 'PR51 fix regression'), '测试名称')
            step('实际保存最小圆', click('#save-form button[type="submit"]'), '保存成功', lambda b, a: '已保存' in a['message'])
            step('新建退化操场测试', click('#new-btn'), '清空', lambda b, a: a['points'] == 0)
            step('放置操场', click('#shape-btn-stadium'), '1操场', lambda b, a: len(a['shapes']) == 1)
            step('操场缩到宽高相等', lambda: drag('[data-handle-key="e"]', -page.locator('.shape-outline').bounding_box()['width']*0.75, 0),
                 '宽高相等', lambda b, a: a['shapes'][0]['width'] == a['shapes'][0]['height'])
            step('生成退化操场', click('#shape-generate-btn'), '至少3唯一点，无重复零长边', lambda b, a: valid_loop(a))
            step('新建上限测试', click('#new-btn'), '清空')
            step('放置上限测试矩形', click('#shape-btn-rect'), '1矩形')
            step('缩小地图以放大实际图形', lambda: wheel(120), 'zoom减小', lambda b, a: a['view']['zoom'] < b['view']['zoom'])
            step('放大矩形东边', lambda: drag('[data-handle-key="e"]', 450, 0), '实际宽度>400米', lambda b, a: a['shapes'][0]['width'] > 400)
            step('放大矩形北边', lambda: drag('[data-handle-key="n"]', 0, -300), '实际周长>1500米',
                 lambda b, a: 2*(a['shapes'][0]['width'] + a['shapes'][0]['height']) > 1500)
            step('间距3米', lambda: fill('#shape-spacing', '3'), '预览不超过500点', lambda b, a: 3 <= a['preview'] <= 500)
            step('生成大矩形', click('#shape-generate-btn'), '最多500唯一点', lambda b, a: valid_loop(a) and a['points'] <= 500)
            step('选择刚保存的测试轨迹', lambda: page.locator('#load-track-select').select_option(args.save_id), '选择新轨迹')
            step('从服务器重新加载', click('#load-btn'), '最小圆至少3点，模板清空', lambda b, a: valid_loop(a) and not a['shapes'])
            step('切平移工具', click('#tool-pan'), 'pan', lambda b, a: a['tool'] == 'pan')
            step('拖动轨迹顶点', lambda: drag('.vertex-marker', 15, 20), '坐标改变、点数不变', lambda b, a: a['coords'] != b['coords'] and a['points'] == b['points'])
            step('打开生成器主页', lambda: page.goto(args.url + '/', wait_until='networkidle'), '主页可用')
            step('选择隔离轨迹', lambda: page.locator('#track-select').select_option(args.save_id),
                 '主页预览新轨迹', lambda b, a: a['preview'] == 'PR51 fix regression')
            step('切换单文件模式', click('[data-mode="single"]'), '单文件表单可用')
            step('填写测试日期', lambda: fill('#single-date', '2025-01-01'), '固定日期')
            step('填写0.1km距离', lambda: fill('#single-distance', '0.1'), '最小回归距离')
            step('设置隔离输出目录', lambda: fill('#single-output-dir', str(args.output.resolve() / 'generated')), '写入报告目录')
            def generate():
                page.locator('#single-form button[type="submit"]').click()
                page.wait_for_function("!document.querySelector('#download-btn').disabled", timeout=30000)
            step('真实生成FIT', generate, '生成成功，可下载', lambda b, a: a['downloadEnabled'])
            def download():
                with page.expect_download() as event:
                    page.locator('#download-btn').click()
                event.value.save_as(str(args.output / ('download-' + event.value.suggested_filename)))
            step('下载FIT结果', download, '浏览器下载到隔离目录')
            step('切换TCX输出', lambda: page.locator('#single-output-format').select_option('tcx'), 'TCX格式')
            step('真实生成TCX', generate, '生成成功，可下载', lambda b, a: a['downloadEnabled'])
            step('下载TCX结果', download, '浏览器下载到隔离目录')
        finally:
            ctx.tracing.stop(path=str(args.output / 'trace.zip'))
            for name, data in [('browser-errors', errors), ('network', network), ('dialogs', dialogs)]:
                (args.output / (name + '.json')).write_text(json.dumps(data, ensure_ascii=False, indent=2))
            browser.close()
        assert not errors, errors


if __name__ == '__main__':
    main()
