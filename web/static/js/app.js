// 校园跑步数据生成器 - Web前端

let currentJobId = null;

// 页面加载时初始化
document.addEventListener('DOMContentLoaded', async () => {
    initDates();
    initTabs();
    initCalendar();
    await loadTracks();
    await loadTemplates();
    initForms();
});

// 初始化日期默认值
function initDates() {
    const today = new Date();
    const weekLater = new Date(today.getTime() + 7 * 24 * 60 * 60 * 1000);
    const dateFormat = (d) => d.toISOString().split('T')[0];

    document.getElementById('daily-start-date').value = dateFormat(today);
    document.getElementById('daily-end-date').value = dateFormat(weekLater);
    document.getElementById('total-start-date').value = dateFormat(today);
    document.getElementById('total-end-date').value = dateFormat(weekLater);
    document.getElementById('single-date').value = dateFormat(today);
}

// ============================================================
// 日历选择器（指定日期批量模式）
// ============================================================
const calendarState = {
    currentYear: new Date().getFullYear(),
    currentMonth: new Date().getMonth(), // 0-based
    selectedDates: new Set(), // 存储 "YYYY-MM-DD" 格式
};

function initCalendar() {
    renderCalendar();
    document.getElementById('cal-prev').addEventListener('click', () => {
        calendarState.currentMonth--;
        if (calendarState.currentMonth < 0) {
            calendarState.currentMonth = 11;
            calendarState.currentYear--;
        }
        renderCalendar();
    });
    document.getElementById('cal-next').addEventListener('click', () => {
        calendarState.currentMonth++;
        if (calendarState.currentMonth > 11) {
            calendarState.currentMonth = 0;
            calendarState.currentYear++;
        }
        renderCalendar();
    });
    document.getElementById('cal-clear').addEventListener('click', () => {
        calendarState.selectedDates.clear();
        renderCalendar();
        renderSelectedTags();
    });
    document.getElementById('cal-select-weekdays').addEventListener('click', () => {
        selectDaysByType('weekday');
    });
    document.getElementById('cal-select-weekends').addEventListener('click', () => {
        selectDaysByType('weekend');
    });
}

function renderCalendar() {
    const year = calendarState.currentYear;
    const month = calendarState.currentMonth;

    // 更新标题
    const monthNames = ['1月', '2月', '3月', '4月', '5月', '6月',
                        '7月', '8月', '9月', '10月', '11月', '12月'];
    document.getElementById('cal-title').textContent = `${year}年 ${monthNames[month]}`;

    const grid = document.getElementById('cal-grid');
    grid.innerHTML = '';

    const today = new Date();
    const todayStr = formatDateStr(today);

    // 本月第一天是星期几（0=日,1=一,...,6=六）=> 转换为周一=0
    const firstDay = new Date(year, month, 1);
    let startWeekday = firstDay.getDay() - 1; // 周一=0
    if (startWeekday < 0) startWeekday = 6; // 周日 => 6

    // 本月天数
    const daysInMonth = new Date(year, month + 1, 0).getDate();

    // 上月补位
    const prevMonthDays = new Date(year, month, 0).getDate();
    for (let i = startWeekday - 1; i >= 0; i--) {
        const day = prevMonthDays - i;
        const el = document.createElement('div');
        el.className = 'cal-day cal-empty cal-other-month';
        el.textContent = day;
        grid.appendChild(el);
    }

    // 本月日期
    for (let d = 1; d <= daysInMonth; d++) {
        const dateStr = formatDateStr(new Date(year, month, d));
        const el = document.createElement('div');
        el.className = 'cal-day';
        el.textContent = d;

        // 判断是否周末（0=日, 6=六）
        const dayOfWeek = new Date(year, month, d).getDay();
        if (dayOfWeek === 0 || dayOfWeek === 6) {
            el.classList.add('cal-weekend');
        }

        if (dateStr === todayStr) {
            el.classList.add('cal-today');
        }

        if (calendarState.selectedDates.has(dateStr)) {
            el.classList.add('cal-selected');
        }

        el.addEventListener('click', () => toggleDate(dateStr, el));
        grid.appendChild(el);
    }

    // 下月补位（补齐到6行 = 42格）
    const totalCells = grid.children.length;
    const remaining = totalCells <= 35 ? (35 - totalCells) : (42 - totalCells);
    for (let i = 1; i <= remaining; i++) {
        const el = document.createElement('div');
        el.className = 'cal-day cal-empty cal-other-month';
        el.textContent = i;
        grid.appendChild(el);
    }
}

