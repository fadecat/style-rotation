<script setup>
import axios from "axios";
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref, watch } from "vue";
import { use, init } from "echarts/core";
import { CanvasRenderer } from "echarts/renderers";
import { LineChart, ScatterChart } from "echarts/charts";
import {
  AxisPointerComponent,
  DataZoomComponent,
  GridComponent,
  LegendComponent,
  MarkLineComponent,
  TitleComponent,
  TooltipComponent,
} from "echarts/components";

use([
  CanvasRenderer,
  LineChart,
  ScatterChart,
  GridComponent,
  LegendComponent,
  MarkLineComponent,
  TitleComponent,
  TooltipComponent,
  DataZoomComponent,
  AxisPointerComponent,
]);

const API_BASE = "http://127.0.0.1:8000";
const BUY_ARROW = "path://M512 128l224 320H608v448H416V448H288z";
const SELL_ARROW = "path://M512 896L288 576h128V128h192v448h128z";

const instruments = ref([]);
const loading = reactive({
  instruments: false,
  analysis: false,
  sync: false,
});
const form = reactive({
  leftSymbol: "399376",
  rightSymbol: "399373",
  startDate: "2024-01-01",
  endDate: new Date().toISOString().slice(0, 10),
});
const latestSyncWindow = reactive({
  source: "tencent",
  startDate: "2018-01-01",
  endDate: new Date().toISOString().slice(0, 10),
});
const response = ref(null);
const errorMessage = ref("");
const valuationUploadMessage = ref("");
const valuationUpload = reactive({
  symbol: "",
});

const chartRef = ref(null);
let chartInstance;
const peFileInputRef = ref(null);
const pbFileInputRef = ref(null);
const dividendFileInputRef = ref(null);

const leftInstrument = computed(() => instruments.value.find((item) => item.symbol === form.leftSymbol));
const rightInstrument = computed(() => instruments.value.find((item) => item.symbol === form.rightSymbol));
const indexInstruments = computed(() => instruments.value.filter((item) => item.asset_type === "INDEX"));
const selectedValuationInstrument = computed(() =>
  indexInstruments.value.find((item) => item.symbol === valuationUpload.symbol)
);

const summaryCards = computed(() => {
  if (!response.value) {
    return [];
  }
  const summary = response.value.summary;
  return [
    { label: "最新价差", value: summary.latest_spread },
    { label: "最新均线", value: summary.latest_ma },
    { label: "全局 P90", value: summary.global_p90 },
    { label: "全局 P10", value: summary.global_p10 },
    { label: "信号数", value: summary.signal_count },
    { label: "最新信号", value: summary.latest_signal },
  ];
});

function formatNumber(value, digits = 2) {
  if (typeof value !== "number") {
    return value;
  }
  return value.toFixed(digits);
}

function buildStrengthAreaData(spread, predicate) {
  return spread.map((value) => (predicate(value) ? value : "-"));
}

function buildFlatReference(dates, value) {
  return dates.map(() => value);
}

function extractSeriesColor(color) {
  if (!color) {
    return "#6b7280";
  }
  if (typeof color === "string") {
    return color;
  }
  if (color.colorStops?.length) {
    return color.colorStops[0].color;
  }
  return "#6b7280";
}

function formatTooltipValue(seriesName, value) {
  if (value === "-" || value == null || Number.isNaN(value)) {
    return "--";
  }
  if (seriesName.includes("收益") || seriesName.includes("价差") || seriesName.includes("信号")) {
    return `${Number(value).toFixed(2)}%`;
  }
  return Number(value).toFixed(4);
}

function tooltipFormatter(params) {
  if (!params?.length) {
    return "";
  }
  const rows = params.filter(
    (item) =>
      item.seriesName &&
      !item.seriesName.startsWith("_") &&
      !["价差>0(左侧强)", "价差<0(右侧强)"].includes(item.seriesName) &&
      item.value !== "-" &&
      item.value != null
  );
  let html = `<div style="font-size:13px;font-weight:700;margin-bottom:8px;color:#162032;">${params[0].axisValue}</div>`;

  rows.forEach((item) => {
    const color = extractSeriesColor(item.color);
    const marker =
      `<span style="display:inline-block;margin-right:6px;border-radius:10px;width:10px;height:10px;background:${color};"></span>`;
    html += `<div style="display:flex;justify-content:space-between;gap:16px;width:240px;margin-top:4px;">
      <span style="color:#4b5563;">${marker}${item.seriesName}</span>
      <span style="font-weight:700;color:#111827;">${formatTooltipValue(item.seriesName, item.value)}</span>
    </div>`;
  });

  return html;
}

