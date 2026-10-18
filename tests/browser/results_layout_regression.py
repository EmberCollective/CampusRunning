"""Check result boundaries in a real browser against an isolated Flask server.

Use synthetic tracks and a disposable server working directory. The script
generates real FIT/TCX files under --output and writes screenshots/trace there.

python tests/browser/results_layout_regression.py --url http://127.0.0.1:5053 \
    --output /tmp/pr53-rework --chromium /usr/bin/chromium
"""

import argparse
import json
from pathlib import Path
from zipfile import ZipFile, is_zipfile

from playwright.sync_api import sync_playwright


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', default='http://127.0.0.1:5053')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--chromium', default='/usr/bin/chromium')
    args = parser.parse_args()
    args.output = args.output.resolve()
    shots = args.output / 'screenshots'
    shots.mkdir(parents=True, exist_ok=True)
    records, errors = [], []

    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=args.chromium, headless=True,
                                     args=['--no-sandbox'])
        ctx = browser.new_context(viewport={'width': 1600, 'height': 900}, accept_downloads=True)
        # External map images/fonts are outside this layout regression.
        ctx.route('**/*', lambda route: route.continue_()
                  if route.request.url.startswith(args.url) else route.abort())
        ctx.tracing.start(screenshots=True, snapshots=True, sources=True)
        page = ctx.new_page()
        page.on('pageerror', lambda error: errors.append(str(error)))

        def record(name, detail):
            records.append({'name': name, 'result': 'PASS', 'detail': detail})
            (args.output / 'results.json').write_text(json.dumps(records, ensure_ascii=False, indent=2))
            print('PASS', name, json.dumps(detail, ensure_ascii=False), flush=True)

        def metrics():
            return page.evaluate('''() => {
                const rect = selector => {
                    const e = document.querySelector(selector), r = e.getBoundingClientRect();
                    return {top: r.top + scrollY, bottom: r.bottom + scrollY,
                        height: r.height, width: r.width};
                };
                const box = document.querySelector('.results-scroll');
                return {main: rect('.param-main'), side: rect('.cfg-side'),
                    area: rect('.results-area'), card: rect('.results-section'),
                    footer: rect('.statusbar'), viewport: {width: innerWidth, height: innerHeight},
                    documentHeight: document.documentElement.scrollHeight,
                    documentWidth: document.documentElement.scrollWidth,
                    rows: box.querySelectorAll('tbody tr').length,
                    scrollHeight: box.scrollHeight, clientHeight: box.clientHeight,
                    scrollTop: box.scrollTop, scrollWidth: box.scrollWidth,
                    clientWidth: box.clientWidth};
            }''')

        def same_boundary(before, after):
            for key in ('main', 'card', 'footer'):
                assert abs(before[key]['bottom'] - after[key]['bottom']) <= 1, (key, before, after)
            for key in ('documentHeight', 'documentWidth'):
                assert abs(before[key] - after[key]) <= 1, (key, before, after)

        def check_layout(m):
            # The card stays inside the main panel's original 16px bottom inset.
            assert abs(m['main']['bottom'] - m['card']['bottom'] - 17) <= 1, m
            assert m['card']['height'] <= m['viewport']['height'] - 56 + 1, m
            assert m['clientHeight'] >= 50, m
            if m['viewport']['width'] > 960:
                assert abs(m['main']['bottom'] - m['side']['bottom']) <= 1, m
            else:
                assert m['main']['top'] >= m['side']['bottom'], m

        def shot(name, full=False):
            page.evaluate('scrollTo({top:0,behavior:"instant"})') if full else page.locator(
                '#results-section').evaluate('(e) => e.scrollIntoView({block:"start",behavior:"instant"})')
            dest = shots / (name + '.png')
            page.screenshot(path=str(dest), full_page=full)
            return str(dest)

        def render(count):
            page.evaluate('''n => showResults({files: Array.from({length:n}, (_, i) => ({
                date: new Date(Date.UTC(2026,0,1+i)).toISOString().slice(0,10),
                distance_km: 0.2, pace_min_per_km: 7, duration_seconds: 84, calories: 12
            }))})''', count)
            page.evaluate('scrollTo({top:0,behavior:"instant"})')

        def generate(mode, fields, fmt, label):
            page.locator(f'[data-mode="{mode}"]').click()
            for selector, value in fields.items():
                page.locator(selector).fill(value)
            page.locator(f'#{mode}-output-dir').fill(str(args.output / 'generated' / label))
            page.locator(f'#{mode}-output-format').select_option(fmt)
            with page.expect_response(lambda r: r.url.endswith('/api/generate/' + mode)) as pending:
                page.locator(f'#{mode}-form button[type="submit"]').click()
            response = pending.value
            result = response.json()
            assert response.ok and result['total_files'] > 0, result
            page.wait_for_function('n => document.querySelectorAll("#results-body tr").length === n',
                                   arg=result['total_files'])
            page.wait_for_timeout(400)
            assert metrics()['scrollTop'] == 0, metrics()
            check_layout(metrics())
            with page.expect_download() as pending:
                page.locator('#download-btn').click()
            download = pending.value
            dest = args.output / (label + '-' + download.suggested_filename)
            download.save_as(dest)
            if is_zipfile(dest):
                with ZipFile(dest) as archive:
                    assert len(archive.namelist()) == result['total_files']
                    assert all(name.endswith('.' + fmt) for name in archive.namelist())
            else:
                assert result['total_files'] == 1 and dest.suffix == '.' + fmt
            record(label, {'mode': mode, 'files': result['total_files'], 'format': fmt,
                           'download': str(dest), 'metrics': metrics()})
            return metrics()

        try:
            page.goto(args.url, wait_until='domcontentloaded')
            page.wait_for_function('document.querySelectorAll("#template-select option").length > 2')
            page.wait_for_timeout(100)
            assert not page.locator('#results-section').is_visible()
            initial = metrics()

            short = generate('daily', {'#daily-start-date': '2026-01-01', '#daily-end-date': '2026-01-01',
                                      '#daily-min-km': '0.2', '#daily-max-km': '0.2'}, 'fit', 'real-short')
            assert abs(initial['main']['bottom'] - short['main']['bottom']) <= 1
            shot('01-desktop-real-short', True)
            long = generate('daily', {'#daily-end-date': '2026-03-31'}, 'fit', 'real-long')
            same_boundary(short, long)
            assert long['scrollHeight'] > long['clientHeight']
            shot('02-desktop-real-long', True)
            record('real-short-long-boundary', {'short': short, 'long': long})

            box = page.locator('.results-scroll')
            box.evaluate('(e) => e.scrollTop = e.scrollHeight')
            assert box.evaluate('''e => {
                const b=e.getBoundingClientRect(), h=e.querySelector('th').getBoundingClientRect();
                const last=e.querySelector('tbody tr:last-child').getBoundingClientRect();
                return Math.abs(h.top-b.top)<=1 && last.bottom<=b.bottom+1 && last.top>=h.bottom;
            }''')
            shot('03-desktop-scrolled-last-row', True)
            before_scroll = page.evaluate('scrollY')
            b = box.bounding_box()
            page.mouse.move(b['x'] + b['width']/2, b['y'] + b['height']/2)
            page.mouse.wheel(0, 500)
            page.wait_for_timeout(200)
            assert abs(page.evaluate('scrollY') - before_scroll) <= 1
            record('sticky-last-row-and-no-scroll-chaining', metrics())

            again = generate('daily', {'#daily-end-date': '2026-01-01'}, 'fit', 'real-short-again')
            same_boundary(short, again)
            record('real-long-short-boundary', {'first': short, 'again': again})
            before = metrics()
            page.wait_for_timeout(5200)
            same_boundary(before, metrics())
            record('feedback-timeout-keeps-boundary', metrics())

            # Different form heights, breakpoint crossing and small windows. Stress
            # data exercises layout only; real backend/downloads are checked above/below.
            viewports = [(1600, 900), (1200, 800), (961, 700), (900, 900),
                         (900, 700), (900, 240), (390, 844), (390, 240), (1600, 240)]
            for mode in ('daily', 'total', 'single', 'dates'):
                page.locator(f'[data-mode="{mode}"]').click()
                for width, height in viewports:
                    page.set_viewport_size({'width': width, 'height': height})
                    render(1)
                    first = metrics()
                    check_layout(first)
                    render(1000)
                    many = metrics()
                    check_layout(many)
                    same_boundary(first, many)
                    assert many['scrollHeight'] > many['clientHeight'], many
                    box.evaluate('(e) => e.scrollTop = e.scrollHeight')
                    page.locator('#results-section').evaluate('(e) => e.scrollIntoView({block:"start",behavior:"instant"})')
                    assert box.evaluate('''e => {
                        const b=e.getBoundingClientRect(), h=e.querySelector('th').getBoundingClientRect();
                        const toolbar=document.querySelector('.topbar').getBoundingClientRect();
                        const card=document.querySelector('#results-section').getBoundingClientRect();
                        return h.top >= toolbar.bottom && Math.abs(h.top-b.top)<=1
                            && card.bottom<=innerHeight+1;
                    }'''), metrics()
                    if mode == 'daily' and (width, height) in ((900,900),(900,240),(390,844)):
                        shot(f'matrix-{width}x{height}')
                    render(1)
                    same_boundary(first, metrics())
                    record(f'{mode}-{width}x{height}-1-1000-1', {'short': first, 'long': many})

            page.set_viewport_size({'width': 1600, 'height': 900})
            generate('total', {'#total-start-date': '2026-01-01', '#total-end-date': '2026-01-06',
                              '#total-km': '1.2', '#total-min-daily': '0.2',
                              '#total-max-daily': '0.3', '#total-rest-days': '0'}, 'fit', 'real-total')
            generate('single', {'#single-date': '2026-01-01', '#single-distance': '0.2'}, 'tcx', 'real-single')
            page.locator('[data-mode="dates"]').click()
            page.locator('#cal-select-weekdays').click()
            generate('dates', {'#dates-min-km': '0.2', '#dates-max-km': '0.2'}, 'tcx', 'real-dates')
            assert not errors, errors
            record('no-page-errors', errors)
        finally:
            (args.output / 'errors.json').write_text(json.dumps(errors, ensure_ascii=False, indent=2))
            ctx.tracing.stop(path=str(args.output / 'trace.zip'))
            browser.close()


if __name__ == '__main__':
    main()