function toggleDate(dateStr, el) {
    if (calendarState.selectedDates.has(dateStr)) {
        calendarState.selectedDates.delete(dateStr);
        el.classList.remove('cal-selected');
    } else {
        calendarState.selectedDates.add(dateStr);
        el.classList.add('cal-selected');
    }
    renderSelectedTags();
}

function renderSelectedTags() {
    const container = document.getElementById('selected-dates-tags');
    const countEl = document.getElementById('dates-count');
    const dates = Array.from(calendarState.selectedDates).sort();

    countEl.textContent = `(已选 ${dates.length} 天)`;

    if (dates.length === 0) {
        container.innerHTML = '<span class="dates-placeholder">点击日历上的日期进行选择</span>';
        return;
    }

    // 用 DOM API 构建：日期字符串可能来自上传的模板文件，
    // 只经 textContent/dataset 写入，禁止拼入 innerHTML（防存储型 XSS，与 loadTracks 同策略）
    const weekdays = ['日', '一', '二', '三', '四', '五', '六'];
    container.innerHTML = '';
    dates.forEach(d => {
        const dt = new Date(d + 'T00:00:00');
        // 非法日期字符串（模板中的脏数据）直接显示原文，避免渲染出 "NaN-NaN 周NaN"
        const label = Number.isNaN(dt.getTime())
            ? d
            : `${(dt.getMonth()+1).toString().padStart(2,'0')}-${dt.getDate().toString().padStart(2,'0')} 周${weekdays[dt.getDay()]}`;

        const tag = document.createElement('span');
        tag.className = 'date-tag';
        tag.dataset.date = d;
        tag.appendChild(document.createTextNode(label));

        const remove = document.createElement('span');
        remove.className = 'tag-remove';
        remove.textContent = '×';
        remove.addEventListener('click', () => removeDateTag(d));
        tag.appendChild(remove);

        container.appendChild(tag);
    });
}

function removeDateTag(dateStr) {
    calendarState.selectedDates.delete(dateStr);
    renderSelectedTags();
    renderCalendar(); // 刷新日历上的选中状态
}

function selectDaysByType(type) {
    const year = calendarState.currentYear;
    const month = calendarState.currentMonth;
    const daysInMonth = new Date(year, month + 1, 0).getDate();

    for (let d = 1; d <= daysInMonth; d++) {
        const dayOfWeek = new Date(year, month, d).getDay();
        const dateStr = formatDateStr(new Date(year, month, d));
        if (type === 'weekday' && dayOfWeek >= 1 && dayOfWeek <= 5) {
            calendarState.selectedDates.add(dateStr);
        } else if (type === 'weekend' && (dayOfWeek === 0 || dayOfWeek === 6)) {
            calendarState.selectedDates.add(dateStr);
        }
    }
    renderCalendar();
    renderSelectedTags();
}

function formatDateStr(d) {
    const y = d.getFullYear();
    const m = String(d.getMonth() + 1).padStart(2, '0');
    const day = String(d.getDate()).padStart(2, '0');
    return `${y}-${m}-${day}`;
}

// 获取当前选中的输出格式
function getSelectedFormat() {
    const sel = document.querySelector('.mode-content.active .output-format');
    return sel ? sel.value : 'fit';
}

