// Código comum a todas as páginas: vocabulário (países, bandeiras, níveis),
// grelha XYZ, URLs dos dados, formatação e avisos. Nada de Leaflet nem de
// estado de página.

// Códigos de país por ordem de apresentação. Acrescentar um país é acrescentar
// aqui + a bandeira em BANDEIRA_PATHS; o resto (toggles, tabelas, pills) lê
// destas tabelas em vez de ter a lista escrita à mão.
const PAIS_NOME = {
  PT: 'Portugal',
  ES: 'Espanha',
  AD: 'Andorra',
  DE: 'Alemanha',
  MA: 'Marrocos',
  // resto da Europa (nomes pt, Natural Earth): só para dar nome a um país
  // DETETADO por contorno num square sem dados de região (ver classify.py).
  // Sem bandeira própria em BANDEIRA_PATHS -> bandeiraSvg devolve uma genérica.
  AL: 'Albânia', AT: 'Áustria', AX: 'Åland', BA: 'Bósnia e Herzegovina',
  BE: 'Bélgica', BG: 'Bulgária', BY: 'Bielorrússia', CH: 'Suíça',
  CZ: 'Chéquia', DK: 'Dinamarca', EE: 'Estónia', FI: 'Finlândia',
  FO: 'Ilhas Feroe', FR: 'França', GB: 'Reino Unido', GG: 'Guernsey',
  GR: 'Grécia', HR: 'Croácia', HU: 'Hungria', IE: 'República da Irlanda',
  IM: 'Ilha de Man', IS: 'Islândia', IT: 'Itália', JE: 'Jersey',
  LI: 'Liechtenstein', LT: 'Lituânia', LU: 'Luxemburgo', LV: 'Letónia',
  MC: 'Mónaco', MD: 'Moldávia', ME: 'Montenegro', MK: 'Macedónia do Norte',
  MT: 'Malta', NL: 'Países Baixos', NO: 'Noruega', PL: 'Polónia',
  RO: 'Roménia', RS: 'Sérvia', RU: 'Rússia', SE: 'Suécia',
  SI: 'Eslovénia', SK: 'Eslováquia', SM: 'San Marino', UA: 'Ucrânia',
  VA: 'Vaticano', XK: 'Kosovo',
};

// Interior do <svg> de cada bandeira, sempre no mesmo viewBox 15x11, o tamanho
// final é escolhido por quem chama (o index usa 15x11, o club 13x10).
// SVG e não emoji (🇵🇹/🇪🇸) de propósito: o emoji depende da fonte do sistema e
// em vários ambientes (Linux/Chrome headless, algumas versões mobile) cai para
// as letras "PT"/"ES". Simplificadas, sem brasão, servem para identificar o
// país num relance, não para serem exactas.
const BANDEIRA_PATHS = {
  PT: '<rect width="15" height="11" fill="#da020e"/><rect width="6" height="11" fill="#046a38"/><circle cx="6" cy="5.5" r="2" fill="#ffd400"/>',
  ES: '<rect width="15" height="11" fill="#aa151b"/><rect y="2.75" width="15" height="5.5" fill="#f1bf00"/>',
  AD: '<rect width="15" height="11" fill="#fcdd09"/><rect width="5" height="11" fill="#0018a8"/><rect x="10" width="5" height="11" fill="#d50032"/>',
  DE: '<rect width="15" height="3.67" y="0" fill="#000000"/><rect width="15" height="3.67" y="3.67" fill="#dd0000"/><rect width="15" height="3.67" y="7.33" fill="#ffce00"/>',
  MA: '<rect width="15" height="11" fill="#c1272d"/><polygon points="7.5,2.5 8.2,4.53 10.35,4.57 8.64,5.87 9.26,7.93 7.5,6.7 5.74,7.93 6.36,5.87 4.65,4.57 6.8,4.53" fill="#006233"/>',
};

function bandeiraSvg(cc, largura, altura) {
  // país sem bandeira própria (detetado por contorno): pendão cinzento
  // genérico, para aparecer na mesma com "sem dados por região".
  const inner = BANDEIRA_PATHS[cc]
    || '<rect width="15" height="11" fill="#3a3550"/><rect x="1" y="1" width="13" height="9" fill="none" stroke="#5a5478" stroke-width="1"/>';
  return `<svg width="${largura}" height="${altura}" viewBox="0 0 15 11" class="bandeira">${inner}</svg>`;
}

