import { createApp } from "vue";
import { createRouter, createWebHistory } from "vue-router";
import App from "./App.vue";
const DashboardView = () => import("./views/DashboardView.vue");
const DiscoverView = () => import("./views/DiscoverView.vue");
const DownloadsView = () => import("./views/DownloadsView.vue");
const RequestsView = () => import("./views/RequestsView.vue");
const LibraryView = () => import("./views/LibraryView.vue");
const CalendarView = () => import("./views/CalendarView.vue");
const UsersView = () => import("./views/UsersView.vue");
const NotificationsView = () => import("./views/NotificationsView.vue");
const SettingsView = () => import("./views/SettingsView.vue");
const MaintenanceView = () => import("./views/MaintenanceView.vue");
const ReleaseSearchView = () => import("./views/ReleaseSearchView.vue");
const ProfileView = () => import("./views/ProfileView.vue");
const LogsView = () => import("./views/LogsView.vue");
const IssuesView = () => import("./views/IssuesView.vue");
const MediaDetailView = () => import("./views/MediaDetailView.vue");
import "./styles.css";

const routes = [
  { path: "/", redirect: "/dashboard" },
  { path: "/dashboard", component: DashboardView },
  { path: "/discover", component: DiscoverView },
  { path: "/downloads", component: DownloadsView },
  { path: "/requests", component: RequestsView },
  { path: "/library", component: LibraryView },
  { path: "/issues", component: IssuesView },
  { path: "/calendar", component: CalendarView },
  { path: "/users", component: UsersView },
  { path: "/users/:userId", component: UsersView },
  { path: "/notifications", component: NotificationsView },
  { path: "/logs", component: LogsView },
  { path: "/settings", component: SettingsView },
  { path: "/maintenance", component: MaintenanceView },
  { path: "/profile", component: ProfileView },
  { path: "/releases/:requestId", component: ReleaseSearchView },
  { path: "/media/:kind/:id", component: MediaDetailView },
  { path: "/:pathMatch(.*)*", redirect: "/dashboard" },
];

const router = createRouter({
  history: createWebHistory("/"),
  routes,
});

createApp(App).use(router).mount("#app");