// 初始化Tab切换
function initTabs() {
    const tabButtons = document.querySelectorAll('.tab-button');
    const modeContents = document.querySelectorAll('.mode-content');

    tabButtons.forEach(button => {
        button.addEventListener('click', () => {
            const mode = button.dataset.mode;

            tabButtons.forEach(btn => btn.classList.remove('active'));
            button.classList.add('active');

            modeContents.forEach(content => {
                content.classList.remove('active');
                if (content.id === `${mode}-mode`) {
                    content.classList.add('active');
                }
            });
        });
    });
}

// 加载轨迹列表
async function loadTracks() {
    try {
        const response = await fetch('/api/tracks');
        if (!response.ok) throw new Error('加载轨迹失败');

        const tracks = await response.json();
        const select = document.getElementById('track-select');
        // 用 DOM API 构建（name 来自 JSON 文件的任意文本，禁止拼入 innerHTML 防存储型 XSS）
        select.replaceChildren();
        tracks.forEach(t => select.add(new Option(`${t.name} (${t.lap_distance_km}km/圈)`, t.id)));
    } catch (error) {
        showMessage('加载轨迹列表失败: ' + error.message, 'error');
    }
}

// 本地模板缓存键
const TEMPLATE_CACHE_KEY = 'template_cache';

// 保存模板到本地缓存
function saveTemplateToLocal(template) {
    const cache = JSON.parse(localStorage.getItem(TEMPLATE_CACHE_KEY) || '{}');
    cache[template.id] = template;
    localStorage.setItem(TEMPLATE_CACHE_KEY, JSON.stringify(cache));
}

// 获取本地缓存的模板列表
function getLocalTemplates() {
    const cache = JSON.parse(localStorage.getItem(TEMPLATE_CACHE_KEY) || '{}');
    return Object.values(cache);
}

// 从本地缓存删除模板
function removeLocalTemplate(id) {
    const cache = JSON.parse(localStorage.getItem(TEMPLATE_CACHE_KEY) || '{}');
    delete cache[id];
    localStorage.setItem(TEMPLATE_CACHE_KEY, JSON.stringify(cache));
}

// 加载模板列表
async function loadTemplates() {
    try {
        const response = await fetch('/api/templates');
        if (!response.ok) throw new Error('加载模板失败');

        const templates = await response.json();
        const select = document.getElementById('template-select');

        // 构建下拉框选项
        let optionsHtml = '<option value="">不使用模板</option>' +
            '<option value="__upload__">上传模板...</option>';

        // 服务器模板
        templates.forEach(t => {
            optionsHtml += `<option value="${t.id}">${t.name}</option>`;
        });

        // 本地缓存模板
        const localTemplates = getLocalTemplates();
        if (localTemplates.length > 0) {
            optionsHtml += '<optgroup label="本地模板">';
            localTemplates.forEach(t => {
                optionsHtml += `<option value="local_${t.id}">${t.name}</option>`;
            });
            optionsHtml += '</optgroup>';
        }

        select.innerHTML = optionsHtml;

        // 监听模板选择变化
        select.addEventListener('change', async (e) => {
            const templateId = e.target.value;
            if (!templateId) {
                resetFormsToDefaults();
                return;
            }
            if (templateId === '__upload__') {
                document.getElementById('template-upload').click();
                return;
            }
            if (templateId.startsWith('local_')) {
                // 本地模板
                const id = templateId.replace('local_', '');
                const cache = JSON.parse(localStorage.getItem(TEMPLATE_CACHE_KEY) || '{}');
                if (cache[id]) {
                    applyTemplateToForms(cache[id]);
                }
                return;
            }
            try {
                const resp = await fetch(`/api/template/${templateId}`);
                if (!resp.ok) throw new Error('获取模板失败');
                const template = await resp.json();
                applyTemplateToForms(template);
            } catch (error) {
                showMessage('加载模板失败: ' + error.message, 'error');
            }
        });

        // 监听文件上传
        document.getElementById('template-upload').addEventListener('change', handleTemplateUpload);
    } catch (error) {
        showMessage('加载模板列表失败: ' + error.message, 'error');
    }
}