// Tabela de bandeiras já dimensionada, para quem só quer indexar por código.
function bandeiras(largura, altura) {
  const t = {};
  for (const cc of Object.keys(BANDEIRA_PATHS)) t[cc] = bandeiraSvg(cc, largura, altura);
  return t;
}

// Nomes neutros dos três níveis: "distrito/concelho" só serve em Portugal.
const NIVEL_LABEL = { pais: 'País', regiao: 'Região', zona: 'Zona' };

// Slug de uma região, igual ao pipeline/slugs.py::slugify (NFKD, sem acentos,
// minúsculas, não-alfanumérico -> "-"). Tem de bater certo com os nomes dos
// ficheiros lugares/<key>.html gerados no build.
function slugify(s) {
  return String(s).normalize('NFKD').replace(/[̀-ͯ]/g, '')
    .toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '');
}

// URL da página de um lugar. Espelha o pipeline/regioes.py::key_de:
//   PT           c-<slug> (concelho) / d-<slug> (distrito), sem cc (os
//                bookmarks e os links antigos já assim, não mudam)
//   país         pais-<ccl>
//   estrangeiro  <ccl>-r-<slug> (nível 2) / <ccl>-z-<slug> (nível 3)
// `cc` é opcional: sem ele assume PT.
function regiaoHref(nivel, nome, cc) {
  cc = (cc || 'PT').toUpperCase();
  if (nivel === 'pais') return `lugares/pais-${cc.toLowerCase()}.html`;
  if (cc === 'PT') return `lugares/${nivel === 'concelho' ? 'c' : 'd'}-${slugify(nome)}.html`;
  const p = (nivel === 'zona' || nivel === 'concelho' || nivel === 'municipio') ? 'z' : 'r';
  return `lugares/${cc.toLowerCase()}-${p}-${slugify(nome)}.html`;
}

// --- primitivas de render partilhadas ---

// Cores de identidade dos atletas. Fonte em runtime: data/membros_cores.json,
// que carregarCores() funde em CORES. Este objecto é o fallback offline E a
// única lista do plantel escrita à mão que resta no front-end: as páginas
// derivam os nomes de club.json / club_regioes.json (que os têm por ordem de
// bit) e só caem aqui quando não há rede.
const COR_FALLBACK = {
  'Zé': '#e03131', 'Xeira': '#9c46d8', 'Carolina': '#c99a00',
  'Inês S.': '#e8710a', 'Pedro': '#2f5fd0',
};
let CORES = { ...COR_FALLBACK };
const cor = n => CORES[n] || '#7d8598';

// funde membros_cores.json em CORES. Falha em silêncio: fica o fallback.
async function carregarCores(url, opts) {
  try {
    const r = await fetch(url, opts);
    if (r.ok) { const j = await r.json(); CORES = { ...COR_FALLBACK, ...(j.cores || {}) }; }
  } catch (e) { /* offline: fallback */ }
}

const esc = s => String(s).replace(/[&<>"]/g,
  c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));

// número em pt-PT; null/undefined -> "·", não "0".
const nfmt = n => (n == null ? '·' : n.toLocaleString('pt-PT'));

// quadrado de cor do atleta (.tile do site.css)
const tile = n => `<span class="tile" style="background:${cor(n)}"></span>`;

// link para o perfil do atleta. O ../ entra sozinho a partir de atletas/ ou
// lugares/ (mesmo teste do nav.js: não conta segmentos, aguenta o prefixo do
// repo no GitHub Pages).
const atl = n => `<a class="atl" href="${/\/(atletas|lugares)\//.test(location.pathname) ? '../' : ''}atletas/${slugify(n)}.html">${esc(n)}</a>`;

