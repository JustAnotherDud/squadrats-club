"""Ganhos diários de squadratinhos por concelho/distrito, por atleta,
data/gains_regioes.json. Alimenta o drill-down da tabela "Ganhos diários"
nos perfis (atletas/<slug>.html): clicar num "+N" da coluna Squadratinhos
mostra em que regiões caíram.

Só z17: o club.json é z17, portanto só a coluna Squadratinhos tem "onde".

Consumido por:
  - append_gains_regioes.py    (passo do run_all.py, diff de dois snapshots
    consecutivos de club_regioes.json, sem classificação nova)
  - build_profiles.py          (fatia por atleta para dentro de cada perfil)

O ganho por região de um dia é a subtracção de dois snapshots cumulativos
(hoje - ontem), por (atleta, nivel, regiao). Só ganhos positivos entram,
uma perda (re-scan a corrigir) não é um "ganho do dia".
"""
import json
import os

DESDE = "2026-07-26"  # 1.º dia de squadrats.json / daily_gains.json
NIVEIS = ("concelho", "distrito")
_BUCKET = {"concelho": "by_concelho", "distrito": "by_distrito"}


def _diff_bucket(b0, b1):
    """{chave: ganho>0} entre dois dicionários {chave: cumulativo}."""
    fora = {}
    for k, v in (b1 or {}).items():
        d = v - (b0 or {}).get(k, 0)
        if d > 0:
            fora[k] = d
    return fora


def diff_snapshots(ant, novo):
    """{nome: {"concelho": {reg: ganho}, "distrito": {reg: ganho},
    "pais": {cc: ganho}}}, só entradas com ganho > 0. `pais` é só o
    estrangeiro (exclui PT), para dar nome ao resíduo do drill-down; vem do
    bucket `country` do club_regioes.json ou de `by_pais` (snapshots
    reconstruídos antes de 15 ago).

    Atleta ausente em `ant` (1.ª aparição) não gera ganho, o total dele
    inteiro apareceria como um pico. Mesmo critério do daily_gains.py."""
    ant_at = (ant or {}).get("atletas", {}) or {}
    fora = {}
    for nome, info in (novo or {}).get("atletas", {}).items():
        if nome not in ant_at:
            continue
        base = ant_at[nome] or {}
        por_nivel = {}
        for nivel in NIVEIS:
            ganhos = _diff_bucket(base.get(_BUCKET[nivel]), info.get(_BUCKET[nivel]))
            if ganhos:
                por_nivel[nivel] = ganhos
        pais = _diff_bucket(base.get("country") or base.get("by_pais"),
                            info.get("country") or info.get("by_pais"))
        pais.pop("PT", None)
        if pais:
            por_nivel["pais"] = pais
        if por_nivel:
            fora[nome] = por_nivel
    return fora


def carregar(out_dir):
    path = os.path.join(out_dir, "gains_regioes.json")
    try:
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"gerado": None, "desde": DESDE, "dias": []}
    d.setdefault("dias", [])
    return d


def escrever(out_dir, dias, gerado):
    """`dias`: lista [{"data": "AAAA-MM-DD", "atletas": {nome: {...}}}, ...].
    Reordena por data e grava."""
    dias = sorted((x for x in dias if x.get("atletas")), key=lambda x: x["data"])
    path = os.path.join(out_dir, "gains_regioes.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"gerado": gerado, "desde": DESDE, "dias": dias},
                  f, ensure_ascii=False, separators=(",", ":"))
    return path