// 处理模板文件上传
function handleTemplateUpload(e) {
    const file = e.target.files[0];
    if (!file) {
        // 用户取消选择，恢复下拉框
        document.getElementById('template-select').value = '';
        return;
    }

    const reader = new FileReader();
    reader.onload = (event) => {
        try {
            const template = JSON.parse(event.target.result);
            // 保存到本地缓存
            saveTemplateToLocal(template);
            // 应用模板到表单
            applyTemplateToForms(template);
            showMessage('模板导入成功', 'success');
            // 刷新模板列表以显示本地模板
            loadTemplates();
            // 选中新导入的模板
            document.getElementById('template-select').value = `local_${template.id}`;
        } catch (error) {
            showMessage('模板文件格式错误: ' + error.message, 'error');
        }
    };
    reader.readAsText(file);
    e.target.value = '';
}

// 切换到指定模式
function switchToMode(mode) {
    const tabButton = document.querySelector(`.tab-button[data-mode="${mode}"]`);
    if (tabButton && !tabButton.classList.contains('active')) {
        tabButton.click();
    }
}

// 应用模板到表单
function applyTemplateToForms(template) {
    // 检查哪个配置节有内容，自动切换到对应模式
    const hasDaily = template.daily_config && Object.keys(template.daily_config).length > 0;
    const hasTotal = template.total_config && Object.keys(template.total_config).length > 0;
    const hasSingle = template.single_config && Object.keys(template.single_config).length > 0;
    const hasDates = template.dates_config && Object.keys(template.dates_config).length > 0;

    if (hasDaily) {
        switchToMode('daily');
    } else if (hasTotal) {
        switchToMode('total');
    } else if (hasSingle) {
        switchToMode('single');
    } else if (hasDates) {
        switchToMode('dates');
    }

    const activeMode = document.querySelector('.mode-content.active').id;
    let config = {};

    // 根据当前模式获取对应配置
    if (activeMode === 'daily-mode' && template.daily_config) {
        config = template.daily_config;
    } else if (activeMode === 'total-mode' && template.total_config) {
        config = template.total_config;
    } else if (activeMode === 'single-mode' && template.single_config) {
        config = template.single_config;
    } else if (activeMode === 'dates-mode' && template.dates_config) {
        config = template.dates_config;
    } else {
        // 兼容旧格式（无模式分离）
        config = template.generation_config || {};
    }

    // 应用轨迹选择
    if (template.track_id) {
        document.getElementById('track-select').value = template.track_id;
    }

    // 应用输出格式
    if (config.output_format !== undefined) {
        document.querySelectorAll('.output-format').forEach(sel => {
            sel.value = config.output_format;
        });
    }

    // 通用字段（配速、时间）
    if (config.min_pace !== undefined) {
        document.getElementById('daily-min-pace').value = config.min_pace;
        document.getElementById('total-min-pace').value = config.min_pace;
        document.getElementById('dates-min-pace').value = config.min_pace;
    }
    if (config.max_pace !== undefined) {
        document.getElementById('daily-max-pace').value = config.max_pace;
        document.getElementById('total-max-pace').value = config.max_pace;
        document.getElementById('dates-max-pace').value = config.max_pace;
    }
    if (config.start_time_min !== undefined) {
        document.getElementById('daily-start-time-min').value = config.start_time_min;
        document.getElementById('total-start-time-min').value = config.start_time_min;
        document.getElementById('dates-start-time-min').value = config.start_time_min;
    } else if (config.start_hour_min !== undefined) {
        // 向后兼容旧模板
        const minTime = String(config.start_hour_min).padStart(2, '0') + ':00';
        document.getElementById('daily-start-time-min').value = minTime;
        document.getElementById('total-start-time-min').value = minTime;
        document.getElementById('dates-start-time-min').value = minTime;
    }
    if (config.start_time_max !== undefined) {
        document.getElementById('daily-start-time-max').value = config.start_time_max;
        document.getElementById('total-start-time-max').value = config.start_time_max;
        document.getElementById('dates-start-time-max').value = config.start_time_max;
    } else if (config.start_hour_max !== undefined) {
        // 向后兼容旧模板
        const maxTime = String(config.start_hour_max).padStart(2, '0') + ':00';
        document.getElementById('daily-start-time-max').value = maxTime;
        document.getElementById('total-start-time-max').value = maxTime;
        document.getElementById('dates-start-time-max').value = maxTime;
    }

    // 处理恒定配速checkbox（模板的enable_pace_fluctuation是true表示启用，checkbox是checked表示禁用）
    const dailyNoFluctuation = document.getElementById('daily-no-fluctuation');
    const totalNoFluctuation = document.getElementById('total-no-fluctuation');
    const dailyNoTrack = document.getElementById('daily-no-track');
    const totalNoTrack = document.getElementById('total-no-track');
    const dailyNoCorrection = document.getElementById('daily-no-correction');
    const totalNoCorrection = document.getElementById('total-no-correction');

    if (config.enable_pace_fluctuation !== undefined) {
        if (dailyNoFluctuation) dailyNoFluctuation.checked = !config.enable_pace_fluctuation;
        if (totalNoFluctuation) totalNoFluctuation.checked = !config.enable_pace_fluctuation;
    }
    if (config.include_track !== undefined) {
        if (dailyNoTrack) dailyNoTrack.checked = !config.include_track;
        if (totalNoTrack) totalNoTrack.checked = !config.include_track;
    }
    if (config.apply_correction !== undefined) {
        if (dailyNoCorrection) dailyNoCorrection.checked = !config.apply_correction;
        if (totalNoCorrection) totalNoCorrection.checked = !config.apply_correction;
    }

    // 日期字段
    if (config.start_date) {
        document.getElementById('daily-start-date').value = config.start_date;
        document.getElementById('total-start-date').value = config.start_date;
    }
    if (config.end_date) {
        document.getElementById('daily-end-date').value = config.end_date;
        document.getElementById('total-end-date').value = config.end_date;
    }

    // 每日模式特有字段
    if (activeMode === 'daily-mode') {
        if (config.min_km !== undefined) {
            document.getElementById('daily-min-km').value = config.min_km;
        }
        if (config.max_km !== undefined) {
            document.getElementById('daily-max-km').value = config.max_km;
        }
    }

    // 总公里数模式特有字段
    if (activeMode === 'total-mode') {
        if (config.total_km !== undefined) {
            document.getElementById('total-km').value = config.total_km;
        }
        if (config.weekend_factor !== undefined) {
            document.getElementById('total-weekend-factor').value = config.weekend_factor;
        }
        if (config.min_daily_km !== undefined) {
            document.getElementById('total-min-daily').value = config.min_daily_km;
        }
        if (config.max_daily_km !== undefined) {
            document.getElementById('total-max-daily').value = config.max_daily_km;
        }
        if (config.rest_days_per_week !== undefined) {
            document.getElementById('total-rest-days').value = config.rest_days_per_week;
        }
    }

    // 单文件模式字段
    if (activeMode === 'single-mode') {
        if (config.pace !== undefined) {
            document.getElementById('single-pace').value = config.pace;
        }
    }

    // 指定日期批量模式字段
    if (activeMode === 'dates-mode') {
        if (config.distance !== undefined) {
            document.getElementById('dates-distance').value = config.distance;
        }
        if (config.dates && Array.isArray(config.dates)) {
            calendarState.selectedDates = new Set(config.dates);
            renderCalendar();
            renderSelectedTags();
        }
    }
}

