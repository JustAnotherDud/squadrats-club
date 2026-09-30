"""Perfil por atleta, data/atletas/<slug>.json, um ficheiro por atleta, com
tudo o que a página /atletas/<slug>.html mostra num só sítio.

Passo 5 do run_all.py: corre depois de squadrats.json, club.json,
club_regioes.json, daily_gains.json e stats.json já estarem escritos na mesma
corrida. NÃO varre o Squadrats, só junta e pivota o que os passos anteriores
produziram. Zero pedidos de rede.

O que entra em cada perfil (só dados que já existem hoje, ver
squadrats-multi-membro): as 8 contagens (squadrats.json), a fatia de ganhos
diários do atleta (daily_gains.json), a sobreposição de squadratinhos
(club.json), o detalhe geográfico de squadratinhos com % (club_regioes.json +
totais partilhados de stats.json) e a posição do atleta em cada região
(pivot de club_regioes.json, o mesmo que o club.html faz no browser).
"""
import datetime
import json
import os

from atletas import ATHLETES
from slugs import slug_map
from util import load_json


CAMPOS = ["squadrats", "squadratinhos", "yard", "yardinho",
          "ubersquadrat", "ubersquadratinho"]

# nivel do perfil -> par de buckets de stats.json (PT / estrangeiro), a mesma
# correspondência que o club.html usa em bucketDe()/linhasGeo()
NIVEIS = {
    "pais": None,
    "regiao": ("by_distrito", "by_region"),
    "zona": ("by_concelho", "by_municipio"),
}


def _carregar(out_dir, nome):
    with open(os.path.join(out_dir, nome), encoding="utf-8") as f:
        return json.load(f)


def _total_stats(stats, bucket, nome=None):
    """z17.total de um bucket de stats.json. `pais` é plano (country_pt.z17.total,
    sem nome lá dentro); os outros são nome -> zoom -> total. None se não houver."""
    if not stats:
        return None
    no = stats.get(bucket)
    if no is None:
        return None
    if nome is not None:
        no = no.get(nome)
        if no is None:
            return None
    z17 = no.get("z17")
    return z17.get("total") if z17 else None


def _pct(captured, total):
    if not total:
        return None
    return round(100 * captured / total, 2)


def _geo_atleta(geo_nome, stats):
    """{pais: [...], regiao: [...], zona: [...]}, cada linha
    {cc, nome, captured, total, pct}, ordenada por captured desc."""
    if not geo_nome:
        return {"pais": [], "regiao": [], "zona": []}

    pais = []
    for cc, captured in (geo_nome.get("country") or {}).items():
        total = _total_stats(stats, f"country_{cc.lower()}")
        pais.append({"cc": cc, "nome": cc, "captured": captured,
                     "total": total, "pct": _pct(captured, total)})
    pais.sort(key=lambda r: -r["captured"])

    def nivel(pt_key, foreign_base, pt_bucket, foreign_bucket_base):
        linhas = []
        for nm, captured in (geo_nome.get(pt_key) or {}).items():
            total = _total_stats(stats, pt_bucket, nm)
            linhas.append({"cc": "PT", "nome": nm, "captured": captured,
                           "total": total, "pct": _pct(captured, total)})
        for cc, por_nome in (geo_nome.get(foreign_base) or {}).items():
            for nm, captured in por_nome.items():
                total = _total_stats(stats, f"{foreign_bucket_base}_{cc.lower()}", nm)
                linhas.append({"cc": cc.upper(), "nome": nm, "captured": captured,
                               "total": total, "pct": _pct(captured, total)})
        linhas.sort(key=lambda r: -r["captured"])
        return linhas

    return {
        "pais": pais,
        "regiao": nivel("by_distrito", "by_region", "by_distrito", "by_region"),
        "zona": nivel("by_concelho", "by_municipio", "by_concelho", "by_municipio"),
    }


def _pivot_ranking(regioes_atletas):
    """{nivel: {chave: [(nome, captured), ...] ordenado desc}}, o mesmo pivot
    (por região -> por atleta) que o club.html faz em pivotRegioes()."""
    saida = {n: {} for n in NIVEIS}
    for nome, geo in regioes_atletas.items():
        # país
        for cc, captured in (geo.get("country") or {}).items():
            saida["pais"].setdefault(cc, {"cc": cc, "nome": cc, "e": []})
            saida["pais"][cc]["e"].append((nome, captured))
        # região / zona
        for nivel, (pt_key, foreign_key) in (
            ("regiao", ("by_distrito", "by_region")),
            ("zona", ("by_concelho", "by_municipio")),
        ):
            for nm, captured in (geo.get(pt_key) or {}).items():
                chave = f"PT|{nm}"
                saida[nivel].setdefault(chave, {"cc": "PT", "nome": nm, "e": []})
                saida[nivel][chave]["e"].append((nome, captured))
            for cc, por_nome in (geo.get(foreign_key) or {}).items():
                for nm, captured in por_nome.items():
                    chave = f"{cc.upper()}|{nm}"
                    saida[nivel].setdefault(chave, {"cc": cc.upper(), "nome": nm, "e": []})
                    saida[nivel][chave]["e"].append((nome, captured))
    for nivel in saida:
        for reg in saida[nivel].values():
            reg["e"].sort(key=lambda t: -t[1])
    return saida


