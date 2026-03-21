<script setup>
import { useRoute } from "vue-router";
const route = useRoute();
</script>

<template>
  <nav class="app-nav">
    <router-link to="/" class="app-nav-tab" :class="{ active: route.path === '/' }">
      分析
    </router-link>
    <router-link to="/backtest" class="app-nav-tab" :class="{ active: route.path === '/backtest' }">
      回测
    </router-link>
  </nav>
  <router-view />
</template>
