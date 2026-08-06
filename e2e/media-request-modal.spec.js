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
          cast: [{ tmdb_id: 287, name: 'Acteur test', character: 'Personnage principal', profile_url: null }],
          recommendations: [{ tmdb_id: 550, media_type: 'movie', title: 'Film recommandé', year: 1999 }],
          similar: [{ tmdb_id: 551, media_type: 'show', title: 'Série similaire', year: 2000 }],
        },
      });
      return;
    }
    if (url.pathname === '/api/discover/person/287') {
      await route.fulfill({ json: {
        tmdb_id: 287,
        name: 'Acteur test',
        biography: 'Une biographie de test.',
        known_for_department: 'Acting',
        credits: [{ tmdb_id: 550, media_type: 'movie', title: 'Film joué', year: 1999 }],
      } });
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

test('affiche casting, recommandations et ouvre la filmographie acteur', async ({ page }) => {
  await expect(page.getByRole('heading', { name: 'Casting' })).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Recommandés pour vous' })).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Titres similaires' })).toBeVisible();
  await page.getByRole('link', { name: 'Voir la fiche de Acteur test' }).click();
  await expect(page).toHaveURL(/\/discover\/person\/287$/);
  await expect(page.getByRole('heading', { name: 'Acteur test' })).toBeVisible();
  await expect(page.getByText('Film joué')).toBeVisible();
});