def _merge_geo(nome, geo_nome, stats, pivot):
    """Uma tabela por nível (país/região/zona) que junta, para cada divisão
    onde o atleta tem squares: capturado + total + % (de `_geo_atleta`) com a
    posição dele e a folga para as posições adjacentes (do pivot).

    `acima` = capturado de quem está uma posição à frente (None se o atleta é
    1º); `abaixo` = capturado de quem está uma posição atrás (None se é
    último). O frontend transforma isto em "−N para subir" / "+N de folga".
    """
    base = _geo_atleta(geo_nome, stats)
    saida = {}
    for nivel, linhas in base.items():
        merged = []
        for r in linhas:
            chave = r["cc"] if nivel == "pais" else f"{r['cc']}|{r['nome']}"
            reg = pivot.get(nivel, {}).get(chave)
            pos, de, acima, abaixo = 1, 1, None, None
            if reg:
                nomes = [n for n, _ in reg["e"]]
                if nome in nomes:
                    i = nomes.index(nome)
                    pos, de = i + 1, len(reg["e"])
                    acima = reg["e"][i - 1][1] if i > 0 else None
                    abaixo = reg["e"][i + 1][1] if i + 1 < de else None
            merged.append({**r, "posicao": pos, "de": de,
                           "acima": acima, "abaixo": abaixo, "disputada": de >= 2})
        saida[nivel] = merged
    return saida


def main(out_dir):
    squadrats = _carregar(out_dir, "squadrats.json")
    club = load_json(os.path.join(out_dir, "club.json")) or {"atletas": []}
    regioes = load_json(os.path.join(out_dir, "club_regioes.json")) or {"atletas": {}}
    ganhos = load_json(os.path.join(out_dir, "daily_gains.json")) or {"dias": []}
    gains_reg = load_json(os.path.join(out_dir, "gains_regioes.json")) or {"dias": []}
    stats = load_json(os.path.join(out_dir, "stats.json"))

    # {data: {nome: {"concelho": {...}, "distrito": {...}}}}, drill-down da
    # coluna Squadratinhos na tabela de ganhos diários (só z17)
    gr_por_dia = {d["data"]: d.get("atletas", {}) for d in gains_reg.get("dias", [])}

    slugs = slug_map(ATHLETES.keys())
    sobrep = {a["nome"]: a for a in club.get("atletas", [])}
    pivot = _pivot_ranking(regioes.get("atletas", {}))

    destino = os.path.join(out_dir, "atletas")
    os.makedirs(destino, exist_ok=True)

    gerado = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    indice = []

    for nome, uid in ATHLETES.items():
        slug = slugs[nome]
        totais = {c: (squadrats.get("atletas", {}).get(nome, {}).get(c, 0)) for c in CAMPOS}

        # só os CAMPOS actuais, dias antigos podem trazer métricas já removidas
        # (ex. backyardinhos, tirado em 2026-09-04); um dia que só tivesse
        # dessas deixa de contar como ganho.
        dias_atleta = []
        for d in ganhos.get("dias", []):
            g = {c: v for c, v in d.get("atletas", {}).get(nome, {}).items() if c in CAMPOS}
            if not g:
                continue
            entrada = {"data": d["data"], **g}
            reg = gr_por_dia.get(d["data"], {}).get(nome)
            if reg and g.get("squadratinhos", 0) > 0:
                entrada["regioes"] = reg  # {"concelho": {reg: n}, "distrito": {reg: n}}
            dias_atleta.append(entrada)

        s = sobrep.get(nome)
        sobreposicao = None
        if s:
            sobreposicao = {
                "total": s.get("total", 0),
                "exclusivos": s.get("exclusivos", 0),
                "partilhados": s.get("partilhados", 0),
            }

        perfil = {
            "slug": slug,
            "nome": nome,
            "uid": uid,
            "atualizado": squadrats.get("atualizado", gerado),
            "gerado": gerado,
            "totais": totais,
            "sobreposicao": sobreposicao,
            "ganhos_diarios": dias_atleta,
            "geo": _merge_geo(nome, regioes.get("atletas", {}).get(nome), stats, pivot),
        }

        caminho = os.path.join(destino, f"{slug}.json")
        with open(caminho, "w", encoding="utf-8") as f:
            json.dump(perfil, f, ensure_ascii=False, separators=(",", ":"))
        print(f"{nome} -> {caminho}")
        indice.append({"slug": slug, "nome": nome})

    # ordem = ordem de ATHLETES (a mesma dos bits/cores)
    idx_path = os.path.join(destino, "index.json")
    with open(idx_path, "w", encoding="utf-8") as f:
        json.dump({"gerado": gerado, "atletas": indice}, f, ensure_ascii=False, separators=(",", ":"))
    print(f"índice -> {idx_path}")
