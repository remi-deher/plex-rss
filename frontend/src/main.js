import { createApp } from "vue";
import { createRouter, createWebHistory } from "vue-router";
import App from "./App.vue";
import PageHeader from "./components/ui/PageHeader.vue";
import StatusBadge from "./components/ui/StatusBadge.vue";
import UiFeedback from "./components/ui/UiFeedback.vue";
import FilterBar from "./components/ui/FilterBar.vue";
import FormSaveBar from "./components/ui/FormSaveBar.vue";
const DashboardView = () => import("./views/DashboardView.vue");
const DiscoverView = () => import("./views/DiscoverView.vue");
const DownloadsView = () => import("./views/DownloadsView.vue");
const ActivityView = () => import("./views/ActivityView.vue");
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

const ASSET_RELOAD_KEY = "plexarr:asset-reload";
function recoverFromStaleAssets(error) {
  const message = String(error?.message || error || "");
  if (!/dynamically imported module|failed to fetch module|importing a module script/i.test(message)) return;
  if (sessionStorage.getItem(ASSET_RELOAD_KEY)) return;
  sessionStorage.setItem(ASSET_RELOAD_KEY, String(Date.now()));
  const url = new URL(window.location.href);
  url.searchParams.set("_asset_reload", Date.now());
  window.location.replace(url);
}

window.addEventListener("vite:preloadError", event => {
  event.preventDefault();
  recoverFromStaleAssets(event.payload);
});

const routes = [
  { path: "/", redirect: "/dashboard" },
  { path: "/dashboard", component: DashboardView },
  { path: "/discover", component: DiscoverView },
  { path: "/downloads", component: DownloadsView },
  { path: "/activity", component: ActivityView },
  // Bibliotheque et Demandes ont fusionne en une seule page (voir /library) : les
  // demandes disposent maintenant de leurs actions (approuver/refuser/etc.) directement
  // dans la fiche detaillee. Redirection pour les favoris/liens externes existants.
  { path: "/requests", redirect: (to) => ({ path: "/library", query: to.query }) },
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

router.onError(recoverFromStaleAssets);

createApp(App)
  .component('PageHeader', PageHeader)
  .component('StatusBadge', StatusBadge)
  .component('UiFeedback', UiFeedback)
  .component('FilterBar', FilterBar)
  .component('FormSaveBar', FormSaveBar)
  .use(router)
  .mount("#app");

// Un chargement resté stable autorise une nouvelle récupération lors d'un futur déploiement.
window.setTimeout(() => sessionStorage.removeItem(ASSET_RELOAD_KEY), 10_000);
