"""真实框选回归；先启动使用一次性 config 的 Flask，禁止对正式轨迹库运行。

python tests/browser/selection_regression.py --output /tmp/selection-regression
截图、逐步状态与 trace 均写到 --output（仓库外），需要 Playwright + Chromium。
"""
import argparse
import json
import math
from pathlib import Path

from playwright.sync_api import sync_playwright


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', default='http://127.0.0.1:5000')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--chromium', default='/usr/bin/chromium')
    parser.add_argument('--save-id', default='selection_regression')
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    records, errors, network = [], [], []
    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=args.chromium, headless=True, args=['--no-sandbox'])
        ctx = browser.new_context(viewport={'width': 1440, 'height': 1000})
        ctx.tracing.start(screenshots=True, snapshots=True, sources=True)
        page = ctx.new_page()
        page.on('pageerror', lambda e: errors.append(str(e)))
        page.on('requestfailed', lambda r: network.append({'url': r.url, 'failure': r.failure}))

        def state():
            return page.evaluate('''() => ({coords: points, indices: SelectionLayer.indices(),
                pixels: points.map(p=>MapEngine.latLngToContainer(p.lat,p.lng)),
                tool: currentTool, trackId: editingTrackId, undo: undoStack.length, redo: redoStack.length,
                view: MapEngine.activeAdapter().getView(), correction: activeCorrection,
                lines: MapEngine.adapters.leaflet.lineLayer.getLayers().map(l=>l.getLatLngs()),
                handles: document.querySelectorAll('.selection-handle').length,
                frame: document.querySelector('.selection-frame')?.parentNode.getAttribute('transform'),
                message: document.querySelector('#message').textContent})''')

        def step(name, action, check=lambda b, a: True):
            before = state() if records else {}
            try:
                action()
                page.wait_for_timeout(80)
                after = state()
                assert check(before, after), '状态断言失败'
                records.append(dict(name=name, before=before, after=after, result='PASS'))
                print('PASS', name, flush=True)
            except Exception as exc:
                records.append(dict(name=name, before=before, after=state(), result='FAIL', error=str(exc)))
                raise
            finally:
                page.screenshot(path=str(args.output / f'{len(records):02}.png'), full_page=True)
                (args.output / 'results.json').write_text(json.dumps(records, ensure_ascii=False, indent=2))

        def click(selector):
            return lambda: page.locator(selector).click()

        def drag_xy(a, b, button='left'):
            page.mouse.move(*a)
            page.mouse.down(button=button)
            page.mouse.move(*b, steps=10)
            page.mouse.up(button=button)

        def stage_xy(p):
            r = page.locator('.map-stage').bounding_box()
            return p['x'] + r['x'], p['y'] + r['y']

        def center(selector):
            r = page.locator(selector).bounding_box()
            return r['x'] + r['width']/2, r['y'] + r['height']/2

        def drag_handle(key, dx, dy):
            a = center(f'[data-selection-key="{key}"]')
            drag_xy(a, (a[0]+dx, a[1]+dy))

        def drag_handle_middle():
            a = center('.selection-frame')
            drag_xy(a, (a[0]+35, a[1]+25), 'middle')

        def select(ids=(0, 1, 2, 3), reverse=False):
            p = [state()['pixels'][i] for i in ids]
            a = stage_xy({'x': min(q['x'] for q in p)-18, 'y': min(q['y'] for q in p)-18})
            b = stage_xy({'x': max(q['x'] for q in p)+18, 'y': max(q['y'] for q in p)+18})
            drag_xy(b, a) if reverse else drag_xy(a, b)

        def draw(pixels):
            page.locator('#tool-draw').click()
            for x, y in pixels:
                page.mouse.click(*stage_xy({'x': x, 'y': y}))

        def unchanged_others(b, a):
            return len(a['coords']) == len(b['coords']) and a['coords'][4:] == b['coords'][4:]

        def near(a, b):
            return abs(a-b) < 1e-5

        try:
            step('打开编辑器', lambda: page.goto(args.url+'/track-editor', wait_until='networkidle'),
                 lambda b, a: not a['coords'])
            assert args.save_id not in page.locator('#load-track-select option').evaluate_all('(es)=>es.map(e=>e.value)')
            step('画笔实际创建六节点', lambda: draw([(380,310),(500,310),(500,430),(380,430),(750,380),(700,600)]),
                 lambda b, a: len(a['coords']) == 6)
            step('开启框选工具', click('#tool-select'), lambda b, a: a['tool'] == 'select')
            step('正向框选四节点，八柄出现，地图不移动', select,
                 lambda b, a: a['indices'] == [0,1,2,3] and a['handles'] == 8 and a['view'] == b['view'])
            step('反向框选四节点', lambda: select(reverse=True), lambda b, a: a['indices'] == [0,1,2,3])
            def center_rule():
                page.keyboard.press('Escape')
                p = state()['pixels']
                drag_xy(stage_xy({'x': p[0]['x']+4, 'y': p[0]['y']-20}),
                        stage_xy({'x': p[2]['x']+20, 'y': p[2]['y']+20}))
            step('只按节点中心命中，半径相交不选', center_rule,
                 lambda b, a: a['indices'] == [1,2] and a['coords'] == b['coords'])
            step('恢复四节点选择', select, lambda b, a: a['indices'] == [0,1,2,3])
            step('整组移动，拓扑及其他节点不变，一次撤销', lambda: drag_handle('move',30,20),
                 lambda b, a: unchanged_others(b,a) and a['undo'] == b['undo']+1 and a['view'] == b['view']
                 and all(near(a['pixels'][i]['x'],b['pixels'][i]['x']+30)
                         and near(a['pixels'][i]['y'],b['pixels'][i]['y']+20) for i in range(4))
                 and a['lines'][0] == a['coords'])
            moved = state()['coords']
            step('Ctrl+Z 一步撤销并清选择', lambda: page.keyboard.press('Control+z'),
                 lambda b, a: a['undo'] == b['undo']-1 and not a['indices'] and a['coords'] != b['coords'])
            step('Ctrl+Shift+Z 重做', lambda: page.keyboard.press('Control+Shift+z'), lambda b,a:a['coords']==moved)
            step('重新框选', select, lambda b,a:a['indices']==[0,1,2,3])
            for key, dx, dy in [('e',12,0),('w',-12,0),('n',0,-12),('s',0,12),
                                ('ne',8,-8),('nw',-8,-8),('se',8,8),('sw',-8,8)]:
                def check_scale(b,a,k=key):
                    axes = all(
                        (near(a['pixels'][i]['y'],b['pixels'][i]['y']) if k in ('e','w') else
                         near(a['pixels'][i]['x'],b['pixels'][i]['x']) if k in ('n','s') else
                         True) for i in range(4))
                    changed = all(any(not near(a['pixels'][i][axis],b['pixels'][i][axis]) for i in range(4))
                                  for axis in (('x',) if k in ('e','w') else ('y',) if k in ('n','s') else ('x','y')))
                    return unchanged_others(b,a) and a['undo']==b['undo']+1 and a['view']==b['view'] and axes and changed
                step('缩放 '+key, lambda k=key,x=dx,y=dy:drag_handle(k,x,y), check_scale)
            def rotate():
                c = center('.selection-frame'); a = center('[data-selection-key="rotate"]')
                drag_xy(a, (c[0]+math.dist(c,a), c[1]))
            def rigid(b,a):
                return unchanged_others(b,a) and a['undo']==b['undo']+1 and all(
                    near(sum(p[k] for p in a['pixels'][:4]),sum(p[k] for p in b['pixels'][:4])) for k in ('x','y'))
            step('绕选区中心旋转90度', rotate, rigid)
            step('旋转后沿局部边轴缩放', lambda:drag_handle('e',0,12),
                 lambda b,a:unchanged_others(b,a) and a['undo']==b['undo']+1)
            def wheel(delta=-120):
                page.mouse.move(*center('.selection-frame'));page.mouse.wheel(0,delta);page.wait_for_timeout(650)
            step('选框内滚轮缩放，地理数据不变', wheel,
                 lambda b,a:a['view']['zoom']>b['view']['zoom'] and a['coords']==b['coords'] and a['indices']==b['indices'])
            step('选框内中键平移地图', lambda:drag_handle_middle(),
                 lambda b,a:a['view']!=b['view'] and a['coords']==b['coords'] and a['undo']==b['undo'])
            for mode in ('fresh','satellite','classic'):
                step('切底图 '+mode,click('#mode-'+mode),lambda b,a:a['coords']==b['coords'] and a['indices']==b['indices'])
            step('调整窗口保持选择',lambda:page.set_viewport_size({'width':1300,'height':900}),
                 lambda b,a:a['coords']==b['coords'] and a['handles']==8)
            step('恢复窗口',lambda:page.set_viewport_size({'width':1440,'height':1000}))
            step('恢复缩放供取消测试',lambda:wheel(120),lambda b,a:a['coords']==b['coords'])
            def interrupt(kind):
                a=center('[data-selection-key="move"]');page.mouse.move(*a);page.mouse.down()
                page.mouse.move(a[0]+20,a[1]+10,steps=5)
                if kind=='Escape':page.keyboard.press('Escape')
                else:page.evaluate('(kind)=>window.dispatchEvent(new Event(kind))',kind)
                page.mouse.up()
            step('失焦回滚未完成移动',lambda:interrupt('blur'),lambda b,a:a['coords']==b['coords'] and a['undo']==b['undo'])
            step('Esc 回滚并清选择',lambda:interrupt('Escape'),
                 lambda b,a:a['coords']==b['coords'] and a['undo']==b['undo'] and not a['indices'])
            step('重新选择供取消测试',select)
            def cancel_pointer():
                a=center('[data-selection-key="move"]');page.mouse.move(*a);page.mouse.down()
                page.mouse.move(a[0]+20,a[1]+20,steps=5)
                page.dispatch_event('#selection-layer','pointercancel',{'pointerId':1});page.mouse.up()
            step('pointercancel 回滚',cancel_pointer,lambda b,a:a['coords']==b['coords'] and a['undo']==b['undo'])
            step('选框内无位移点击不记录历史',lambda:page.mouse.click(*center('.selection-frame')),
                 lambda b,a:a['coords']==b['coords'] and a['undo']==b['undo'])
            def out_of_bounds():
                a=center('[data-selection-key="move"]');page.mouse.move(*a);page.mouse.down()
                page.dispatch_event('#selection-layer','pointermove',{'pointerId':1,'buttons':1,'clientX':1e9,'clientY':a[1]})
                page.mouse.up()
            step('地理越界整帧拒绝，无损坏坐标或额外历史',out_of_bounds,
                 lambda b,a:a['coords']==b['coords'] and a['undo']==b['undo'])
            step('切工具退出清选择',click('#tool-pan'),lambda b,a:not a['indices'])
            def save():
                page.locator('#track-id').fill(args.save_id)
                page.locator('#track-name').fill('框选回归')
                page.locator('#save-form button[type="submit"]').click()
                page.wait_for_function("document.querySelector('#message').textContent.includes('已保存')")
            step('真实保存变换结果',save,lambda b,a:'已保存' in a['message'])
            saved=state()
            data=ctx.request.get(args.url+f'/api/tracks/{args.save_id}/coords').json()
            assert data['base_coordinates']==[{'latitude':p['lat'],'longitude':p['lng']} for p in saved['coords']]
            assert data['coordinate_correction']==saved['correction']
            step('刷新页面按ID重新打开',lambda:page.goto(args.url+'/track-editor?track='+args.save_id,wait_until='networkidle'),
                 lambda b,a:a['coords']==saved['coords'] and a['correction']==saved['correction'] and a['undo']==0)
            step('重开后框选原有节点',lambda:(page.locator('#tool-select').click(),select()),
                 lambda b,a:a['indices']==[0,1,2,3])
            step('重开后变换保留轨迹ID',lambda:drag_handle('move',8,5),
                 lambda b,a:a['trackId']==args.save_id and a['undo']==1 and unchanged_others(b,a))
            step('覆盖保存原轨迹',save,lambda b,a:a['trackId']==args.save_id and a['coords']==b['coords'])
            overwritten=state()
            step('覆盖后刷新坐标和修正仍正确',lambda:page.reload(wait_until='networkidle'),
                 lambda b,a:a['coords']==overwritten['coords'] and a['correction']==saved['correction'])
            step('新建退化选区测试',click('#new-btn'),lambda b,a:not a['coords'])
            step('创建竖直三点',lambda:draw([(400,310),(400,370),(400,430)]))
            step('开启退化选区框选',click('#tool-select'))
            step('零宽选区',lambda:select((0,1,2)),lambda b,a:a['indices']==[0,1,2] and a['handles']==8)
            step('零宽边柄禁用且不记录历史',lambda:drag_handle('e',30,0),lambda b,a:a['coords']==b['coords'] and a['undo']==b['undo'])
            step('零宽选区仍可单轴拉伸',lambda:drag_handle('n',0,-12),lambda b,a:a['undo']==b['undo']+1
                 and all(near(x['x'],y['x']) for x,y in zip(a['pixels'],b['pixels'])))
            step('选择单点',lambda:(page.keyboard.press('Escape'),select((0,))),lambda b,a:a['indices']==[0])
            step('单点双轴缩放安全无历史',lambda:drag_handle('ne',15,-15),lambda b,a:a['coords']==b['coords'] and a['undo']==b['undo'])
            step('单点移动',lambda:drag_handle('move',20,10),lambda b,a:a['undo']==b['undo']+1 and a['coords'][1:]==b['coords'][1:])
            step('新建负缩放测试',click('#new-btn'))
            step('创建矩形节点',lambda:draw([(380,310),(500,310),(500,430),(380,430)]))
            step('开启负缩放测试',click('#tool-select'))
            step('选择矩形',select)
            step('边柄越过锚点禁用翻转',lambda:drag_handle('e',-300,0),lambda b,a:a['undo']==b['undo']+1
                 and a['pixels'][1]['x']>a['pixels'][0]['x'] and near(a['pixels'][0]['x'],b['pixels'][0]['x']))
            step('撤销压缩恢复精确坐标',click('#undo-btn'),lambda b,a:a['coords']==records[-2]['after']['coords'])
            step('空白点击不选点、不加历史',lambda:page.mouse.click(*stage_xy({'x':300,'y':600})),
                 lambda b,a:not a['indices'] and a['coords']==b['coords'] and a['undo']==b['undo'])
            step('重新框选供舞台外松手测试',select)
            step('拖出舞台后松手仍只提交一次',lambda:drag_handle('move',-450,0),
                 lambda b,a:a['undo']==b['undo']+1 and a['coords']!=b['coords'] and a['view']==b['view'])
            assert not errors, errors
        finally:
            ctx.tracing.stop(path=str(args.output/'trace.zip'))
            (args.output/'browser-errors.json').write_text(json.dumps(errors,ensure_ascii=False,indent=2))
            (args.output/'network.json').write_text(json.dumps(network,ensure_ascii=False,indent=2))
            browser.close()

if __name__=='__main__':
    main()