async function fetchInstruments() {
  loading.instruments = true;
  errorMessage.value = "";
  try {
    const { data } = await axios.get(`${API_BASE}/api/instruments`);
    instruments.value = data.data.items;
    if (!indexInstruments.value.some((item) => item.symbol === valuationUpload.symbol)) {
      valuationUpload.symbol = "";
    }
  } catch (error) {
    errorMessage.value = error.response?.data?.message ?? "无法加载标的列表";
  } finally {
    loading.instruments = false;
  }
}

async function analyze() {
  if (!form.leftSymbol || !form.rightSymbol) {
    errorMessage.value = "请选择左右标的";
    return;
  }
  loading.analysis = true;
  errorMessage.value = "";
  try {
    const { data } = await axios.get(`${API_BASE}/api/style-rotation`, {
      params: {
        left_symbol: form.leftSymbol,
        right_symbol: form.rightSymbol,
        start_date: form.startDate,
        end_date: form.endDate,
      },
    });
    response.value = data.data;
    await nextTick();
    renderChart();
  } catch (error) {
    response.value = null;
    errorMessage.value = error.response?.data?.message ?? "分析失败";
    renderChart();
  } finally {
    loading.analysis = false;
  }
}

function triggerValuationUpload(metricType) {
  const mapping = {
    pe: peFileInputRef,
    pb: pbFileInputRef,
    dividend_yield: dividendFileInputRef,
  };
  mapping[metricType]?.value?.click();
}

async function uploadValuationFile(metricType, event) {
  const file = event.target.files?.[0];
  event.target.value = "";

  if (!file) {
    return;
  }
  if (!valuationUpload.symbol) {
    errorMessage.value = "请先选择目标指数代码";
    return;
  }
  if (!selectedValuationInstrument.value) {
    errorMessage.value = "目标指数代码无效，请重新选择";
    return;
  }

  const confirmed = window.confirm(
    `确认上传 ${file.name}\n目标指数：${selectedValuationInstrument.value.symbol} / ${selectedValuationInstrument.value.name}\n指标类型：${metricType}`
  );
  if (!confirmed) {
    return;
  }

  loading.sync = true;
  errorMessage.value = "";
  valuationUploadMessage.value = "";
  try {
    const formData = new FormData();
    formData.append("symbol", valuationUpload.symbol);
    formData.append("metric_type", metricType);
    formData.append("file", file);

    const { data } = await axios.post(`${API_BASE}/api/valuations/upload`, formData, {
      headers: { "Content-Type": "multipart/form-data" },
    });
    const result = data.data;
    valuationUploadMessage.value =
      `${metricType.toUpperCase()} 上传成功：${selectedValuationInstrument.value.name}(${result.symbol})，${result.row_count} 行，范围 ${result.earliest_date} 至 ${result.latest_date}`;
  } catch (error) {
    errorMessage.value = error.response?.data?.message ?? "估值文件上传失败";
  } finally {
    loading.sync = false;
  }
}

async function syncData() {
  if (!leftInstrument.value || !rightInstrument.value) {
    errorMessage.value = "同步前请先加载并选择标的";
    return;
  }
  if (
    latestSyncWindow.source === "tencent" &&
    [leftInstrument.value, rightInstrument.value].some((item) => item.asset_type === "ETF")
  ) {
    errorMessage.value = "腾讯数据源当前只支持指数，请改选指数标的";
    return;
  }
  loading.sync = true;
  errorMessage.value = "";
  try {
    await axios.post(`${API_BASE}/api/market-data/sync`, {
      symbols: [leftInstrument.value, rightInstrument.value],
      source: latestSyncWindow.source,
      start_date: latestSyncWindow.startDate,
      end_date: latestSyncWindow.endDate,
    });
    await analyze();
  } catch (error) {
    errorMessage.value = error.response?.data?.message ?? "同步失败";
  } finally {
    loading.sync = false;
  }
}

function ensureChart() {
  if (!chartRef.value) {
    return undefined;
  }
  if (!chartInstance) {
    chartInstance = init(chartRef.value);
  }
  return chartInstance;
}

