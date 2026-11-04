"""Render das frases do historico.html (fraseEvento / icoEvento / eventoDe do
shared.js), corrido em node. Salta se não houver node."""
import json
import os
import re
import shutil
import subprocess

import pytest

RAIZ = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="sem node")

JS = r"""
const fs = require('fs'), vm = require('vm');
const ctx = { location: { pathname: '/', hostname: 'x' }, document: {} };
vm.createContext(ctx);
vm.runInContext(fs.readFileSync(process.argv[1], 'utf8') + `
;globalThis.out = (entradas) => entradas.map(e => ({
  frase: fraseEvento(e, { atleta: n => n, regiao: (nivel, r) => r }),
  fraseLocal: fraseEvento(e, { atleta: n => n, regiao: null }),
  ico: icoEvento(e),
  de: ['Zé', 'Pedro', 'Xeira'].filter(a => eventoDe(e, a)),
}));`, ctx);
const entradas = JSON.parse(fs.readFileSync(0, 'utf8'));
process.stdout.write(JSON.stringify(ctx.out(entradas)));
"""


def _render(entradas):
    r = subprocess.run(["node", "-e", JS, os.path.join(RAIZ, "shared.js")],
                       input=json.dumps(entradas), capture_output=True, text=True, check=True)
    out = json.loads(r.stdout)
    for o in out:  # texto simples: sem etiquetas
        o["frase"] = re.sub(r"<[^>]+>", "", o["frase"])
        o["fraseLocal"] = re.sub(r"<[^>]+>", "", o["fraseLocal"])
    return out


def _e(regiao, partes, contagem, quem="Zé", nivel="concelho"):
    return {"data": "2026-11-04", "nivel": nivel, "cc": "PT", "regiao": regiao,
            "quem": quem, "partes": partes, "contagem": contagem}


EST = {"tipo": "primeira_presenca"}
M = lambda n: {"tipo": "marco", "valores": [n]}
ULTRA = lambda sobre, vals: {"tipo": "ultrapassagem", "sobre": sobre, "valores": vals}
LIDER = lambda sobre, v: {"tipo": "novo_lider", "sobre": sobre, "valores": [v]}


def test_frases_do_04_nov():
    out = _render([
        _e("Matosinhos", [EST, M(25), ULTRA(["Pedro"], [12])], 26),
        _e("Maia", [EST, M(25)], 44),
        _e("Porto", [M(100)], 125, nivel="distrito"),
    ])
    assert [o["frase"] for o in out] == [
        "Zé estreou-se em Matosinhos, passou os 25 e superou o Pedro (26 vs 12)",
        "Zé estreou-se em Maia e passou os 25, agora 44",
        "Zé passou os 100 em Porto, agora 125",
    ]


def test_varios_superados_e_artigos():
    (o,) = _render([_e("Arouca", [ULTRA(["Pedro", "Carolina"], [20, 15])], 22)])
    # y = o superado com mais squadratinhos no fim do dia (o rival mais próximo)
    assert o["frase"] == "Zé superou o Pedro e a Carolina em Arouca (22 vs 20)"
    (o,) = _render([_e("Arouca", [M(25), ULTRA(["Xeira", "Pedro"], [21, 20])], 22)])
    assert o["frase"] == "Zé passou os 25 em Arouca e superou o Xeira e o Pedro (22 vs 21)"


def test_novo_lider_conta_com_o_ex_lider_e_regiao_uma_vez():
    out = _render([
        _e("Gaia", [M(50), ULTRA(["Xeira"], [40]), LIDER("Carolina", 45)], 60),
        _e("Gaia", [LIDER("Pedro", 30)], 60),
        _e("Gaia", [EST], 3),
    ])
    assert out[0]["frase"] == \
        "Zé passou os 50 em Gaia, superou o Xeira e tirou a liderança à Carolina (60 vs 45)"
    assert out[1]["frase"] == "Zé tirou a liderança ao Pedro em Gaia (60 vs 30)"
    assert out[2]["frase"] == "Zé estreou-se em Gaia com 3"
    assert out[0]["frase"].count("Gaia") == 1


def test_pagina_da_regiao_nao_repete_o_nome():
    (o,) = _render([_e("Maia", [EST, M(25)], 44)])
    assert o["fraseLocal"] == "Zé estreou-se aqui e passou os 25, agora 44"
    (o,) = _render([_e("Maia", [EST], 3)])
    assert o["fraseLocal"] == "Zé estreou-se aqui com 3"
    (o,) = _render([_e("Porto", [M(100)], 125)])
    assert o["fraseLocal"] == "Zé passou os 100, agora 125"


def test_icone_da_parte_mais_forte():
    out = _render([
        _e("A", [EST, M(25), ULTRA(["Pedro"], [1]), LIDER("Xeira", 2)], 9),
        _e("A", [EST, M(25), ULTRA(["Pedro"], [1])], 9),
        _e("A", [EST, M(25)], 9),
        _e("A", [EST], 9),
    ])
    assert [o["ico"] for o in out] == ["👑", "⇅", "🚩", "📍"]


def test_filtro_por_atleta_apanha_quem_e_sobre():
    out = _render([
        _e("A", [ULTRA(["Pedro", "Xeira"], [1, 1])], 9),
        _e("B", [LIDER("Pedro", 2)], 9),
        _e("C", [M(25)], 9, quem="Pedro"),
    ])
    assert [o["de"] for o in out] == [["Zé", "Pedro", "Xeira"], ["Zé", "Pedro"], ["Pedro"]]
