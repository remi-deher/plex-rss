// `form`/`secretsPresent`/isDirty sont des singletons de module (voir le commentaire en
// tete de settingsForm.js) : chaque test re-importe le module a neuf via resetModules(),
// sinon l'etat d'un test fuiterait dans le suivant.
import { beforeEach, describe, expect, it, vi } from 'vitest';

const apiMock = vi.fn();
vi.mock('@/api', () => ({ api: (...args) => apiMock(...args) }));

async function freshSettingsForm() {
  vi.resetModules();
  apiMock.mockReset();
  return import('./settingsForm.js');
}

describe('settingsForm', () => {
  beforeEach(() => {
    apiMock.mockReset();
  });

  it('load() peuple le formulaire et vide les champs secrets tout en gardant leur presence', async () => {
    const { form, secretsPresent, load } = await freshSettingsForm();
    apiMock.mockResolvedValueOnce({
      plex_url: 'http://plex.local',
      plex_token: '••••••••',
      smtp_password: '••••••••',
      email_enabled: true,
    });

    await load();

    expect(form.plex_url).toBe('http://plex.local');
    expect(form.email_enabled).toBe(true);
    // Un champ secret n'est jamais affiche, meme masque : sa presence est portee par
    // `secretsPresent`, pas par la valeur du formulaire (voir commentaire du fichier).
    expect(form.plex_token).toBe('');
    expect(form.smtp_password).toBe('');
    expect(secretsPresent.plex_token).toBe(true);
    expect(secretsPresent.smtp_password).toBe(true);
  });

  it('load() marque un secret absent comme non-present', async () => {
    const { form, secretsPresent, load } = await freshSettingsForm();
    apiMock.mockResolvedValueOnce({ plex_token: null });

    await load();

    expect(form.plex_token).toBe('');
    expect(secretsPresent.plex_token).toBe(false);
  });

  it('save() omet un champ secret laisse vide (ne l\'ecrase pas cote serveur)', async () => {
    const { form, load, save } = await freshSettingsForm();
    apiMock.mockResolvedValueOnce({ plex_url: 'http://plex.local', plex_token: 'real-token' });
    await load();
    apiMock.mockResolvedValueOnce({ status: 'ok' });

    await save();

    const [, options] = apiMock.mock.calls[1];
    const payload = JSON.parse(options.body);
    expect(payload).not.toHaveProperty('plex_token');
    expect(payload.plex_url).toBe('http://plex.local');
  });

  it('save() inclut un champ secret si l\'utilisateur y a saisi une nouvelle valeur', async () => {
    const { form, load, save } = await freshSettingsForm();
    apiMock.mockResolvedValueOnce({ plex_token: 'old-token' });
    await load();
    form.plex_token = 'nouveau-token';
    apiMock.mockResolvedValueOnce({ status: 'ok' });

    await save();

    const [, options] = apiMock.mock.calls[1];
    const payload = JSON.parse(options.body);
    expect(payload.plex_token).toBe('nouveau-token');
  });

  it('isDirty reste faux juste apres load(), devient vrai apres une modification', async () => {
    const { form, load, isDirty } = await freshSettingsForm();
    apiMock.mockResolvedValueOnce({ plex_url: 'http://plex.local' });
    await load();

    expect(isDirty.value).toBe(false);

    form.plex_url = 'http://autre.local';

    expect(isDirty.value).toBe(true);
  });

  it('isDirty redevient faux apres save()', async () => {
    const { form, load, save, isDirty } = await freshSettingsForm();
    apiMock.mockResolvedValueOnce({ plex_url: 'http://plex.local' });
    await load();
    form.plex_url = 'http://autre.local';
    expect(isDirty.value).toBe(true);
    apiMock.mockResolvedValueOnce({ status: 'ok' });

    await save();

    expect(isDirty.value).toBe(false);
  });

  it('fail() apres un load() en erreur peuple error sans lever d\'exception', async () => {
    const { load, error } = await freshSettingsForm();
    apiMock.mockRejectedValueOnce(new Error('HTTP 500'));

    await load();

    expect(error.value).toBe('HTTP 500');
  });
});
