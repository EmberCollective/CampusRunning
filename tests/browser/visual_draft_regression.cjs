// Compare approved draft and production chrome at identical sizes and fixture data.
// Online map content and copy that changes from preview to real behavior are excluded from pixel crops.
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const { pathToFileURL } = require('node:url');
const fs = require('node:fs');
const path = require('node:path');
const [base, output, executablePath] = process.argv.slice(2);
if (!base || !output || !executablePath) throw new Error('Usage: node visual_draft_regression.cjs URL OUTPUT CHROMIUM');
const root = path.resolve(__dirname, '../..');
if (path.resolve(output).startsWith(root + path.sep)) throw new Error('OUTPUT must be outside the repository');
fs.mkdirSync(output, { recursive: true });
let activeBrowser;
(async () => {
    const browser = await chromium.launch({ executablePath, headless: true });
    activeBrowser = browser;
    const draft = await browser.newPage({ reducedMotion: 'reduce' }), app = await browser.newPage({ reducedMotion: 'reduce' });
    const errors = [], results = [];
    for (const page of [draft, app]) page.on('pageerror', error => errors.push(error.message));
    await draft.goto(pathToFileURL(path.join(root, 'docs/design/frontend-draft.html')).href);
    const fixture = await draft.evaluate(() => ({ track: DraftEditor.get('campus'), records: sampleRecords }));
    const coords = fixture.track.points.map(p => ({ longitude: 106.67 + (p.x - 500) * .5 / (111195 * Math.cos(26.42 * Math.PI / 180)), latitude: 26.42 - (p.y - 345) * .5 / 111195 }));
    const meta = { id: 'campus_default', name: fixture.track.name, description: fixture.track.description,
        lap_distance_km: fixture.track.distance / 1000, num_points: coords.length, is_clockwise: true };
    const watch = { running: true, ready: true, connected: false, mac: 'D6:41:8B:20:7E:32',
        binding_address: { value: 'C2:7A:4D:91:0B:68', medium: 'virtual' }, transport: 'netsim',
        records: fixture.records.map(r => ({ date: r.date + 'T' + r.time, distance_km: r.km, duration_seconds: r.seconds, received: r.received })),
        pending: 3, received: 5, total_km: 27.4, error: null };
    await app.route('**/*', route => {
        const url = new URL(route.request().url());
        if (!route.request().url().startsWith(base)) return route.abort();
        if (!url.pathname.startsWith('/api/')) return route.continue();
        const body = url.pathname === '/api/tracks' ? [meta] : url.pathname.endsWith('/coords') ? { ...meta, base_coordinates: coords } :
            url.pathname === '/api/watch/status' ? watch : url.pathname === '/api/templates' ? [] :
            url.pathname === '/api/watch/config' ? {transport:'netsim',python:'',btvs:'',tshark:'',running:true,netsim_configured:true} :
            url.pathname === '/api/amap-key' ? { key: '', securityJsCode: '' } :
            url.pathname === '/api/defaults' ? { default_track_id: 'campus_default' } :
            url.pathname === '/api/version' ? { version: '3.1.2' } : url.pathname.startsWith('/api/generate/') ? {
                job_id: 'visual-fixture', status: 'complete', total_files: 8,
                files: [6, 8, 10, 12, 13, 14, 15, 16].map(d => ({ date: `2026-11-${String(d).padStart(2, '0')}`, distance_km: 3.5, pace_min_per_km: 7.5, duration_seconds: 1575, filename: 'fixture.sport44' }))
            } : {};
        route.fulfill({ json: body });
    });
    const sets = {
        tracks: ['.appbar', '.viewbar', '#editor-workspace', '.editor-library', '.editor-center', '.editor-toolbar', '.canvas-wrap', '.editor-readout', '.editor-properties', '.editor-properties>.pane-footer'],
        generate: ['.appbar', '.viewbar', '.generator-layout', '.generator-settings', '.generator-content', '.overview', '.route-stage', '.route-overview-info', '#generation-results', '#generation-results>.table-toolbar', '#generation-results>.table-foot', '#generate-form>.pane-footer'],
        watch: ['.appbar', '.viewbar', '.watch-layout', '.device-pane', '.watch-content', '.stats', '.watch-records-pane', '#watch-table-scroll', '.device-pane>.pane-footer'],
        settings: ['#settings-dialog', '.settings-heading', '.settings-layout', '.settings-nav', '.settings-body', '.settings-footer']
    };
    async function rects(page, selectors) {
        return page.evaluate(selectors => Object.fromEntries(selectors.map(s => {
            const e = document.querySelector(s), r = e.getBoundingClientRect();
            return [s, { x: r.x, y: r.y + scrollY, width: r.width, height: r.height }];
        })), selectors);
    }
    async function capture(name, selectors) {
        await Promise.all([draft, app].map(p => p.evaluate(() => { document.getElementById('toast').hidden = true; scrollTo(0, 0); })));
        await app.waitForFunction(() => !document.querySelector('.leaflet-zoom-anim') && !document.querySelector('.selection-layer.is-hidden'));
        await app.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
        const a = await rects(draft, selectors), b = await rects(app, selectors);
        const expectedChanges = {};
        // Requested addition: the receipt progress occupies one extra toolbar row on mobile.
        if (name === 'watch-390') {
            const header = '.watch-records-pane > .table-toolbar';
            const row = (await app.locator(header).first().boundingBox()).height - (await draft.locator(header).first().boundingBox()).height;
            const indicator = await app.locator('#watch-progress-wrap').evaluate(e => e.getBoundingClientRect().height + parseFloat(getComputedStyle(e.parentElement).rowGap));
            if (row <= 0 || Math.abs(row - indicator) > 1) throw new Error('Mobile toolbar must grow by one progress row');
            for (const selector of ['.watch-layout', '.watch-content', '.watch-records-pane']) expectedChanges[selector] = {height:row};
            expectedChanges['#watch-table-scroll'] = {y:row};
        }
        const deltas = Object.fromEntries(selectors.map(s => [s, Math.max(...Object.keys(a[s]).map(k => Math.abs(a[s][k] + (expectedChanges[s]?.[k] || 0) - b[s][k])))]));
        results.push({ name, draft: a, implementation: b, expectedChanges, deltas });
        for (const [label, page] of [['draft', draft], ['implementation', app]])
            await page.screenshot({ path: path.join(output, name + '-' + label + '.png'), fullPage: true });
        console.log(name, 'max frame difference', Math.max(...Object.values(deltas)).toFixed(2), 'px');
    }
    for (const [width, height] of [[1440, 960], [1024, 768], [390, 844], [2560, 1440]]) {
        for (const page of [draft, app]) await page.setViewportSize({ width, height });
        await app.goto(base + '/?visualViewport=' + width + '#tracks');
        await app.waitForFunction(() => TrackEditor.isReady() && points.length > 0);
        await draft.evaluate(() => { location.hash = 'tracks'; });
        await Promise.all([draft, app].map(p => p.locator('#select-all').click()));
        await capture(`editor-${width}`, sets.tracks);
        const rotation = await app.locator('.shape-handle-rot').boundingBox();
        const canvas = await app.locator('.canvas-wrap').boundingBox();
        if (rotation.y < canvas.y || rotation.y + rotation.height > canvas.y + canvas.height)
            throw new Error('Rotation handle is clipped at viewport ' + width);
        // Pixel crops contain unchanged controls, with no map or live text normalization.
        if (width === 1440) {
            for (const [name, selector] of [['toolbar', '.editor-toolbar'], ['shapes', '.shape-picker'], ['selection', '#selection-properties']])
                for (const [label, page] of [['draft', draft], ['implementation', app]])
                    await page.locator(selector).screenshot({ path: path.join(output, `crop-${name}-${label}.png`) });
        }
        await Promise.all([draft, app].map(p => p.locator('[data-nav="generate"]').click()));
        for (const page of [draft, app]) {
            await page.locator('[data-mode="dates"]').click();
            await page.locator('#clear-dates').click();
            await page.locator('#calendar-month').fill('2026-11'); await page.locator('#calendar-month').press('Tab');
            for (const d of [6, 8, 10, 12, 13, 14, 15, 16]) await page.locator(`[data-date="2026-11-${String(d).padStart(2, '0')}"]`).click();
            await page.locator('#generate-form button[type="submit"]').click();
        }
        await app.waitForFunction(() => document.querySelectorAll('#result-rows tr').length === 8);
        await capture(`generate-${width}`, sets.generate);
        if (width === 1440)
            for (const [label, page] of [['draft', draft], ['implementation', app]])
                await page.locator('#calendar-field').screenshot({ path: path.join(output, `crop-calendar-${label}.png`) });
        await Promise.all([draft, app].map(p => p.locator('[data-nav="watch"]').click()));
        await app.waitForFunction(() => document.querySelectorAll('#watch-records tr').length === 8);
        await capture(`watch-${width}`, sets.watch);
        await Promise.all([draft, app].map(p => p.locator('#open-settings').click()));
        await Promise.all([draft, app].map(p => p.locator('[data-setting-tab="maps"]').click()));
        await app.waitForFunction(() => !document.querySelector('#apply-settings').disabled);
        // Windows configuration now has functional controls; compare the unchanged settings shell on Maps.
        await capture(`settings-maps-${width}`, sets.settings);
        await Promise.all([draft, app].map(p => p.keyboard.press('Escape')));
    }
    fs.writeFileSync(path.join(output, 'geometry.json'), JSON.stringify({ results, errors }, null, 2));
    await browser.close();
    if (errors.length) throw new Error(errors.join('\n'));
    const mismatches = results.filter(r => Object.values(r.deltas).some(delta => delta > 0.1));
    if (mismatches.length) throw new Error('Layout differs from the approved draft: ' + mismatches.map(r => r.name).join(', '));
})().catch(async error => { console.error(error); await activeBrowser?.close(); process.exitCode = 1; });
