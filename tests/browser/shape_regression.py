"""真实 Flask + Chromium 的一次性图形节点回归。

先启动使用一次性 config 的 Flask；禁止对正式轨迹库运行。
python tests/browser/shape_regression.py --url http://127.0.0.1:5000 \
    --output /tmp/shape-nodes --save-id shape_nodes_regression
截图与状态仅写入仓库外；外部瓦片/字体不参与本交互测试。
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
    parser.add_argument('--save-id', default='shape_nodes_regression')
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    records, errors = [], []
    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=args.chromium, headless=True, args=['--no-sandbox'])
        ctx = browser.new_context(viewport={'width': 1440, 'height': 1000})
        page = ctx.new_page()
        page.route('**/*', lambda r: r.continue_() if r.request.url.startswith(args.url + '/') else r.abort())
        page.on('pageerror', lambda e: errors.append(str(e)))

        def state():
            return page.evaluate('''() => ({coords: points, indices: SelectionLayer.indices(),
                pixels: points.map(p => MapEngine.latLngToContainer(p.lat, p.lng)),
                tool: currentTool, undo: undoStack.length, redo: redoStack.length,
                view: MapEngine.activeAdapter().getView(), trackId: editingTrackId,
                correction: activeCorrection, message: document.querySelector('#message').textContent,
                stage: {w: document.querySelector('.map-stage').clientWidth,
                        h: document.querySelector('.map-stage').clientHeight}})''')

        def step(name, action, check=lambda b, a: True):
            before = state() if records else {}
            try:
                action()
                page.wait_for_timeout(100)
                after = state()
                assert check(before, after), '状态断言失败'
                records.append({'name': name, 'result': 'PASS'})
                print('PASS', name, flush=True)
            except Exception:
                page.screenshot(path=str(args.output / 'failure.png'), full_page=True)
                raise

        def click(selector):
            return lambda: page.locator(selector).click()

        def drag(a, b):
            page.mouse.move(*a)
            page.mouse.down()
            page.mouse.move(*b, steps=10)
            page.mouse.up()

        def stage_xy(p):
            box = page.locator('.map-stage').bounding_box()
            return box['x'] + p['x'], box['y'] + p['y']

        def drag_handle(key, dx, dy):
            box = page.locator(f'[data-selection-key="{key}"]').bounding_box()
            a = (box['x'] + box['width']/2, box['y'] + box['height']/2)
            drag(a, (a[0] + dx, a[1] + dy))

        def select_all():
            s = state()
            ps = s['pixels']
            drag(stage_xy({'x': min(p['x'] for p in ps)-12, 'y': min(p['y'] for p in ps)-12}),
                 stage_xy({'x': max(p['x'] for p in ps)+12, 'y': max(p['y'] for p in ps)+12}))

        def valid(s):
            pts = s['coords']
            return (3 <= len(pts) <= 500 and len({(p['lat'], p['lng']) for p in pts}) == len(pts)
                    and all(0 < p['x'] < s['stage']['w'] and 0 < p['y'] < s['stage']['h'] for p in s['pixels'])
                    and s['indices'] == list(range(len(pts))) and s['tool'] == 'select')

        def zoom(value):
            page.evaluate('(z) => MapEngine.activeAdapter().map.setZoom(z, {animate:false})', value)
            page.wait_for_timeout(150)

        try:
            step('打开真实编辑器，无模板专属覆盖层',
                 lambda: page.goto(args.url + '/track-editor', wait_until='networkidle'),
                 lambda b, a: not a['coords'] and page.locator('#shape-layer').count() == 0)
            assert args.save_id not in page.locator('#load-track-select option').evaluate_all('(es)=>es.map(e=>e.value)')
            for width, height, zoom_level in [(1440, 1000, 3), (900, 700, 17), (650, 700, 20)]:
                page.set_viewport_size({'width': width, 'height': height})
                zoom(zoom_level)
                for shape in ['rect', 'circle', 'stadium']:
                    page.locator('#new-btn').click()
                    step(f'{shape} 一次生成普通点 {width}x{height} zoom={zoom_level}',
                         click('#shape-btn-' + shape), lambda b, a: valid(a) and a['undo'] == 1)
                    original = state()['coords']
                    step('间距变化只影响下一次添加', lambda: page.locator('#shape-spacing').fill('30'),
                         lambda b, a: a['coords'] == b['coords'])
                    page.locator('#shape-spacing').press('Tab')
                    step('撤销整次生成', click('#undo-btn'), lambda b, a: not a['coords'] and not a['indices'])
                    step('重做恢复同一普通点列', click('#redo-btn'), lambda b, a: a['coords'] == original)

            page.set_viewport_size({'width': 1440, 'height': 1000})
            zoom(18)
            page.locator('#new-btn').click()
            page.locator('#shape-spacing').fill('30')
            page.locator('#shape-spacing').press('Tab')
            step('生成后立即自动框选', click('#shape-btn-stadium'), lambda b, a: valid(a))
            generated = state()['coords']
            step('整组移动占一次历史', lambda: drag_handle('move', 35, 20),
                 lambda b, a: a['coords'] != b['coords'] and a['undo'] == b['undo'] + 1)
            step('整组旋转占一次历史', lambda: drag_handle('rotate', 60, 30),
                 lambda b, a: a['coords'] != b['coords'] and a['undo'] == b['undo'] + 1)
            step('旋转后普通框选缩放', lambda: drag_handle('se', 30, 20),
                 lambda b, a: a['coords'] != b['coords'] and a['undo'] == b['undo'] + 1)
            page.screenshot(path=str(args.output / '01-generated-selected.png'), full_page=True)
            step('按钮删除整组节点', click('#delete-selection-btn'), lambda b, a: not a['coords'])
            step('撤销整组删除', click('#undo-btn'), lambda b, a: len(a['coords']) == len(generated))
            step('重做整组删除', click('#redo-btn'), lambda b, a: not a['coords'])
            page.locator('#undo-btn').click()
            page.locator('#tool-pan').click()
            def move_vertex():
                p = state()['pixels'][2]
                a = stage_xy(p)
                drag(a, (a[0]+18, a[1]+14))
            step('模板点可直接单点拖动', move_vertex,
                 lambda b, a: len(a['coords']) == len(b['coords']) and a['coords'][2] != b['coords'][2]
                 and a['coords'][:2] == b['coords'][:2] and a['coords'][3:] == b['coords'][3:])
            page.locator('#tool-erase').click()
            step('橡皮擦删除一个普通节点', lambda: page.mouse.click(*stage_xy(state()['pixels'][3])),
                 lambda b, a: len(a['coords']) == len(b['coords'])-1)
            step('撤销单点删除', click('#undo-btn'), lambda b, a: len(a['coords']) == len(b['coords'])+1)
            page.locator('#tool-pan').click()
            step('普通中点插入', lambda: page.locator('.midpoint-handle').nth(2).click(),
                 lambda b, a: len(a['coords']) == len(b['coords'])+1)
            page.locator('#tool-select').click()
            def select_part():
                s = state(); ps = s['pixels']; x = s['stage']['w']/2
                drag(stage_xy({'x': min(p['x'] for p in ps)-12, 'y': min(p['y'] for p in ps)-12}),
                     stage_xy({'x': x, 'y': max(p['y'] for p in ps)+12}))
            step('模板拆开框选部分节点', select_part,
                 lambda b, a: 0 < len(a['indices']) < len(a['coords']))
            step('拆开移动只改变选中节点', lambda: drag_handle('move', -20, 10),
                 lambda b, a: all(a['coords'][i] == p for i, p in enumerate(b['coords']) if i not in b['indices'])
                 and a['coords'] != b['coords'])
            page.screenshot(path=str(args.output / '02-edit-part.png'), full_page=True)
            step('键盘删除部分节点', lambda: page.keyboard.press('Delete'),
                 lambda b, a: len(a['coords']) == len(b['coords'])-len(b['indices']))
            page.locator('#undo-btn').click()
            page.locator('#tool-select').click()
            select_all()
            page.locator('#track-name').fill('普通节点回归（合成数据）')
            step('输入框 Delete 不删轨迹', lambda: page.locator('#track-name').press('Delete'),
                 lambda b, a: a['coords'] == b['coords'])
            page.locator('#tool-select').click()
            select_all()
            page.locator('#tool-select').focus()
            step('Backspace 整组删除', lambda: page.keyboard.press('Backspace'), lambda b, a: not a['coords'])

            # 真实追加：先把第一组整体移到左侧，第二组在当前视野中心生成。
            page.locator('#new-btn').click()
            page.locator('#shape-btn-rect').click()
            drag_handle('se', -360, -220)
            drag_handle('move', -260, -100)
            first = state()['coords']
            step('追加新模板，旧节点保持原坐标和顺序', click('#shape-btn-circle'),
                 lambda b, a: len(a['coords']) > len(first)
                 and [p for i, p in enumerate(a['coords']) if i not in a['indices']] == first)
            join_state = state()
            step('追加无新交叉连接', lambda: None,
                 lambda b, a: page.evaluate('''() => {
                    const ps = points.map(p => MapEngine.latLngToContainer(p.lat,p.lng));
                    return ps.every((p,i) => ps.every((q,j) => j <= i || j === i+1 || i === 0 && j === ps.length-1
                        || !segmentsConflict(p, ps[(i+1)%ps.length], q, ps[(j+1)%ps.length])));
                 }'''))
            page.screenshot(path=str(args.output / '03-appended.png'), full_page=True)
            step('重叠模板拒绝追加，原轨迹与历史保持', click('#shape-btn-circle'),
                 lambda b, a: a['coords'] == b['coords'] and a['undo'] == b['undo'] and '重叠' in a['message'])
            step('仅删除追加一组，完整恢复原节点列', click('#delete-selection-btn'), lambda b, a: a['coords'] == first)
            step('撤销追加组删除', click('#undo-btn'), lambda b, a: a['coords'] == join_state['coords'])
            step('撤销模板追加', click('#undo-btn'), lambda b, a: a['coords'] == first)
            step('重做模板追加', click('#redo-btn'), lambda b, a: a['coords'] == join_state['coords'])

            saved = state()['coords']
            page.locator('#track-id').fill(args.save_id)
            page.locator('#track-name').fill('图形节点回归（合成数据）')
            def save():
                page.locator('#save-form button[type="submit"]').click()
                page.wait_for_function("document.querySelector('#message').textContent.startsWith('已保存')")
            step('实际 POST 保存普通轨迹格式', save, lambda b, a: a['trackId'] == args.save_id)
            response = ctx.request.get(args.url + '/api/tracks/' + args.save_id + '/coords').json()
            assert response['base_coordinates'] == [{'longitude': p['lng'], 'latitude': p['lat']} for p in saved]
            assert 'segments' not in response
            step('刷新按 ID 重开', lambda: page.goto(args.url + '/track-editor?track=' + args.save_id, wait_until='networkidle'),
                 lambda b, a: a['coords'] == saved and not a['indices'] and a['undo'] == 0)
            page.locator('#tool-pan').click()
            step('重开后仍可单点编辑', move_vertex, lambda b, a: a['coords'] != b['coords'])
            edited = state()['coords']
            step('实际覆盖保存原 ID', save, lambda b, a: a['trackId'] == args.save_id)
            step('再次刷新核对编辑结果', lambda: page.reload(wait_until='networkidle'), lambda b, a: a['coords'] == edited)
            assert not errors, errors
        finally:
            (args.output / 'results.json').write_text(json.dumps({'steps': records, 'errors': errors}, ensure_ascii=False, indent=2))
            browser.close()
    print(f'{len(records)} passed; page errors: {len(errors)}')


if __name__ == '__main__':
    main()
