"""真实生成/下载及工作台布局回归；只对隔离配置的 Flask 服务运行。

--output 必须在仓库外。矩阵使用明确标记的合成 API 结果，真实四模式另验。
"""
import argparse
import json
from pathlib import Path
from zipfile import ZipFile, is_zipfile

from playwright.sync_api import sync_playwright


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', default='http://127.0.0.1:5174')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--chromium', default='/usr/bin/chromium')
    args = parser.parse_args()
    args.output = args.output.resolve()
    root = Path(__file__).resolve().parents[2]
    if args.output.is_relative_to(root):
        parser.error('--output 必须在仓库外')
    args.output.mkdir(parents=True, exist_ok=True)
    records, errors = [], []
    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=args.chromium, headless=True)
        ctx = browser.new_context(viewport={'width': 1440, 'height': 960}, accept_downloads=True)
        ctx.route('**/*', lambda r: r.continue_() if r.request.url.startswith(args.url) else r.abort())
        page = ctx.new_page()
        page.on('pageerror', lambda e: errors.append(str(e)))

        def record(name):
            records.append({'name': name, 'result': 'PASS'})
            print('PASS', name, flush=True)

        def metrics():
            return page.evaluate('''() => {
                const rect=s=>{const r=document.querySelector(s).getBoundingClientRect();return {top:r.top,bottom:r.bottom,height:r.height,width:r.width}};
                const box=document.querySelector('#generation-results .table-scroll');
                return {settings:rect('.generator-settings'),content:rect('.generator-content'),results:rect('#generation-results'),
                    footer:rect('.statusbar'),scrollHeight:box.scrollHeight,clientHeight:box.clientHeight,scrollTop:box.scrollTop,
                    width:innerWidth,height:innerHeight,docWidth:document.documentElement.scrollWidth,docHeight:document.documentElement.scrollHeight};
            }''')

        def check(m):
            assert m['docWidth'] <= m['width'], m
            if m['width'] > 760:
                assert m['docHeight'] == m['height'], m
                assert abs(m['settings']['bottom'] - m['content']['bottom']) <= 1, m
                assert m['results']['bottom'] <= m['footer']['top'], m
                assert m['clientHeight'] > 60, m

        def submit():
            with page.expect_response(lambda r: '/api/generate/' in r.url) as pending:
                page.locator('#generate-button').click()
            response = pending.value
            result = response.json()
            assert response.ok, result
            page.wait_for_function('n => document.querySelectorAll("#result-rows tr").length===n', arg=result['total_files'])
            page.wait_for_function('!document.querySelector("#generate-button").disabled')
            return result

        def generate(mode, fields, fmt, label):
            page.locator(f'[data-mode="{mode}"]').click()
            page.locator('#output-format').select_option(fmt)
            details = page.locator('#advanced-section details')
            if not details.evaluate('(e)=>e.open'):
                details.locator('summary').click()
            for selector, value in fields.items():
                page.locator(selector).fill(value)
            page.locator('#output-directory').fill(str(args.output / 'generated' / label))
            result = submit()
            with page.expect_download() as pending:
                page.locator('#result-next').click()
            download = pending.value
            dest = args.output / (label + '-' + download.suggested_filename)
            download.save_as(dest)
            if is_zipfile(dest):
                with ZipFile(dest) as archive:
                    assert len(archive.namelist()) == result['total_files']
                    assert all(name.endswith('.' + fmt) for name in archive.namelist())
            else:
                assert result['total_files'] == 1 and dest.suffix == '.' + fmt
            check(metrics())
            record(label)
            return metrics()

        try:
            page.goto(args.url)
            page.wait_for_function('document.querySelectorAll("#track-choice option").length>1')
            page.wait_for_function('document.querySelectorAll("#template-choice option").length>2')
            short = generate('daily', {'#start-date': '2026-01-01', '#end-date': '2026-01-01', '#min-distance': '0.2', '#max-distance': '0.2'}, 'fit', 'real-short-fit')
            long = generate('daily', {'#end-date': '2026-03-31'}, 'fit', 'real-long-fit')
            assert abs(short['results']['bottom'] - long['results']['bottom']) <= 1
            assert long['scrollHeight'] > long['clientHeight']
            box = page.locator('#generation-results .table-scroll')
            box.evaluate('(e)=>e.scrollTop=e.scrollHeight')
            assert box.evaluate('''e=>{const b=e.getBoundingClientRect(),h=e.querySelector('th').getBoundingClientRect(),last=e.querySelector('tbody tr:last-child').getBoundingClientRect();return Math.abs(b.top-h.top)<=1&&last.bottom<=b.bottom+1}''')
            page.screenshot(path=str(args.output / 'long-results.png'), full_page=True)
            again = generate('daily', {'#end-date': '2026-01-01'}, 'fit', 'real-short-again')
            assert abs(short['results']['bottom'] - again['results']['bottom']) <= 1 and again['scrollTop'] == 0
            record('short-long-short-stable-boundary-and-sticky-header')
            generate('total', {'#start-date': '2026-01-01', '#end-date': '2026-01-06', '#total-distance': '1.2', '#min-daily': '0.2', '#max-daily': '0.3', '#rest-days': '0'}, 'fit', 'real-total')
            generate('single', {'#start-date': '2026-01-01', '#single-distance': '0.2'}, 'tcx', 'real-single-tcx')
            page.locator('[data-mode="dates"]').click()
            page.locator('#clear-dates').click()
            page.locator('#calendar-month').fill('2026-01')
            page.locator('#calendar-month').press('Tab')
            page.locator('[data-date="2026-01-31"]').click()
            page.locator('#next-month').click()
            page.locator('[data-date="2026-02-02"]').click()
            assert page.locator('.date-chip').count() == 2
            generate('dates', {'#min-distance': '0.2', '#max-distance': '0.2'}, 'tcx', 'real-cross-month-dates')
            page.locator('#min-distance').fill('0.3')
            assert page.locator('#result-next').is_disabled()
            record('changed-parameters-disable-old-result')

            synthetic_count = [1]
            def synthetic(route):
                n = synthetic_count[0]
                route.fulfill(json={'job_id': 'layout-fixture', 'status': 'complete', 'total_files': n,
                    'files': [{'date': '2026-01-01', 'distance_km': 1., 'duration_seconds': 450, 'pace_min_per_km': 7.5, 'filename': 'fixture.fit'} for _ in range(n)]})
            page.route('**/api/generate/*', synthetic)
            for width, height in [(320, 800), (390, 844), (600, 900), (760, 900), (800, 800), (1024, 768), (1440, 960), (1920, 1080), (2560, 1440)]:
                page.set_viewport_size({'width': width, 'height': height})
                for mode in ['daily', 'total', 'single', 'dates']:
                    page.locator(f'[data-mode="{mode}"]').click()
                    for selector, value in {'#start-date': '2026-01-01', '#end-date': '2026-01-02', '#min-distance': '0.2', '#max-distance': '0.2'}.items():
                        page.locator(selector).evaluate('(e,v)=>e.value=v', value)
                    synthetic_count[0] = 1; submit(); first = metrics(); check(first)
                    synthetic_count[0] = 1000; submit(); many = metrics(); check(many)
                    assert many['scrollHeight'] > many['clientHeight'], many
                    if width > 760:
                        assert abs(first['results']['bottom'] - many['results']['bottom']) <= 1
                    record(f'layout-{mode}-{width}x{height}-1-1000')
            assert not errors, errors
            record('no-page-errors')
        finally:
            (args.output / 'results.json').write_text(json.dumps({'checks': records, 'errors': errors}, ensure_ascii=False, indent=2), encoding='utf-8')
            browser.close()


if __name__ == '__main__':
    main()
