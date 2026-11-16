'use strict';
const WatchPanel = (() => {
    document.querySelector('.watch-records-pane > .table-toolbar h2').insertAdjacentHTML('afterend', `<div class="watch-progress" id="watch-progress-wrap" hidden>
        <div class="row between"><label for="watch-progress">文件接收进度</label><span class="num" id="watch-progress-text">已接收 0 / 0 · 0%</span></div>
        <progress id="watch-progress" max="1" value="0"></progress>
    </div>`);
    let snapshot = null, candidate = workbenchConfig.candidate, busy = false, refreshing = false;
    let unknown = true, filter = 'all', requestEpoch = 0;
    function address() {
        if (unknown || !snapshot?.running || !snapshot.ready) return null;
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
        const blocked = busy || unknown || pending > 0 || !!snapshot?.error;
        $('load-candidate').disabled = blocked; $('load-blocked').hidden = !blocked;
        $('load-blocked').textContent = busy ? '正在处理本次操作，请稍候' : unknown ? '连接状态未知，重新检查后再载入' : pending ? '当前还有待接收记录，完成后再载入下一批' : snapshot?.error || '';
        $('step-load').className = 'step' + (records.length ? ' done' : ' current');
        $('step-load').querySelector('.step-index').textContent = records.length ? '✓' : '1';
        $('step-load-title').textContent = records.length ? '记录已载入' : '先生成并载入记录';
        $('step-loaded').textContent = records.length ? `${records.length} 条记录，源文件保留` : '空目录可以先连接，不会发送活动';
        $('step-receipt-copy').textContent = pending ? `剩余 ${pending} 条，等待 Keep 读取` : records.length ? '本批文件接收完成，请核对活动' : '载入并连接后再接收';
    }
    function render() {
        const running = !unknown && snapshot?.running, connected = running && snapshot.connected;
        const ready = running && snapshot.ready, validAddress = address();
        const title = unknown ? '连接状态未知' : !running ? '广播已停止' : connected ? '已连接 Keep' : ready ? '等待 Keep 连接' : '正在启动广播…';
        $('connection-text').textContent = title;
        $('nav-status').textContent = title;
        $('connection-help').textContent = unknown ? '无法读取本地服务。保留上次记录，重新检查前不显示为已连接' :
            snapshot.error || (!running ? '记录和接收标记保留。启动广播后再到 Keep 中检查连接' :
                connected ? '蓝牙连接已建立，是否接收以列表为准' : ready ? '请在同一已准备好的官方模拟器里连接 B5' : '等待虚拟蓝牙环境确认广播启动');
        $('connection-pill').className = 'pill' + (connected ? ' positive' : ready ? ' waiting' : '');
        $('sample-mac').textContent = validAddress?.replaceAll(':', '') || '—';
        $('dialog-mac').textContent = $('sample-mac').textContent;
        $('settings-binding-address').textContent = validAddress ? validAddress + ' · 虚拟' : '未知 / 已失效';
        $('device-identity').textContent = snapshot?.mac || '—';
        $('copy-address').disabled = $('dialog-copy').disabled = !validAddress;
        $('address-medium').textContent = validAddress ? '虚拟地址' : '地址不可用';
        $('address-help').textContent = validAddress ? '附近实体手机看不到这个虚拟地址' : '不使用设备业务身份或电脑永久地址代替';
        $('toggle-broadcast').disabled = busy || unknown;
        $('toggle-broadcast').querySelector('span').textContent = busy ? '正在处理…' : running ? '停止广播' : '启动广播';
        $('toggle-broadcast').querySelector('use').setAttribute('href', running ? '#i-stop' : '#i-play');
        $('state-warning').hidden = !unknown && !snapshot?.error;
        $('state-warning').querySelector('span').textContent = unknown ? '连接状态未知，保留上次记录。恢复本地服务后重新检查' : snapshot?.error || '';
        $('retry-status').disabled = busy || refreshing;
        $('step-connect').className = 'step' + (connected ? ' done' : ready ? ' current' : '');
        $('step-connect-title').textContent = unknown ? '先恢复状态读取' : !running ? '先启动广播' : !validAddress ? '等待确认本轮地址' : connected ? 'Keep 已连接' : '在 Keep 里连接 B5';
        $('step-connect-copy').textContent = connected ? '连接与文件接收分开核对' : '使用当前有效地址，避免复用过期地址';
        const complete = snapshot?.records.length > 0 && snapshot.pending === 0;
        $('step-receipt').className = 'step' + (complete ? ' done' : connected ? ' current' : '');
        $('step-receipt-title').textContent = complete ? '本批文件已接收' : '等 Keep 接收文件';
        renderRecords();
    }
    async function refresh() {
        if (refreshing || busy) return;
        refreshing = true; const epoch = requestEpoch;
        try {
            const data = await requestJSON('/api/watch/status', { timeout: 6000 });
            if (epoch !== requestEpoch) return;
            snapshot = data; unknown = false;
            $('watch-updated').textContent = '状态已更新';
        } catch {
            if (epoch !== requestEpoch) return;
            unknown = true; $('watch-updated').textContent = '上次读取失败';
        } finally { refreshing = false; render(); }
    }
    async function act(action, body = {}) {
        if (busy || unknown || !snapshot) return;
        if (action === 'load' && (snapshot.pending > 0 || snapshot.error)) return;
        busy = true; requestEpoch++; render();
        try {
            snapshot = await postJSON('/api/watch/' + action, body, 25000); unknown = false;
            if (action === 'load') { candidate = null; notify('本批记录已载入；等待 Keep 连接并读取文件'); }
            else notify(action === 'stop' ? '广播已停止，记录与接收标记保留' : '已请求启动，等待确认广播与地址');
        } catch (error) {
            unknown = true;
            notify('操作结果待确认：' + error.message + '。重新检查状态后再操作');
        } finally { busy = false; render(); await refresh(); }
    }
    async function copy() {
        const value = address(); if (!value) return;
        try { await navigator.clipboard.writeText(value.replaceAll(':', '')); notify('本轮虚拟地址已复制'); }
        catch { showInfo('请手动复制地址', `浏览器未允许自动复制。本轮可填写地址：${value.replaceAll(':', '')}`); }
    }
    document.querySelectorAll('[data-filter]').forEach(button => button.onclick = () => {
        filter = button.dataset.filter;
        document.querySelectorAll('[data-filter]').forEach(b => b.setAttribute('aria-pressed', String(b === button))); renderRecords();
    });
    $('toggle-broadcast').onclick = () => act(snapshot.running ? 'stop' : 'start');
    $('copy-address').onclick = $('dialog-copy').onclick = copy;
    $('retry-status').onclick = refresh;
    $('load-candidate').onclick = () => { if (candidate) act('load', { job_id: candidate.id }); };
    document.addEventListener('workbench:page', event => { if (event.detail === 'watch') refresh(); });
    document.addEventListener('visibilitychange', () => { if (!document.hidden) refresh(); });
    setInterval(() => { if (!document.hidden && currentPage() === 'watch') refresh(); }, 2000);
    render();
    return { setCandidate(value) { candidate = value; render(); refresh(); } };
})();
