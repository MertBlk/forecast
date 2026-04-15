console.log("🔧 app.js starting...");

const form = document.getElementById("forecastForm");
const statusBadge = document.getElementById("statusBadge");
const runButton = document.getElementById("runButton");
const generatedAt = document.getElementById("generatedAt");
const pointsTableBody = document.getElementById("pointsTableBody");
const forecastErrorBox = document.getElementById("forecastErrorBox");
const chartCanvas = document.getElementById("forecastChart");
const tabButtons = Array.from(document.querySelectorAll(".tab-button"));
const forecastView = document.getElementById("forecastView");
const analyticsView = document.getElementById("analyticsView");


const crossSummaryForm = document.getElementById("crossSummaryForm");
const vmTrendForm = document.getElementById("vmTrendForm");
const accuracyForm = document.getElementById("accuracyForm");
const crossSummaryButton = document.getElementById("crossSummaryButton");
const vmTrendButton = document.getElementById("vmTrendButton");
const accuracyButton = document.getElementById("accuracyButton");
const analyticsTitle = document.getElementById("analyticsTitle");
const analyticsHead = document.getElementById("analyticsHead");
const analyticsBody = document.getElementById("analyticsBody");
const analyticsErrorBox = document.getElementById("analyticsErrorBox");
const analyticsChartCanvas = document.getElementById("analyticsChart");
const analyticsChartTitle = document.getElementById("analyticsChartTitle");

const metaAlgorithm = document.getElementById("metaAlgorithm");
const metaMape = document.getElementById("metaMape");
const metaHistory = document.getElementById("metaHistory");
const metaCached = document.getElementById("metaCached");

let lastPoints = [];
let analyticsChartData = null;

const money = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
  maximumFractionDigits: 2,
});

// ── Dark mode initialization ─────────────────────────────────────
function initDarkMode() {
  document.documentElement.classList.add("dark-mode");
}

async function checkHealth() {
  try {
    const resp = await fetch("/api/v1/health");
    if (!resp.ok) {
      throw new Error("Health endpoint failed");
    }
    setStatus("ok", "API hazir");
  } catch {
    setStatus("error", "API erisilemiyor");
  }
}

function setStatus(kind, text) {
  statusBadge.textContent = text;
  statusBadge.className = "status";
  statusBadge.classList.add(`status-${kind}`);
}

function setView(viewName) {
  const isForecast = viewName === "forecast";
  forecastView.hidden = !isForecast;
  analyticsView.hidden = isForecast;

  tabButtons.forEach((button) => {
    const selected = button.dataset.view === viewName;
    button.classList.toggle("is-active", selected);
  });

  if (isForecast && lastPoints.length) {
    drawChart(lastPoints);
  }

  if (!isForecast) {
    drawAnalyticsChart();
  }
}

function setLoading(loading) {
  runButton.disabled = loading;
  runButton.textContent = loading ? "Hesaplaniyor..." : "Tahmin Uret";
}

function setAnalyticsLoading(button, loading) {
  button.disabled = loading;
  button.textContent = loading ? "Yukleniyor..." : "Getir";
}

function showError(errorElement, message) {
  errorElement.hidden = false;
  errorElement.textContent = message;
}

function hideError(errorElement) {
  errorElement.hidden = true;
  errorElement.textContent = "";
}

function normalizeErrorBody(body) {
  if (!body) {
    return "Bilinmeyen hata";
  }

  if (typeof body.detail === "string") {
    return body.detail;
  }

  if (Array.isArray(body.detail)) {
    return body.detail.map((item) => item.msg || JSON.stringify(item)).join("\n");
  }

  if (body.detail && typeof body.detail === "object") {
    if (body.detail.error_code || body.detail.message) {
      return `${body.detail.error_code || "ERROR"}: ${body.detail.message || ""}`;
    }
    return JSON.stringify(body.detail, null, 2);
  }

  return JSON.stringify(body, null, 2);
}

