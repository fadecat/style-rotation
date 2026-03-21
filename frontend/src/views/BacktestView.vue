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
  MarkAreaComponent,
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
  MarkAreaComponent,
  MarkLineComponent,
  TitleComponent,
  TooltipComponent,
  DataZoomComponent,
  AxisPointerComponent,
]);

const API_BASE = "http://127.0.0.1:8000";

const instruments = ref([]);
const strategies = ref([]);
const loading = reactive({ instruments: false, backtest: false });
const form = reactive({
  leftSymbol: "399376",
  rightSymbol: "399373",
  startDate: "2018-01-01",
  endDate: new Date().toISOString().slice(0, 10),
  strategy: "ratio_mom20",
  fee: 0.001,
  rebalance: "weekly",
});
const result = ref(null);
const errorMessage = ref("");

const VISIBLE_INSTRUMENT_SYMBOLS = new Set(["399376", "399373", "000852", "000922"]);

async function loadInstruments() {
  loading.instruments = true;
  try {
    const res = await axios.get(`${API_BASE}/api/instruments`);
    const items = res.data.data?.items || res.data.data || [];
    instruments.value = items.filter(
      (i) => VISIBLE_INSTRUMENT_SYMBOLS.has(i.symbol)
    );
  } catch (e) {
    console.error("loadInstruments failed:", e.message);
  }
  loading.instruments = false;
}

async function runBacktest() {
  errorMessage.value = "";
  loading.backtest = true;
  try {
    const res = await axios.get(`${API_BASE}/api/backtest`, {
      params: {
        left_symbol: form.leftSymbol,
        right_symbol: form.rightSymbol,
        start_date: form.startDate,
        end_date: form.endDate,
        strategy: form.strategy,
        fee: form.fee,
        rebalance: form.rebalance,
      },
    });
    if (res.data.code === 200) {
      result.value = res.data.data;
      if (!strategies.value.length && res.data.data.available_strategies) {
        strategies.value = res.data.data.available_strategies;
      }
      await nextTick();
      renderChart();
    } else {
      errorMessage.value = res.data.message || "回测失败";
    }
  } catch (e) {
    errorMessage.value = e.response?.data?.message || e.message;
  }
  loading.backtest = false;
}

// Load strategies from dedicated endpoint
async function loadStrategies() {
  try {
    const res = await axios.get(`${API_BASE}/api/strategies`);
    if (res.data.code === 200) {
      strategies.value = res.data.data;
    }
  } catch (e) {
    console.error("loadStrategies failed:", e.message);
  }
}

// ── Chart ──
let chartInstance = null;
const chartRef = ref(null);

function renderChart() {
  if (!result.value || !chartRef.value) return;
  const d = result.value;

  if (chartInstance) chartInstance.dispose();
  chartInstance = init(chartRef.value);

  const option = buildChartOption(d);
  chartInstance.setOption(option);
}

