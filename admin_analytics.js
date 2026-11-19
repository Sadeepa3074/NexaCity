/* CivicFix local prototype analytics, based only on server-supplied MySQL aggregates. */
document.addEventListener('DOMContentLoaded', function () {
  document.querySelectorAll('.analytics-category-fill').forEach(function (bar) {
    const raw = Number(bar.dataset.percentage);
    const pct = Number.isFinite(raw) ? Math.max(0, Math.min(100, raw)) : 0;
    bar.style.width = pct + '%';
  });

  const dataEl = document.getElementById('civicfix-analytics-json');
  if (!dataEl) return;
  let info;
  try { info = JSON.parse(dataEl.textContent); }
  catch (error) { console.error('CivicFix analytics JSON could not be parsed.', error); return; }

  if (typeof Chart === 'undefined') {
    document.querySelectorAll('.analytics-canvas-wrap').forEach(function (container) {
      const notice = document.createElement('p');
      notice.className = 'analytics-footnote';
      notice.textContent = 'Chart library could not load. Check internet access or browser blocking. Numeric summaries are still available.';
      container.replaceChildren(notice);
    });
    return;
  }

  const grid = '#e9eef7';
  const label = '#8797b1';
  Chart.defaults.font.family = "Inter, 'Segoe UI', Arial, sans-serif";
  Chart.defaults.color = label;

  const trend = document.getElementById('resolution-trend-chart');
  if (trend && Array.isArray(info.months)) {
    new Chart(trend, {
      type: 'line',
      data: {
        labels: info.months.map(item => item.label),
        datasets: [{
          label: 'Average days to resolve',
          data: info.months.map(item => item.avg_days),
          borderColor: '#2e63ed',
          backgroundColor: 'rgba(62,122,243,.11)',
          tension: .35,
          borderWidth: 3,
          pointRadius: 5,
          pointHoverRadius: 7,
          pointBackgroundColor: '#2e63ed',
          fill: 'origin',
          spanGaps: false
        }]
      },
      options: {
        responsive: true, maintainAspectRatio: false,
        plugins: {legend: {display:false}, tooltip: {callbacks: {
          afterLabel: ctx => {
            const point = info.months[ctx.dataIndex];
            return (point.sample || 0) + ' resolved report(s) measured';
          }
        }}},
        scales: {
          x: {grid: {display:false}, border:{display:false}, ticks:{maxRotation:0}},
          y: {beginAtZero:true, grid:{color:grid}, border:{display:false}, title:{display:true,text:'Days'}}
        }
      }
    });
  }

  const volume = document.getElementById('report-volume-chart');
  if (volume && Array.isArray(info.volume)) {
    const rows = info.volume;
    const tickEvery = rows.length <= 7 ? 1 : (rows.length <= 30 ? 5 : 14);
    new Chart(volume, {
      type: 'bar',
      data: {
        labels: rows.map(row => row.label),
        datasets: [
          {label:'Reports submitted', data:rows.map(row=>row.submitted), backgroundColor:'#4557e9', borderRadius:4, maxBarThickness:22},
          {label:'Resolution events', data:rows.map(row=>row.resolved), backgroundColor:'#bad6fc', borderRadius:4, maxBarThickness:22}
        ]
      },
      options: {
        responsive:true, maintainAspectRatio:false,
        plugins:{legend:{display:false}, tooltip:{mode:'index',intersect:false}},
        scales:{
          x:{grid:{display:false}, border:{display:false}, ticks:{autoSkip:false,maxRotation:0,callback:function(value,index){return index%tickEvery===0?rows[index].label:'';}}},
          y:{beginAtZero:true, ticks:{precision:0}, grid:{color:grid}, border:{display:false}}
        }
      }
    });
  }
});
