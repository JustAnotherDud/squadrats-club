// Vocabulário e componentes partilhados pelas páginas de regiões: o índice
// (index.html) e o renderer de lugares (regiao.js). Carregar depois de
// shared.js e antes desses. Não é um módulo: define no scope global do <script>, como o
// shared.js.

/* eslint-disable no-unused-vars */

// cor / esc / nfmt / tile / atl / tira / carregarCores / COR_FALLBACK / CORES:
// shared.js (carregado antes deste ficheiro).

// % de squadratinhos: 1 casa em geral. Opções:
//   piso      "<0,01%" em vez de "0,00%" (páginas de país, % de um país inteiro)
//   casas     nº de casas decimais (default 1; país usa 2)
//   compacto  >= 9,5% mostra inteiro ("20%" em vez de "20,0%"), no índice
const pctfmt = (p, opts) => {
  if (p == null) return '';
  opts = opts || {};
  if (opts.piso && p > 0 && p < 0.005) return '<0,01%';
  if (opts.compacto && p >= 9.5) return Math.round(p) + '%';
  return p.toFixed(opts.casas != null ? opts.casas : 1) + '%';
};
// Medidor de profundidade da cobertura do clube numa região (a primitiva
// .cobertura do site.css). NÃO é uma barra proporcional: das 100 regiões com
// actividade, 61 estão abaixo de 1% e 47 abaixo de 0,5%, uma barra linear de
// 0 a 100% estaria quase sempre vazia. É uma escada de patamares ~x3, cada
// célula acesa = passou esse patamar. Com estes seis, a contagem de células
// espalha-se bem pela distribuição real (0..6 células, todas povoadas).
const COBERTURA_PATAMARES = [0.05, 0.2, 0.7, 2, 6, 18];
function barraCobertura(pct) {
  if (pct == null) return '';
  const n = COBERTURA_PATAMARES.filter(t => pct >= t).length;
  const cels = COBERTURA_PATAMARES
    .map((_, i) => `<i class="${i < n ? 'on' : ''}"></i>`).join('');
  return `<span class="cobertura" role="img" aria-label="profundidade da `
    + `cobertura: ${n} de ${COBERTURA_PATAMARES.length}" style="grid-template-`
    + `columns:repeat(${COBERTURA_PATAMARES.length},6px);color:var(--ganho)">`
    + `${cels}</span>`;
}

// Tabela de sub-regiões (concelhos de um distrito, zonas de uma região,
// sub-regiões de um país). Colunas ordenáveis por clique/tecla no cabeçalho,
// mesmo padrão das tabelas do perfil (th clicável, indicador ▲/▼).
//   lugar | % | <rotulo> | total | por explorar | membros | líder
//   linhas   [{nome, key?, uniao, pct, total?, lider, n?, disp?}]
//   opts.rotulo   cabeçalho da coluna da união (default "do clube")
//   opts.linkKey  se true e a linha tem `key`, o nome liga a <key>.html
//   opts.pctOpts  passado a pctfmt ({casas:2, piso:true} nos países)
//   opts.sort     {k, dir} mutável; default {k:'uniao', dir:'desc'}.
//                 ligarOrdenacaoSub() actualiza-o ao clicar num cabeçalho.
const SR_COLS = [
  { k: 'nome',     rot: 'lugar',        num: false, val: x => x.nome },
  { k: 'pct',      rot: '%',            num: true,  val: x => x.pct },
  { k: 'uniao',    rot: null,           num: true,  val: x => x.uniao },
  { k: 'total',    rot: 'total',        num: true,  val: x => x.total },
  { k: 'explorar', rot: 'por explorar', num: true,  val: x => (x.total != null ? x.total - x.uniao : null) },
  { k: 'n',        rot: 'membros',      num: true,  val: x => x.n },
  { k: 'lider',    rot: 'líder',        num: false, val: x => x.lider || '' },
];

function ordenarSub(linhas, sort) {
  const col = SR_COLS.find(c => c.k === sort.k) || SR_COLS[2];
  const dir = sort.dir === 'asc' ? 1 : -1;
  return [...linhas].sort((a, b) => {
    let va = col.val(a), vb = col.val(b);
    if (col.num) {
      va = va == null ? -Infinity : va;
      vb = vb == null ? -Infinity : vb;
      return (va - vb) * dir || a.nome.localeCompare(b.nome, 'pt');
    }
    return String(va).localeCompare(String(vb), 'pt') * dir;
  });
}

function tabelaSubRegioes(linhas, opts) {
  opts = opts || {};
  const rot = opts.rotulo || 'do clube';
  const sort = opts.sort || (opts.sort = { k: 'uniao', dir: 'desc' });
  const ord = ordenarSub(linhas, sort);

  const cabecas = SR_COLS.map(c => {
    const activa = c.k === sort.k;
    const seta = activa ? (sort.dir === 'asc' ? ' ▲' : ' ▼') : '';
    const cls = [
      c.k === 'nome' ? 'h-nome' : '',
      activa ? 'ord' : '',
      c.k === 'total' ? 'sr-total' : '',
      c.k === 'explorar' ? 'sr-explorar' : '',
      c.k === 'n' ? 'sr-membros' : '',
    ].filter(Boolean).join(' ');
    const asort = activa ? (sort.dir === 'asc' ? 'ascending' : 'descending') : 'none';
    return `<th data-sort="${c.k}"${cls ? ` class="${cls}"` : ''} aria-sort="${asort}">${esc(c.k === 'uniao' ? rot : c.rot)}${seta}</th>`;
  }).join('');

  const corpo = ord.map(x => {
    const nomeCel = (opts.linkKey && x.key)
      ? `<a class="idx-nome${x.disp ? ' disp' : ''}" href="${x.key}.html">${esc(x.nome)}</a>`
      : `<span class="sr-nome">${esc(x.nome)}</span>`;
    const explorar = x.total != null ? x.total - x.uniao : null;
    const lid = x.lider ? `${tile(x.lider)}${esc(x.lider)}` : '';
    return `<tr>
      <td>${nomeCel}</td>
      <td class="pct">${pctfmt(x.pct, opts.pctOpts)}</td>
      <td class="num">${nfmt(x.uniao)}</td>
      <td class="num sr-total">${x.total != null ? nfmt(x.total) : ''}</td>
      <td class="num sr-explorar">${explorar != null ? nfmt(explorar) : ''}</td>
      <td class="num sr-membros">${x.n != null ? x.n : ''}</td>
      <td class="uni">${lid}</td>
    </tr>`;
  }).join('');

  return `<div class="sr-scroll"><table class="reg-rank sr-sort">
    <thead><tr>${cabecas}</tr></thead>
    <tbody>${corpo}</tbody></table></div>`;
}

// Liga clique/tecla nos cabeçalhos <th data-sort>. Mesmo k alterna asc/desc;
// k novo começa desc nos numéricos e asc no nome/líder. `render()` volta a
// desenhar a tabela (mesmo padrão do desenhar() das tabelas do perfil).
function ligarOrdenacaoSub(container, sort, render) {
  if (!container) return;
  container.querySelectorAll('th[data-sort]').forEach(th => {
    th.tabIndex = 0;
    const activar = () => {
      const k = th.dataset.sort;
      if (sort.k === k) sort.dir = sort.dir === 'asc' ? 'desc' : 'asc';
      else { sort.k = k; sort.dir = (k === 'nome' || k === 'lider') ? 'asc' : 'desc'; }
      render();
    };
    th.onclick = activar;
    th.onkeydown = e => {
      if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); activar(); }
    };
  });
}