function buildChartOption(d) {
  // Trade entry/exit markers
  const entryData = [];
  const exitData = [];
  for (const t of d.trades) {
    const ei = d.dates.indexOf(t.entry_date);
    const xi = d.dates.indexOf(t.exit_date);
    if (ei >= 0) entryData.push({ coord: [ei, d.nav[ei]], trade: t });
    if (xi >= 0) exitData.push({ coord: [xi, d.nav[xi]], trade: t });
  }

  return {
    animation: false,
    tooltip: { trigger: "axis" },
    axisPointer: { link: [{ xAxisIndex: "all" }] },
    legend: {
      data: ["策略NAV", "左基准", "右基准", "信号"],
      top: 0,
      textStyle: { fontSize: 12 },
    },
    dataZoom: [
      { type: "inside", xAxisIndex: [0, 1, 2], start: 0, end: 100 },
      { type: "slider", xAxisIndex: [0, 1, 2], bottom: 4, height: 20 },
    ],
    grid: [
      { left: 60, right: 20, top: 40, height: "42%" },
      { left: 60, right: 20, top: "56%", height: "14%" },
      { left: 60, right: 20, top: "76%", height: "14%" },
    ],
    xAxis: [
      { type: "category", data: d.dates, gridIndex: 0, show: false },
      { type: "category", data: d.dates, gridIndex: 1, show: false },
      { type: "category", data: d.dates, gridIndex: 2, axisLabel: { fontSize: 10 } },
    ],
    yAxis: [
      { type: "value", gridIndex: 0, name: "NAV", scale: true },
      { type: "value", gridIndex: 1, name: "回撤%", scale: true },
      { type: "value", gridIndex: 2, name: "信号", scale: true },
    ],
    series: [
      {
        name: "策略NAV",
        type: "line",
        xAxisIndex: 0, yAxisIndex: 0,
        data: d.nav,
        lineStyle: { width: 2, color: "#d9a441" },
        itemStyle: { color: "#d9a441" },
        symbol: "none",
        markPoint: {
          data: [
            ...entryData.map((e) => ({
              coord: e.coord,
              symbol: "triangle",
              symbolSize: 10,
              itemStyle: { color: "#0b6b41" },
            })),
            ...exitData.map((e) => ({
              coord: e.coord,
              symbol: "diamond",
              symbolSize: 10,
              itemStyle: { color: "#b84c3d" },
            })),
          ],
        },
      },
      {
        name: "左基准",
        type: "line",
        xAxisIndex: 0, yAxisIndex: 0,
        data: d.left_nav,
        lineStyle: { width: 1, color: "#2563eb", type: "dashed" },
        itemStyle: { color: "#2563eb" },
        symbol: "none",
      },
      {
        name: "右基准",
        type: "line",
        xAxisIndex: 0, yAxisIndex: 0,
        data: d.right_nav,
        lineStyle: { width: 1, color: "#f97316", type: "dashed" },
        itemStyle: { color: "#f97316" },
        symbol: "none",
      },
      {
        name: "回撤",
        type: "line",
        xAxisIndex: 1, yAxisIndex: 1,
        data: d.drawdown,
        lineStyle: { width: 1, color: "#b84c3d" },
        areaStyle: { color: "rgba(184, 76, 61, 0.25)" },
        itemStyle: { color: "#b84c3d" },
        symbol: "none",
      },
      {
        name: "信号",
        type: "line",
        xAxisIndex: 2, yAxisIndex: 2,
        data: d.signal,
        lineStyle: { width: 1, color: "#274c77" },
        itemStyle: { color: "#274c77" },
        symbol: "none",
        markLine: {
          silent: true,
          data: [{ yAxis: 0, lineStyle: { color: "#999", type: "dashed" } }],
        },
      },
    ],
  };
}

function handleResize() {
  chartInstance?.resize();
}

onMounted(() => {
  loadInstruments();
  loadStrategies();
  window.addEventListener("resize", handleResize);
});

onBeforeUnmount(() => {
  window.removeEventListener("resize", handleResize);
  chartInstance?.dispose();
});

function fmtPct(v) {
  if (v == null) return "—";
  return (v >= 0 ? "+" : "") + v.toFixed(2) + "%";
}
function pctClass(v) {
  if (v == null) return "";
  return v >= 0 ? "text-green" : "text-red";
}
</script>

