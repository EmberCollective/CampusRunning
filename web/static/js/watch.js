'use strict';
const WatchPanel = (() => {
    document.querySelector('.watch-records-pane > .table-toolbar h2').insertAdjacentHTML('afterend', `<div class="watch-progress" id="watch-progress-wrap" hidden>
        <div class="row between"><label for="watch-progress">文件接收进度</label><span class="num" id="watch-progress-text">已接收 0 / 0 · 0%</span></div>
        <progress id="watch-progress" max="1" value="0"></progress>
    </div>`);
    let snapshot = null, candidate = workbenchConfig.candidate, busy = false, refreshing = false;
    let unknown = true, filter = 'all', requestEpoch = 0;
    let logText = '', logsRefreshing = false, logsUnknown = false;
    async function refreshLogs() {
        if (logsRefreshing) return;
        logsRefreshing = true;
        try {
            const data = await requestJSON('/api/watch/logs', { timeout:6000,
                headers:{'X-Watch-Token':workbenchConfig.token} });
            const output = $('watch-log-output');
            const follow = output.scrollHeight - output.scrollTop - output.clientHeight < 32;
            if (data.text !== logText) {
                logText = data.text; output.textContent = logText;
                if (follow) output.scrollTop = output.scrollHeight;
            }
            logsUnknown = false;
            $('watch-log-status').textContent = `最近 ${data.files} 轮 · 自动更新`;
        } catch {
            logsUnknown = true;
            $('watch-log-status').textContent = '读取失败，保留上次日志';
        } finally { logsRefreshing = false; $('copy-watch-log').disabled = !logText; }
    }
    $('copy-watch-log').onclick = async () => {
        const text = (logsUnknown ? '日志读取失败，以下为上次读取结果\n\n' : '') + logText;
        try { await navigator.clipboard.writeText(text); notify('连接日志已复制'); }
        catch {
            $('watch-log-output').hidden = false;
            $('toggle-watch-log').setAttribute('aria-expanded', 'true');
            $('toggle-watch-log').textContent = '收起';
            const range = document.createRange(); range.selectNodeContents($('watch-log-output'));
            const selection = window.getSelection(); selection.removeAllRanges(); selection.addRange(range);
            notify('已选中日志，请按 Ctrl+C 复制');
        }
    };
    $('toggle-watch-log').onclick = () => {
        const collapsed = $('toggle-watch-log').getAttribute('aria-expanded') === 'true';
        $('watch-log-output').hidden = collapsed;
        $('toggle-watch-log').setAttribute('aria-expanded', String(!collapsed));
        $('toggle-watch-log').textContent = collapsed ? '展开' : '收起';
    };
    function address() {
        if (busy || unknown || !snapshot?.running || !snapshot.ready || snapshot.stopping || snapshot.operation) return null;
        const value = snapshot.binding_address?.value;
        return typeof value === 'string' && /^(?:[0-9A-F]{2}:){5}[0-9A-F]{2}$/.test(value) ? value : null;
    }
    function renderRecords() {
        const records = snapshot?.records || [];
        const visible = records.filter(row => filter === 'all' || (filter === 'received' ? row.received : !row.received));
        $('watch-records').replaceChildren();
        for (const record of [...visible].sort((a, b) => b.date.localeCompare(a.date))) {
            const row = document.createElement('tr'), date = document.createElement('td');
            date.textContent = record.date.slice(0, 10);
            const time = document.createElement('span'); time.className = 'date-time num'; time.textContent = record.date.slice(11, 19); date.append(time); row.append(date);
            for (const value of [record.distance_km.toFixed(2), timeLabel(record.duration_seconds)]) {
                const cell = document.createElement('td'); cell.className = 'num'; cell.textContent = value; row.append(cell);
            }
            const status = document.createElement('td'), label = document.createElement('span');
            label.className = 'pill' + (record.received ? ' positive' : ''); label.textContent = record.received ? '已接收' : '待接收'; status.append(label); row.append(status);
            $('watch-records').append(row);
        }
        const pending = records.filter(r => !r.received).length, received = records.length - pending;
        const progress = $('watch-progress'), percent = records.length ? Math.round(received / records.length * 100) : 0;
        $('watch-progress-wrap').hidden = !records.length;
        $('watch-progress-wrap').classList.toggle('is-stale', unknown);
        progress.max = records.length || 1; progress.value = received;
        const progressText = `${unknown ? '上次确认 ' : '已接收 '}${received} / ${records.length} · ${percent}%`;
        $('watch-progress-text').textContent = progressText;
        progress.setAttribute('aria-valuetext', progressText + (unknown ? '，当前状态未知' : '，文件接收不代表活动有效'));
        progress.textContent = progressText;
        for (const [id, value] of Object.entries({ 'all-count': records.length, 'pending-count': snapshot ? pending : '—',
            'received-count': snapshot ? received : '—', 'tab-pending': pending, 'tab-received': received,
            'total-km': snapshot ? snapshot.total_km.toFixed(2) : '—', 'visible-record-count': `${visible.length} 条记录` })) $(id).textContent = value;
        $('empty-records').hidden = visible.length > 0;
        $('empty-action').hidden = records.length > 0 || unknown;
        $('empty-title').textContent = unknown && !snapshot ? '暂时无法读取记录' : records.length ? '这个分类没有记录' : '还没有载入记录';
        $('empty-copy').textContent = unknown && !snapshot ? '恢复本地服务后点击“重新检查”' : records.length ? '切换到“全部”查看本批记录' : '先生成 B5 手表记录，再载入这里';
        $('candidate').hidden = !candidate; $('candidate-count').textContent = candidate?.count || 0;
        const working = busy || snapshot?.operation || snapshot?.stopping;
        const blocked = working || unknown || pending > 0 || !!snapshot?.error;
        $('load-candidate').disabled = blocked; $('load-blocked').hidden = !blocked;
        $('load-blocked').textContent = working ? '正在处理本次操作，请稍候' : unknown ? '连接状态未知，重新检查后再载入' : pending ? '当前还有待接收记录，完成后再载入下一批' : snapshot?.error || '';
        $('step-load').className = 'step' + (records.length ? ' done' : ' current');
        $('step-load').querySelector('.step-index').textContent = records.length ? '✓' : '1';
        $('step-load-title').textContent = records.length ? '记录已载入' : '先生成并载入记录';
        $('step-loaded').textContent = records.length ? `${records.length} 条记录，源文件保留` : '空目录可以先连接，不会发送活动';
        $('step-receipt-copy').textContent = pending ? `剩余 ${pending} 条，等待 Keep 读取` : records.length ? '本批文件接收完成，请核对活动' : '载入并连接后再接收';
    }
    function render() {
        const running = !unknown && snapshot?.running, connected = running && snapshot.connected;
        const physical = snapshot?.transport === 'windows', stopping = snapshot?.stopping || snapshot?.operation === 'stop';
        const working = busy || snapshot?.operation || stopping;
        const ready = running && snapshot.ready, validAddress = address();
        const title = unknown ? '连接状态未知' : stopping ? '正在停止并清理…' : snapshot?.operation === 'load' ? '正在载入记录…' : snapshot?.operation === 'start' ? '正在检查启动条件…' :
            !running ? '广播已停止' : connected ? '蓝牙客户端已连接' : !validAddress ? '正在确认广播与地址…' : ready ? '等待 Keep 连接' : '正在启动广播…';
        document.querySelector('.device-mode').textContent = physical ? 'Windows · 实体蓝牙广播' : '安卓模拟器 · 虚拟广播';
        $('connection-text').textContent = title;
        $('nav-status').textContent = title;
        $('connection-help').textContent = unknown ? '无法读取本地服务。保留上次记录，重新检查前不显示为已连接' :
            snapshot.error || (stopping ? '等待广播退出和名称恢复，完成前请勿关闭面板' : !running ?
                physical ? '启动将临时更名并重启电脑蓝牙，其他蓝牙连接可能短暂断开' : '记录和接收标记保留。启动广播后再到 Keep 中检查连接' :
                connected ? '蓝牙客户端已订阅；请在 Keep 核对连接，文件接收以列表为准' : !validAddress ? '等待本轮有效地址，确认前不能复制或复用旧值' :
                physical ? '请在附近手机的官方 Keep 中连接 B5；本轮广播最长 1 小时' : '请在同一已准备好的官方模拟器里连接 B5');
        $('connection-pill').className = 'pill' + (connected ? ' positive' : ready ? ' waiting' : '');
        $('sample-mac').textContent = validAddress?.replaceAll(':', '') || '—';
        const qrImage = $('binding-qr-image'), qrMac = validAddress?.replaceAll(':', '') || '';
        if (qrImage.dataset.mac !== qrMac) {
            qrImage.dataset.mac = qrMac;
            if (qrMac) qrImage.src = '/api/watch/binding-qr?mac=' + qrMac;
            else qrImage.removeAttribute('src');
        }
        $('binding-qr').hidden = !qrMac || !qrImage.complete || !qrImage.naturalWidth;
        $('binding-qr-error').hidden = !qrMac || !qrImage.complete || !!qrImage.naturalWidth;
        $('dialog-mac').textContent = $('sample-mac').textContent;
        $('settings-binding-address').textContent = validAddress ? validAddress + (physical ? ' · 实体' : ' · 虚拟') : '未知 / 已失效';
        $('device-identity').textContent = snapshot?.mac || '—';
        $('copy-address').disabled = $('dialog-copy').disabled = !validAddress;
        $('address-medium').textContent = validAddress ? physical ? '实体广播地址' : '虚拟地址' : '地址不可用';
        $('address-help').textContent = validAddress ? physical ? '来自本轮 HCI 观察，重启后可能变化' : '附近实体手机看不到这个虚拟地址' : '不使用设备业务身份或电脑永久地址代替';
        $('connect-scope').textContent = physical ? '当前是 Windows 实体广播：在附近手机的官方 Keep 中操作；如果地址变化，先在 Keep 解绑后按新地址重新添加。iOS 尚未通过验收' :
            '当前是虚拟广播：在同一已准备好的官方模拟器中操作 Keep，附近实体手机看不到这个地址';
        $('toggle-broadcast').disabled = working || unknown;
        $('reset-binding').disabled = $('confirm-reset-binding').disabled = working || unknown || !!running;
        $('reset-binding-help').textContent = unknown ? '等待读取状态后再操作' : working || running ?
            '先停止广播并等待退出清理完成，再删除本地绑定记录' : '仅在 Keep 已解绑或已没有 B5 时使用；保留运动数据与接收标记';
        $('toggle-broadcast').querySelector('span').textContent = working ? stopping ? '等待退出清理…' : '正在处理…' : running ? '停止广播' : '启动广播';
        $('toggle-broadcast').querySelector('use').setAttribute('href', running ? '#i-stop' : '#i-play');
        $('state-warning').hidden = !unknown && !snapshot?.error;
        $('state-warning').querySelector('span').textContent = unknown ? '连接状态未知，保留上次记录。恢复本地服务后重新检查' : snapshot?.error || '';
        $('retry-status').disabled = busy || refreshing;
        $('step-connect').className = 'step' + (connected ? ' done' : ready ? ' current' : '');
        $('step-connect-title').textContent = unknown ? '先恢复状态读取' : stopping ? '等待退出清理' : !running ? '先启动广播' : !validAddress ? '等待确认本轮地址' : connected ? '核对 Keep 连接' : '在 Keep 里连接 B5';
        $('step-connect-copy').textContent = connected ? '连接与文件接收分开核对' : '使用当前有效地址，避免复用过期地址';
        const complete = snapshot?.records.length > 0 && snapshot.pending === 0;
        $('step-receipt').className = 'step' + (complete ? ' done' : connected ? ' current' : '');
        $('step-receipt-title').textContent = complete ? '本批文件已接收' : '等 Keep 接收文件';
        renderRecords();
    }
    async function refresh() {
        if (refreshing || busy) return;
        refreshing = true; const epoch = requestEpoch;
        const logs = refreshLogs();
        try {
            const data = await requestJSON('/api/watch/status', { timeout: 6000 });
            if (epoch !== requestEpoch) return;
            snapshot = data; unknown = false;
            if (candidate && snapshot.loaded_job === candidate.id && !snapshot.operation) {
                candidate = null;
                notify(snapshot.error ? '记录已载入，广播启动失败；请查看连接提示' : '本批记录已载入；等待 Keep 连接并读取文件');
            }
            $('watch-updated').textContent = '状态已更新';
        } catch {
            if (epoch !== requestEpoch) return;
            unknown = true; $('watch-updated').textContent = '上次读取失败';
        } finally { refreshing = false; render(); }
        await logs;
    }
    async function act(action, body = {}) {
        if (busy || unknown || !snapshot || snapshot.operation || snapshot.stopping) return;
        if (action === 'load' && (snapshot.pending > 0 || snapshot.error)) return;
        if (action === 'reset-binding' && snapshot.running) return;
        busy = true; requestEpoch++; render();
        try {
            snapshot = await postJSON('/api/watch/' + action, body, 25000); unknown = false;
            notify(snapshot.operation ? action === 'stop' ? '停止请求已发送，等待名称恢复和退出清理' : '请求已受理，等待操作完成' :
                action === 'stop' ? '广播已停止，记录与接收标记保留' : action === 'reset-binding' ?
                    '本地绑定记录已删除；请启动广播，再到 Keep 添加 B5。运动数据与接收标记保留' : '已请求启动，等待确认广播与地址');
        } catch (error) {
            unknown = true;
            notify('操作结果待确认：' + error.message + '。重新检查状态后再操作');
        } finally { busy = false; render(); await refresh(); }
    }
    async function copy() {
        const value = address(); if (!value) return;
        try { await navigator.clipboard.writeText(value.replaceAll(':', '')); notify('本轮有效地址已复制'); }
        catch { showInfo('请手动复制地址', `浏览器未允许自动复制。本轮可填写地址：${value.replaceAll(':', '')}`); }
    }
    document.querySelectorAll('[data-filter]').forEach(button => button.onclick = () => {
        filter = button.dataset.filter;
        document.querySelectorAll('[data-filter]').forEach(b => b.setAttribute('aria-pressed', String(b === button))); renderRecords();
    });
    $('toggle-broadcast').onclick = () => act(snapshot.running ? 'stop' : 'start');
    let resetTransport = null;
    $('reset-binding').onclick = () => {
        resetTransport = snapshot.transport;
        $('reset-binding-route').textContent = resetTransport === 'windows' ? 'Windows 实体蓝牙' : '安卓模拟器';
        $('reset-binding-dialog').showModal();
    };
    $('confirm-reset-binding').onclick = () => {
        $('reset-binding-dialog').close();
        act('reset-binding', { keep_unbound: true, transport: resetTransport });
    };
    $('copy-address').onclick = $('dialog-copy').onclick = copy;
    $('binding-qr-image').onload = $('binding-qr-image').onerror = render;
    $('retry-status').onclick = refresh;
    $('load-candidate').onclick = () => { if (candidate) act('load', { job_id: candidate.id }); };
    document.addEventListener('workbench:page', event => { if (event.detail === 'watch') refresh(); });
    document.addEventListener('workbench:connection', refresh);
    document.addEventListener('visibilitychange', () => { if (!document.hidden) refresh(); });
    setInterval(() => { if (!document.hidden && currentPage() === 'watch') refresh(); }, 2000);
    render();
    return { setCandidate(value) { candidate = value; render(); refresh(); } };
})();