function renderSummary(meta) {
  metaAlgorithm.textContent = meta.algorithm_used || "-";
  metaMape.textContent = typeof meta.mape_score === "number" ? `${meta.mape_score}%` : "n/a";
  metaHistory.textContent = meta.history_used ?? "-";
  metaCached.textContent = meta.cached ? "hit" : "miss";
}

function renderTable(points) {
  if (!points.length) {
    pointsTableBody.innerHTML = '<tr><td colspan="4" class="empty">Nokta bulunamadi.</td></tr>';
    return;
  }

  const rows = points
    .map(
      (point) =>
        `<tr>
          <td>${point.month}</td>
          <td>${money.format(point.predicted)}</td>
          <td>${money.format(point.lower_ci)}</td>
          <td>${money.format(point.upper_ci)}</td>
        </tr>`
    )
    .join("");

  pointsTableBody.innerHTML = rows;
}

function escapeHtml(value) {
  return String(value)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/\"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function formatAnalyticsCell(key, value) {
  if (value === null || value === undefined) {
    return "-";
  }

  if (typeof value === "number") {
    if (/(cost|predicted|lower|upper)/i.test(key)) {
      return money.format(value);
    }

    if (/(mape|score|ratio|pct|percent)/i.test(key)) {
      return String(value);
    }

    return new Intl.NumberFormat("en-US", { maximumFractionDigits: 4 }).format(value);
  }

  if (typeof value === "object") {
    return JSON.stringify(value);
  }

  return String(value);
}

function renderAnalyticsTable(title, rows) {
  analyticsTitle.textContent = title;

  if (!rows.length) {
    analyticsHead.innerHTML = "<tr><th>Sonuc</th></tr>";
    analyticsBody.innerHTML = '<tr><td class="empty">Kayit bulunamadi.</td></tr>';
    return;
  }

  const columns = Object.keys(rows[0]);
  analyticsHead.innerHTML = `<tr>${columns.map((key) => `<th>${escapeHtml(key)}</th>`).join("")}</tr>`;
  analyticsBody.innerHTML = rows
    .map((row) => {
      const cells = columns
        .map((key) => `<td>${escapeHtml(formatAnalyticsCell(key, row[key]))}</td>`)
        .join("");
      return `<tr>${cells}</tr>`;
    })
    .join("");
}

async function fetchJson(url) {
  const resp = await fetch(url);
  let body = null;

  try {
    body = await resp.json();
  } catch {
    body = null;
  }

  if (!resp.ok) {
    throw new Error(normalizeErrorBody(body));
  }

  return body;
}

