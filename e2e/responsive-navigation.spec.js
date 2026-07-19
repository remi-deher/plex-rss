import { expect, test } from "@playwright/test";

test.beforeEach(async ({ page }) => {
  await page.route("**/api/**", async (route) => {
    const pathname = new URL(route.request().url()).pathname;
    const body = pathname === "/api/session" ? { role: "admin", is_owner: true } : {};
    await route.fulfill({ json: body });
  });
  await page.goto("/dashboard");
});

test("navigation remains usable at the configured viewport", async ({ page }, testInfo) => {
  const desktopSidebar = page.locator(".sidebar");
  const mobileNavigation = page.locator(".mobile-nav-bar");

  if (testInfo.project.name === "mobile") {
    await expect(desktopSidebar).toBeHidden();
    await expect(mobileNavigation).toBeVisible();
    await page.getByRole("button", { name: "Plus" }).click();
    await expect(page.getByRole("heading", { name: "Menu" })).toBeVisible();
    await expect(page.getByRole("link", { name: "Telechargements" })).toBeVisible();
  } else {
    await expect(desktopSidebar).toBeVisible();
    await expect(mobileNavigation).toBeHidden();

    if (testInfo.project.name === "tablet") {
      await page.getByRole("button", { name: "Afficher le menu" }).click();
      await expect(desktopSidebar).toHaveAttribute("aria-expanded", "true");
    } else {
      await page.getByRole("button", { name: "Réduire le menu" }).click();
      await expect(desktopSidebar).toHaveAttribute("aria-expanded", "false");
      await page.reload();
      await expect(desktopSidebar).toHaveAttribute("aria-expanded", "false");
    }
  }

  const horizontalOverflow = await page.evaluate(
    () => document.documentElement.scrollWidth > document.documentElement.clientWidth,
  );
  expect(horizontalOverflow).toBe(false);
});

test("library filters can be compacted", async ({ page }, testInfo) => {
  await page.goto("/library");
  const trigger = page.locator(".compact-filter-toggle");
  const filters = page.locator(".filter-pills-scroll");

  if (testInfo.project.name === "mobile") {
    await expect(trigger).toHaveAttribute("aria-expanded", "false");
    await expect(filters).toBeHidden();
    await trigger.click();
    await expect(filters).toBeVisible();
  } else {
    await expect(trigger).toHaveAttribute("aria-expanded", "true");
    await trigger.click();
    await expect(filters).toBeHidden();
  }
});