// tira de quota: `frac` (0..1) -> N células na cor `corHex`, comparáveis em
// comprimento dentro do mesmo grupo. NÃO é magnitude (o número mono leva
// isso). `n` = máximo de células.
function tira(corHex, frac, n) {
  n = n || 16;
  const cheias = frac > 0 ? Math.max(1, Math.min(n, Math.round(frac * n))) : 0;
  return `<span class="tira" style="color:${corHex}">${'<i></i>'.repeat(cheias)}</span>`;
}

// --- datas ---
// Formato único do site: "6 set 2026" (dia sem zero, mês abreviado em
// minúsculas, ano). A linha "Actualizado" mantém a hora: "8 set 2026, 00:11 UTC"
// (sem segundos). Tudo UTC, como os campos `gerado`/`atualizado` dos JSON.
const MESES = ['jan', 'fev', 'mar', 'abr', 'mai', 'jun', 'jul', 'ago', 'set', 'out', 'nov', 'dez'];

function fmtData(iso) {
  const p = String(iso || '').slice(0, 10).split('-');
  if (p.length !== 3) return String(iso || '');
  return `${+p[2]} ${MESES[+p[1] - 1]} ${p[0]}`;
}

// "AAAA-MM-DDTHH:MM:SSZ" -> "8 set 2026, 00:11 UTC"
function fmtDataHora(ts) {
  const m = String(ts || '').match(/^(\d{4}-\d{2}-\d{2})T(\d{2}):(\d{2})/);
  if (!m) return String(ts || '').replace('T', ' ').replace('Z', ' UTC');
  return `${fmtData(m[1])}, ${m[2]}:${m[3]} UTC`;
}

// lat/lng -> tile x/y da grelha XYZ, para um dado zoom. Mesma convenção do
// pipeline (pipeline/kml_parse.py lonlat_to_tile), se um dia divergirem, os
// squares desenhados deixam de bater com os capturados.
function lonlatParaTile(lat, lng, zoom) {
  const n = Math.pow(2, zoom);
  const rad = lat * Math.PI / 180;
  return [
    Math.floor((lng + 180) / 360 * n),
    Math.floor((1 - Math.asinh(Math.tan(rad)) / Math.PI) / 2 * n),
  ];
}

// canto noroeste de um tile -> [lat, lon]. Inverso do lonlatParaTile.
function tileNoroeste(x, y, z) {
  const n = Math.pow(2, z);
  return [
    Math.atan(Math.sinh(Math.PI * (1 - 2 * y / n))) * 180 / Math.PI,
    x / n * 360 - 180,
  ];
}