function drawChart(points) {
  const ctx = chartCanvas.getContext("2d");
  if (!ctx || !points.length) {
    return;
  }

  const rect = chartCanvas.getBoundingClientRect();
  if (rect.width === 0 || rect.height === 0) {
    return;
  }

  const isDark = document.documentElement.classList.contains("dark-mode");
  const gridColor = isDark ? "rgba(168, 181, 197, 0.15)" : "rgba(74, 103, 121, 0.25)";
  const textColor = isDark ? "#a8b5c5" : "#4a6779";
  const brandColor = isDark ? "#2cdb9b" : "#007f5f";
  const accentColor = isDark ? "rgba(255, 157, 82, 0.2)" : "rgba(247, 127, 0, 0.2)";

  const dpr = window.devicePixelRatio || 1;
  chartCanvas.width = Math.floor(rect.width * dpr);
  chartCanvas.height = Math.floor(rect.height * dpr);
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

  const width = rect.width;
  const height = rect.height;
  const pad = { top: 18, right: 16, bottom: 30, left: 46 };

  ctx.clearRect(0, 0, width, height);

  const maxVal = Math.max(...points.map((p) => p.upper_ci)) * 1.08;
  const minVal = Math.max(0, Math.min(...points.map((p) => p.lower_ci)) * 0.92);
  const valueRange = Math.max(1, maxVal - minVal);

  const xFor = (index) => {
    if (points.length === 1) {
      return width / 2;
    }
    return pad.left + (index / (points.length - 1)) * (width - pad.left - pad.right);
  };

  const yFor = (value) => pad.top + ((maxVal - value) / valueRange) * (height - pad.top - pad.bottom);

  ctx.strokeStyle = gridColor;
  ctx.lineWidth = 1;
  for (let i = 0; i <= 4; i += 1) {
    const y = pad.top + (i / 4) * (height - pad.top - pad.bottom);
    ctx.beginPath();
    ctx.moveTo(pad.left, y);
    ctx.lineTo(width - pad.right, y);
    ctx.stroke();
  }

  ctx.fillStyle = accentColor;
  ctx.beginPath();
  points.forEach((point, index) => {
    const x = xFor(index);
    const y = yFor(point.upper_ci);
    if (index === 0) {
      ctx.moveTo(x, y);
    } else {
      ctx.lineTo(x, y);
    }
  });
  for (let index = points.length - 1; index >= 0; index -= 1) {
    const point = points[index];
    const x = xFor(index);
    const y = yFor(point.lower_ci);
    ctx.lineTo(x, y);
  }
  ctx.closePath();
  ctx.fill();

  ctx.strokeStyle = brandColor;
  ctx.lineWidth = 2.5;
  ctx.beginPath();
  points.forEach((point, index) => {
    const x = xFor(index);
    const y = yFor(point.predicted);
    if (index === 0) {
      ctx.moveTo(x, y);
    } else {
      ctx.lineTo(x, y);
    }
  });
  ctx.stroke();

  ctx.fillStyle = brandColor;
  points.forEach((point, index) => {
    const x = xFor(index);
    const y = yFor(point.predicted);
    ctx.beginPath();
    ctx.arc(x, y, 3.2, 0, Math.PI * 2);
    ctx.fill();
  });

  ctx.fillStyle = textColor;
  ctx.font = "11px IBM Plex Mono";
  ctx.textAlign = "center";
  points.forEach((point, index) => {
    const x = xFor(index);
    ctx.fillText(point.month, x, height - 10);
  });
}

function setAnalyticsChart(title, labels, values, mode) {
  analyticsChartTitle.textContent = title;
  analyticsChartData = { title, labels, values, mode };
  drawAnalyticsChart();
}

function clearAnalyticsChart(title) {
  analyticsChartTitle.textContent = title;
  analyticsChartData = { title, labels: [], values: [], mode: "line" };
  drawAnalyticsChart();
}

