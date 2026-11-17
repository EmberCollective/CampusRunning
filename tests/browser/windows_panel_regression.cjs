// Explicit API fixtures: exercise panel states without starting a Bluetooth process.
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const [base, output, executablePath] = process.argv.slice(2);
if (!base || !output || !executablePath) throw new Error('Usage: node windows_panel_regression.cjs URL OUTPUT CHROMIUM');
if (path.resolve(output).startsWith(path.resolve(__dirname, '../..') + path.sep)) throw new Error('OUTPUT must be outside the repository');
fs.mkdirSync(output, { recursive: true });
let browser;
(async () => {
    browser = await chromium.launch({ executablePath, headless: true });
    const page = await browser.newPage({ viewport: { width:1440, height:960 }, reducedMotion:'reduce' });
    const errors = [], checks = [], actions = [];
    page.on('pageerror', error => errors.push(error.message));
    const pass = name => { checks.push(name); console.log('PASS', name); };
    let config = { transport:'netsim', netsim_ini:'', netsim_state:'C:/lab/netsim-state.json', windows_state:'C:/lab/windows-state.json',
        config_file:'C:/lab/connection.json', data_dir:'C:/lab', python:'C:/lab/python.exe', btvs:'C:/lab/btvs.exe', tshark:'C:/lab/tshark.exe', running:false, operation:null, netsim_configured:false };
    let state = { transport:'netsim', running:false, ready:false, connected:false, stopping:false, operation:null,
        mac:'C2:7A:4D:91:0B:68', binding_address:{ value:null, medium:'virtual' }, records:[], pending:0, received:0, total_km:0, error:null };
    let probeReady = false, probeError = false, qrFailure = false, statusFailure = false;
    let logText = 'CONNECTED; fixture session\nDISCONNECTED reason=19', logFailure = false;
    await page.addInitScript(() => {
        Object.defineProperty(navigator, 'clipboard', {value:{writeText:async text => {window.copiedLog = text;}}});
    });
    await page.route('**/api/watch/**', async route => {
        const action = new URL(route.request().url()).pathname.split('/').at(-1);
        if (action === 'binding-qr') {
            // A tiny image fixture checks visibility; the real QR is decoded separately.
            return route.fulfill(qrFailure ? {status:409,json:{error:'address changed'}} :
                {contentType:'image/png',body:Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aP1sAAAAASUVORK5CYII=', 'base64')});
        }
        if (action === 'logs') {
            assert(route.request().headers()['x-watch-token']);
            return route.fulfill(logFailure ? {status:500,json:{error:'fixture unavailable'}} : {json:{text:logText,files:1}});
        }
        if (route.request().method() === 'GET') return route.fulfill(statusFailure && action === 'status' ?
            {status:503,json:{error:'fixture unavailable'}} : {json:action === 'config' ? config : state});
        actions.push(action);
        if (action === 'reset-binding') {
            assert.deepEqual(route.request().postDataJSON(), { keep_unbound:true, transport:state.transport });
            assert(!state.running && !state.operation && !state.stopping);
            assert(route.request().headers()['x-watch-token']);
            return route.fulfill({json:state});
        }
        if (action === 'config') {
            config = {...config, ...route.request().postDataJSON()};
            config.netsim_configured = !!config.netsim_ini;
            state.transport = config.transport; state.binding_address.medium = config.transport === 'windows' ? 'physical' : 'virtual';
            return route.fulfill({json:config});
        }
        if (action === 'check') {
            const draft = route.request().postDataJSON();
            if (draft.transport === 'netsim') return route.fulfill(!draft.netsim_ini ? {status:400,json:{error:'请填写模拟器生成的 netsim.ini 完整路径。'}} :
                {json:{ready:draft.netsim_ini === 'C:/lab/netsim.ini',checks:{netsim_ini:draft.netsim_ini === 'C:/lab/netsim.ini'}}});
            return route.fulfill(probeError ? {status:400,json:{error:'找不到工具，请检查程序位置'}} : {json:{ready:probeReady,checks:{python:true,bless:true,administrator:probeReady,peripheral:true,radio_on:true}}});
        }
        state.operation = action; state.running = action !== 'load';
        if (action === 'stop') { state.stopping = true; state.ready = state.connected = false; }
        return route.fulfill({json:state});
    });
    const refresh = async predicate => {
        await page.locator('#retry-status').evaluate(e => e.click());
        await page.waitForFunction(predicate);
    };
    try {
        await page.goto(base + '/#watch');
        await page.waitForFunction(() => !document.querySelector('#toggle-broadcast').disabled);
        await page.waitForFunction(() => document.querySelector('#watch-log-output').textContent.includes('DISCONNECTED'));
        await page.locator('#copy-watch-log').click();
        assert.equal(await page.evaluate(() => window.copiedLog), logText);
        await page.locator('#toggle-watch-log').click();
        assert(await page.locator('#watch-log-output').isHidden());
        await page.locator('#toggle-watch-log').click();
        pass('connection logs show real diagnostics, copy exact text and collapse without losing history');
        await page.locator('#open-settings').click();
        await page.waitForFunction(() => !document.querySelector('#apply-settings').disabled);
        assert.equal(await page.locator('#connection-config-file').innerText(), config.config_file);
        assert.equal(await page.locator('#netsim-state-path').inputValue(), config.netsim_state);
        await page.locator('#transport-choice').selectOption('windows');
        assert(await page.locator('#windows-python').isEnabled());
        await page.locator('#windows-state-path').fill('C:/lab/selected-windows.json');
        await page.locator('#windows-options details summary').click();
        assert.equal(await page.locator('#btvs-path').inputValue(), config.btvs);
        await page.locator('#environment-check').click();
        await page.waitForFunction(() => document.querySelector('#environment-result').textContent.includes('未通过'));
        assert.match(await page.locator('#environment-result').innerText(), /管理员权限/);
        assert.deepEqual(actions, ['check']);
        probeError = true;
        await page.locator('#environment-check').click();
        await page.waitForFunction(() => document.querySelector('#environment-result').textContent.includes('检查未完成'));
        probeError = false; probeReady = true;
        await page.locator('#environment-check').click();
        await page.waitForFunction(() => document.querySelector('#environment-result').textContent.includes('前置检查通过'));
        await page.locator('#windows-python').fill('C:/lab/updated-python.exe');
        assert.match(await page.locator('#environment-result').innerText(), /重新检查/);
        pass('read-only check reports missing permission, tool failure, recovery and stale inputs');
        await page.locator('#apply-settings').click();
        await page.waitForFunction(() => !document.querySelector('#settings-dialog').open);
        assert(!actions.includes('start'));
        assert.equal(config.python, 'C:/lab/updated-python.exe');
        assert.equal(config.windows_state, 'C:/lab/selected-windows.json');
        await page.waitForFunction(() => document.querySelector('#connection-help').textContent.includes('临时更名'));
        assert(await page.locator('#copy-address').isDisabled());
        pass('saving Windows configuration persists paths without starting Bluetooth');
        await page.locator('#toggle-broadcast').click();
        assert(await page.locator('#toggle-broadcast').isDisabled());
        assert.match(await page.locator('#connection-text').innerText(), /检查启动条件/);
        state.operation = null; state.ready = true;
        await refresh(() => !document.querySelector('#toggle-broadcast').disabled);
        assert(await page.locator('#copy-address').isDisabled());
        assert(await page.locator('#binding-qr').isHidden());
        state.binding_address.value = '42:23:45:67:89:AB';
        await refresh(() => !document.querySelector('#copy-address').disabled);
        await page.waitForFunction(() => !document.querySelector('#binding-qr').hidden);
        assert.match(await page.locator('#binding-qr-image').getAttribute('src'), /mac=4223456789AB$/);
        qrFailure = true; state.binding_address.value = '52:23:45:67:89:AB';
        await refresh(() => !document.querySelector('#binding-qr-error').hidden);
        assert(await page.locator('#binding-qr').isHidden());
        qrFailure = false; state.binding_address.value = '62:23:45:67:89:AB';
        await refresh(() => !document.querySelector('#binding-qr').hidden);
        assert.match(await page.locator('#binding-qr-image').getAttribute('src'), /mac=6223456789AB$/);
        statusFailure = true;
        await refresh(() => document.querySelector('#connection-text').textContent.includes('未知'));
        assert(await page.locator('#binding-qr').isHidden());
        assert.equal(await page.locator('#binding-qr-image').getAttribute('src'), null);
        statusFailure = false;
        await refresh(() => !document.querySelector('#binding-qr').hidden);
        pass('binding QR follows the advertised address, hides on unavailable status and falls back on image failure');
        assert.match(await page.locator('#address-medium').innerText(), /实体/);
        assert.match(await page.locator('#connect-scope').innerText(), /附近手机/);
        state.connected = true;
        await refresh(() => document.querySelector('#connection-text').textContent.includes('客户端'));
        assert(await page.locator('#reset-binding').isDisabled());
        pass('startup waits for this run’s address; subscription identifies a Bluetooth client');
        await page.locator('#toggle-broadcast').click();
        assert(await page.locator('#toggle-broadcast').isDisabled());
        assert.equal(await page.locator('#sample-mac').innerText(), '—');
        assert(await page.locator('#binding-qr').isHidden());
        assert.match(await page.locator('#connection-text').innerText(), /清理/);
        assert(await page.locator('#reset-binding').isDisabled());
        config.running = true; config.operation = 'stop';
        await page.locator('#open-settings').click();
        await page.waitForFunction(() => document.querySelector('#transport-choice').disabled);
        assert(await page.locator('#apply-settings').isDisabled());
        await page.locator('[data-setting-tab="maps"]').click();
        assert(await page.locator('#apply-settings').isEnabled());
        await page.keyboard.press('Escape');
        state.running = state.stopping = false; state.operation = null; state.binding_address.value = null;
        config.running = false; config.operation = null;
        await refresh(() => !document.querySelector('#toggle-broadcast').disabled);
        pass('stopping clears stale address and locks connection changes while maps remain independent');
        await page.locator('.device-facts summary').click();
        await page.locator('#reset-binding').click();
        assert.equal(await page.locator('#reset-binding-route').innerText(), 'Windows 实体蓝牙');
        assert.match(await page.locator('#reset-binding-copy').innerText(), /运动文件与接收标记均保留/);
        await page.locator('#reset-binding-dialog [data-close-dialog]').click();
        assert(!actions.includes('reset-binding'));
        await page.locator('#reset-binding').click();
        await page.locator('#confirm-reset-binding').click();
        await page.waitForFunction(() => document.querySelector('#toast').textContent.includes('本地绑定记录已删除'));
        assert.equal(actions.filter(a => a === 'reset-binding').length, 1);
        assert(!state.running);
        pass('manual reset requires stopped broadcast and confirmation; cancel does not mutate or start');
        await page.evaluate(() => WatchPanel.setCandidate({id:'windows-new-batch',count:1}));
        await page.waitForFunction(() => !document.querySelector('#load-candidate').disabled);
        await page.locator('#load-candidate').click();
        assert(await page.locator('#candidate').isVisible());
        assert(await page.locator('#load-candidate').isDisabled());
        state.loaded_job = 'windows-new-batch'; state.operation = null;
        state.records = [{date:'2026-11-16T07:00:00',distance_km:.2,duration_seconds:90,received:false}];
        state.pending = 1; state.total_km = .2;
        await refresh(() => document.querySelector('#candidate').hidden);
        assert.equal(await page.locator('#watch-records tr').count(),1);
        pass('async loading retains its candidate until the selected job is confirmed');
        for (const [width,height] of [[1440,960],[1024,768],[1280,600],[390,844]]) {
            await page.setViewportSize({width,height});
            await page.locator('#open-settings').click();
            await page.waitForFunction(() => !document.querySelector('#apply-settings').disabled);
            await page.locator('#windows-options details').evaluate(e => {e.open = true;});
            const bounds = await page.evaluate(() => {
                const dialog = document.querySelector('#settings-dialog'), body = dialog.querySelector('.settings-body');
                const r = dialog.getBoundingClientRect(), f = dialog.querySelector('.settings-footer').getBoundingClientRect();
                return {left:r.left,right:r.right,top:r.top,bottom:r.bottom,footer:f.bottom,scroll:body.scrollHeight > body.clientHeight,
                    overflow:body.scrollWidth > body.clientWidth, viewport:innerWidth, height:innerHeight,
                    bodyHeight:body.clientHeight,contentHeight:body.scrollHeight,tab:settingsTab};
            });
            assert(bounds.left >= 0 && bounds.right <= bounds.viewport && bounds.top >= 0 && bounds.bottom <= bounds.height);
            assert(bounds.footer <= bounds.height && !bounds.overflow);
            await page.screenshot({path:path.join(output,`windows-settings-${width}.png`)});
            if (height <= 844) assert(bounds.scroll, 'Long Windows configuration should scroll inside its body: ' + JSON.stringify({width,...bounds}));
            await page.keyboard.press('Escape');
            await page.screenshot({path:path.join(output,`windows-watch-${width}.png`),fullPage:true});
        }
        pass('desktop, compact desktop and mobile keep configuration in an internal scroll area');
        config.netsim_configured = false;
        await page.setViewportSize({width:1440,height:960});
        await page.locator('#open-settings').click();
        await page.waitForFunction(() => !document.querySelector('#apply-settings').disabled);
        await page.locator('#transport-choice').selectOption('netsim');
        assert(await page.locator('#netsim-source').isEnabled());
        assert(await page.locator('#apply-settings').isEnabled());
        await page.locator('#environment-check').click();
        await page.waitForFunction(() => document.querySelector('#environment-result').textContent.includes('请填写'));
        await page.locator('#netsim-source').fill('C:/lab/missing.ini');
        await page.locator('#environment-check').click();
        await page.waitForFunction(() => document.querySelector('#environment-result').textContent.includes('未通过'));
        assert.doesNotMatch(await page.locator('#environment-result').innerText(), /管理员/);
        await page.locator('#netsim-source').fill('C:/lab/netsim.ini');
        await page.locator('#environment-check').click();
        await page.waitForFunction(() => document.querySelector('#environment-result').textContent.includes('仅确认文件存在'));
        assert.equal(config.netsim_ini, '');
        const broadcasts = actions.filter(a => a === 'start' || a === 'load').length;
        await page.locator('#apply-settings').click();
        await page.waitForFunction(() => !document.querySelector('#settings-dialog').open);
        assert.equal(config.transport, 'netsim');
        assert.equal(config.netsim_ini, 'C:/lab/netsim.ini');
        assert.equal(actions.filter(a => a === 'start' || a === 'load').length, broadcasts);
        for (const [width,height] of [[1440,960],[1024,768],[390,844]]) {
            await page.setViewportSize({width,height});
            await page.locator('#open-settings').click();
            await page.waitForFunction(() => !document.querySelector('#apply-settings').disabled);
            assert.equal(await page.locator('#netsim-source').inputValue(), 'C:/lab/netsim.ini');
            assert.equal(await page.locator('#windows-python').inputValue(), config.python);
            const bounds = await page.locator('#settings-dialog').evaluate(dialog => {
                const r = dialog.getBoundingClientRect(), body = dialog.querySelector('.settings-body');
                return {left:r.left,right:r.right,bottom:r.bottom,overflow:body.scrollWidth > body.clientWidth};
            });
            assert(bounds.left >= 0 && bounds.right <= width && bounds.bottom <= height && !bounds.overflow);
            await page.screenshot({path:path.join(output,`netsim-settings-${width}.png`)});
            await page.keyboard.press('Escape');
        }
        pass('missing Netsim settings can be checked, saved and reopened without starting a broadcast at all viewport sizes');
        config.running = true; config.operation = 'stop';
        await page.locator('#open-settings').click();
        await page.waitForFunction(() => document.querySelector('#transport-choice').disabled);
        assert(await page.locator('#netsim-source').isDisabled());
        assert(await page.locator('#apply-settings').isDisabled());
        await page.keyboard.press('Escape');
        pass('Netsim configuration stays locked while broadcast cleanup is active');
        logText = Array.from({length:500}, (_,i) => `CONNECTED; event=${i} ` + 'details '.repeat(20)).join('\n');
        await refresh(() => document.querySelector('#watch-log-output').textContent.includes('event=499'));
        const logOutput = page.locator('#watch-log-output');
        assert(await logOutput.evaluate(e => e.scrollHeight > e.clientHeight));
        await logOutput.evaluate(e => {e.scrollTop=0;});
        logText += '\nCONNECTED; <img src=x onerror=alert(1)> latest event';
        await refresh(() => document.querySelector('#watch-log-output').textContent.includes('latest event'));
        assert.equal(await logOutput.evaluate(e => e.scrollTop),0);
        assert.equal(await logOutput.locator('img').count(),0);
        logFailure = true;
        await refresh(() => document.querySelector('#watch-log-status').textContent.includes('读取失败'));
        await page.locator('#copy-watch-log').click();
        assert.match(await page.evaluate(() => window.copiedLog), /^日志读取失败/);
        await page.evaluate(() => {navigator.clipboard.writeText=async () => {throw Error('denied');};});
        await page.locator('#toggle-watch-log').click();
        await page.locator('#copy-watch-log').click();
        assert.equal(await page.locator('#toggle-watch-log').innerText(), '收起');
        assert.match(await page.evaluate(() => window.getSelection().toString()), /event=499/);
        pass('long logs scroll internally, keep the reading position, render plain text and remain copyable after read or clipboard failures');
        for (const [width,height] of [[1440,960],[1024,768],[1280,600],[390,844]]) {
            await page.setViewportSize({width,height});
            const bounds = await page.locator('.watch-log-panel').evaluate(panel => {
                const r=panel.getBoundingClientRect(), button=panel.querySelector('#copy-watch-log').getBoundingClientRect();
                return {left:r.left,right:r.right,bottom:r.bottom,buttonBottom:button.bottom,overflow:panel.scrollWidth > panel.clientWidth};
            });
            assert(bounds.left >= 0 && bounds.right <= width && !bounds.overflow);
            if (width > 760) assert(bounds.bottom <= height && bounds.buttonBottom <= height, JSON.stringify({width,height,...bounds}));
            await page.screenshot({path:path.join(output,`connection-log-${width}.png`),fullPage:true});
        }
        pass('the bottom log panel and copy action stay reachable on desktop, short windows and mobile');
        assert.deepEqual(errors, []);
        fs.writeFileSync(path.join(output,'checks.json'),JSON.stringify({checks,errors},null,2));
    } finally { await browser.close(); }
})().catch(async error => { console.error(error); await browser?.close(); process.exitCode=1; });
