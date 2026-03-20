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
const LEFT_SERIES_COLOR = "#2563eb";
const RIGHT_SERIES_COLOR = "#f97316";

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
const VISIBLE_INSTRUMENT_SYMBOLS = new Set(["399376", "399373", "000852", "000922"]);
const response = ref(null);
const errorMessage = ref("");
const valuationUploadMessage = ref("");
const valuationUpload = reactive({
  symbol: "",
});
const syncSelection = reactive({
  leftSymbol: "",
  rightSymbol: "",
});
const syncModal = reactive({
  open: false,
  loading: false,
});
const syncStatus = reactive({
  left: null,
  right: null,
});
const syncStatusError = ref("");
const syncMessage = ref("");
const valuationModal = reactive({
  open: false,
  loading: false,
});
const exportModal = reactive({
  open: false,
  scale: "2",
  exporting: false,
  copying: false,
});
const valuationStatus = ref(null);
const valuationStatusError = ref("");
const exportMessage = ref("");
let syncStatusRequestId = 0;
let valuationStatusRequestId = 0;
let analyzeRequestId = 0;
let analyzeDebounceTimer = null;
const analysisReady = ref(false);

const chartRef = ref(null);
let chartInstance;
const peFileInputRef = ref(null);
const pbFileInputRef = ref(null);
const dividendFileInputRef = ref(null);

const visibleInstruments = computed(() => instruments.value.filter((item) => VISIBLE_INSTRUMENT_SYMBOLS.has(item.symbol)));
const leftInstrument = computed(() => visibleInstruments.value.find((item) => item.symbol === form.leftSymbol));
const rightInstrument = computed(() => visibleInstruments.value.find((item) => item.symbol === form.rightSymbol));
const syncLeftInstrument = computed(() => visibleInstruments.value.find((item) => item.symbol === syncSelection.leftSymbol));
const syncRightInstrument = computed(() => visibleInstruments.value.find((item) => item.symbol === syncSelection.rightSymbol));
const indexInstruments = computed(() => visibleInstruments.value.filter((item) => item.asset_type === "INDEX"));
const selectedValuationInstrument = computed(() =>
  indexInstruments.value.find((item) => item.symbol === valuationUpload.symbol)
);

const LEFT_SYMBOL_POOL = new Set(["399376", "000852"]);
const RIGHT_SYMBOL_POOL = new Set(["399373", "000922"]);
const LEFT_NAME_KEYWORDS = ["小盘", "成长", "1000"];
const RIGHT_NAME_KEYWORDS = ["大盘", "价值", "红利"];
const VALUATION_METRICS = [
  { key: "pe", label: "PE" },
  { key: "pb", label: "PB" },
  { key: "dividend_yield", label: "股息率" },
];
const DATE_RANGE_PRESETS = [
  { key: "custom", label: "自定义" },
  { key: "1m", label: "最近1个月" },
  { key: "3m", label: "最近3个月" },
  { key: "6m", label: "最近6个月" },
  { key: "ytd", label: "年初至今" },
  { key: "1y", label: "最近1年" },
  { key: "3y", label: "最近3年" },
  { key: "5y", label: "最近5年" },
  { key: "10y", label: "最近10年" },
  { key: "20y", label: "最近20年" },
];
const dateRangeSelection = reactive({
  analysis: "1y",
  sync: "custom",
});

function matchesKeywords(name, keywords) {
  return keywords.some((keyword) => name.includes(keyword));
}

function buildInstrumentGroups(side) {
  const preferredPool = side === "left" ? LEFT_SYMBOL_POOL : RIGHT_SYMBOL_POOL;
  const preferredKeywords = side === "left" ? LEFT_NAME_KEYWORDS : RIGHT_NAME_KEYWORDS;
  const preferredLabel = side === "left" ? "成长/小盘/科技" : "大盘/价值/红利";
  const preferred = [];

  visibleInstruments.value.forEach((item) => {
    if (preferredPool.has(item.symbol) || matchesKeywords(item.name, preferredKeywords)) {
      preferred.push(item);
    }
  });

  const groups = [];
  if (preferred.length) {
    groups.push({ label: preferredLabel, items: preferred });
  }
  return groups;
}

const leftInstrumentGroups = computed(() => buildInstrumentGroups("left"));
const rightInstrumentGroups = computed(() => buildInstrumentGroups("right"));
const syncStatusCards = computed(() => [
  {
    side: "left",
    title: "左侧标的",
    instrument: syncLeftInstrument.value,
    status: syncStatus.left,
    accent: LEFT_SERIES_COLOR,
  },
  {
    side: "right",
    title: "右侧标的",
    instrument: syncRightInstrument.value,
    status: syncStatus.right,
    accent: RIGHT_SERIES_COLOR,
  },
]);

function flattenInstrumentGroups(groups) {
  return groups.flatMap((group) => group.items);
}

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

const valuationMetricCards = computed(() =>
  VALUATION_METRICS.map((metric) => ({
    ...metric,
    ...(valuationStatus.value?.metrics?.[metric.key] ?? {
      exists: false,
      row_count: 0,
      earliest_date: null,
      latest_date: null,
    }),
  }))
);

function formatNumber(value, digits = 2) {
  if (typeof value !== "number") {
    return value;
  }
  return value.toFixed(digits);
}

function formatRange(status) {
  if (!status?.exists) {
    return "暂无数据";
  }
  return `${status.earliest_date} 至 ${status.latest_date}`;
}

function formatSourceList(status) {
  if (!status?.sources?.length) {
    return "暂无";
  }
  return status.sources.join(", ");
}

function getLatestTradingDate(baseDate = new Date()) {
  const tradingDate = new Date(baseDate);
  const weekday = tradingDate.getDay();
  if (weekday === 6) {
    tradingDate.setDate(tradingDate.getDate() - 1);
  } else if (weekday === 0) {
    tradingDate.setDate(tradingDate.getDate() - 2);
  }
  tradingDate.setHours(0, 0, 0, 0);
  return tradingDate;
}