function buildCompositeOption() {
  const data = response.value;
  if (!data) {
    return {
      title: {
        text: "暂无图表数据",
        left: "center",
        top: "middle",
        textStyle: { color: "#6b7280", fontSize: 18, fontWeight: 600 },
      },
      xAxis: [{ show: false }],
      yAxis: [{ show: false }],
      series: [],
    };
  }

  const { meta, series, summary, signals } = data;
  const positiveArea = buildStrengthAreaData(series.spread, (value) => value > 0);
  const negativeArea = buildStrengthAreaData(series.spread, (value) => value < 0);
  const globalP90 = buildFlatReference(series.dates, summary.global_p90);
  const globalP10 = buildFlatReference(series.dates, summary.global_p10);
  const buySignals = signals
    .filter((item) => item.type === "buy")
    .map((item) => [item.date, item.spread]);
  const sellSignals = signals
    .filter((item) => item.type === "sell")
    .map((item) => [item.date, item.spread]);

  return {
    animation: false,
    legend: {
      top: 16,
      left: "center",
      itemWidth: 12,
      itemHeight: 12,
      textStyle: {
        color: "#475467",
        fontSize: 12,
        fontWeight: 600,
      },
      data: [
        "价差>0(左侧强)",
        "价差<0(右侧强)",
        "收益价差",
        "MA20",
        "全局P90",
        "全局P10",
      ],
    },
    tooltip: {
      trigger: "axis",
      axisPointer: {
        type: "cross",
        snap: true,
        label: {
          backgroundColor: "#d1d5db",
          color: "#111827",
        },
      },
      backgroundColor: "rgba(255, 251, 245, 0.94)",
      borderColor: "rgba(148, 163, 184, 0.35)",
      borderWidth: 1,
      textStyle: {
        color: "#111827",
      },
      extraCssText: "box-shadow: 0 18px 36px rgba(15, 23, 42, 0.16); border-radius: 14px; padding: 10px 12px;",
      formatter: tooltipFormatter,
    },
    axisPointer: {
      link: [{ xAxisIndex: [0] }],
    },
    dataZoom: [
      {
        type: "slider",
        xAxisIndex: [0],
        bottom: 14,
        height: 18,
        start: 0,
        end: 100,
        borderColor: "rgba(148, 163, 184, 0.32)",
        fillerColor: "rgba(39, 76, 119, 0.12)",
      },
      {
        type: "inside",
        xAxisIndex: [0],
      },
    ],
    grid: [
      { top: "10%", bottom: "14%", left: "5%", right: "5%" },
    ],
    xAxis: [
      {
        type: "category",
        data: series.dates,
        boundaryGap: false,
        axisLabel: { color: "#667085", hideOverlap: true },
        axisTick: { show: false },
        axisLine: { lineStyle: { color: "#cbd5e1" } },
      },
    ],
    yAxis: [
      {
        type: "value",
        name: "收益差值(%)",
        nameLocation: "middle",
        nameGap: 42,
        scale: true,
        axisLabel: { color: "#667085" },
        axisLine: { show: false },
        splitLine: { lineStyle: { color: "rgba(148, 163, 184, 0.18)" } },
      },
    ],
    series: [
      {
        name: "价差>0(左侧强)",
        type: "line",
        data: positiveArea,
        symbol: "none",
        lineStyle: { opacity: 0 },
        areaStyle: { color: "rgba(214, 67, 69, 0.22)" },
        tooltip: { show: false },
        z: 1,
      },
      {
        name: "价差<0(右侧强)",
        type: "line",
        data: negativeArea,
        symbol: "none",
        lineStyle: { opacity: 0 },
        areaStyle: { color: "rgba(29, 141, 87, 0.22)" },
        tooltip: { show: false },
        z: 1,
      },
      {
        name: "收益价差",
        type: "line",
        data: series.spread,
        symbol: "none",
        lineStyle: { width: 1.8, color: "#1f2937" },
        z: 4,
      },
      {
        name: "MA20",
        type: "line",
        data: series.ma,
        symbol: "none",
        lineStyle: { width: 1.6, type: "dashed", color: "#f59e0b" },
        z: 4,
      },
      {
        name: "全局P90",
        type: "line",
        data: globalP90,
        symbol: "none",
        lineStyle: { width: 1.2, type: "dashed", color: "#dc2626" },
        z: 3,
      },
      {
        name: "全局P10",
        type: "line",
        data: globalP10,
        symbol: "none",
        lineStyle: { width: 1.2, type: "dashed", color: "#16a34a" },
        z: 3,
      },
      {
        name: "买入信号",
        type: "scatter",
        data: buySignals,
        symbol: BUY_ARROW,
        symbolSize: 16,
        itemStyle: { color: "#16a34a" },
        z: 6,
      },
      {
        name: "卖出信号",
        type: "scatter",
        data: sellSignals,
        symbol: SELL_ARROW,
        symbolSize: 16,
        itemStyle: { color: "#dc2626" },
        z: 6,
      },
    ],
  };
}

function renderChart() {
  const chart = ensureChart();
  chart?.setOption(buildCompositeOption(), true);
}

function handleResize() {
  chartInstance?.resize();
}

watch(
  () => response.value,
  async () => {
    await nextTick();
    renderChart();
  }
);

onMounted(async () => {
  window.addEventListener("resize", handleResize);
  await fetchInstruments();
  await analyze();
});

onBeforeUnmount(() => {
  window.removeEventListener("resize", handleResize);
  chartInstance?.dispose();
});
</script>