// 重置表单为默认值
function resetFormsToDefaults() {
    // 每日模式默认值
    document.getElementById('daily-min-pace').value = 7.0;
    document.getElementById('daily-max-pace').value = 8.0;
    document.getElementById('daily-start-time-min').value = '06:00';
    document.getElementById('daily-start-time-max').value = '08:00';

    // 总公里数模式默认值
    document.getElementById('total-min-pace').value = 7.0;
    document.getElementById('total-max-pace').value = 8.0;
    document.getElementById('total-start-time-min').value = '06:00';
    document.getElementById('total-start-time-max').value = '08:00';

    // 指定日期批量模式默认值
    document.getElementById('dates-min-pace').value = 7.0;
    document.getElementById('dates-max-pace').value = 8.0;
    document.getElementById('dates-start-time-min').value = '06:00';
    document.getElementById('dates-start-time-max').value = '08:00';
}

// 初始化表单提交
function initForms() {
    document.getElementById('daily-form').addEventListener('submit', handleDailySubmit);
    document.getElementById('total-form').addEventListener('submit', handleTotalSubmit);
    document.getElementById('single-form').addEventListener('submit', handleSingleSubmit);
    document.getElementById('dates-form').addEventListener('submit', handleDatesSubmit);
    document.getElementById('download-btn').addEventListener('click', downloadFiles);
    document.getElementById('daily-export-btn').addEventListener('click', showExportModal);
    document.getElementById('total-export-btn').addEventListener('click', showExportModal);
    document.getElementById('single-export-btn').addEventListener('click', showExportModal);
    document.getElementById('dates-export-btn').addEventListener('click', showExportModal);
    document.getElementById('export-form').addEventListener('submit', handleExportSubmit);
    document.querySelector('#export-modal .modal-close').addEventListener('click', hideExportModal);
    document.querySelector('#export-modal .modal-cancel').addEventListener('click', hideExportModal);
}

