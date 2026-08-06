import { expect, test } from '@playwright/test';

test.beforeEach(async ({ page }) => {
  await page.route('**/api/**', async route => {
    const url = new URL(route.request().url());
    if (url.pathname === '/api/session') {
      await route.fulfill({ json: { role: 'user', plex_user_id: 'alice' } });
      return;
    }
    if (url.pathname === '/api/discover/detail') {
      await route.fulfill({
        json: {
          tmdb_id: 1399,
          media_type: 'show',
          title: 'Série test',
          year: 2026,
          number_of_seasons: 3,
          requested: false,
          available: false,
          overview: 'Une série utilisée pour vérifier le parcours de demande.',
        },
      });
      return;
    }
    await route.fulfill({ json: {} });
  });
  await page.goto('/discover/media/discover/1399?media_type=show', { waitUntil: 'domcontentloaded' });
});

test('utilise un CTA unique et choisit les saisons dans une modale', async ({ page }) => {
  await expect(page.locator('.request-panel')).toHaveCount(0);
  const requestButtons = page.getByRole('button', { name: 'Demander la série' });
  await expect(requestButtons).toHaveCount(1);
  await requestButtons.click();

  await expect(page.getByRole('dialog', { name: /Options de la demande/ })).toBeVisible();
  await expect(page.getByLabel('Saison 1')).toBeChecked();
  await expect(page.getByLabel('Saison 2')).toBeChecked();
  await expect(page.getByLabel('Saison 3')).toBeChecked();
  await expect(page.getByLabel('Saison 0')).toHaveCount(0);
});
