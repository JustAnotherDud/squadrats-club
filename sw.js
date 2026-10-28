// Service worker mínimo para a PWA instalar como app (WebAPK no Android
// precisa de um SW com handler de fetch). Estratégia: a app é uma casca
// estática que lê dados de raw.githubusercontent, não tenta ficar offline a
// sério: só serve a casca da cache quando a rede falha.
//
// Registado pelo nav.js. Versão na cache: subir CACHE ao mudar a casca.
const CACHE = 'squadrats-club-v3';

// Âmbito do SW (…/squadrats-club/ no GitHub Pages, / em local).
const BASE = new URL('./', self.registration.scope).pathname;

self.addEventListener('install', e => {
  self.skipWaiting();
  e.waitUntil(caches.open(CACHE).then(c => c.addAll([
    BASE, BASE + 'index.html',
    BASE + 'manifest.json', BASE + 'icon.svg',
    BASE + 'nav.js', BASE + 'shared.js', BASE + 'site.css',
    BASE + 'fonts/bricolage-grotesque.woff2', BASE + 'fonts/ibm-plex-sans-400.woff2',
    BASE + 'fonts/ibm-plex-mono-400.woff2',
  ]).catch(() => {})));
});

self.addEventListener('activate', e => {
  e.waitUntil((async () => {
    for (const k of await caches.keys()) if (k !== CACHE) await caches.delete(k);
    await self.clients.claim();
  })());
});

self.addEventListener('fetch', e => {
  const req = e.request;
  if (req.method !== 'GET') return;
  const url = new URL(req.url);
  const mesmaOrigem = url.origin === self.location.origin;

  // navegações e casca (mesma origem): rede primeiro, cache como recurso.
  if (req.mode === 'navigate' || (mesmaOrigem && !url.pathname.startsWith(BASE + 'data/'))) {
    e.respondWith((async () => {
      try {
        const resp = await fetch(req);
        if (resp.ok && mesmaOrigem) {
          const c = await caches.open(CACHE);
          c.put(req, resp.clone());
        }
        return resp;
      } catch (err) {
        const cached = await caches.match(req);
        if (cached) return cached;
        if (req.mode === 'navigate') {
          const shell = await caches.match(BASE + 'index.html');
          if (shell) return shell;
        }
        throw err;
      }
    })());
  }
  // dados (raw.githubusercontent, data/*): deixa passar, sem cache.
});