// --- URLs dos dados ---
// Em produção os JSON dinâmicos lêem-se da branch `data` via
// raw.githubusercontent (sem rebuild do Pages, ver fetch-map-data.yml); em
// localhost/ficheiro lêem-se da cópia local em data/ (feita com
// `git checkout origin/data -- data/`), para dar para testar sem publicar.
// O membros_cores.json e o adjacency.json vivem no `main`.
const _RAW = 'https://raw.githubusercontent.com/JustAnotherDud/squadrats-club/';
const _LOCAL = ['localhost', '127.0.0.1', ''].includes(location.hostname);
const _DATA_LOCAL = (/\/(atletas|lugares)\//.test(location.pathname) ? '../' : '') + 'data/';
const NC = { cache: 'no-cache' };  // revalida sempre (304 quando não mudou)

// ficheiro regenerado pelo cron (branch `data`): club.json, stats.json,
// events.json, club_regioes.json, regioes_index.json, daily_gains.json,
// gains_regioes.json, tile_info_*.json, trophies.json, suggestions.json,
// atletas/<slug>.json, regioes/<key>.json.
const dadosUrl = nome => _LOCAL ? _DATA_LOCAL + nome : _RAW + 'data/data/' + nome;
// ficheiro estático do `main`: membros_cores.json, adjacency.json.
const mainUrl = nome => _LOCAL ? _DATA_LOCAL + nome : _RAW + 'main/data/' + nome;

// --- carregamento de dados com erro sempre visível ---
// fetch + .json() que lança sempre em falha (rede ou status != 2xx). Quem
// chama mostra o erro com mostrarErroDados().
async function carregarJson(url, opts) {
  const nome = url.split('/').pop();
  let r;
  try {
    r = await fetch(url, opts || NC);
  } catch (e) {
    throw new Error(`sem rede (${nome})`);
  }
  if (!r.ok) throw new Error(`${r.status} (${nome})`);
  return r.json();
}

// Mensagem única de "não deu para carregar", no elemento indicado (ou no
// <main>, ou no <body>). Formato igual em todas as páginas.
function mostrarErroDados(alvo, e) {
  const el = alvo || document.querySelector('main') || document.body;
  const detalhe = e && e.message ? ` (${esc(String(e.message))})` : '';
  el.innerHTML = `<p class="erro-dados">Não consegui carregar os dados${detalhe}. `
    + `Tenta recarregar a página. Se persistir, o pipeline pode estar em baixo: `
    + `vê o <a href="https://github.com/JustAnotherDud/squadrats-club/actions">estado das corridas</a>.</p>`;
}

// --- barras de aviso no topo ---
// Insere uma barra logo a seguir à navbar sticky (o fluxo põe-na nos 46px
// certos e o sticky segura-a lá; antes da navbar no DOM sobrepunham-se). Sem
// navbar (analise.html) ou navbar em overlay (club.html): fixa no topo. As
// barras empilham por ordem de inserção.
function _barraTopo(el) {
  const nav = document.getElementById('site-nav');
  const antes = document.getElementById('aviso-stale');
  if (nav && document.body.dataset.nav !== 'overlay') {
    (antes || nav).after(el);
  } else {
    el.classList.add('overlay');
    document.body.insertBefore(el, (antes && antes.nextSibling) || document.body.firstChild);
  }
}

// Se o snapshot tem mais de DADOS_VELHOS_H horas, o cron pode ter falhado e
// os números estão a mostrar o dia anterior com ar de frescos.
const DADOS_VELHOS_H = 6;
function avisoDadosVelhos(iso) {
  const antigo = document.getElementById('aviso-stale');
  if (antigo) antigo.remove();
  if (!iso) return false;
  const h = (Date.now() - Date.parse(iso)) / 3.6e6;
  if (!(h > DADOS_VELHOS_H)) return false;
  const el = document.createElement('div');
  el.id = 'aviso-stale';
  el.textContent = `⚠ Os dados têm mais de ${DADOS_VELHOS_H} h. O pipeline pode não `
    + `ter corrido, e os números aqui podem estar a repetir o dia anterior. `
    + `Última actualização há ~${h.toFixed(0)} h.`;
  _barraTopo(el);
  return true;
}

// --- aviso de squares por classificar ---
// O pipeline avisa quando alguém foi a um sítio que precisa de trabalho
// manual (clip_misses = fora do recorte de 10 km; sem_dados_regiao = país
// sem geometria de região), mas só nos logs do Actions. Isto torna-o visível
// a quem abre o site. `avisos` vem de club_regioes.json.avisos (classify_club.py).
function avisoPorClassificar(avisos) {
  const antigo = document.getElementById('aviso-classificar');
  if (antigo) antigo.remove();
  avisos = avisos || {};
  const partes = [];
  const total = o => Object.values(o || {}).reduce((s, n) => s + n, 0);
  const lista = o => Object.entries(o || {}).map(([cc, n]) => `${cc} ${n}`).join(', ');
  const nClip = total(avisos.clip_misses), nSem = total(avisos.sem_dados_regiao);
  if (nClip) partes.push(`${lista(avisos.clip_misses)} fora do recorte de 10 km`);
  if (nSem) partes.push(`${lista(avisos.sem_dados_regiao)} num país sem dados de região`);
  if (!partes.length) return false;
  const el = document.createElement('div');
  el.id = 'aviso-classificar';
  el.textContent = `⚠ ${nClip + nSem} squadratinho${nClip + nSem === 1 ? '' : 's'} por `
    + `classificar (${partes.join('; ')}). Falta trabalho manual no pipeline. `
    + `Ver o README e o `;
  const a = document.createElement('a');
  a.href = 'https://github.com/JustAnotherDud/squadrats-club/actions';
  a.textContent = 'estado das corridas';
  el.append(a, document.createTextNode('.'));
  _barraTopo(el);
  return true;
}
