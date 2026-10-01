(() => {
  const $ = (selector) => document.querySelector(selector);
  const numberFormat = new Intl.NumberFormat('ru-RU');
  const moscowTime = new Intl.DateTimeFormat('ru-RU', {
    timeZone: 'Europe/Moscow', hour: '2-digit', minute: '2-digit', second: '2-digit',
  });
  const windowLabels = {
    '15m': ['−15 мин', '−10 мин', '−5 мин', 'Сейчас'],
    '1h': ['−60 мин', '−40 мин', '−20 мин', 'Сейчас'],
    '24h': ['−24 ч', '−16 ч', '−8 ч', 'Сейчас'],
  };
  let currentWindow = '15m';

  function setStatus(prefix, up, uptime) {
    const state = $(`#${prefix}-state`);
    state.classList.toggle('offline', !up);
    state.querySelector('span').textContent = up ? 'Работает' : 'Недоступен';
    const percent = `${Number(uptime).toFixed(2).replace('.', ',')}%`;
    $(`#${prefix}-uptime`).textContent = percent;
    const bar = $(`#${prefix}-bar`);
    bar.style.width = `${Math.max(0, Math.min(100, Number(uptime)))}%`;
    bar.classList.toggle('degraded', !up || Number(uptime) < 99);
  }

  function setSyncStatus(name, up) {
    const node = $(`#sync-${name}`);
    node.classList.toggle('offline', !up);
    node.querySelector('span').textContent = up ? 'Синхронно' : 'Ошибка связи';
  }

  function formatDuration(seconds) {
    const total = Math.max(0, Number(seconds) || 0);
    const hours = Math.floor(total / 3600);
    const minutes = Math.floor((total % 3600) / 60);
    const remainder = total % 60;
    if (hours) return `${String(hours).padStart(2, '0')}:${String(minutes).padStart(2, '0')}:${String(remainder).padStart(2, '0')}`;
    return `${String(minutes).padStart(2, '0')}:${String(remainder).padStart(2, '0')}`;
  }

  function escapeHtml(value) {
    return String(value).replace(/[&<>"']/g, (character) => ({
      '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
    }[character]));
  }

  function renderEvents(events) {
    const container = $('#events-list');
    if (!events.length) {
      container.innerHTML = '<div class="empty-events">Новых событий пока нет — генератор работает</div>';
      return;
    }
    container.innerHTML = events.slice(0, 5).map((event) => {
      const denied = event.kind === 'denied';
      return `<div class="event-row">
        <span class="event-time">${escapeHtml(event.time)}</span>
        <span class="event-main"><strong>${escapeHtml(event.title)}</strong><small>${escapeHtml(event.source)}</small></span>
        <span class="event-badge ${denied ? 'denied' : ''}">${denied ? '403' : 'КОНФЛИКТ'}</span>
      </div>`;
    }).join('');
  }

  function renderChart(buckets) {
    const width = 900;
    const height = 220;
    const left = 8;
    const right = 890;
    const top = 10;
    const bottom = 210;
    const conflicts = buckets.map((bucket) => bucket.conflicts);
    const denied = buckets.map((bucket) => bucket.denied);
    const largest = Math.max(1, ...conflicts, ...denied);
    const maxValue = Math.max(4, Math.ceil(largest / 2) * 2);
    const yFor = (value) => bottom - (value / maxValue) * (bottom - top);
    const xFor = (index, length) => left + (index / Math.max(1, length - 1)) * (right - left);
    const linePoints = (values) => values.map((value, index) =>
      `${xFor(index, values.length).toFixed(1)},${yFor(value).toFixed(1)}`).join(' ');
    const areaPath = (values) => {
      const points = values.map((value, index) =>
        `${xFor(index, values.length).toFixed(1)} ${yFor(value).toFixed(1)}`);
      return `M ${left} ${bottom} L ${points.join(' L ')} L ${right} ${bottom} Z`;
    };
    $('#conflict-line').setAttribute('points', linePoints(conflicts));
    $('#denied-line').setAttribute('points', linePoints(denied));
    $('#conflict-area').setAttribute('d', areaPath(conflicts));
    $('#denied-area').setAttribute('d', areaPath(denied));
    $('#chart-grid').innerHTML = [top, (top + bottom) / 2, bottom].map((y) =>
      `<line class="chart-grid-line" x1="${left}" y1="${y}" x2="${right}" y2="${y}"/>`).join('');
    $('#y-max').textContent = String(maxValue);
    $('#y-mid').textContent = String(Math.round(maxValue / 2));
    const activeSeries = [
      { values: conflicts, color: '#f49b45' },
      { values: denied, color: '#e87887' },
    ];
    const points = [];
    for (const series of activeSeries) {
      series.values.forEach((value, index) => {
        if (value > 0) points.push(`<circle class="chart-point" cx="${xFor(index, series.values.length)}" cy="${yFor(value)}" r="3" fill="${series.color}"/>`);
      });
    }
    $('#chart-points').innerHTML = points.join('');
    $('#chart-x-labels').innerHTML = windowLabels[currentWindow].map((label) => `<span>${label}</span>`).join('');
  }

  async function refresh() {
    try {
      const response = await fetch(`/api/metrics/?window=${encodeURIComponent(currentWindow)}`, {
        cache: 'no-store',
        headers: { Accept: 'application/json' },
      });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const data = await response.json();
      $('#conflicts-value').textContent = numberFormat.format(data.metrics.conflicts);
      $('#denied-value').textContent = numberFormat.format(data.metrics.denied);
      $('#conflicts-rate').textContent = `${numberFormat.format(data.metrics.conflictsPerMinute)} / мин`;
      $('#denied-rate').textContent = `${numberFormat.format(data.metrics.deniedPerMinute)} / мин`;
      setStatus('hadoop', data.services.hadoop.up, data.services.hadoop.uptime);
      setStatus('policy', data.services.policy.up, data.services.policy.uptime);
      Object.entries(data.sync).forEach(([name, up]) => setSyncStatus(name, up));
      renderChart(data.chart);
      renderEvents(data.events);
      $('#last-sync').textContent = moscowTime.format(new Date(data.generatedAt));
      $('#last-updated').textContent = moscowTime.format(new Date(data.generatedAt));
      $('#session-duration').textContent = formatDuration(data.sessionSeconds);
      $('#refresh-button').classList.remove('refreshing');
    } catch (error) {
      console.error('Не удалось получить метрики PolicyConsistency:', error);
      $('.live-state strong').textContent = 'Нет связи с генератором';
      $('.live-state strong').style.color = '#f1979e';
    }
  }

  function updateClock() {
    $('#clock').textContent = `${moscowTime.format(new Date())} MSK`;
  }

  document.querySelectorAll('.window-button').forEach((button) => {
    button.addEventListener('click', () => {
      currentWindow = button.dataset.window;
      document.querySelectorAll('.window-button').forEach((item) =>
        item.classList.toggle('selected', item === button));
      refresh();
    });
  });
  $('#refresh-button').addEventListener('click', refresh);
  updateClock();
  refresh();
  window.setInterval(refresh, 3000);
  window.setInterval(updateClock, 1000);
})();