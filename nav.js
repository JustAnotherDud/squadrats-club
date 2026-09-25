// Barra de navegação partilhada por todas as páginas do site (menos o mapa
// detalhado pessoal, que fica de fora da navegação de propósito).
//
// Injecta-se a si própria: cada página só precisa de <script src="nav.js">
// (ou "../nav.js" a partir de atletas/ e lugares/). Sem dependências.
//
// Páginas de mapa em ecrã cheio (club.html) põem <body data-nav="overlay">:
// a barra fica `position:fixed` e a página trata do offset do #map/#topbar.
// As outras usam `position:sticky` e não precisam de mais nada.
(function () {
  'use strict';

  // Prefixo para os links (raiz vs subpasta). Deriva-se do src do PRÓPRIO
  // <script> desta página ("nav.js" na raiz, "../nav.js" em atletas/ e
  // lugares/), é a mesma declaração de caminho relativo que o autor do HTML
  // já escreveu, por isso não pode discordar da localização real da página.
  // Contar segmentos de location.pathname não serve: no GitHub Pages o path
  // tem o prefixo do repo (/squadrats-club/lugares/x.html = 3 segmentos) e
  // localmente não (/lugares/x.html = 2), mesma página, contagem diferente.
  var P = (document.currentScript.getAttribute('src').match(/\.\.\//g) || []).join('');

  // lugares/* e atletas/* acendem o seu item (a página está "debaixo" desse
  // destino), tal como um perfil acende "Perfis". As de subpasta têm de ser
  // testadas ANTES do file==='index.html' (lugares/index.html não é o hub).
  var file = (location.pathname.split('/').pop() || '').toLowerCase();
  var atual =
    /\/atletas\//.test(location.pathname) ? 'perfis' :
    /\/lugares\//.test(location.pathname) ? 'lugares' :
    file === 'club.html' ? 'mapa' :
    file === 'historico.html' ? 'historico' :
    file === 'ganhos.html' ? 'ganhos' :
    (file === '' || file === 'index.html') ? 'hub' :
    null;  // analise.html, nada destacado

  var DEST = [
    { id: 'mapa', label: 'Mapa', href: P + 'club.html' },
    { id: 'perfis', label: 'Perfis', href: P + 'atletas/' },
    { id: 'lugares', label: 'Lugares', href: P + 'lugares/' },
    { id: 'historico', label: 'Histórico', href: P + 'historico.html' },
    { id: 'ganhos', label: 'Ganhos', href: P + 'ganhos.html' },
  ];

  // Estilo: a barra segue o site.css (tokens, fontes). Nada de pill azul; o
  // item activo leva uma aresta 2px em --marca (canto de tile).
  var CSS = [
    '#site-nav{position:sticky;top:0;z-index:3000;display:flex;align-items:center;',
    'gap:14px;padding:0 16px;height:46px;background:var(--ch-0,#14131b);',
    'border-bottom:1px solid var(--rule,#37334a);box-sizing:border-box;',
    'font-family:var(--f-txt,system-ui,sans-serif);font-size:13px}',
    '#site-nav.overlay{position:fixed;left:0;right:0}',
    '#site-nav .marca{display:flex;align-items:center;gap:8px;text-decoration:none;',
    'font-family:var(--f-tit,sans-serif);font-weight:600;font-size:14px;',
    'color:var(--tinta-2,#a29cb4);letter-spacing:-.01em}',
    '#site-nav .marca:hover,#site-nav .marca[aria-current]{color:var(--tinta,#eceaf4)}',
    '#site-nav .marca .lf{width:11px;height:11px;border-radius:1px;background:#ef7722;flex:0 0 auto}',
    '#site-nav .links{display:flex;gap:2px;margin-left:auto}',
    '#site-nav .links a{color:var(--tinta-2,#a29cb4);text-decoration:none;',
    'padding:14px 9px 12px;border-bottom:2px solid transparent}',
    '#site-nav .links a:hover{color:var(--tinta,#eceaf4)}',
    '#site-nav .links a[aria-current]{color:var(--tinta,#eceaf4);border-bottom-color:var(--marca,#663399)}',
    '@media(max-width:480px){#site-nav{gap:8px;padding:0 12px}',
    '#site-nav .links a{padding:14px 6px 12px;font-size:12px}}',
  ].join('');

  var links = DEST.map(function (d) {
    return '<a href="' + d.href + '"' + (d.id === atual ? ' aria-current="page"' : '') + '>' + d.label + '</a>';
  }).join('');
  var html =
    '<a class="marca" href="' + P + 'index.html"' + (atual === 'hub' ? ' aria-current="page"' : '') +
      '><span class="lf"></span>Squadrats Club</a>' +
    '<span class="links">' + links + '</span>';

  function montar() {
    var st = document.createElement('style');
    st.textContent = CSS;
    document.head.appendChild(st);
    var nav = document.createElement('nav');
    nav.id = 'site-nav';
    if (document.body.dataset.nav === 'overlay') nav.className = 'overlay';
    nav.innerHTML = html;
    document.body.insertBefore(nav, document.body.firstChild);
  }
  if (document.body) montar();
  else document.addEventListener('DOMContentLoaded', montar);

  // PWA: regista o service worker (sw.js na raiz da app). `P` já é o prefixo
  // relativo certo para qualquer profundidade. Sem SW o Android não instala
  // como WebAPK. Falha em silêncio (http:, sem suporte, etc.).
  if ('serviceWorker' in navigator && location.protocol.startsWith('http')) {
    window.addEventListener('load', function () {
      navigator.serviceWorker.register(P + 'sw.js', { scope: P || './' })
        .catch(function () { /* sem PWA, o site funciona na mesma */ });
    });
  }
})();
