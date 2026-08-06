import { createApp } from "vue";
import { createRouter, createWebHistory } from "vue-router";
import App from "./App.vue";
import { isAdminSession, isModeratorSession, loadSession } from "./composables/useSession";
import PageHeader from "./components/ui/PageHeader.vue";
import StatusBadge from "./components/ui/StatusBadge.vue";
import UiFeedback from "./components/ui/UiFeedback.vue";
import FilterBar from "./components/ui/FilterBar.vue";
import FormSaveBar from "./components/ui/FormSaveBar.vue";
const DashboardView = () => import("./views/DashboardView.vue");
const DiscoverView = () => import("./views/DiscoverView.vue");
const DiscoverSourceView = () => import("./views/DiscoverSourceView.vue");
const DownloadsView = () => import("./views/DownloadsView.vue");
const ActivityView = () => import("./views/ActivityView.vue");
const LibraryAnalyticsView = () => import("./views/LibraryAnalyticsView.vue");
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
  { path: "/", redirect: "/discover" },
  { path: "/dashboard", component: DashboardView },
  { path: "/discover/source/:kind/:id", component: DiscoverSourceView },
  { path: "/discover/shows", component: DiscoverView },
  { path: "/discover/movies", component: DiscoverView },
  // Ancienne URL partageable : elle reste valide pour les favoris existants et sert
  // aussi aux recherches mixtes lancees depuis l'accueil.
  { path: "/discover/explore", component: DiscoverView },
  { path: "/discover/requests", component: DiscoverView },
  { path: "/discover/media/:kind/:id", component: MediaDetailView },
  { path: "/discover", component: DiscoverView },
  { path: "/downloads", component: DownloadsView },
  { path: "/activity", component: ActivityView },
  { path: "/analytics", component: LibraryAnalyticsView },
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
  { path: "/:pathMatch(.*)*", redirect: "/discover" },
];

const router = createRouter({
  history: createWebHistory("/"),
  routes,
});

router.onError(recoverFromStaleAssets);

// Aucune page admin-only (Dashboard, Telechargements, Activite, Insights,
// Administration...) n'est proteguee cote route avant ce garde : le masquage de nav
// (App.vue, v-if="isAdmin"/"canModerate") empechait de les voir dans le menu, mais
// naviguer directement par URL les affichait quand meme (donnees en echec 403 en
// cascade, mais la page se montait). Allowlist plutot que blacklist : toute future page
// admin reste protegee par defaut sans avoir a l'ajouter explicitement ici.
const PLAIN_USER_ALLOWED_PREFIXES = ["/discover", "/calendar", "/profile", "/media", "/releases"];
router.beforeEach(async (to) => {
  const session = await loadSession();
  // `to.redirectedFrom` porte le chemin d'origine quand une redirection statique de la
  // table de routes (ex: "/" -> "/discover") a deja resolu `to` vers autre chose : sans
  // ca, la racine ne serait jamais distinguable d'une visite directe de "/discover".
  const originalPath = to.redirectedFrom?.path ?? to.path;
  if (originalPath === "/") {
    const landing = isAdminSession(session) ? "/dashboard" : "/discover";
    if (to.path !== landing) return landing;
    return true;
  }
  if (session && !isAdminSession(session) && !isModeratorSession(session)) {
    if (!PLAIN_USER_ALLOWED_PREFIXES.some(prefix => to.path.startsWith(prefix))) return "/discover";
  }
  return true;
});

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
