import { expect, test } from "@playwright/test";

test.describe.configure({ mode: "serial", timeout: 60_000 });

function catalog(page, totalPages = 2) {
  const offset = (page - 1) * 2;
  return {
    items: [1, 2].map((value) => ({
      tmdb_id: offset + value,
      media_type: value % 2 ? "movie" : "show",
      title: `Média ${offset + value}`,
      year: 2026,
      vote: 7.5,
      poster_url: null,
      requested: false,
      available: false,
      in_library: false,
    })),
    page,
    total_pages: totalPages,
    total_results: totalPages * 2,
  };
}

test.beforeEach(async ({ page }) => {
  await page.route("**/api/**", async (route) => {
    const url = new URL(route.request().url());
    if (url.pathname === "/api/session") {
      await route.fulfill({ json: { role: "admin", is_owner: true } });
    } else if (url.pathname === "/api/discover/genres") {
      await route.fulfill({ json: [{ id: 28, name: "Action" }] });
    } else if (url.pathname.startsWith("/api/discover/")) {
      await route.fulfill({ json: catalog(Number(url.searchParams.get("page") || 1)) });
    } else {
      await route.fulfill({ json: {} });
    }
  });
  await page.goto("/discover/movies", { waitUntil: "domcontentloaded" });
});

test("charge progressivement le catalogue et conserve des liens accessibles", async ({ page }) => {
  await expect(page.locator(".discover-card")).toHaveCount(2, { timeout: 15_000 });
  await expect(page.locator(".discover-poster-link").first()).toHaveAttribute("href", /\/media\/discover\/1/);
  const cardBox = await page.locator('.discover-card').first().boundingBox();
  const posterBox = await page.locator('.discover-card .poster-shell').first().boundingBox();
  expect(Math.abs(cardBox.width - posterBox.width)).toBeLessThanOrEqual(2);
  expect(Math.abs(cardBox.height - posterBox.height)).toBeLessThanOrEqual(2);

  await page.locator(".infinite-scroll-trigger").scrollIntoViewIfNeeded();

  await expect(page.locator(".discover-card")).toHaveCount(4);
  await expect(page.getByText("4 affichés sur 4")).toBeVisible();
});

test("conserve le catalogue Films lors d'une recherche", async ({ page }) => {
  const searchRequest = page.waitForRequest(request => (
    request.url().includes("/api/discover/search")
    && request.url().includes("media_type=movie")
  ));
  await page.getByRole("searchbox", { name: "Rechercher un film" }).fill("Dune");
  await searchRequest;
});

test("affiche la navigation dédiée et replie les filtres", async ({ page }) => {
  const navigation = page.locator('.discover-primary-nav:visible, .discover-mobile-nav:visible');
  await expect(navigation.getByRole("link", { name: "Accueil" })).toBeVisible();
  await expect(navigation.getByRole("link", { name: "Séries" })).toBeVisible();
  await expect(navigation.getByRole("link", { name: "Films" })).toBeVisible();
  await expect(navigation.getByRole("link", { name: "Demandes" })).toBeVisible();
  const filters = page.locator('#discover-filters');
  await expect(filters).toBeHidden();
  await page.getByRole("button", { name: /Filtres/ }).click();
  await expect(filters).toBeVisible();
  await filters.getByRole('button', { name: 'Populaires' }).click();
  const reset = filters.getByRole('button', { name: 'Réinitialiser' });
  await expect(reset).toBeVisible();
  const layoutFits = await filters.evaluate(element => element.scrollWidth <= element.clientWidth + 1);
  expect(layoutFits).toBe(true);
  await navigation.getByRole("link", { name: "Séries" }).click();
  await expect(page).toHaveURL(/\/discover\/shows$/);
  await expect(page.getByRole("searchbox", { name: "Rechercher une série" })).toBeVisible();
  await navigation.getByRole("link", { name: "Accueil" }).click();
  await expect(page).toHaveURL(/\/discover$/);
});

test("reste utilisable au clavier et sur mobile", async ({ page }, testInfo) => {
  const firstCard = page.locator(".discover-card").first();
  const firstLink = firstCard.locator(".discover-poster-link");
  await firstLink.focus();
  await expect(firstLink).toBeFocused();
  if (testInfo.project.name === "mobile") {
    await expect(firstCard.locator(".discover-card-action")).toBeVisible();
  }
});

test("centre la recherche et mémorise la sidebar rabattue", async ({ page }, testInfo) => {
  const searchBox = await page.locator('.discover-command').boundingBox();
  const mainBox = await page.locator('#main-content').boundingBox();
  expect(Math.abs((searchBox.x + searchBox.width / 2) - (mainBox.x + mainBox.width / 2))).toBeLessThan(3);

  if (testInfo.project.name !== 'mobile') {
    const sidebar = page.locator('.discover-sidebar');
    const isExpanded = await sidebar.getAttribute('aria-expanded') === 'true';
    await page.getByRole('button', { name: isExpanded ? 'Réduire le menu' : 'Afficher le menu' }).click();
    const expected = isExpanded ? 'false' : 'true';
    await expect(sidebar).toHaveAttribute('aria-expanded', expected);
    await page.reload();
    await expect(sidebar).toHaveAttribute('aria-expanded', expected);
  }
});