function formatDateToIso(value) {
  const year = value.getFullYear();
  const month = String(value.getMonth() + 1).padStart(2, "0");
  const day = String(value.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

function parseIsoDate(value) {
  if (!value) {
    return new Date();
  }
  const [year, month, day] = value.split("-").map(Number);
  return new Date(year, (month || 1) - 1, day || 1);
}

function subtractMonths(value, months) {
  const target = new Date(value);
  const originalDay = target.getDate();
  target.setDate(1);
  target.setMonth(target.getMonth() - months);
  const maxDay = new Date(target.getFullYear(), target.getMonth() + 1, 0).getDate();
  target.setDate(Math.min(originalDay, maxDay));
  return target;
}

function subtractYears(value, years) {
  const target = new Date(value);
  const originalMonth = target.getMonth();
  target.setFullYear(target.getFullYear() - years);
  if (target.getMonth() !== originalMonth) {
    target.setDate(0);
  }
  return target;
}

function countWeekdayGap(startIso, endIso) {
  if (!startIso || !endIso || startIso >= endIso) {
    return 0;
  }
  const cursor = new Date(`${startIso}T00:00:00`);
  const end = new Date(`${endIso}T00:00:00`);
  let gap = 0;
  cursor.setDate(cursor.getDate() + 1);
  while (cursor <= end) {
    const day = cursor.getDay();
    if (day !== 0 && day !== 6) {
      gap += 1;
    }
    cursor.setDate(cursor.getDate() + 1);
  }
  return gap;
}

const latestTradingDateIso = computed(() => formatDateToIso(getLatestTradingDate()));

function getPresetStartDate(endIso, presetKey) {
  const endDate = parseIsoDate(endIso || formatDateToIso(new Date()));
  let startDate = null;
  if (presetKey === "1m") {
    startDate = subtractMonths(endDate, 1);
  } else if (presetKey === "3m") {
    startDate = subtractMonths(endDate, 3);
  } else if (presetKey === "6m") {
    startDate = subtractMonths(endDate, 6);
  } else if (presetKey === "ytd") {
    startDate = new Date(endDate.getFullYear(), 0, 1);
  } else if (presetKey === "1y") {
    startDate = subtractYears(endDate, 1);
  } else if (presetKey === "3y") {
    startDate = subtractYears(endDate, 3);
  } else if (presetKey === "5y") {
    startDate = subtractYears(endDate, 5);
  } else if (presetKey === "10y") {
    startDate = subtractYears(endDate, 10);
  } else if (presetKey === "20y") {
    startDate = subtractYears(endDate, 20);
  }
  return startDate ? formatDateToIso(startDate) : null;
}

function applyDateRangePreset(scope) {
  const target = scope === "analysis" ? form : latestSyncWindow;
  const presetKey = dateRangeSelection[scope];
  if (presetKey === "custom") {
    return;
  }
  const fallbackEndDate = formatDateToIso(new Date());
  if (!target.endDate) {
    target.endDate = fallbackEndDate;
  }
  const startDate = getPresetStartDate(target.endDate, presetKey);
  if (startDate) {
    target.startDate = startDate;
  }
}

function markCustomDateRange(scope) {
  dateRangeSelection[scope] = "custom";
}

function getSyncFreshness(status) {
  if (!status?.exists || !status.latest_date) {
    return {
      level: "missing",
      label: "缺失，建议同步",
      detail: `目标最新交易日：${latestTradingDateIso.value}`,
    };
  }
  if (status.latest_date >= latestTradingDateIso.value) {
    return {
      level: "fresh",
      label: "已最新",
      detail: `已覆盖到 ${status.latest_date}`,
    };
  }
  const lagDays = countWeekdayGap(status.latest_date, latestTradingDateIso.value);
  return {
    level: "stale",
    label: "建议更新",
    detail: `比最新交易日 ${latestTradingDateIso.value} 落后 ${lagDays} 个交易日`,
  };
}

function buildMetricSubtitle(metricLabel, leftLabel, rightLabel) {
  return `{metric|${metricLabel}}  {left|左: ${leftLabel}}  {right|右: ${rightLabel}}`;
}

function buildValuationEndLabel(label) {
  return {
    show: true,
    formatter: label,
    color: "inherit",
    fontSize: 12,
    fontWeight: 700,
    distance: 6,
    backgroundColor: "rgba(255, 252, 247, 0.92)",
    borderRadius: 10,
    padding: [3, 8],
  };
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
  if (seriesName.includes("股息率")) {
    return `${(Number(value) * 100).toFixed(2)}%`;
  }
  if (seriesName.includes("收益") || seriesName.includes("价差") || seriesName.includes("信号")) {
    return `${Number(value).toFixed(2)}%`;
  }
  return Number(value).toFixed(2);
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
    const leftCandidates = flattenInstrumentGroups(leftInstrumentGroups.value);
    const rightCandidates = flattenInstrumentGroups(rightInstrumentGroups.value);
    if (!leftCandidates.some((item) => item.symbol === form.leftSymbol)) {
      form.leftSymbol = leftCandidates[0]?.symbol ?? "";
    }
    if (!rightCandidates.some((item) => item.symbol === form.rightSymbol)) {
      form.rightSymbol = rightCandidates[0]?.symbol ?? "";
    }
    if (!leftCandidates.some((item) => item.symbol === syncSelection.leftSymbol)) {
      syncSelection.leftSymbol = form.leftSymbol || leftCandidates[0]?.symbol || "";
    }
    if (!rightCandidates.some((item) => item.symbol === syncSelection.rightSymbol)) {
      syncSelection.rightSymbol = form.rightSymbol || rightCandidates[0]?.symbol || "";
    }
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
  const requestId = ++analyzeRequestId;
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
    if (requestId !== analyzeRequestId) {
      return;
    }
    response.value = data.data;
    await nextTick();
    renderChart();
  } catch (error) {
    if (requestId !== analyzeRequestId) {
      return;
    }
    response.value = null;
    errorMessage.value = error.response?.data?.message ?? "分析失败";
    renderChart();
  } finally {
    if (requestId === analyzeRequestId) {
      loading.analysis = false;
    }
  }
}

function scheduleAnalyze() {
  if (!analysisReady.value) {
    return;
  }
  if (analyzeDebounceTimer) {
    clearTimeout(analyzeDebounceTimer);
  }
  analyzeDebounceTimer = setTimeout(() => {
    analyzeDebounceTimer = null;
    analyze();
  }, 160);
}

function openSyncModal() {
  syncModal.open = true;
  syncMessage.value = "";
  syncStatusError.value = "";
  if (!syncSelection.leftSymbol) {
    syncSelection.leftSymbol = form.leftSymbol || flattenInstrumentGroups(leftInstrumentGroups.value)[0]?.symbol || "";
  }
  if (!syncSelection.rightSymbol) {
    syncSelection.rightSymbol = form.rightSymbol || flattenInstrumentGroups(rightInstrumentGroups.value)[0]?.symbol || "";
  }
}

function closeSyncModal() {
  syncModal.open = false;
  syncModal.loading = false;
  syncStatus.left = null;
  syncStatus.right = null;
  syncStatusError.value = "";
  syncMessage.value = "";
}

async function fetchSyncStatus() {
  if (!syncLeftInstrument.value || !syncRightInstrument.value) {
    syncStatus.left = null;
    syncStatus.right = null;
    syncStatusError.value = "请先在弹窗中选择要同步的左右标的";
    return;
  }
  if (syncLeftInstrument.value.symbol === syncRightInstrument.value.symbol) {
    syncStatus.left = null;
    syncStatus.right = null;
    syncStatusError.value = "同步左右标的不能相同";
    return;
  }
  const requestId = ++syncStatusRequestId;
  syncModal.loading = true;
  syncStatusError.value = "";
  try {
    const [{ data: leftData }, { data: rightData }] = await Promise.all([
      axios.get(`${API_BASE}/api/market-data/status`, { params: { symbol: syncLeftInstrument.value.symbol } }),
      axios.get(`${API_BASE}/api/market-data/status`, { params: { symbol: syncRightInstrument.value.symbol } }),
    ]);
    if (
      requestId !== syncStatusRequestId ||
      !syncModal.open ||
      syncLeftInstrument.value?.symbol !== leftData.data.symbol ||
      syncRightInstrument.value?.symbol !== rightData.data.symbol
    ) {
      return;
    }
    syncStatus.left = leftData.data;
    syncStatus.right = rightData.data;
  } catch (error) {
    if (requestId !== syncStatusRequestId || !syncModal.open) {
      return;
    }
    syncStatus.left = null;
    syncStatus.right = null;
    syncStatusError.value = error.response?.data?.message ?? "无法加载价格数据状态";
  } finally {
    if (requestId === syncStatusRequestId) {
      syncModal.loading = false;
    }
  }
}

function openValuationModal() {
  valuationModal.open = true;
  valuationUploadMessage.value = "";
  valuationStatusError.value = "";
  if (!valuationUpload.symbol) {
    valuationUpload.symbol = form.leftSymbol || indexInstruments.value[0]?.symbol || "";
  }
}

function closeValuationModal() {
  valuationModal.open = false;
  valuationModal.loading = false;
  valuationUploadMessage.value = "";
  valuationStatus.value = null;
  valuationStatusError.value = "";
}

async function fetchValuationStatus(symbol) {
  if (!symbol) {
    valuationStatus.value = null;
    valuationStatusError.value = "";
    return;
  }
  const requestId = ++valuationStatusRequestId;
  valuationModal.loading = true;
  valuationStatusError.value = "";
  try {
    const { data } = await axios.get(`${API_BASE}/api/valuations/status`, {
      params: { symbol },
    });
    if (requestId !== valuationStatusRequestId || !valuationModal.open || valuationUpload.symbol !== symbol) {
      return;
    }
    valuationStatus.value = data.data;
  } catch (error) {
    if (requestId !== valuationStatusRequestId || !valuationModal.open || valuationUpload.symbol !== symbol) {
      return;
    }
    valuationStatus.value = null;
    valuationStatusError.value = error.response?.data?.message ?? "无法加载估值数据状态";
  } finally {
    if (requestId === valuationStatusRequestId) {
      valuationModal.loading = false;
    }
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
    await fetchValuationStatus(valuationUpload.symbol);
  } catch (error) {
    errorMessage.value = error.response?.data?.message ?? "估值文件上传失败";
  } finally {
    loading.sync = false;
  }
}

async function syncData() {
  if (!syncLeftInstrument.value || !syncRightInstrument.value) {
    errorMessage.value = "请先在同步弹窗中选择左右标的";
    return;
  }
  if (syncLeftInstrument.value.symbol === syncRightInstrument.value.symbol) {
    errorMessage.value = "同步左右标的不能相同";
    return;
  }
  if (
    latestSyncWindow.source === "tencent" &&
    [syncLeftInstrument.value, syncRightInstrument.value].some((item) => item.asset_type === "ETF")
  ) {
    errorMessage.value = "腾讯数据源当前只支持指数，请改选指数标的";
    return;
  }
  loading.sync = true;
  errorMessage.value = "";
  syncMessage.value = "";
  try {
    const { data } = await axios.post(`${API_BASE}/api/market-data/sync`, {
      symbols: [syncLeftInstrument.value, syncRightInstrument.value],
      source: latestSyncWindow.source,
      start_date: latestSyncWindow.startDate,
      end_date: latestSyncWindow.endDate,
    });
    const items = data.data?.items ?? [];
    syncMessage.value = items.length
      ? items.map((item) => `${item.symbol}: ${item.inserted + item.updated} 行`).join(" | ")
      : "同步完成";
    await fetchSyncStatus();
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

function alignMetricToDates(metricData, masterDates) {
  if (!metricData?.dates?.length) {
    return {
      left: masterDates.map(() => null),
      right: masterDates.map(() => null),
    };
  }
  const valueMap = new Map(metricData.dates.map((date, index) => [date, metricData.left[index] ?? null]));
  const rightMap = new Map(metricData.dates.map((date, index) => [date, metricData.right[index] ?? null]));
  return {
    left: masterDates.map((date) => valueMap.get(date) ?? null),
    right: masterDates.map((date) => rightMap.get(date) ?? null),
  };
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

  const { meta, series, summary, signals, valuations } = data;
  const leftLabel = meta.left_name || meta.left_symbol;
  const rightLabel = meta.right_name || meta.right_symbol;
  const masterDates = series.dates;
  const positiveArea = buildStrengthAreaData(series.spread, (value) => value > 0);
  const negativeArea = buildStrengthAreaData(series.spread, (value) => value < 0);
  const globalP90 = buildFlatReference(masterDates, summary.global_p90);
  const globalP10 = buildFlatReference(masterDates, summary.global_p10);
  const peSeries = alignMetricToDates(valuations.pe, masterDates);
  const pbSeries = alignMetricToDates(valuations.pb, masterDates);
  const dividendSeries = alignMetricToDates(valuations.dividend_yield, masterDates);
  const buySignals = signals
    .filter((item) => item.type === "buy")
    .map((item) => [item.date, item.spread]);
  const sellSignals = signals
    .filter((item) => item.type === "sell")
    .map((item) => [item.date, item.spread]);

  return {
    animation: false,
    title: [
      {
        text: buildMetricSubtitle("PE", leftLabel, rightLabel),
        top: "35.5%",
        left: "7%",
        textStyle: {
          fontSize: 12,
          fontWeight: 700,
          rich: {
            metric: { color: "#475467" },
            left: { color: LEFT_SERIES_COLOR },
            right: { color: RIGHT_SERIES_COLOR },
          },
        },
      },
      {
        text: buildMetricSubtitle("PB", leftLabel, rightLabel),
        top: "54.5%",
        left: "7%",
        textStyle: {
          fontSize: 12,
          fontWeight: 700,
          rich: {
            metric: { color: "#475467" },
            left: { color: LEFT_SERIES_COLOR },
            right: { color: RIGHT_SERIES_COLOR },
          },
        },
      },
      {
        text: buildMetricSubtitle("股息率", leftLabel, rightLabel),
        top: "73.5%",
        left: "7%",
        textStyle: {
          fontSize: 12,
          fontWeight: 700,
          rich: {
            metric: { color: "#475467" },
            left: { color: LEFT_SERIES_COLOR },
            right: { color: RIGHT_SERIES_COLOR },
          },
        },
      },
    ],
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
        `${leftLabel} PE`,
        `${rightLabel} PE`,
        `${leftLabel} PB`,
        `${rightLabel} PB`,
        `${leftLabel} 股息率`,
        `${rightLabel} 股息率`,
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
      link: [{ xAxisIndex: [0, 1, 2, 3] }],
    },
    dataZoom: [
      {
        type: "slider",
        xAxisIndex: [0, 1, 2, 3],
        bottom: 14,
        height: 18,
        start: 0,
        end: 100,
        borderColor: "rgba(148, 163, 184, 0.32)",
        fillerColor: "rgba(39, 76, 119, 0.12)",
      },
      {
        type: "inside",
        xAxisIndex: [0, 1, 2, 3],
      },
    ],
    grid: [
      { top: "7%", height: "29%", left: "7%", right: "12%" },
      { top: "40%", height: "15%", left: "7%", right: "12%" },
      { top: "59%", height: "15%", left: "7%", right: "12%" },
      { top: "78%", height: "11%", left: "7%", right: "12%" },
    ],
    xAxis: [
      {
        type: "category",
        gridIndex: 0,
        data: masterDates,
        boundaryGap: false,
        axisLabel: { show: false },
        axisTick: { show: false },
        axisLine: { show: false },
      },
      {
        type: "category",
        gridIndex: 1,
        data: masterDates,
        boundaryGap: false,
        axisLabel: { color: "#667085", hideOverlap: true, fontSize: 11, margin: 10 },
        axisTick: { show: false },
        axisLine: { lineStyle: { color: "#cbd5e1" } },
      },
      {
        type: "category",
        gridIndex: 2,
        data: masterDates,
        boundaryGap: false,
        axisLabel: { color: "#667085", hideOverlap: true, fontSize: 11, margin: 10 },
        axisTick: { show: false },
        axisLine: { lineStyle: { color: "#cbd5e1" } },
      },
      {
        type: "category",
        gridIndex: 3,
        data: masterDates,
        boundaryGap: false,
        axisLabel: { color: "#667085", hideOverlap: true, fontSize: 11, margin: 10 },
        axisTick: { show: false },
        axisLine: { lineStyle: { color: "#cbd5e1" } },
      },
    ],
    yAxis: [
      {
        type: "value",
        gridIndex: 0,
        name: "收益差值(%)",
        nameLocation: "middle",
        nameGap: 42,
        scale: true,
        axisLabel: { color: "#667085" },
        axisLine: { show: false },
        splitLine: { lineStyle: { color: "rgba(148, 163, 184, 0.18)" } },
      },
      {
        type: "value",
        gridIndex: 1,
        name: `${leftLabel} PE`,
        nameLocation: "middle",
        nameGap: 42,
        position: "left",
        scale: true,
        axisLabel: { color: LEFT_SERIES_COLOR, formatter: (value) => Number(value).toFixed(1) },
        axisLine: { show: false },
        splitLine: { lineStyle: { color: "rgba(148, 163, 184, 0.18)" } },
      },
      {
        type: "value",
        gridIndex: 2,
        name: `${leftLabel} PB`,
        nameLocation: "middle",
        nameGap: 42,
        position: "left",
        scale: true,
        axisLabel: { color: LEFT_SERIES_COLOR, formatter: (value) => Number(value).toFixed(1) },
        axisLine: { show: false },
        splitLine: { lineStyle: { color: "rgba(148, 163, 184, 0.18)" } },
      },
      {
        type: "value",
        gridIndex: 3,
        name: `${leftLabel} 股息率`,
        nameLocation: "middle",
        nameGap: 42,
        position: "left",
        scale: true,
        axisLabel: { color: LEFT_SERIES_COLOR, formatter: (value) => `${(Number(value) * 100).toFixed(1)}%` },
        axisLine: { show: false },
        splitLine: { lineStyle: { color: "rgba(148, 163, 184, 0.18)" } },
      },
      {
        type: "value",
        gridIndex: 1,
        name: `${rightLabel} PE`,
        nameLocation: "middle",
        nameGap: 44,
        position: "right",
        scale: true,
        axisLabel: { color: RIGHT_SERIES_COLOR, formatter: (value) => Number(value).toFixed(1) },
        axisLine: { show: false },
        splitLine: { show: false },
      },
      {
        type: "value",
        gridIndex: 2,
        name: `${rightLabel} PB`,
        nameLocation: "middle",
        nameGap: 44,
        position: "right",
        scale: true,
        axisLabel: { color: RIGHT_SERIES_COLOR, formatter: (value) => Number(value).toFixed(1) },
        axisLine: { show: false },
        splitLine: { show: false },
      },
      {
        type: "value",
        gridIndex: 3,
        name: `${rightLabel} 股息率`,
        nameLocation: "middle",
        nameGap: 44,
        position: "right",
        scale: true,
        axisLabel: { color: RIGHT_SERIES_COLOR, formatter: (value) => `${(Number(value) * 100).toFixed(1)}%` },
        axisLine: { show: false },
        splitLine: { show: false },
      },
    ],
    series: [
      {
        name: "价差>0(左侧强)",
        type: "line",
        xAxisIndex: 0,
        yAxisIndex: 0,
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
        xAxisIndex: 0,
        yAxisIndex: 0,
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
        xAxisIndex: 0,
        yAxisIndex: 0,
        data: series.spread,
        symbol: "none",
        lineStyle: { width: 1.8, color: "#1f2937" },
        z: 4,
      },
      {
        name: "MA20",
        type: "line",
        xAxisIndex: 0,
        yAxisIndex: 0,
        data: series.ma,
        symbol: "none",
        lineStyle: { width: 1.6, type: "dashed", color: "#f59e0b" },
        z: 4,
      },
      {
        name: "全局P90",
        type: "line",
        xAxisIndex: 0,
        yAxisIndex: 0,
        data: globalP90,
        symbol: "none",
        lineStyle: { width: 1.2, type: "dashed", color: "#dc2626" },
        z: 3,
      },
      {
        name: "全局P10",
        type: "line",
        xAxisIndex: 0,
        yAxisIndex: 0,
        data: globalP10,
        symbol: "none",
        lineStyle: { width: 1.2, type: "dashed", color: "#16a34a" },
        z: 3,
      },
      {
        name: "买入信号",
        type: "scatter",
        xAxisIndex: 0,
        yAxisIndex: 0,
        data: buySignals,
        symbol: BUY_ARROW,
        symbolSize: 16,
        itemStyle: { color: "#16a34a" },
        z: 6,
      },
      {
        name: "卖出信号",
        type: "scatter",
        xAxisIndex: 0,
        yAxisIndex: 0,
        data: sellSignals,
        symbol: SELL_ARROW,
        symbolSize: 16,
        itemStyle: { color: "#dc2626" },
        z: 6,
      },
      {
        name: `${leftLabel} PE`,
        type: "line",
        xAxisIndex: 1,
        yAxisIndex: 1,
        data: peSeries.left,
        symbol: "none",
        connectNulls: false,
        lineStyle: { width: 2.4, color: LEFT_SERIES_COLOR },
        endLabel: buildValuationEndLabel(leftLabel),
        labelLayout: { moveOverlap: "shiftY" },
        emphasis: { focus: "series" },
      },
      {
        name: `${rightLabel} PE`,
        type: "line",
        xAxisIndex: 1,
        yAxisIndex: 4,
        data: peSeries.right,
        symbol: "none",
        connectNulls: false,
        lineStyle: { width: 2.4, color: RIGHT_SERIES_COLOR },
        endLabel: buildValuationEndLabel(rightLabel),
        labelLayout: { moveOverlap: "shiftY" },
        emphasis: { focus: "series" },
      },
      {
        name: `${leftLabel} PB`,
        type: "line",
        xAxisIndex: 2,
        yAxisIndex: 2,
        data: pbSeries.left,
        symbol: "none",
        connectNulls: false,
        lineStyle: { width: 2.4, color: LEFT_SERIES_COLOR },
        endLabel: buildValuationEndLabel(leftLabel),
        labelLayout: { moveOverlap: "shiftY" },
        emphasis: { focus: "series" },
      },
      {
        name: `${rightLabel} PB`,
        type: "line",
        xAxisIndex: 2,
        yAxisIndex: 5,
        data: pbSeries.right,
        symbol: "none",
        connectNulls: false,
        lineStyle: { width: 2.4, color: RIGHT_SERIES_COLOR },
        endLabel: buildValuationEndLabel(rightLabel),
        labelLayout: { moveOverlap: "shiftY" },
        emphasis: { focus: "series" },
      },
      {
        name: `${leftLabel} 股息率`,
        type: "line",
        xAxisIndex: 3,
        yAxisIndex: 3,
        data: dividendSeries.left,
        symbol: "none",
        connectNulls: false,
        lineStyle: { width: 2.4, color: LEFT_SERIES_COLOR },
        endLabel: buildValuationEndLabel(leftLabel),
        labelLayout: { moveOverlap: "shiftY" },
        emphasis: { focus: "series" },
      },
      {
        name: `${rightLabel} 股息率`,
        type: "line",
        xAxisIndex: 3,
        yAxisIndex: 6,
        data: dividendSeries.right,
        symbol: "none",
        connectNulls: false,
        lineStyle: { width: 2.4, color: RIGHT_SERIES_COLOR },
        endLabel: buildValuationEndLabel(rightLabel),
        labelLayout: { moveOverlap: "shiftY" },
        emphasis: { focus: "series" },
      },
    ],
  };
}

function renderChart() {
  ensureChart()?.setOption(buildCompositeOption(), true);
}

function handleResize() {
  chartInstance?.resize();
}

function openExportModal() {
  if (!response.value) {
    errorMessage.value = "当前没有可导出的图表数据";
    return;
  }
  exportModal.open = true;
  exportMessage.value = "";
}

function closeExportModal() {
  exportModal.open = false;
  exportModal.exporting = false;
  exportModal.copying = false;
  exportMessage.value = "";
}

function buildChartExportPayload() {
  const chart = ensureChart();
  if (!chart) {
    throw new Error("图表尚未准备完成");
  }

  const leftPart = response.value.meta.left_symbol || form.leftSymbol || "left";
  const rightPart = response.value.meta.right_symbol || form.rightSymbol || "right";
  const startPart = response.value.meta.start_date || form.startDate || "start";
  const endPart = response.value.meta.end_date || form.endDate || "end";
  const fileName = `style-rotation_${leftPart}_${rightPart}_${startPart}_${endPart}.png`;
  const pixelRatio = Number(exportModal.scale || 2);
  const dataUrl = chart.getDataURL({
    type: "png",
    pixelRatio,
    backgroundColor: "#fffaf3",
  });
  return { fileName, dataUrl, pixelRatio };
}

function exportChartImage() {
  try {
    exportModal.exporting = true;
    const { fileName, dataUrl, pixelRatio } = buildChartExportPayload();
    const link = document.createElement("a");
    link.href = dataUrl;
    link.download = fileName;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    exportMessage.value = `已导出 PNG，清晰度 ${pixelRatio}x`;
  } catch (error) {
    errorMessage.value = error.message || "导出图表失败";
  } finally {
    exportModal.exporting = false;
  }
}

async function copyChartImageToClipboard() {
  if (!window.ClipboardItem || !navigator.clipboard?.write) {
    errorMessage.value = "当前浏览器不支持图片复制到剪贴板";
    return;
  }
  try {
    exportModal.copying = true;
    const { dataUrl, pixelRatio } = buildChartExportPayload();
    const blob = await fetch(dataUrl).then((response) => response.blob());
    await navigator.clipboard.write([new ClipboardItem({ [blob.type]: blob })]);
    exportMessage.value = `已复制图表到剪贴板，清晰度 ${pixelRatio}x`;
  } catch (error) {
    errorMessage.value = error.message || "复制图表失败";
  } finally {
    exportModal.copying = false;
  }
}

watch(
  () => exportModal.open,
  (open) => {
    if (!open) {
      return;
    }
    exportModal.scale = "2";
    exportMessage.value = "";
  },
  { immediate: false }
);

watch(
  () => response.value,
  async () => {
    await nextTick();
    renderChart();
  }
);

watch(
  () => [form.leftSymbol, form.rightSymbol, form.startDate, form.endDate],
  () => {
    scheduleAnalyze();
  },
  { immediate: false }
);

watch(
  () => [syncModal.open, syncSelection.leftSymbol, syncSelection.rightSymbol],
  async ([open]) => {
    if (!open) {
      return;
    }
    await fetchSyncStatus();
  },
  { immediate: false }
);

watch(
  () => [valuationModal.open, valuationUpload.symbol],
  async ([open, symbol]) => {
    if (!open) {
      return;
    }
    await fetchValuationStatus(symbol);
  },
  { immediate: false }
);

onMounted(async () => {
  window.addEventListener("resize", handleResize);
  await fetchInstruments();
  applyDateRangePreset("analysis");
  analysisReady.value = true;
  await analyze();
});

onBeforeUnmount(() => {
  window.removeEventListener("resize", handleResize);
  if (analyzeDebounceTimer) {
    clearTimeout(analyzeDebounceTimer);
  }
  chartInstance?.dispose();
});
</script>

<template>
  <main class="page-shell">
    <section class="hero-panel">
      <div class="hero-copy">
        <p class="eyebrow">Style Rotation Dashboard</p>
        <h1>风格轮动单页分析台</h1>
        <p class="hero-text">围绕筛选和图表查看做紧凑布局，减少无效占位。</p>
      </div>
    </section>

    <aside class="side-action-rail">
      <button class="side-action-card side-action-sync" :disabled="loading.sync || loading.instruments" @click="openSyncModal">
        <span class="side-action-kicker">数据维护</span>
        <strong>{{ loading.sync ? "同步价格中" : "同步价格数据" }}</strong>
        <small>{{ loading.sync ? "正在拉取腾讯指数行情" : "检查价格库范围并补齐缺口" }}</small>
      </button>
      <button class="side-action-card side-action-valuation" :disabled="loading.instruments" @click="openValuationModal">
        <span class="side-action-kicker">估值导入</span>
        <strong>上传估值数据</strong>
        <small>导入 PE / PB / 股息率 CSV</small>
      </button>
      <button class="side-action-card side-action-export" :disabled="loading.analysis || !response" @click="openExportModal">
        <span class="side-action-kicker">图表导出</span>
        <strong>{{ loading.analysis ? "图表更新中" : "导出或复制图表" }}</strong>
        <small>{{ response ? "支持 PNG 下载和复制到剪贴板" : "当前暂无可导出的图表" }}</small>
      </button>
    </aside>

    <section v-if="errorMessage" class="error-banner">
      {{ errorMessage }}
    </section>

    <section class="workspace-strip">
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
    </section>

    <section class="control-panel">
      <div class="control-panel-header">
        <div>
          <span class="section-kicker">Query Filter</span>
          <h2>分析筛选</h2>
        </div>
        <p>把主要空间留给图表，筛选区保留一行紧凑操作。</p>
      </div>

      <div class="field">
        <label>左侧标的</label>
        <select v-model="form.leftSymbol" :disabled="loading.instruments">
          <optgroup v-for="group in leftInstrumentGroups" :key="`left-${group.label}`" :label="group.label">
            <option v-for="item in group.items" :key="item.symbol" :value="item.symbol">
              {{ item.symbol }} / {{ item.name }}
            </option>
          </optgroup>
        </select>
      </div>
      <div class="field">
        <label>右侧标的</label>
        <select v-model="form.rightSymbol" :disabled="loading.instruments">
          <optgroup v-for="group in rightInstrumentGroups" :key="`right-${group.label}`" :label="group.label">
            <option v-for="item in group.items" :key="item.symbol" :value="item.symbol">
              {{ item.symbol }} / {{ item.name }}
            </option>
          </optgroup>
        </select>
      </div>
      <div class="field">
        <label>快捷范围</label>
        <select v-model="dateRangeSelection.analysis" @change="applyDateRangePreset('analysis')">
          <option v-for="preset in DATE_RANGE_PRESETS" :key="`analysis-${preset.key}`" :value="preset.key">
            {{ preset.label }}
          </option>
        </select>
      </div>
      <div class="field">
        <label>开始日期</label>
        <input v-model="form.startDate" type="date" @change="markCustomDateRange('analysis')" />
      </div>
      <div class="field">
        <label>结束日期</label>
        <input v-model="form.endDate" type="date" @change="markCustomDateRange('analysis')" />
      </div>
    </section>

    <section class="charts-grid">
      <article class="chart-card chart-card-composite">
        <div ref="chartRef" class="chart-canvas chart-canvas-composite"></div>
      </article>
    </section>

    <section v-if="exportModal.open" class="modal-shell" @click.self="closeExportModal">
      <article class="modal-panel export-modal-panel">
        <div class="modal-header">
          <div>
            <span class="section-kicker">Chart Export</span>
            <h2>导出或复制当前图表</h2>
          </div>
          <button class="modal-close" @click="closeExportModal">关闭</button>
        </div>

        <div class="modal-grid export-modal-grid">
          <div class="field">
            <label>清晰度</label>
            <select v-model="exportModal.scale" :disabled="exportModal.exporting || exportModal.copying">
              <option value="2">2x 高清</option>
              <option value="3">3x 超清</option>
            </select>
          </div>
          <div class="modal-target">
            <span>当前图表范围</span>
            <strong>{{ response ? `${response.meta.left_symbol} vs ${response.meta.right_symbol}` : "暂无图表" }}</strong>
            <strong>{{ response ? `${response.meta.start_date} 至 ${response.meta.end_date}` : "" }}</strong>
          </div>
        </div>

        <div class="valuation-upload-actions">
          <button class="upload-button" :disabled="exportModal.exporting || exportModal.copying" @click="exportChartImage">
            {{ exportModal.exporting ? "导出中..." : "下载 PNG" }}
          </button>
          <button class="upload-button secondary-upload-button" :disabled="exportModal.exporting || exportModal.copying" @click="copyChartImageToClipboard">
            {{ exportModal.copying ? "复制中..." : "复制到剪贴板" }}
          </button>
        </div>

        <p class="export-help">2x 适合普通分享，3x 适合高分屏或文档插图。</p>
        <p v-if="exportMessage" class="upload-success">{{ exportMessage }}</p>
      </article>
    </section>

    <section v-if="syncModal.open" class="modal-shell" @click.self="closeSyncModal">
      <article class="modal-panel">
        <div class="modal-header">
          <div>
            <span class="section-kicker">Market Sync</span>
            <h2>价格数据同步</h2>
          </div>
          <button class="modal-close" @click="closeSyncModal">关闭</button>
        </div>

        <div class="modal-grid">
          <div class="field">
            <label>左侧同步标的</label>
            <select v-model="syncSelection.leftSymbol" :disabled="loading.instruments || syncModal.loading">
              <optgroup v-for="group in leftInstrumentGroups" :key="`sync-left-${group.label}`" :label="group.label">
                <option v-for="item in group.items" :key="item.symbol" :value="item.symbol">
                  {{ item.symbol }} / {{ item.name }}
                </option>
              </optgroup>
            </select>
          </div>
          <div class="field">
            <label>右侧同步标的</label>
            <select v-model="syncSelection.rightSymbol" :disabled="loading.instruments || syncModal.loading">
              <optgroup v-for="group in rightInstrumentGroups" :key="`sync-right-${group.label}`" :label="group.label">
                <option v-for="item in group.items" :key="item.symbol" :value="item.symbol">
                  {{ item.symbol }} / {{ item.name }}
                </option>
              </optgroup>
            </select>
          </div>
        </div>

        <div class="modal-grid sync-meta-grid">
          <div class="field">
            <label>同步来源</label>
            <input value="Tencent" type="text" disabled />
          </div>
          <div class="modal-target">
            <span>当前同步标的</span>
            <strong>{{ syncLeftInstrument ? `${syncLeftInstrument.symbol} / ${syncLeftInstrument.name}` : "未选择" }}</strong>
            <strong>{{ syncRightInstrument ? `${syncRightInstrument.symbol} / ${syncRightInstrument.name}` : "未选择" }}</strong>
          </div>
        </div>

        <div class="modal-grid sync-date-grid">
          <div class="field">
            <label>快捷范围</label>
            <select v-model="dateRangeSelection.sync" @change="applyDateRangePreset('sync')">
              <option v-for="preset in DATE_RANGE_PRESETS" :key="`sync-${preset.key}`" :value="preset.key">
                {{ preset.label }}
              </option>
            </select>
          </div>
          <div class="field">
            <label>同步开始</label>
            <input v-model="latestSyncWindow.startDate" type="date" @change="markCustomDateRange('sync')" />
          </div>
          <div class="field">
            <label>同步结束</label>
            <input v-model="latestSyncWindow.endDate" type="date" @change="markCustomDateRange('sync')" />
          </div>
        </div>

        <div class="valuation-status-block">
          <div class="status-header">
            <strong>数据库已有价格数据</strong>
            <span v-if="syncModal.loading">读取中...</span>
          </div>
          <p v-if="syncStatusError" class="status-error">{{ syncStatusError }}</p>
          <div class="status-grid sync-status-grid">
            <article
              v-for="card in syncStatusCards"
              :key="card.side"
              class="status-card sync-status-card"
              :style="{ borderColor: `${card.accent}33` }"
            >
              <span>{{ card.title }}</span>
              <strong :style="{ color: card.accent }">
                {{ card.instrument ? `${card.instrument.symbol} / ${card.instrument.name}` : "未选择" }}
              </strong>
              <p class="sync-status-flag" :class="`sync-status-${getSyncFreshness(card.status).level}`">
                {{ getSyncFreshness(card.status).label }}
              </p>
              <p>{{ getSyncFreshness(card.status).detail }}</p>
              <p>是否存在：{{ card.status?.exists ? "已存在" : "不存在" }}</p>
              <p>条数：{{ card.status?.row_count ?? 0 }}</p>
              <p>范围：{{ formatRange(card.status) }}</p>
              <p>来源：{{ formatSourceList(card.status) }}</p>
            </article>
          </div>
        </div>

        <div class="valuation-upload-actions">
          <button class="upload-button" :disabled="loading.sync || syncModal.loading" @click="syncData">
            {{ loading.sync ? "同步中..." : "开始同步" }}
          </button>
        </div>

        <p v-if="syncMessage" class="upload-success">{{ syncMessage }}</p>
      </article>
    </section>

    <section v-if="valuationModal.open" class="modal-shell" @click.self="closeValuationModal">
      <article class="modal-panel">
        <div class="modal-header">
          <div>
            <span class="section-kicker">Valuation Upload</span>
            <h2>目标指数估值 CSV 上传</h2>
          </div>
          <button class="modal-close" @click="closeValuationModal">关闭</button>
        </div>

        <div class="modal-grid">
          <div class="field">
            <label>目标指数代码</label>
            <select v-model="valuationUpload.symbol" :disabled="loading.instruments || valuationModal.loading">
              <option value="">请选择指数</option>
              <option v-for="item in indexInstruments" :key="item.symbol" :value="item.symbol">
                {{ item.symbol }} / {{ item.name }}
              </option>
            </select>
          </div>
          <div class="modal-target">
            <span>当前目标</span>
            <strong>{{ selectedValuationInstrument ? `${selectedValuationInstrument.symbol} / ${selectedValuationInstrument.name}` : "未选择" }}</strong>
          </div>
        </div>

        <div class="valuation-status-block">
          <div class="status-header">
            <strong>数据库已有估值数据</strong>
            <span v-if="valuationModal.loading">读取中...</span>
          </div>
          <p v-if="valuationStatusError" class="status-error">{{ valuationStatusError }}</p>
          <div class="status-grid">
            <article v-for="metric in valuationMetricCards" :key="metric.key" class="status-card">
              <span>{{ metric.label }}</span>
              <strong>{{ metric.exists ? "已存在" : "不存在" }}</strong>
              <p>条数：{{ metric.row_count }}</p>
              <p>范围：{{ formatRange(metric) }}</p>
            </article>
          </div>
        </div>

        <div class="valuation-upload-actions">
          <button class="upload-button" :disabled="loading.sync || !valuationUpload.symbol" @click="triggerValuationUpload('pe')">上传 PE CSV</button>
          <button class="upload-button" :disabled="loading.sync || !valuationUpload.symbol" @click="triggerValuationUpload('pb')">上传 PB CSV</button>
          <button class="upload-button" :disabled="loading.sync || !valuationUpload.symbol" @click="triggerValuationUpload('dividend_yield')">
            上传股息率 CSV
          </button>
        </div>

        <p v-if="valuationUploadMessage" class="upload-success">{{ valuationUploadMessage }}</p>

        <input ref="peFileInputRef" class="hidden-input" type="file" accept=".csv,text/csv" @change="uploadValuationFile('pe', $event)" />
        <input ref="pbFileInputRef" class="hidden-input" type="file" accept=".csv,text/csv" @change="uploadValuationFile('pb', $event)" />
        <input
          ref="dividendFileInputRef"
          class="hidden-input"
          type="file"
          accept=".csv,text/csv"
          @change="uploadValuationFile('dividend_yield', $event)"
        />
      </article>
    </section>
  </main>
</template>
