import { describe, expect, it } from 'vitest';

import { proxyUrl } from './mediaImage';

const isProxied = (url) => proxyUrl(url).startsWith('/api/image-proxy');

describe('proxyUrl', () => {
  it('laisse passer le CDN TMDB en direct', () => {
    // Le navigateur charge ces affiches sur le CDN, en parallele et sans traverser notre
    // process Python : les proxifier serait le pire cas pour une grille de posters.
    const url = 'https://image.tmdb.org/t/p/w500/abc.jpg';
    expect(proxyUrl(url)).toBe(url);
  });

  it('ne proxifie pas une URL publique dont le chemin ressemble a une IP privee', () => {
    // Regression : l'ancien test travaillait sur la chaine brute et cherchait "/10." ou
    // "/192.168." n'importe ou dans l'URL, chemin compris.
    expect(isProxied('https://cdn.example.com/10.jpg')).toBe(false);
    expect(isProxied('https://cdn.example.com/posters/192.168.jpg')).toBe(false);
  });

  it('proxifie les adresses privees RFC 1918', () => {
    expect(isProxied('https://192.168.1.5:32400/photo')).toBe(true);
    expect(isProxied('https://10.0.0.4/photo')).toBe(true);
    expect(isProxied('https://127.0.0.1/photo')).toBe(true);
    // Plage 172.16-31.x, absente de l'ancien test.
    expect(isProxied('https://172.16.0.9/photo')).toBe(true);
    expect(isProxied('https://172.31.255.1/photo')).toBe(true);
  });

  it('laisse passer les adresses 172.x hors plage privee', () => {
    expect(isProxied('https://172.15.0.1/photo')).toBe(false);
    expect(isProxied('https://172.32.0.1/photo')).toBe(false);
  });

  it('proxifie les noms d’hotes du reseau local', () => {
    expect(isProxied('https://plex.local/photo')).toBe(true);
    expect(isProxied('https://nas.lan/photo')).toBe(true);
    // Nom nu, resolvable uniquement sur le LAN.
    expect(isProxied('https://plex/photo')).toBe(true);
  });

  it('proxifie le HTTP en clair quand la page est en HTTPS (mixed content)', () => {
    const original = window.location;
    // jsdom sert la page en http:// par defaut ; on force https pour ce cas.
    Object.defineProperty(window, 'location', {
      configurable: true,
      value: { ...original, origin: 'https://plexarr.example.com', protocol: 'https:' },
    });
    try {
      expect(isProxied('http://cdn.example.com/poster.jpg')).toBe(true);
    } finally {
      Object.defineProperty(window, 'location', { configurable: true, value: original });
    }
  });

  it('laisse passer une affiche servie par l’application elle-meme', () => {
    const url = `${window.location.origin}/static/poster.jpg`;
    expect(proxyUrl(url)).toBe(url);
  });

  it('retourne la valeur telle quelle pour une entree vide ou invalide', () => {
    expect(proxyUrl('')).toBe('');
    expect(proxyUrl(null)).toBe(null);
    expect(proxyUrl(undefined)).toBe(undefined);
    expect(proxyUrl('pas-une-url')).toBe('pas-une-url');
  });
});
