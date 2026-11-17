"""Exercise pace settings, previews and actual exports against an isolated local app."""

import argparse
import json
from pathlib import Path
from tempfile import mkdtemp

from playwright.sync_api import sync_playwright


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--chromium', required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    if output.is_relative_to(Path(__file__).resolve().parents[2]):
        parser.error('Output must be outside the repository')
    output.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=args.chromium, headless=True)
        page = browser.new_page(viewport={'width':1440, 'height':960}, reduced_motion='reduce', accept_downloads=True)
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.route('**/*', lambda route: route.continue_() if route.request.url.startswith(args.url) else route.abort())
        def preview(action):
            with page.expect_response(lambda response: response.url.endswith('/api/pace/preview')) as pending:
                action()
            response = pending.value
            assert response.ok, response.text()
            page.locator('#pace-preview-charts').wait_for(state='visible')
            assert page.locator('#pace-timeline .pace-line').count() == 1
            assert page.locator('#pace-distribution .pace-bar').count() == 10
            return response.json()
        try:
            page.goto(args.url)
            page.wait_for_function('document.querySelectorAll("#pace-algorithm option").length >= 3')
            page.locator('#pace-settings summary').click()
            samples = []
            for algorithm in ('natural', 'steady', 'progressive'):
                page.locator('#pace-algorithm').select_option(algorithm)
                data = preview(lambda: page.locator('#preview-pace').click())
                assert data['pace_algorithm'] == algorithm
                assert abs(data['times_seconds'][-1]-data['distance_km']*data['average_pace']*60) < .001
                samples.append(data['paces_min_per_km'])
                if algorithm == 'natural':
                    page.screenshot(path=str(output/'pace-preview-desktop.png'))
                    page.locator('#pace-dialog').screenshot(path=str(output/'pace-preview.png'))
                page.keyboard.press('Escape')
            assert samples[0] != samples[1] != samples[2]

            page.locator('#pace-fluctuation').uncheck()
            assert page.locator('#pace-algorithm').is_disabled()
            data = preview(lambda: page.locator('#preview-pace').click())
            assert len(set(data['paces_min_per_km'])) == 1
            page.locator('#pace-preview-distance').fill('2.25')
            page.locator('#pace-preview-average').fill('7.25')
            assert page.locator('#pace-preview-charts').is_hidden()
            data = preview(lambda: page.locator('#pace-preview-refresh').click())
            assert data['distance_km'] == 2.25 and data['average_pace'] == 7.25
            page.evaluate('''() => {
                const original = window.fetch;
                window.delayNextPreview = true;
                window.fetch = async (...args) => {
                    const response = await original(...args);
                    if (String(args[0]).endsWith('/api/pace/preview') && window.delayNextPreview) {
                        window.delayNextPreview = false;
                        await new Promise(resolve => setTimeout(resolve, 600));
                        window.delayedPreviewDone = true;
                    }
                    return response;
                };
            }''')
            page.locator('#pace-preview-refresh').click()
            page.wait_for_function('window.delayNextPreview === false')
            page.locator('#pace-preview-distance').fill('4')
            preview(lambda: page.locator('#pace-preview-refresh').click())
            page.wait_for_function('window.delayedPreviewDone === true')
            assert page.locator('#pace-preview-summary').inner_text().startswith('4 km')
            page.keyboard.press('Escape')
            page.locator('#pace-fluctuation').check()

            page.route('**/api/pace/preview', lambda route: route.fulfill(status=400, json={'error':'Temporary preview error'}))
            page.locator('#preview-pace').click()
            page.wait_for_function('document.querySelector("#pace-preview-status").textContent.includes("Temporary preview error")')
            assert page.locator('#pace-preview-charts').is_hidden()
            assert page.locator('#pace-preview-refresh').is_enabled()
            page.unroute('**/api/pace/preview')
            preview(lambda: page.locator('#pace-preview-refresh').click())
            page.keyboard.press('Escape')

            template = {'id':'pace_test', 'name':'Pace sample', 'generation_config':{'pace_algorithm':'steady', 'pace_intensity':.3}}
            page.locator('#template-upload').set_input_files({'name':'pace.json', 'mimeType':'application/json', 'buffer':json.dumps(template).encode()})
            page.wait_for_function('document.querySelector("#pace-algorithm").value === "steady"')
            assert page.locator('#pace-intensity').input_value() == '0.3'
            page.locator('#save-template').click()
            page.locator('#template-name').fill('Pace settings')
            with page.expect_download() as download:
                page.locator('#template-form button[type=submit]').click()
            saved = output/'pace-template.json'
            download.value.save_as(saved)
            config = json.loads(saved.read_text())['daily_config']
            assert config['pace_algorithm'] == 'steady' and config['pace_intensity'] == .3

            page.locator('[data-mode=single]').click()
            page.locator('#single-distance').fill('3.2')
            page.locator('#min-pace').fill('7.5')
            page.locator('#max-pace').fill('7.5')
            page.locator('#advanced-section summary').click()
            generated = Path(mkdtemp(prefix='exports-', dir=output))/'generated'
            page.locator('#output-directory').fill(str(generated))
            assert not generated.exists()
            for fmt in ('tcx', 'fit'):
                page.locator('#output-format').select_option(fmt)
                with page.expect_response(lambda response: '/api/generate/single' in response.url) as pending:
                    page.locator('#generate-button').click()
                response = pending.value
                assert response.ok, response.text()
                record, = response.json()['files']
                assert abs(record['duration_seconds']-3.2*7.5*60) <= 1.001
                assert (generated/record['filename']).is_file()

            for width, height in ((1280,720), (390,844)):
                page.set_viewport_size({'width':width, 'height':height})
                preview(lambda: page.locator('#preview-pace').click())
                bounds = page.locator('#pace-dialog').bounding_box()
                assert bounds['x'] >= 0 and bounds['x']+bounds['width'] <= width+1
                assert bounds['y'] >= 0 and bounds['y']+bounds['height'] <= height+1
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
                page.screenshot(path=str(output/f'pace-preview-{width}.png'))
                page.keyboard.press('Escape')
            assert not errors, errors
            print('PASS: algorithms, weighted previews, uniform mode, edits, error recovery, template round trip, FIT/TCX exports and responsive layout')
        finally:
            browser.close()


if __name__ == '__main__':
    main()
