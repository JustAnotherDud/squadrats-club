// Perfil de atleta, lê data/atletas/<slug>.json (branch `data`) e desenha
// tudo numa página só. Sem Leaflet, sem dependências além do shared.js
// (bandeiras, PAIS_NOME, NIVEL_LABEL). O build (pipeline/build_profiles.py)
// já juntou e pivotou os dados; aqui é só render.
//
// Duas entradas: #perfil[data-slug] (um atleta) e #perfil-indice (a lista,
// que só precisa das cores).

(function () {
  'use strict';

  // dadosUrl / mainUrl / NC / carregarJson / mostrarErroDados /
  // avisoDadosVelhos: shared.js

  const BANDEIRA = bandeiras(15, 11); // shared.js
  const NIVEL_NOME = {
    pais: NIVEL_LABEL.pais, regiao: NIVEL_LABEL.regiao, zona: NIVEL_LABEL.zona,
  };
  const NIVEL_ORDEM = ['pais', 'regiao', 'zona'];

  // linha de cima = grelha squadrats (1609 m); linha de baixo = squadratinhos
  // (201 m). A grelha do CSS é 3 por linha, por isso a ordem aqui é a ordem
  // visual: os 3 "grandes" primeiro, os 3 "-inhos" a seguir.
  const METRICAS = [
    ['squadrats', 'Squadrats', 'Nº de squares de 1609 m visitados.'],
    ['yard', 'Yard', 'Nº de squares do maior cluster fechado, cada square com os 4 vizinhos também visitados.'],
    ['ubersquadrat', 'Übersquadrat', 'Lado do maior quadrado NxN totalmente preenchido, em squadrats.'],
    ['squadratinhos', 'Squadratinhos', 'Nº de squares de 201 m visitados.'],
    ['yardinho', 'Yardinho', 'Igual ao Yard, na grelha fina dos squadratinhos.'],
    ['ubersquadratinho', 'Übersquadratinho', 'Lado do maior quadrado NxN totalmente preenchido, em squadratinhos.'],
  ];

  // Países com página própria em lugares/pais-<cc>.html. Só se linka os que
  // existem, tal como as regiões/zonas.
  const PAIS_COM_PAGINA = new Set(['PT', 'ES', 'DE', 'MA']);

  // Ganhos diários: quantos dias mostrar antes do "mostrar todos". O sparkline
  // por cima continua a cobrir o período todo.
  const GANHOS_INICIAIS = 8;

  // esc / nfmt / cor / carregarCores / CORES: shared.js.
  const paisNome = cc => PAIS_NOME[cc] || cc;
  const flag = cc => BANDEIRA[cc] || '';

  // ---------- índice ----------
  async function renderIndice() {
    await carregarCores(mainUrl('membros_cores.json'), NC);  // funde membros_cores.json em CORES
    INDICE.querySelectorAll('.perfil-cor').forEach(el => {
      el.style.background = cor(el.dataset.nome);
    });
  }

  // ---------- perfil ----------
  const alvo = document.getElementById('perfil');
  const INDICE = document.getElementById('perfil-indice');

  let SEC_N = 0;
  function seccao(titulo, corpoHtml) {
    return `<section class="perfil-seccao"><div class="sec">`
      + `<span class="n">${String(++SEC_N).padStart(2, '0')}</span>`
      + `<span class="t">${esc(titulo)}</span></div>${corpoHtml}</section>`;
  }

  function blocoTotais(totais) {
    const cards = METRICAS.map(([k, rotulo, tip]) => `
      <div class="perfil-num">
        <div class="v">${nfmt(totais[k])}</div>
        <div class="k" data-tip="${esc(tip)}" tabindex="0">${esc(rotulo)}</div>
      </div>`).join('');
    return `<div class="perfil-grid">${cards}</div>`;
  }

  function blocoSobreposicao(s, cor) {
    if (!s || !s.total) {
      return '<p class="perfil-vazio">Sem conta Squadrats ou sem squadratinhos capturados.</p>';
    }
    const ex = s.exclusivos, pa = s.partilhados, tot = s.total;
    const pex = (100 * ex / tot).toFixed(0), ppa = (100 * pa / tot).toFixed(0);
    return `<div class="perfil-barra">
      <div class="perfil-barra-faixa">
        <i style="width:${pex}%;background:${cor || '#7d8598'}"></i>
        <i style="width:${ppa}%;background:#4a5568"></i>
      </div>
      <div class="perfil-barra-legenda">
        <span class="p"><span class="tile" style="background:${cor || '#7d8598'}"></span>
          só deste atleta <b>${nfmt(ex)}</b> (${pex}%)</span>
        <span class="p"><span class="tile" style="background:#4a5568"></span>
          partilhados <b>${nfmt(pa)}</b> (${ppa}%)</span>
        <span class="p">total <b>${nfmt(tot)}</b></span>
      </div>
    </div>`;
  }

  // Tabela geográfica de squadratinhos: uma coluna por dado, todas ordenáveis,
  // todas as divisões de uma vez (sem "mostrar mais", o scroll da página trata).
  // acima = capturado de quem está uma posição à FRENTE (falta para subir);
  // abaixo = capturado de quem está uma posição ATRÁS (folga que se tem).
  const COLS = [
    { k: 'divisao', label: 'Divisão', num: false, val: r => r.cc === r.nome ? paisNome(r.cc) : r.nome },
    { k: 'captured', label: 'Capturados', num: true, val: r => r.captured },
    { k: 'total', label: 'Total', num: true, val: r => r.total },
    { k: 'pct', label: '%', num: true, val: r => r.pct },
    { k: 'posicao', label: 'Posição', num: true, val: r => r.posicao },
    // squares que faltam para passar a posição de cima (null = já é 1º)
    { k: 'subir', label: 'Subir', num: true, val: r => r.acima != null ? r.acima - r.captured : null },
    // quanto está à frente da posição de baixo (null = já é último)
    { k: 'folga', label: 'Folga', num: true, val: r => r.abaixo != null ? r.captured - r.abaixo : null },
  ];

  function ordenar(linhas, sort) {
    const col = COLS.find(c => c.k === sort.k) || COLS[1];
    const dir = sort.dir === 'asc' ? 1 : -1;
    return [...linhas].sort((a, b) => {
      let va = col.val(a), vb = col.val(b);
      if (col.num) {
        va = va == null ? -Infinity : va;
        vb = vb == null ? -Infinity : vb;
        return (va - vb) * dir;
      }
      return String(va).localeCompare(String(vb), 'pt') * dir;
    });
  }

  // Placeholder "·": visualmente um ponto, mas com nome para leitor de ecrã.
  // O "·" em si fica aria-hidden; o <span.sr-only> leva o significado.
  const vazio = sr => `<span class="sr-only">${sr}</span><span class="fraco" aria-hidden="true">·</span>`;

  function linhaGeo(r, nivel) {
    const ehPais = r.cc === r.nome;
    const txt = ehPais ? paisNome(r.cc) : esc(r.nome);
    // em PT o nível chama-se distrito/concelho, no estrangeiro regiao/zona
    const hrefNivel = r.cc === 'PT'
      ? (nivel === 'regiao' ? 'distrito' : 'concelho')
      : nivel;
    const nome = (nivel === 'regiao' || nivel === 'zona') && !ehPais
      ? `<a href="../${regiaoHref(hrefNivel, r.nome, r.cc)}">${txt}</a>`
      : (ehPais && PAIS_COM_PAGINA.has(r.cc))
        ? `<a href="../lugares/pais-${r.cc.toLowerCase()}.html">${txt}</a>`
        : txt;
    const cls = r.posicao <= 3 && r.de > 1 ? ` p${r.posicao}` : '';
    const subir = r.acima != null
      ? `<span class="mg-neg">${nfmt(r.acima - r.captured)}</span>` : vazio('já lidera');
    const folga = r.abaixo != null
      ? `<span class="mg-pos">${nfmt(r.captured - r.abaixo)}</span>` : vazio('sem ninguém atrás');
    return `<tr>
      <td><span class="nome">${flag(r.cc)}<span>${nome}</span></span></td>
      <td class="n"><b>${nfmt(r.captured)}</b></td>
      <td class="n fraco">${r.total != null ? nfmt(r.total) : vazio('sem dados')}</td>
      <td class="n">${r.pct != null ? r.pct.toFixed(1) + '%' : vazio('sem dados')}</td>
      <td class="n"><span class="perfil-pos${cls}">${r.posicao}º</span><span class="fraco"> / ${r.de}</span></td>
      <td class="n mg">${subir}</td>
      <td class="n mg">${folga}</td>
    </tr>`;
  }

  function tabelaGeo(nivel, linhas, sort) {
    if (!linhas.length) return '<p class="perfil-vazio">Sem squares neste nível.</p>';
    const ord = ordenar(linhas, sort);
    const cabecas = COLS.map(c => {
      const activa = c.k === sort.k;
      const seta = activa ? (sort.dir === 'asc' ? ' ▲' : ' ▼') : '';
      return `<th data-sort="${c.k}"${activa ? ' class="ord"' : ''}>${c.label}${seta}</th>`;
    }).join('');
    return `<div class="perfil-scroll"><table class="perfil-tabela geo">
      <thead><tr>${cabecas}</tr></thead>
      <tbody>${ord.map(r => linhaGeo(r, nivel)).join('')}</tbody>
    </table></div>`;
  }

  function blocoGeo(geo, soDisputadas, sort) {
    const btn = `<button class="perfil-toggle${soDisputadas ? ' on' : ''}" data-geo-filtro>Só disputadas (2+)</button>`;
    const corpo = NIVEL_ORDEM.map(nivel => {
      let linhas = geo[nivel] || [];
      if (soDisputadas) linhas = linhas.filter(r => r.disputada);
      return `<h3 class="perfil-nivel">${esc(NIVEL_NOME[nivel])}</h3>${tabelaGeo(nivel, linhas, sort)}`;
    }).join('');
    return btn + corpo;
  }

  function blocoSpark(dias) {
    const vals = (dias || []).map(d => ({ data: d.data, v: d.squadratinhos || 0 }));
    if (!vals.length || vals.every(d => !d.v)) return '';
    const w = 600, h = 90, pad = 14;
    const max = Math.max(...vals.map(d => d.v), 1);
    const bw = (w - pad * 2) / vals.length;
    const barras = vals.map((d, i) => {
      const bh = (h - pad * 2) * d.v / max;
      const x = pad + i * bw;
      return `<rect x="${x.toFixed(1)}" y="${(h - pad - bh).toFixed(1)}"
        width="${Math.max(bw - 1.5, 1).toFixed(1)}" height="${bh.toFixed(1)}">
        <title>${fmtData(d.data)}: +${d.v} squadratinhos</title></rect>`;
    }).join('');
    const primeiro = fmtData(vals[0].data), ultimo = fmtData(vals[vals.length - 1].data);
    return `<svg class="perfil-spark" viewBox="0 0 ${w} ${h}" preserveAspectRatio="none">
      ${barras}
      <text x="${pad}" y="${h - 2}">${primeiro}</text>
      <text x="${w - pad}" y="${h - 2}" text-anchor="end">${ultimo}</text>
    </svg>`;
  }

  // Detalhe de um "+N" de Squadratinhos: onde caíram. Distrito primeiro (chips
  // ligados à página da região), concelhos na linha muda por baixo. O
  // estrangeiro não tem página, aparece por nome de país (span tracejado).
  // Só z17, o club.json é z17, por isso é a única coluna com "onde".
  function ganhoDetalhe(reg, total) {
    const ord = o => Object.entries(o || {}).sort((a, b) => b[1] - a[1]);
    const conc = ord(reg.concelho), dist = ord(reg.distrito), pais = ord(reg.pais);
    const soma = a => a.reduce((s, [, n]) => s + n, 0);
    const resid = total - soma(dist) - soma(pais);
    const chip = (nivel, nome, n) =>
      `<a class="gan-chip" href="../${regiaoHref(nivel, nome)}">${esc(nome)} <b>+${n}</b></a>`;
    let h = `<div class="gan-linha">${dist.map(([nome, n]) => chip('distrito', nome, n)).join('')}`;
    h += pais.map(([cc, n]) => `<span class="gan-pais">${esc(paisNome(cc))} <b>+${n}</b></span>`).join('');
    if (resid > 0) h += `<span class="gan-resid">+${resid} sem classificação</span>`;
    h += '</div>';
    if (conc.length) {
      h += `<div class="gan-linha gan-sub">concelhos: ${conc.map(([nome, n]) => chip('concelho', nome, n)).join('')}</div>`;
    }
    return h;
  }

  function blocoGanhos(dias, estado) {
    if (!dias || !dias.length) {
      return '<p class="perfil-vazio">Sem ganhos registados desde que o registo diário começou.</p>';
    }
    // sempre as 6 métricas, na mesma ordem das Contagens; uma métrica sem
    // ganho nesse dia fica com a célula vazia (a grelha já diz que existe),
    // o que acontece quase sempre com Yard/Über
    const cab = METRICAS.map(m => `<th>${esc(m[1])}</th>`).join('');
    const campos = METRICAS.map(m => m[0]);
    const ncols = 1 + METRICAS.length;
    // colapsada por defeito: só os primeiros GANHOS_INICIAIS dias, o resto
    // atrás de um botão. O sparkline por cima mantém o período todo.
    const todos = [...dias].reverse().slice(0, 30);
    const limite = estado.ganhosExpandido ? todos.length : GANHOS_INICIAIS;
    const linhas = todos.slice(0, limite).map(d => {
      const aberto = estado.ganhoAberto === d.data;
      const temDetalhe = d.regioes && (d.squadratinhos || 0) > 0;
      const celulas = campos.map(c => {
        const v = d[c] || 0;
        if (c === 'squadratinhos' && temDetalhe) {
          // caret à frente do número: assim o "+N" fica na aresta direita, a
          // alinhar com o cabeçalho e com as outras colunas
          return `<td class="n gan-z${aberto ? ' aberto' : ''}" data-dia="${esc(d.data)}">
            <button class="gan-btn" type="button" aria-expanded="${aberto}"
              aria-label="+${v} squadratinhos em ${fmtData(d.data)}, ver onde">
              <span class="gan-caret" aria-hidden="true">▸</span>+${v}</button></td>`;
        }
        return `<td class="n">${v > 0 ? '+' + v : (v < 0 ? v : '')}</td>`;
      }).join('');
      const detalhe = aberto && temDetalhe
        ? `<tr class="gan-det"><td colspan="${ncols}">${ganhoDetalhe(d.regioes, d.squadratinhos)}</td></tr>`
        : '';
      // dia/mês/ano cada um no seu span de largura fixa: dia à direita, mês e
      // ano à esquerda -> "8 set 2026" e "21 ago 2026" alinham em 3 colunas
      const [dnum, dmes, dano] = fmtData(d.data).split(' ');
      return `<tr><td class="gan-dia"><span class="d-num">${esc(dnum)}</span>` +
        `<span class="d-mes">${esc(dmes)}</span><span class="d-ano">${esc(dano)}</span></td>` +
        `${celulas}</tr>${detalhe}`;
    }).join('');
    const escondidos = todos.length - GANHOS_INICIAIS;
    const maisBtn = escondidos > 0
      ? `<button class="perfil-toggle perfil-mais" data-ganhos-mais>${estado.ganhosExpandido
          ? 'Mostrar menos' : `Mostrar os outros ${escondidos} dias`}</button>`
      : '';
    return blocoSpark(dias) + `<div class="perfil-scroll"><table class="perfil-tabela">
      <thead><tr><th>Dia</th>${cab}</tr></thead><tbody>${linhas}</tbody></table></div>` + maisBtn;
  }

  function pintar(d, cor) {
    const mapaUrl = `https://squadrats.com/map/${encodeURIComponent(d.uid)}/17`;
    const quando = fmtDataHora(d.atualizado);
    avisoDadosVelhos(d.atualizado);  // shared.js
    let estado = {
      soDisputadas: false, sort: { k: 'captured', dir: 'desc' },
      ganhoAberto: null, ganhosExpandido: false,
    };

    function desenhar() {
      SEC_N = 0;
      alvo.innerHTML = `
        <div class="perfil-cabeca">
          <span class="perfil-cor tile" style="background:${cor || 'var(--tinta-2)'}"></span>
          <h1>${esc(d.nome)}</h1>
        </div>
        <dl class="meta">
          <dt>actualizado</dt><dd>${esc(quando)}</dd>
          <dt>mapa</dt><dd><a href="${mapaUrl}" target="_blank" rel="noopener">squadrats.com</a></dd>
        </dl>

        ${seccao('Contagens', blocoTotais(d.totais || {}))}
        ${seccao('Sobreposição de squadratinhos', blocoSobreposicao(d.sobreposicao, cor))}
        ${seccao('Ganhos diários', blocoGanhos(d.ganhos_diarios, estado))}
        ${seccao('Squadratinhos', blocoGeo(d.geo || {}, estado.soDisputadas, estado.sort))}

        <p class="perfil-nota">
          Só <b>squadratinhos</b> (zoom 17, ~201 m): na grelha dos squadrats os quadrados
          são grandes demais para a comparação dizer alguma coisa. <b>Capturados</b> pelo atleta,
          <b>Total</b> da divisão (o mesmo para toda a gente). <b>Posição</b> = ranking por squares
          capturados dentro da divisão. <b class="mg-neg">Subir</b> = squares que
          faltam para passar a posição de cima; <b class="mg-pos">Folga</b> = quanto
          está à frente da posição de baixo. Clica num cabeçalho para ordenar.
          Dados actualizados 6×/dia.
        </p>`;

      alvo.querySelectorAll('.perfil-tabela.geo th[data-sort]').forEach(th => {
        th.onclick = () => {
          const k = th.dataset.sort;
          if (estado.sort.k === k) {
            estado.sort.dir = estado.sort.dir === 'asc' ? 'desc' : 'asc';
          } else {
            // "mais é melhor" arranca em desc; divisão/posição/subir em asc
            estado.sort = { k, dir: ['captured', 'total', 'pct', 'folga'].includes(k) ? 'desc' : 'asc' };
          }
          desenhar();
        };
      });
      const filtro = alvo.querySelector('[data-geo-filtro]');
      if (filtro) filtro.onclick = () => {
        estado.soDisputadas = !estado.soDisputadas;
        desenhar();
      };
      const ganhosMais = alvo.querySelector('[data-ganhos-mais]');
      if (ganhosMais) ganhosMais.onclick = () => {
        estado.ganhosExpandido = !estado.ganhosExpandido;
        desenhar();
      };
      alvo.querySelectorAll('.gan-z[data-dia] .gan-btn').forEach(btn => {
        btn.onclick = () => {
          const dia = btn.closest('.gan-z').dataset.dia;
          estado.ganhoAberto = estado.ganhoAberto === dia ? null : dia;
          desenhar();
        };
      });
    }
    desenhar();
  }

  async function renderPerfil() {
    const slug = alvo.dataset.slug;
    await carregarCores(mainUrl('membros_cores.json'), NC);
    let dados;
    try {
      dados = await carregarJson(dadosUrl('atletas/' + encodeURIComponent(slug) + '.json'));
    } catch (e) {
      mostrarErroDados(alvo, e);
      return;
    }
    document.title = `${dados.nome} · Squadrats Club`;
    pintar(dados, cor(dados.nome));
  }

  if (alvo && alvo.dataset.slug) renderPerfil();
  else if (INDICE) renderIndice();
})();
