import { createApp } from "vue";
import { createRouter, createWebHistory } from "vue-router";
import App from "./App.vue";
import DashboardView from "./views/DashboardView.vue";
import DiscoverView from "./views/DiscoverView.vue";
import DownloadsView from "./views/DownloadsView.vue";
import RequestsView from "./views/RequestsView.vue";
import LibraryView from "./views/LibraryView.vue";
import CalendarView from "./views/CalendarView.vue";
import UsersView from "./views/UsersView.vue";
import NotificationsView from "./views/NotificationsView.vue";
import SettingsView from "./views/SettingsView.vue";
import MaintenanceView from "./views/MaintenanceView.vue";
import ReleaseSearchView from "./views/ReleaseSearchView.vue";
import "./styles.css";

const routes = [
  { path: "/", redirect: "/dashboard" },
  { path: "/dashboard", component: DashboardView },
  { path: "/discover", component: DiscoverView },
  { path: "/downloads", component: DownloadsView },
  { path: "/requests", component: RequestsView },
  { path: "/library", component: LibraryView },
  { path: "/calendar", component: CalendarView },
  { path: "/users", component: UsersView },
  { path: "/notifications", component: NotificationsView },
  { path: "/settings", component: SettingsView },
  { path: "/maintenance", component: MaintenanceView },
  { path: "/releases/:requestId", component: ReleaseSearchView },
  { path: "/:pathMatch(.*)*", redirect: "/dashboard" },
];

const router = createRouter({
  history: createWebHistory("/app"),
  routes,
});

createApp(App).use(router).mount("#app");
