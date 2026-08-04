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
  await page.goto("/discover/explore", { waitUntil: "domcontentloaded" });
});

test("charge progressivement le catalogue et conserve des liens accessibles", async ({ page }) => {
  await expect(page.locator(".discover-card")).toHaveCount(2);
  await expect(page.locator(".discover-poster-link").first()).toHaveAttribute("href", /\/media\/discover\/1/);

  await page.getByRole("button", { name: "Charger plus de médias" }).click();

  await expect(page.locator(".discover-card")).toHaveCount(4);
  await expect(page.getByText("4 affichés sur 4")).toBeVisible();
});

test("applique le filtre Films à une recherche", async ({ page }, testInfo) => {
  if (testInfo.project.name === "mobile") {
    await page.getByRole("button", { name: /Filtres/ }).click();
  }
  await page.getByRole("button", { name: "Films", exact: true }).click();
  const searchRequest = page.waitForRequest(request => (
    request.url().includes("/api/discover/search")
    && request.url().includes("media_type=movie")
  ));
  await page.getByRole("searchbox", { name: "Rechercher un film ou une série" }).fill("Dune");
  await searchRequest;
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