<template>
  <div class="backtest-page">
    <!-- Controls -->
    <div class="backtest-controls">
      <div class="control-panel-header">
        <div>
          <h2>因子回测</h2>
          <p>选择标的、时间区间和策略，运行回测</p>
        </div>
      </div>
      <div class="field">
        <label>左标的</label>
        <select v-model="form.leftSymbol">
          <option v-for="i in instruments" :key="i.symbol" :value="i.symbol">
            {{ i.symbol }} {{ i.name }}
          </option>
        </select>
      </div>
      <div class="field">
        <label>右标的</label>
        <select v-model="form.rightSymbol">
          <option v-for="i in instruments" :key="i.symbol" :value="i.symbol">
            {{ i.symbol }} {{ i.name }}
          </option>
        </select>
      </div>
      <div class="field">
        <label>开始日期</label>
        <input type="date" v-model="form.startDate" />
      </div>
      <div class="field">
        <label>结束日期</label>
        <input type="date" v-model="form.endDate" />
      </div>
      <div class="field">
        <label>策略</label>
        <select v-model="form.strategy">
          <option v-for="s in strategies" :key="s.key" :value="s.key">
            {{ s.label }}
          </option>
          <option v-if="!strategies.length" value="ratio_mom20">动量(20)</option>
        </select>
      </div>
      <div class="field">
        <label>手续费</label>
        <input type="number" v-model.number="form.fee" step="0.0001" min="0" max="0.05" />
      </div>
      <div class="field">
        <label>调仓频率</label>
        <select v-model="form.rebalance">
          <option value="daily">每日</option>
          <option value="weekly">每周</option>
          <option value="monthly">每月</option>
        </select>
      </div>
      <div class="field backtest-run-btn">
        <label>&nbsp;</label>
        <button class="primary-button" :disabled="loading.backtest" @click="runBacktest">
          {{ loading.backtest ? "运行中…" : "运行回测" }}
        </button>
      </div>
    </div>

    <div v-if="errorMessage" class="error-banner">{{ errorMessage }}</div>

    <!-- Results -->
    <template v-if="result">
      <!-- Stats cards -->
      <div class="backtest-stats-grid">
        <div class="backtest-stat-card">
          <span>总收益</span>
          <strong :class="pctClass(result.stats.total_return_pct)">
            {{ fmtPct(result.stats.total_return_pct) }}
          </strong>
        </div>
        <div class="backtest-stat-card">
          <span>年化收益</span>
          <strong :class="pctClass(result.stats.annual_return_pct)">
            {{ fmtPct(result.stats.annual_return_pct) }}
          </strong>
        </div>
        <div class="backtest-stat-card">
          <span>最大回撤</span>
          <strong class="text-red">-{{ result.stats.max_drawdown_pct }}%</strong>
        </div>
        <div class="backtest-stat-card">
          <span>回撤天数</span>
          <strong>{{ result.stats.max_drawdown_days }}</strong>
        </div>
        <div class="backtest-stat-card">
          <span>交易次数</span>
          <strong>{{ result.stats.trade_count }}</strong>
        </div>
        <div class="backtest-stat-card">
          <span>胜率</span>
          <strong>{{ result.stats.win_rate }}%</strong>
        </div>
        <div class="backtest-stat-card">
          <span>平均持仓天数</span>
          <strong>{{ result.stats.avg_holding_days }}</strong>
        </div>
        <div class="backtest-stat-card">
          <span>策略终值</span>
          <strong>{{ result.stats.final_nav }}</strong>
        </div>
      </div>

      <!-- Chart -->
      <div class="backtest-chart-wrap">
        <div ref="chartRef" class="backtest-chart-canvas"></div>
      </div>

      <!-- Tables row -->
      <div class="tables-row">
        <!-- Yearly table -->
        <div class="backtest-table-section">
          <h3>按年收益</h3>
          <table class="yearly-table">
            <thead>
              <tr><th>年份</th><th>收益率</th><th>最大回撤</th><th>交易</th></tr>
            </thead>
            <tbody>
              <tr v-for="y in result.yearly" :key="y.year">
                <td>{{ y.year }}</td>
                <td :class="pctClass(y.return_pct)">{{ fmtPct(y.return_pct) }}</td>
                <td class="text-red">-{{ y.max_drawdown_pct }}%</td>
                <td>{{ y.trade_count }}</td>
              </tr>
            </tbody>
          </table>
        </div>

        <!-- Trade table -->
        <div class="backtest-table-section">
          <h3>交易记录</h3>
          <div class="trade-table-scroll">
            <table class="trade-table">
              <thead>
                <tr>
                  <th>入场日期</th><th>出场日期</th><th>方向</th>
                  <th>天数</th><th>入场NAV</th><th>出场NAV</th><th>收益率</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="(t, idx) in result.trades" :key="idx">
                  <td>{{ t.entry_date }}</td>
                  <td>{{ t.exit_date }}</td>
                  <td>{{ t.holding === 'left' ? '持左' : '持右' }}</td>
                  <td>{{ t.days }}</td>
                  <td>{{ t.entry_nav }}</td>
                  <td>{{ t.exit_nav }}</td>
                  <td :class="pctClass(t.return_pct)">{{ fmtPct(t.return_pct) }}</td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </template>
  </div>
</template>
