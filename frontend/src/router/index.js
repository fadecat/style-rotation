import { createRouter, createWebHistory } from "vue-router";
import AnalysisView from "../views/AnalysisView.vue";

const routes = [
  { path: "/", name: "analysis", component: AnalysisView },
  {
    path: "/backtest",
    name: "backtest",
    component: () => import("../views/BacktestView.vue"),
  },
];

const router = createRouter({
  history: createWebHistory(),
  routes,
});

export default router;