<template>
  <main class="page-shell">
    <section class="hero-panel">
      <div class="hero-copy">
        <p class="eyebrow">Style Rotation Dashboard</p>
        <h1>风格轮动单页分析台</h1>
        <p class="hero-text">
          选择任意两只指数或 ETF，拉取历史数据，计算收益价差、动态分位数和买卖信号，并在同一页面完成查看。
        </p>
      </div>
      <div class="hero-actions">
        <button class="ghost-button" :disabled="loading.sync" @click="syncData">
          {{ loading.sync ? "同步中..." : "同步数据" }}
        </button>
        <button class="primary-button" :disabled="loading.analysis" @click="analyze">
          {{ loading.analysis ? "分析中..." : "开始分析" }}
        </button>
      </div>
    </section>

    <section class="control-panel">
      <div class="field">
        <label>左侧标的</label>
        <select v-model="form.leftSymbol" :disabled="loading.instruments">
          <option v-for="item in instruments" :key="item.symbol" :value="item.symbol">
            {{ item.symbol }} / {{ item.name }}
          </option>
        </select>
      </div>
      <div class="field">
        <label>右侧标的</label>
        <select v-model="form.rightSymbol" :disabled="loading.instruments">
          <option v-for="item in instruments" :key="item.symbol" :value="item.symbol">
            {{ item.symbol }} / {{ item.name }}
          </option>
        </select>
      </div>
      <div class="field">
        <label>开始日期</label>
        <input v-model="form.startDate" type="date" />
      </div>
      <div class="field">
        <label>结束日期</label>
        <input v-model="form.endDate" type="date" />
      </div>
      <div class="field">
        <label>同步来源</label>
        <input value="Tencent" type="text" disabled />
      </div>
      <div class="field">
        <label>同步开始</label>
        <input v-model="latestSyncWindow.startDate" type="date" />
      </div>
      <div class="field">
        <label>同步结束</label>
        <input v-model="latestSyncWindow.endDate" type="date" />
      </div>
    </section>

    <section v-if="errorMessage" class="error-banner">
      {{ errorMessage }}
    </section>

    <section class="valuation-upload-panel">
      <div class="valuation-upload-header">
        <div>
          <span class="section-kicker">Valuation Upload</span>
          <h2>目标指数估值 CSV 上传</h2>
        </div>
        <div class="field">
          <label>目标指数代码</label>
          <select v-model="valuationUpload.symbol" :disabled="loading.instruments">
            <option value="">请选择指数</option>
            <option v-for="item in indexInstruments" :key="item.symbol" :value="item.symbol">
              {{ item.symbol }} / {{ item.name }}
            </option>
          </select>
        </div>
      </div>
      <div class="valuation-upload-actions">
        <button class="upload-button" :disabled="loading.sync || !valuationUpload.symbol" @click="triggerValuationUpload('pe')">上传 PE CSV</button>
        <button class="upload-button" :disabled="loading.sync || !valuationUpload.symbol" @click="triggerValuationUpload('pb')">上传 PB CSV</button>
        <button class="upload-button" :disabled="loading.sync || !valuationUpload.symbol" @click="triggerValuationUpload('dividend_yield')">
          上传股息率 CSV
        </button>
      </div>
      <p class="upload-target">
        当前目标：
        <strong>{{ selectedValuationInstrument ? `${selectedValuationInstrument.symbol} / ${selectedValuationInstrument.name}` : "未选择" }}</strong>
      </p>
      <input ref="peFileInputRef" class="hidden-input" type="file" accept=".csv,text/csv" @change="uploadValuationFile('pe', $event)" />
      <input ref="pbFileInputRef" class="hidden-input" type="file" accept=".csv,text/csv" @change="uploadValuationFile('pb', $event)" />
      <input
        ref="dividendFileInputRef"
        class="hidden-input"
        type="file"
        accept=".csv,text/csv"
        @change="uploadValuationFile('dividend_yield', $event)"
      />
      <p v-if="valuationUploadMessage" class="upload-success">{{ valuationUploadMessage }}</p>
    </section>

    <section class="summary-grid">
      <article v-for="card in summaryCards" :key="card.label" class="summary-card">
        <span>{{ card.label }}</span>
        <strong>{{ typeof card.value === 'number' ? formatNumber(card.value) : card.value }}</strong>
      </article>
    </section>

    <section v-if="response" class="meta-strip">
      <div>
        <span>左侧</span>
        <strong>{{ response.meta.left_symbol }} / {{ response.meta.left_name }}</strong>
      </div>
      <div>
        <span>右侧</span>
        <strong>{{ response.meta.right_symbol }} / {{ response.meta.right_name }}</strong>
      </div>
      <div>
        <span>窗口</span>
        <strong>{{ response.meta.start_date }} 至 {{ response.meta.end_date }}</strong>
      </div>
    </section>

    <section class="charts-grid">
      <article class="chart-card chart-card-composite">
        <div ref="chartRef" class="chart-canvas chart-canvas-composite"></div>
      </article>
    </section>
  </main>
</template>
