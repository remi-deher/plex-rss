import { createApp } from "vue";
import { createRouter, createWebHistory } from "vue-router";
import App from "./App.vue";
import DashboardView from "./views/DashboardView.vue";
import DiscoverView from "./views/DiscoverView.vue";
import DownloadsView from "./views/DownloadsView.vue";
import "./styles.css";

const routes = [
  { path: "/", redirect: "/dashboard" },
  { path: "/dashboard", component: DashboardView },
  { path: "/discover", component: DiscoverView },
  { path: "/downloads", component: DownloadsView },
];

const router = createRouter({
  history: createWebHistory("/app"),
  routes,
});

createApp(App).use(router).mount("#app");