// 显示导出模态框
function showExportModal() {
    document.getElementById('export-template-name').value = '';
    document.getElementById('export-modal').style.display = 'flex';
}

// 隐藏导出模态框
function hideExportModal() {
    document.getElementById('export-modal').style.display = 'none';
}

// 处理导出提交
function handleExportSubmit(e) {
    e.preventDefault();
    const name = document.getElementById('export-template-name').value.trim();
    if (!name) return;
    hideExportModal();
    doExportTemplate(name);
}

// 执行导出
let pendingExportConfig = null;

function doExportTemplate(name) {
    const data = getCurrentActiveFormData();
    const activeMode = document.querySelector('.mode-content.active').id;

    let config = {};
    if (activeMode === 'daily-mode') {
        config = {
            min_pace: data.min_pace,
            max_pace: data.max_pace,
            start_time_min: data.start_time_min,
            start_time_max: data.start_time_max,
            start_date: data.start_date,
            end_date: data.end_date,
            min_km: data.min_km,
            max_km: data.max_km,
            include_track: data.include_track,
            apply_correction: data.apply_correction,
            enable_pace_fluctuation: data.enable_pace_fluctuation,
            output_format: data.output_format,
        };
    } else if (activeMode === 'total-mode') {
        config = {
            min_pace: data.min_pace,
            max_pace: data.max_pace,
            start_time_min: data.start_time_min,
            start_time_max: data.start_time_max,
            start_date: data.start_date,
            end_date: data.end_date,
            total_km: data.total_km,
            weekend_factor: data.weekend_factor,
            min_daily_km: data.min_daily_km,
            max_daily_km: data.max_daily_km,
            rest_days_per_week: data.rest_days_per_week,
            include_track: data.include_track,
            apply_correction: data.apply_correction,
            enable_pace_fluctuation: data.enable_pace_fluctuation,
            output_format: data.output_format,
        };
    } else if (activeMode === 'dates-mode') {
        config = {
            dates: data.dates,
            distance: data.distance,
            min_pace: data.min_pace,
            max_pace: data.max_pace,
            start_time_min: data.start_time_min,
            start_time_max: data.start_time_max,
            output_format: data.output_format,
        };
    } else {
        config = {
            pace: data.pace,
            include_track: data.include_track,
            apply_correction: data.apply_correction,
            enable_pace_fluctuation: data.enable_pace_fluctuation,
            output_format: data.output_format,
        };
    }

    const template = {
        id: `custom_${Date.now()}`,
        name: name,
        description: '',
        track_id: data.track_id || '',
        daily_config: activeMode === 'daily-mode' ? config : {},
        total_config: activeMode === 'total-mode' ? config : {},
        single_config: activeMode === 'single-mode' ? config : {},
        dates_config: activeMode === 'dates-mode' ? config : {},
    };

    // 保存到本地缓存
    saveTemplateToLocal(template);

    // 下载JSON文件
    const blob = new Blob([JSON.stringify(template, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `${name.replace(/[^a-zA-Z0-9一-龥]/g, '_')}_${Date.now()}.json`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);

    showMessage('模板已导出', 'success');
}

// 获取当前活动表单的配置数据
function getCurrentActiveFormData() {
    const activeMode = document.querySelector('.mode-content.active').id;

    if (activeMode === 'daily-mode') {
        return collectDailyFormData();
    } else if (activeMode === 'total-mode') {
        return collectTotalFormData();
    } else if (activeMode === 'dates-mode') {
        return collectDatesFormData();
    } else {
        return collectSingleFormData();
    }
}

// 处理每日模式提交
async function handleDailySubmit(e) {
    e.preventDefault();
    const data = collectDailyFormData();
    await generate('daily', data);
}

// 处理总公里数模式提交
async function handleTotalSubmit(e) {
    e.preventDefault();
    const data = collectTotalFormData();
    await generate('total', data);
}

// 处理单文件模式提交
async function handleSingleSubmit(e) {
    e.preventDefault();
    const data = collectSingleFormData();
    await generate('single', data);
}

// 收集每日表单数据
function collectDailyFormData() {
    const trackId = document.getElementById('track-select').value;
    const templateId = document.getElementById('template-select').value;

    return {
        track_id: trackId,
        template_id: templateId || undefined,
        start_date: document.getElementById('daily-start-date').value,
        end_date: document.getElementById('daily-end-date').value,
        min_km: parseFloat(document.getElementById('daily-min-km').value),
        max_km: parseFloat(document.getElementById('daily-max-km').value),
        min_pace: parseFloat(document.getElementById('daily-min-pace').value),
        max_pace: parseFloat(document.getElementById('daily-max-pace').value),
        start_time_min: document.getElementById('daily-start-time-min').value || '06:00',
        start_time_max: document.getElementById('daily-start-time-max').value || '08:00',
        output_dir: document.getElementById('daily-output-dir').value,
        include_track: !(document.getElementById('daily-no-track')?.checked ?? false),
        apply_correction: !(document.getElementById('daily-no-correction')?.checked ?? false),
        enable_pace_fluctuation: !(document.getElementById('daily-no-fluctuation')?.checked ?? false),
        output_format: getSelectedFormat(),
    };
}

// 收集总公里数表单数据
function collectTotalFormData() {
    const trackId = document.getElementById('track-select').value;
    const templateId = document.getElementById('template-select').value;

    return {
        track_id: trackId,
        template_id: templateId || undefined,
        start_date: document.getElementById('total-start-date').value,
        end_date: document.getElementById('total-end-date').value,
        total_km: parseFloat(document.getElementById('total-km').value),
        weekend_factor: parseFloat(document.getElementById('total-weekend-factor').value),
        min_daily_km: parseFloat(document.getElementById('total-min-daily').value),
        max_daily_km: parseFloat(document.getElementById('total-max-daily').value),
        rest_days_per_week: parseInt(document.getElementById('total-rest-days').value),
        min_pace: parseFloat(document.getElementById('total-min-pace').value),
        max_pace: parseFloat(document.getElementById('total-max-pace').value),
        start_time_min: document.getElementById('total-start-time-min').value || '06:00',
        start_time_max: document.getElementById('total-start-time-max').value || '08:00',
        output_dir: document.getElementById('total-output-dir').value,
        output_format: getSelectedFormat(),
    };
}

// 收集单文件表单数据
function collectSingleFormData() {
    const trackId = document.getElementById('track-select').value;
    const templateId = document.getElementById('template-select').value;
    const pace = document.getElementById('single-pace').value;

    return {
        track_id: trackId,
        template_id: templateId || undefined,
        date: document.getElementById('single-date').value,
        distance: parseFloat(document.getElementById('single-distance').value),
        pace: pace ? parseFloat(pace) : undefined,
        output_dir: document.getElementById('single-output-dir').value,
        start_time_min: document.getElementById('single-start-time').value || '07:00',
        start_time_max: document.getElementById('single-start-time').value || '07:00',
        include_track: !(document.getElementById('single-no-track')?.checked ?? false),
        apply_correction: !(document.getElementById('single-no-correction')?.checked ?? false),
        enable_pace_fluctuation: !(document.getElementById('single-no-fluctuation')?.checked ?? false),
        output_format: getSelectedFormat(),
    };
}

// 处理指定日期批量模式提交
async function handleDatesSubmit(e) {
    e.preventDefault();
    if (calendarState.selectedDates.size === 0) {
        showMessage('请至少选择一个日期', 'error');
        return;
    }
    const data = collectDatesFormData();
    await generate('dates', data);
}

// 收集指定日期批量表单数据
function collectDatesFormData() {
    const trackId = document.getElementById('track-select').value;
    const templateId = document.getElementById('template-select').value;
    const dates = Array.from(calendarState.selectedDates).sort();

    return {
        track_id: trackId,
        template_id: templateId || undefined,
        dates: dates,
        distance: parseFloat(document.getElementById('dates-distance').value),
        min_pace: parseFloat(document.getElementById('dates-min-pace').value),
        max_pace: parseFloat(document.getElementById('dates-max-pace').value),
        start_time_min: document.getElementById('dates-start-time-min').value || '06:00',
        start_time_max: document.getElementById('dates-start-time-max').value || '08:00',
        output_dir: document.getElementById('dates-output-dir').value,
        output_format: getSelectedFormat(),
    };
}

// 调用API生成
async function generate(mode, data) {
    showMessage('正在生成...', 'loading');
    disableButtons(true);

    try {
        const response = await fetch(`/api/generate/${mode}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data)
        });

        const result = await response.json();

        if (!response.ok) {
            throw new Error(result.error || '生成失败');
        }

        currentJobId = result.job_id;
        showResults(result);
        showMessage(`生成完成！共 ${result.total_files} 个文件`, 'success');

    } catch (error) {
        showMessage('生成失败: ' + error.message, 'error');
        currentJobId = null;
    } finally {
        disableButtons(false);
    }
}

// 显示结果
function showResults(result) {
    const section = document.getElementById('results-section');
    const tbody = document.getElementById('results-body');
    const downloadBtn = document.getElementById('download-btn');

    tbody.innerHTML = result.files.map(f => `
        <tr>
            <td>${f.date}</td>
            <td>${f.distance_km.toFixed(2)} km</td>
            <td>${f.pace_min_per_km.toFixed(2)} min/km</td>
            <td>${formatDuration(f.duration_seconds)}</td>
            <td>${f.calories}</td>
        </tr>
    `).join('');

    section.classList.add('show');
    downloadBtn.disabled = false;
}

// 格式化时长
function formatDuration(seconds) {
    const mins = Math.floor(seconds / 60);
    const secs = Math.round(seconds % 60);
    return `${mins}:${secs.toString().padStart(2, '0')}`;
}

// 下载文件
function downloadFiles() {
    if (!currentJobId) return;
    window.location.href = `/api/download/${currentJobId}`;
}

// 显示消息
function showMessage(text, type) {
    const msg = document.getElementById('message');
    msg.textContent = text;
    msg.className = `message ${type} show`;

    if (type !== 'loading') {
        setTimeout(() => {
            msg.classList.remove('show');
        }, 5000);
    }
}

// 禁用/启用按钮
function disableButtons(disabled) {
    document.querySelectorAll('button[type="submit"]').forEach(btn => {
        btn.disabled = disabled;
    });
    document.getElementById('download-btn').disabled = disabled;
}