function drawAnalyticsChart() {
  const ctx = analyticsChartCanvas.getContext("2d");
  if (!ctx) {
    return;
  }

  const rect = analyticsChartCanvas.getBoundingClientRect();
  if (rect.width === 0 || rect.height === 0) {
    return;
  }

  const isDark = document.documentElement.classList.contains("dark-mode");
  const gridColor = isDark ? "rgba(168, 181, 197, 0.15)" : "rgba(74, 103, 121, 0.25)";
  const textColor = isDark ? "#a8b5c5" : "#4a6779";
  const brandColor = isDark ? "#2cdb9b" : "#007f5f";
  const barColor = isDark ? "rgba(255, 157, 82, 0.6)" : "rgba(247, 127, 0, 0.75)";

  const dpr = window.devicePixelRatio || 1;
  analyticsChartCanvas.width = Math.floor(rect.width * dpr);
  analyticsChartCanvas.height = Math.floor(rect.height * dpr);
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

  const width = rect.width;
  const height = rect.height;
  const pad = { top: 18, right: 18, bottom: 40, left: 52 };
  ctx.clearRect(0, 0, width, height);

  if (!analyticsChartData || analyticsChartData.values.length === 0) {
    ctx.fillStyle = textColor;
    ctx.font = "13px IBM Plex Mono";
    ctx.textAlign = "center";
    ctx.fillText("Grafik icin veri yok", width / 2, height / 2);
    return;
  }

  const labels = analyticsChartData.labels;
  const values = analyticsChartData.values;
  const mode = analyticsChartData.mode;

  const maxVal = Math.max(...values) * 1.1;
  const minVal = 0;
  const range = Math.max(1, maxVal - minVal);

  const yFor = (value) => pad.top + ((maxVal - value) / range) * (height - pad.top - pad.bottom);
  const usableWidth = width - pad.left - pad.right;

  ctx.strokeStyle = gridColor;
  ctx.lineWidth = 1;
  for (let i = 0; i <= 4; i += 1) {
    const y = pad.top + (i / 4) * (height - pad.top - pad.bottom);
    ctx.beginPath();
    ctx.moveTo(pad.left, y);
    ctx.lineTo(width - pad.right, y);
    ctx.stroke();
  }

  if (mode === "bar") {
    const barGap = 8;
    const count = values.length;
    const barWidth = Math.max(10, (usableWidth - barGap * (count + 1)) / count);
    values.forEach((value, index) => {
      const x = pad.left + barGap + index * (barWidth + barGap);
      const y = yFor(value);
      const h = height - pad.bottom - y;
      ctx.fillStyle = barColor;
      ctx.fillRect(x, y, barWidth, h);
    });

    ctx.fillStyle = textColor;
    ctx.font = "10px IBM Plex Mono";
    ctx.textAlign = "center";
    labels.forEach((label, index) => {
      const x = pad.left + barGap + index * (barWidth + barGap) + barWidth / 2;
      ctx.fillText(String(label).slice(0, 10), x, height - 12);
    });
    return;
  }

  const xFor = (index) => {
    if (values.length === 1) {
      return width / 2;
    }
    return pad.left + (index / (values.length - 1)) * usableWidth;
  };

  ctx.strokeStyle = brandColor;
  ctx.lineWidth = 2.2;
  ctx.beginPath();
  values.forEach((value, index) => {
    const x = xFor(index);
    const y = yFor(value);
    if (index === 0) {
      ctx.moveTo(x, y);
    } else {
      ctx.lineTo(x, y);
    }
  });
  ctx.stroke();

  ctx.fillStyle = brandColor;
  values.forEach((value, index) => {
    const x = xFor(index);
    const y = yFor(value);
    ctx.beginPath();
    ctx.arc(x, y, 3.2, 0, Math.PI * 2);
    ctx.fill();
  });

  ctx.fillStyle = textColor;
  ctx.font = "10px IBM Plex Mono";
  ctx.textAlign = "center";
  labels.forEach((label, index) => {
    const x = xFor(index);
    ctx.fillText(String(label).slice(0, 10), x, height - 12);
  });
}

async function runForecast(event) {
  event.preventDefault();
  hideError(forecastErrorBox);
  setLoading(true);

  const payload = {
    project_id: document.getElementById("projectId").value.trim(),
    horizon: Number(document.getElementById("horizon").value),
    history_months: Number(document.getElementById("historyMonths").value),
    algorithm: document.getElementById("algorithm").value,
    include_breakdown: false,
    currency: "USD",
  };

  try {
    const resp = await fetch("/api/v1/forecast", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });

    const body = await resp.json();
    if (!resp.ok) {
      throw new Error(normalizeErrorBody(body));
    }

    renderSummary(body.meta || {});
    renderTable(body.points || []);
    lastPoints = body.points || [];
    drawChart(lastPoints);

    generatedAt.textContent = `Uretildi: ${new Date(body.generated_at).toLocaleString("tr-TR")}`;
  } catch (error) {
    showError(forecastErrorBox, error instanceof Error ? error.message : "Beklenmeyen hata");
  } finally {
    setLoading(false);
  }
}

