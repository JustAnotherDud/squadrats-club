// Página de um lugar: concelho / distrito (PT), região / zona (estrangeiro)
// ou país. Lê regioes/<key>.json + regioes_index.json + events.json da branch
// `data`. Um renderer para os cinco níveis.
(function () {
  'use strict';

  // dadosUrl / mainUrl / NC / carregarJson / mostrarErroDados /
  // avisoDadosVelhos: shared.js
  const alvo = document.getElementById('regiao');
  const KEY = alvo.dataset.key, NIVEL = alvo.dataset.nivel;

  // cor / esc / nfmt / tile / atl / tira / carregarCores: shared.js
  // pctfmt / barraCobertura / tabelaSubRegioes: comum.js

  // palavra sob o título e cabeçalho da secção de sub-regiões, por nível e
  // país (onde "distrito/concelho" não serve). Mesma ideia do NIVEL_LABEL.
  const SUB = {
    pais: 'país', distrito: 'distrito', concelho: 'concelho',
    regiao: { ES: 'província', DE: 'Land', MA: 'região' },
    zona: { ES: 'município', DE: 'município', MA: 'cercle' },
  };
  const FILHOS_TIT = {
    pais: { PT: 'Distritos', ES: 'Províncias', DE: 'Länder', MA: 'Regiões' },
    distrito: 'Concelhos',
    regiao: { ES: 'Municípios', DE: 'Municípios', MA: 'Cercles' },
  };
  const rotulo = (m, nivel, cc) => {
    const v = m[nivel];
    return typeof v === 'string' ? v : (v && v[cc]) || nivel;
  };

  const ICO = { ultrapassagem: '⇅', novo_lider: '👑', primeira_presenca: '📍', marco: '🚩' };
  const LEGENDA_EV = `<details class="legenda">
    <summary>👑 ⇅ 📍 🚩 <span class="lg-q">o que significam</span></summary>
    <div class="lg-corpo">
      <span>👑 <b>nova liderança</b> desta região</span>
      <span>⇅ <b>ultrapassagem</b> (troca de posição fora do topo)</span>
      <span>📍 <b>primeira presença</b> de um atleta aqui</span>
      <span>🚩 <b>marco</b> de squadratinhos (25/50/100/…)</span>
    </div>
  </details>`;
  function frase(e) {
    const v = e.valores;
    if (e.tipo === 'ultrapassagem')
      return `${tile(e.quem)}${atl(e.quem)} passou ${tile(e.sobre)}${atl(e.sobre)}
        <span class="num">${nfmt(v[0])} vs ${nfmt(v[1])}</span>`;
    if (e.tipo === 'novo_lider')
      return `${tile(e.quem)}${atl(e.quem)} assumiu a liderança, passou ${tile(e.sobre)}${atl(e.sobre)}
        <span class="num">${nfmt(v[0])} vs ${nfmt(v[1])}</span>`;
    if (e.tipo === 'primeira_presenca')
      return `${tile(e.quem)}${atl(e.quem)} estreou-se aqui
        <span class="num">${nfmt(v[0])} squadratinho${v[0] === 1 ? '' : 's'}</span>`;
    return `${tile(e.quem)}${atl(e.quem)} passou os <b>${nfmt(v[0])}</b> squadratinhos,
      <span class="num">agora ${nfmt(v[1])}</span>`;
  }

  // vizinho "disputado" = com evento de troca (ultrapassagem / novo líder),
  // mesma definição da coluna "Lugares contestados" do historico.html. cc
  // separa uma província ES de um distrito PT com o mesmo nome.
  function temEventoTroca(eventos, cc, nivel, regiao) {
    return eventos.some(e =>
      (e.tipo === 'ultrapassagem' || e.tipo === 'novo_lider') &&
      (e.cc || 'PT') === cc && e.nivel === nivel && e.regiao === regiao);
  }

  // "8 set 2026" -> "8 set" para a coluna de data do feed
  const diaCurto = iso => fmtData(iso).replace(/\s\d{4}$/, '');

  function pintar(d, eventos, filhos) {
    const cc = d.cc || 'PT';
    const ehPais = d.nivel === 'pais';
    const q = fmtDataHora(d.gerado);
    avisoDadosVelhos(d.gerado);  // shared.js
    let ns = 0;
    const sec = t => `<div class="sec"><span class="n">${String(++ns).padStart(2, '0')}</span><span class="t">${t}</span></div>`;

    // hierarquia acima: pai e avô quando existem, cada um numa linha de meta.
    // O rótulo é "país" se a key for pais-*, senão o nível do pai (distrito
    // para um concelho, província/Land/região para uma zona).
    const rotPai = k => k && k.indexOf('pais-') === 0
      ? 'país'
      : rotulo(SUB, d.nivel === 'concelho' ? 'distrito' : 'regiao', cc);
    const linkMeta = (rot, k, nome) => (k && nome)
      ? `<dt>${rot}</dt><dd><a href="${esc(k)}.html">${esc(nome)}</a></dd>` : '';
    // pai primeiro (o mais próximo), avô a seguir: concelho -> distrito, país
    const paiRows = linkMeta(rotPai(d.pai_key), d.pai_key, d.pai_nome)
      + linkMeta(rotPai(d.avo_key), d.avo_key, d.avo_nome);

    const temExc = d.ranking.some(r => r.exclusivos != null);
    const lider = d.ranking.length ? d.ranking[0].captured : 0;
    const rankRows = d.ranking.map((r, i) => `
      <tr class="${i === 0 ? 'p1' : ''}">
        <td class="pos${i === 0 ? ' p1' : ''}">${i + 1}</td>
        <td><span class="nome">${tile(r.nome)}${atl(r.nome)}</span></td>
        <td class="tira-td">${tira(cor(r.nome), lider ? r.captured / lider : 0)}</td>
        <td class="num">${nfmt(r.captured)}</td>
        ${temExc ? `<td class="uni">${r.exclusivos ? nfmt(r.exclusivos) : ''}</td>` : ''}
        <td class="pct">${r.pct != null ? r.pct.toFixed(ehPais ? 2 : 1) + '%' : ''}</td>
      </tr>`).join('');
    const rankHead = `<thead><tr>
      <th></th><th class="h-nome">atleta</th><th class="h-nome">quota</th>
      <th title="squadratinhos do atleta, partilhados incluídos">total</th>
      ${temExc ? '<th title="squadratinhos que mais nenhum membro do clube tem aqui">únicos</th>' : ''}
      <th>%</th></tr></thead>`;
    const rankTable = d.ranking.length
      ? `<table class="reg-rank">${rankHead}<tbody>${rankRows}</tbody></table>`
      : '<p class="reg-vazio">Nenhum membro do clube tem squadratinhos aqui.</p>';

    const uni = d.uniao && d.uniao.z17 != null ? d.uniao : null;
    const pctOpts = ehPais ? { casas: 2, piso: true } : undefined;
    const medidor = uni && uni.pct != null && !ehPais ? ' ' + barraCobertura(uni.pct) : '';
    const cobre = `<p class="reg-cobre">${ehPais ? 'País' : 'Região'} com <b>${d.totais.z17 != null ? nfmt(d.totais.z17) : '?'}</b>
      squadratinhos${uni ? `, o clube cobre <b>${nfmt(uni.z17)}</b>${uni.pct != null ? ` (${pctfmt(uni.pct, pctOpts)})` : ''}` : ''}.${medidor}</p>`;

    const evReg = ehPais ? [] : eventos
      .filter(e => (e.cc || 'PT') === cc && e.nivel === d.nivel && e.regiao === d.regiao)
      .sort((a, b) => b.data.localeCompare(a.data));
    const evHtml = evReg.length ? evReg.map(e => `
      <div class="reg-ev">
        <span class="dia">${diaCurto(e.data)}</span>
        <span class="ico">${ICO[e.tipo] || ''}</span>
        <span class="corpo">${frase(e)}</span>
      </div>`).join('') : '<p class="reg-vazio">Nada registado nesta região.</p>';

    const vizDisp = v => v.tem_pagina && temEventoTroca(eventos, cc, d.nivel, v.nome);
    const viz = d.vizinhos.length ? d.vizinhos.map(v => {
      if (!v.tem_pagina) return `<span>${esc(v.nome)}</span>`;
      const dp = vizDisp(v);
      return `<a class="${dp ? 'viz-disp' : ''}" href="${v.key}.html"${dp ? ' title="troca de posição no ranking desde 26 jul"' : ''}>${esc(v.nome)}</a>`;
    }).join(' ') : '<span class="reg-vazio">sem vizinhos com página</span>';
    const algumVizDisp = d.vizinhos.some(vizDisp);

    // "ver no mapa": o club.html recebe #lugar=<key>, vai buscar este mesmo
    // regioes/<key>.json e usa o `centro` (setView) e a `fronteira` (traço por
    // cima dos squares). A página de lugar não tem mapa, por isso é um <a> que
    // navega, com o mesmo alvo do botão do leaderboard (site.css, .lb-saltar).
    // País não tem centróide, logo não tem botão.
    const saltar = Array.isArray(d.centro)
      ? ` <a class="lb-saltar" href="../club.html#lugar=${encodeURIComponent(KEY)}"
           aria-label="ver ${esc(d.regiao)} no mapa do clube"></a>`
      : '';

    const temSubs = ['distrito', 'regiao', 'pais'].includes(d.nivel);
    const subSort = { k: 'uniao', dir: 'desc' };
    function renderSubs() {
      const box = document.getElementById('subs-tab');
      if (!box) return;
      box.innerHTML = tabelaSubRegioes(filhos, { linkKey: true, pctOpts, sort: subSort });
      ligarOrdenacaoSub(box.querySelector('.sr-sort'), subSort, renderSubs);
    }
    const filhosBloco = filhos && filhos.length
      ? '<div id="subs-tab"></div>'
        + `<p class="reg-viz-nota"><b>por explorar</b> = squadratinhos do lugar que
           mais ninguém do clube tem ainda. Por defeito ordenado pela cobertura do
           clube; clica num cabeçalho para ordenar por outra coluna.${d.nivel === 'distrito' ? ' A ouro: concelho com troca de posição no ranking.' : ''}</p>`
      : (temSubs ? '<p class="reg-vazio">Sem sub-regiões com actividade.</p>' : '');

    alvo.innerHTML = `
      <div class="reg-cab">
        <h1>${esc(d.regiao)}${saltar}</h1>
        <p class="sub">${rotulo(SUB, d.nivel, cc)}</p>
        <dl class="meta">
          ${paiRows}
          <dt>actualizado</dt><dd>${esc(q)}</dd>
          ${ehPais ? '' : '<dt>eventos desde</dt><dd>26 jul 2026</dd>'}
        </dl>
      </div>

      ${sec('Ranking')}
      ${rankTable}
      ${cobre}

      ${filhosBloco ? sec(rotulo(FILHOS_TIT, d.nivel, cc)) + filhosBloco : ''}

      ${ehPais ? '' : sec('Eventos') + (evReg.length ? LEGENDA_EV : '') + evHtml}

      ${sec('Faz fronteira com')}
      <div class="reg-viz">${viz}</div>
      ${algumVizDisp ? '<p class="reg-viz-nota">A ouro: vizinhos com troca de posição no ranking desde 26 jul.</p>' : ''}

      <p class="reg-rodape">
        <a class="voltar" href="index.html">todos os lugares</a><br>
        ranking e % são de <b>squadratinhos</b> (zoom 17, ~201 m). <b>únicos</b> =
        sem mais nenhum membro do clube.${medidor ? ' O medidor a seguir à % é uma escada de '
          + 'patamares (0,05% a 18%), não uma barra proporcional: quase toda a gente '
          + 'cobre menos de 1% de uma região.' : ''} Dados 6×/dia, mesmo processo que o
        <a href="../club.html">mapa do clube</a>. O
        <a href="../historico.html">histórico</a> tem o feed completo.</p>`;

    renderSubs();
  }

  async function carregar() {
    await carregarCores(mainUrl('membros_cores.json'), NC);
    let d;
    try {
      d = await carregarJson(dadosUrl(`regioes/${KEY}.json`));  // primário
    } catch (e) {
      mostrarErroDados(alvo, e);
      return;
    }
    const eventos = await carregarJson(dadosUrl('events.json'))
      .then(j => j.eventos || [])
      .catch(e => { console.warn('events.json:', e.message); return []; });

    // sub-regiões (concelhos de um distrito, zonas de uma região, distritos/
    // províncias de um país): do índice agregado, por pai_key.
    let filhos = [];
    if (['distrito', 'regiao', 'pais'].includes(NIVEL)) {
      filhos = await carregarJson(dadosUrl('regioes_index.json'))
        .then(j => (j.regioes || [])
          .filter(x => x.pai_key === KEY)
          .map(x => ({ nome: x.regiao, key: x.key, uniao: x.uniao,
                       pct: x.uniao_pct, total: x.total, lider: x.lider,
                       n: x.n, disp: x.disp }))
          .sort((a, b) => (b.uniao - a.uniao) || a.nome.localeCompare(b.nome, 'pt')))
        .catch(e => { console.warn('regioes_index.json:', e.message); return []; });
    }

    document.title = `${d.regiao} · Squadrats Club`;
    pintar(d, eventos, filhos);
  }
  carregar();
})();
