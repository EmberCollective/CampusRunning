'use strict';
const PacePreview = (() => {
    let options = {}, sample = null, version = 0, seed = 42;
    const ns = 'http://www.w3.org/2000/svg';
    function node(tag, attrs, text) {
        const el = document.createElementNS(ns, tag);
        for (const [key, value] of Object.entries(attrs)) el.setAttribute(key, value);
        if (text !== undefined) el.textContent = text;
        return el;
    }
    function chart(id, low, high, end, xLabel, yLabel) {
        const svg = $(id), width = Math.max(280, svg.clientWidth), height = 210;
        svg.replaceChildren(); svg.setAttribute('viewBox', `0 0 ${width} ${height}`);
        const x = v => 54 + v / end * (width - 72), y = v => 12 + (v - low) / (high - low) * 162;
        for (let i = 0; i <= 4; i++) {
            const value = low + (high - low) * i / 4, py = y(value);
            svg.append(node('line', {x1:54, x2:width-18, y1:py, y2:py, class:'pace-grid'}));
            svg.append(node('text', {x:46, y:py+4, 'text-anchor':'end', class:'pace-axis'}, yLabel(value)));
        }
        for (let i = 0; i <= 2; i++) svg.append(node('text', {x:x(end*i/2), y:198, 'text-anchor':'middle', class:'pace-axis'}, xLabel(end*i/2)));
        return {svg, x, y};
    }
    function draw() {
        if (!sample || !$('pace-dialog').open) return;
        const paces = sample.paces_min_per_km, times = sample.times_seconds, end = times.at(-1);
        const fastest = Math.min(...paces), slowest = Math.max(...paces), padding = Math.max(.12, (slowest-fastest)*.1);
        const low = fastest-padding, high = slowest+padding;
        const timeline = chart('pace-timeline', low, high, end, timeLabel, p => timeLabel(p*60));
        timeline.svg.append(node('path', {class:'pace-line', d:paces.map((p,i) => `${i?'L':'M'}${timeline.x(times[i]).toFixed(2)},${timeline.y(p).toFixed(2)}`).join(' ')}));
        const bins = Array(10).fill(0), span = high-low;
        for (let i = 0; i < paces.length-1; i++) bins[Math.min(9, Math.floor((paces[i]-low)/span*10))] += (times[i+1]-times[i])/end*100;
        const maximum = Math.max(10, Math.ceil(Math.max(...bins)/10)*10);
        const histogram = chart('pace-distribution', maximum, 0, span, v => timeLabel((low+v)*60), v => `${Math.round(v)}%`);
        bins.forEach((percent,i) => {
            const rect = node('rect', {class:'pace-bar', x:histogram.x(span*i/10)+1, y:histogram.y(percent),
                width:Math.max(1, histogram.x(span/10)-histogram.x(0)-2), height:histogram.y(0)-histogram.y(percent)});
            rect.append(node('title', {}, `${timeLabel((low+span*i/10)*60)}–${timeLabel((low+span*(i+1)/10)*60)} /km：${percent.toFixed(1)}%`));
            histogram.svg.append(rect);
        });
        $('pace-preview-summary').textContent = `${sample.distance_km} km · 用时 ${timeLabel(end)} · 平均 ${timeLabel(sample.average_pace*60)} /km · 最快 ${timeLabel(fastest*60)} /km`;
    }
    function invalidate() {
        version++; sample = null; $('pace-preview-charts').hidden = true;
        $('pace-preview-refresh').disabled = false; $('pace-preview-refresh').textContent = '更新样例';
        $('pace-preview-status').textContent = '参数已修改，更新后查看';
    }
    async function refresh(event) {
        event?.preventDefault();
        if (!$('pace-preview-form').reportValidity()) return;
        const current = ++version;
        $('pace-preview-refresh').disabled = true; $('pace-preview-charts').hidden = true;
        $('pace-preview-status').textContent = '正在生成样例…'; sample = null;
        try {
            const data = await postJSON('/api/pace/preview', {...options, distance_km:Number($('pace-preview-distance').value), pace:Number($('pace-preview-average').value), seed:seed++});
            if (current !== version) return;
            sample = data; $('pace-preview-charts').hidden = false; draw();
            $('pace-preview-status').textContent = options.enable_pace_fluctuation ? '样例已更新，正式生成会重新随机' : '配速波动已关闭，显示匀速样例';
            $('pace-preview-refresh').textContent = '换个样例';
        } catch (error) {
            if (current === version) $('pace-preview-status').textContent = '预览未完成：' + error.message + '；请重试';
        } finally { if (current === version) $('pace-preview-refresh').disabled = false; }
    }
    $('pace-preview-form').addEventListener('submit', refresh);
    $('pace-preview-form').addEventListener('input', invalidate);
    $('pace-dialog').addEventListener('close', () => {version++; sample=null;});
    window.addEventListener('resize', draw);
    return {open(data, distance) {
        options = {pace_algorithm:data.pace_algorithm, pace_intensity:data.pace_intensity, enable_pace_fluctuation:data.enable_pace_fluctuation};
        seed = 42; $('pace-preview-distance').value = distance; $('pace-preview-average').value = (data.min_pace+data.max_pace)/2;
        $('pace-dialog').showModal(); refresh();
    }};
})();