async function runCrossSummary(event) {
  event.preventDefault();
  hideError(analyticsErrorBox);
  setAnalyticsLoading(crossSummaryButton, true);

  const startMonth = document.getElementById("crossStartMonth").value;
  const endMonth = document.getElementById("crossEndMonth").value;

  try {
    const params = new URLSearchParams({
      start_month: startMonth,
      end_month: endMonth,
    });
    const body = await fetchJson(`/api/v1/analytics/cross-project-summary?${params.toString()}`);
    const rows = body.projects || [];
    renderAnalyticsTable("Cross Project Summary", rows);
    const topRows = rows.slice(0, 10);
    setAnalyticsChart(
      "Top Project Cost",
      topRows.map((row) => row.project_id),
      topRows.map((row) => Number(row.total_cost || 0)),
      "bar"
    );
  } catch (error) {
    showError(analyticsErrorBox, error instanceof Error ? error.message : "Beklenmeyen hata");
    clearAnalyticsChart("Analytics Grafik");
  } finally {
    setAnalyticsLoading(crossSummaryButton, false);
  }
}

async function runVmTrend(event) {
  event.preventDefault();
  hideError(analyticsErrorBox);
  setAnalyticsLoading(vmTrendButton, true);

  const projectId = document.getElementById("vmTrendProjectId").value.trim();
  const months = document.getElementById("vmTrendMonths").value;

  try {
    const params = new URLSearchParams({ months });
    const body = await fetchJson(
      `/api/v1/analytics/vm-type-trend/${encodeURIComponent(projectId)}?${params.toString()}`
    );
    const rows = body.trend || [];
    renderAnalyticsTable(`VM Type Trend: ${projectId}`, rows);

    const monthly = new Map();
    rows.forEach((row) => {
      const month = String(row.billing_month || "-").slice(0, 10);
      const current = monthly.get(month) || 0;
      monthly.set(month, current + Number(row.cost || 0));
    });
    const labels = Array.from(monthly.keys());
    const values = labels.map((label) => monthly.get(label));
    setAnalyticsChart(`Aylik Toplam Cost: ${projectId}`, labels, values, "line");
  } catch (error) {
    showError(analyticsErrorBox, error instanceof Error ? error.message : "Beklenmeyen hata");
    clearAnalyticsChart("Analytics Grafik");
  } finally {
    setAnalyticsLoading(vmTrendButton, false);
  }
}

async function runForecastAccuracy(event) {
  event.preventDefault();
  hideError(analyticsErrorBox);
  setAnalyticsLoading(accuracyButton, true);

  const projectId = document.getElementById("accuracyProjectId").value.trim();
  const limit = document.getElementById("accuracyLimit").value;

  try {
    const params = new URLSearchParams({ limit });
    const body = await fetchJson(
      `/api/v1/analytics/forecast-accuracy/${encodeURIComponent(projectId)}?${params.toString()}`
    );
    const rows = body.forecasts || [];
    renderAnalyticsTable(`Forecast Accuracy: ${projectId}`, rows);

    const ordered = [...rows].reverse();
    setAnalyticsChart(
      `MAPE History: ${projectId}`,
      ordered.map((row) => String(row.created_at || "-").slice(0, 10)),
      ordered.map((row) => Number(row.mape_score || 0)),
      "line"
    );
  } catch (error) {
    showError(analyticsErrorBox, error instanceof Error ? error.message : "Beklenmeyen hata");
    clearAnalyticsChart("Analytics Grafik");
  } finally {
    setAnalyticsLoading(accuracyButton, false);
  }
}

window.addEventListener("resize", () => {
  if (lastPoints.length) {
    drawChart(lastPoints);
  }

  if (!analyticsView.hidden) {
    drawAnalyticsChart();
  }
});

form.addEventListener("submit", runForecast);
crossSummaryForm.addEventListener("submit", runCrossSummary);
vmTrendForm.addEventListener("submit", runVmTrend);
accuracyForm.addEventListener("submit", runForecastAccuracy);

tabButtons.forEach((button) => {
  button.addEventListener("click", () => {
    setView(button.dataset.view || "forecast");
  });
});

setView("forecast");
clearAnalyticsChart("Analytics Grafik");
checkHealth();
initDarkMode();
