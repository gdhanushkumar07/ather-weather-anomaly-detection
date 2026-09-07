// ATHER (SkyGuard AI) — Real-Time Monitoring & Diagnostic Engine

let telemetryChart;
const maxDataPoints = 30;
const timeLabels = [];
const rawTempData = [];
const correctedTempData = [];
const anomalyPoints = [];

let pendingFault = null;
let pollInterval = null;

// Initialize Dashboard
document.addEventListener('DOMContentLoaded', () => {
    initChart();
    startTelemetryStream();
});

function initChart() {
    const ctx = document.getElementById('telemetryChart').getContext('2d');

    telemetryChart = new Chart(ctx, {
        type: 'line',
        data: {
            labels: timeLabels,
            datasets: [
                {
                    label: 'Raw Telemetry (°C)',
                    data: rawTempData,
                    borderColor: '#38bdf8',
                    backgroundColor: 'rgba(56, 189, 248, 0.05)',
                    borderWidth: 2,
                    tension: 0.25,
                    pointRadius: 3,
                    pointHoverRadius: 6
                },
                {
                    label: 'Self-Healed Imputed (°C)',
                    data: correctedTempData,
                    borderColor: '#10b981',
                    borderDash: [5, 5],
                    borderWidth: 2,
                    tension: 0.25,
                    pointRadius: 0
                },
                {
                    label: 'Anomaly Flagged',
                    data: anomalyPoints,
                    borderColor: '#f43f5e',
                    backgroundColor: '#f43f5e',
                    borderWidth: 0,
                    showLine: false,
                    pointRadius: 6,
                    pointHoverRadius: 8
                }
            ]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            animation: { duration: 300 },
            scales: {
                x: {
                    grid: { color: 'rgba(255, 255, 255, 0.04)' },
                    ticks: { color: '#64748b', font: { family: 'JetBrains Mono', size: 10 } }
                },
                y: {
                    grid: { color: 'rgba(255, 255, 255, 0.04)' },
                    ticks: { color: '#64748b', font: { family: 'JetBrains Mono', size: 10 } },
                    title: { display: true, text: 'Temperature (°C)', color: '#94a3b8' }
                }
            },
            plugins: {
                legend: { display: false }
            }
        }
    });
}

function startTelemetryStream() {
    fetchNextTelemetry();
    pollInterval = setInterval(fetchNextTelemetry, 1600);
}

async function fetchNextTelemetry() {
    try {
        let url = '/api/v1/stream/next';
        if (pendingFault) {
            url += `?inject_fault=${pendingFault}`;
            pendingFault = null; // Clear trigger after one injection
        }

        const res = await fetch(url);
        if (!res.ok) return;
        const data = await res.json();

        updateDashboard(data);
    } catch (err) {
        console.error('Error fetching telemetry:', err);
    }
}

function updateDashboard(payload) {
    const reading = payload.reading;
    const alert = payload.alert;

    // 1. Update KPI Values
    document.getElementById('current-temp').innerText = reading.temperature_c.toFixed(1);
    document.getElementById('current-press').innerText = reading.pressure_hpa.toFixed(1);
    document.getElementById('current-rh').innerText = reading.humidity_pct.toFixed(1);
    document.getElementById('station-health').innerText = alert.sensor_health_index.toFixed(1);

    // Health styling
    const healthVal = alert.sensor_health_index;
    const healthEl = document.getElementById('station-health');
    if (healthVal > 80) {
        healthEl.style.color = '#10b981';
    } else if (healthVal > 50) {
        healthEl.style.color = '#f59e0b';
    } else {
        healthEl.style.color = '#f43f5e';
    }

    if (alert.estimated_days_to_failure !== null && alert.estimated_days_to_failure < 14) {
        document.getElementById('drift-projection').innerText = `CRITICAL: Failure in ${alert.estimated_days_to_failure.toFixed(1)} days!`;
        document.getElementById('drift-projection').style.color = '#f43f5e';
    } else {
        document.getElementById('drift-projection').innerText = `Drift: Minimal (Tolerance > 30d)`;
        document.getElementById('drift-projection').style.color = '#94a3b8';
    }

    // 2. Update 5-Layer Anomaly Progress Bars
    updateLayerProgress('phys', alert.layer_scores.physics || 0);
    updateLayerProgress('temp', alert.layer_scores.temporal || 0);
    updateLayerProgress('mv', alert.layer_scores.multivariate || 0);
    updateLayerProgress('sp', alert.layer_scores.spatial || 0);
    updateLayerProgress('drift', alert.layer_scores.drift || 0);

    // VETO Badge
    const vetoBadge = document.getElementById('veto-badge');
    if (alert.veto_fired) {
        vetoBadge.className = 'veto-badge fired';
        vetoBadge.innerText = 'VETO FIRED';
    } else {
        vetoBadge.className = 'veto-badge neutral';
        vetoBadge.innerText = 'VETO INACTIVE';
    }

    // 3. Update Chart
    const timeStr = new Date(reading.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    timeLabels.push(timeStr);
    rawTempData.push(reading.temperature_c);
    correctedTempData.push(alert.corrected_values.temperature_c);

    if (alert.is_anomaly) {
        anomalyPoints.push(reading.temperature_c);
        addAlertToFeed(alert, timeStr);
    } else {
        anomalyPoints.push(null);
    }

    if (timeLabels.length > maxDataPoints) {
        timeLabels.shift();
        rawTempData.shift();
        correctedTempData.shift();
        anomalyPoints.shift();
    }

    telemetryChart.update();
}

function updateLayerProgress(key, score) {
    const scoreEl = document.getElementById(`score-${key}`);
    const fillEl = document.getElementById(`fill-${key}`);
    if (!scoreEl || !fillEl) return;

    scoreEl.innerText = score.toFixed(2);
    const pct = Math.min(100, Math.round(score * 100));
    fillEl.style.width = `${pct}%`;

    if (score > 0.7) {
        fillEl.style.background = 'linear-gradient(90deg, #f43f5e, #fb7185)';
    } else if (score > 0.4) {
        fillEl.style.background = 'linear-gradient(90deg, #f59e0b, #fbbf24)';
    } else {
        fillEl.style.background = 'linear-gradient(90deg, #06b6d4, #0284c7)';
    }
}

function addAlertToFeed(alert, timeStr) {
    const feed = document.getElementById('alert-feed');
    const entry = document.createElement('div');
    entry.className = `alert-entry ${alert.veto_fired ? 'anomaly' : 'warning'}`;

    entry.innerHTML = `
        <div class="alert-time">${timeStr}</div>
        <div class="alert-content">
            <span class="alert-tag">${alert.root_cause}</span>
            <span>${alert.explanation}</span>
        </div>
    `;

    feed.insertBefore(entry, feed.firstChild);
    if (feed.children.length > 20) {
        feed.removeChild(feed.lastChild);
    }
}

function injectFault(faultType) {
    pendingFault = faultType;
    console.log(`Triggering fault injection: ${faultType}`);
}

function clearAlerts() {
    document.getElementById('alert-feed').innerHTML = '';
}
