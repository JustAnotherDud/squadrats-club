"""Lógica partilhada das páginas de lugar (PT, estrangeiro e país).

Consumido por:
  - append_regioes.py    (passo do run_all.py: reescreve o estado actual de
                          cada região activa, idempotente)
  - gen_lugar_stubs.py   (escreve lugares/<key>.html a partir de data/regioes/)

Cada lugar com actividade tem um ficheiro data/regioes/<key>.json (ver
key_de). O slug é o de slugs.slugify, igual ao slugify do shared.js.
"""
import json
import os

from eventos import ATLETAS_ORDEM  # ordem canónica (bits/cores); fonte única
from slugs import slugify

NIVEIS = ("concelho", "distrito")
CHAVE_BUCKET = {"concelho": "by_concelho", "distrito": "by_distrito"}
CHAVE_ADJ = {"concelho": "concelhos", "distrito": "distritos"}
CHAVE_STATS = {"concelho": "by_concelho", "distrito": "by_distrito"}

# estrangeiro: nível 2 = "regiao" (província/Land/région), nível 3 = "zona"
# (município/cercle). bucket no club_regioes por atleta e na uniao; bucket de
# adjacência (compute_adjacency.py); os totais do stats.json são by_region_<cc>
# / by_municipio_<cc>. AD só tem paróquias (7), servem de nível 2 e 3.
BUCKET_ATLETA_ESTR = {"regiao": "by_region", "zona": "by_municipio"}
ADJ_REGIAO = {"es": "provincias_es", "de": "laender_de", "ma": "regioes_ma", "ad": "paroquias_ad"}
ADJ_ZONA = {"es": "municipios_es", "de": "municipios_de", "ma": "municipios_ma", "ad": "paroquias_ad"}

# nome do país para o campo `regiao` da página de país, pai_nome/avo_nome e o
# nome dos vizinhos-país. Os com actividade (PT + by_pais) mais os que possam
# aparecer como vizinhos em adjacency['paises'] (nomes pt, ver shared.js).
PAIS_NOME = {
    "PT": "Portugal", "ES": "Espanha", "AD": "Andorra", "DE": "Alemanha",
    "MA": "Marrocos", "FR": "França", "AT": "Áustria", "BE": "Bélgica",
    "CH": "Suíça", "CZ": "Chéquia", "DK": "Dinamarca", "LU": "Luxemburgo",
    "NL": "Países Baixos", "PL": "Polónia", "IT": "Itália",
}

# fronteira do lugar para o botão "ver no mapa" do club.html: uma feature por
# lugar, identificada pelo nome (mesma string do regioes_index), gravada
# dentro do regioes/<key>.json. A página de lugar ignora-o, só o club.html a
# usa. País não tem (grande de mais, nem há botão).
#
# Fonte por nível: os níveis finos (concelho PT, zona estrangeira) leem a
# geometria precisa de refdata/: a cópia simplificada de data/ perde lóbulos
# de municípios pequenos. Distrito e região estrangeira usam data/, onde a
# diferença não se vê.
_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_GEOJSON_DIR = os.path.join(_REPO, "data")
REFDATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "refdata")
FRONTEIRA_FILES = {
    ("PT", "concelho"): ("refdata", "concelhos_pt.geojson", "NAME_2"),
    ("PT", "distrito"): ("data", "distritos_pt.geojson", "district"),
    ("ES", "regiao"): ("data", "provincias_es.geojson", "region"),
    ("ES", "zona"): ("refdata", "foreign_muni/ES.geojson", "region"),
    ("DE", "regiao"): ("data", "laender_de.geojson", "region"),
    ("DE", "zona"): ("refdata", "foreign_muni/DE.geojson", "region"),
    ("MA", "regiao"): ("data", "regioes_ma.geojson", "region"),
    ("MA", "zona"): ("refdata", "foreign_muni/MA.geojson", "region"),
    ("AD", "regiao"): ("data", "paroquias_ad.geojson", "region"),
    ("AD", "zona"): ("data", "paroquias_ad.geojson", "region"),
}
_fronteira_cache = {}


def _geojson_features(base, rel):
    chave = (base, rel)
    if chave not in _fronteira_cache:
        raiz = REFDATA_DIR if base == "refdata" else DATA_GEOJSON_DIR
        try:
            with open(os.path.join(raiz, rel), encoding="utf-8") as f:
                _fronteira_cache[chave] = json.load(f).get("features", [])
        except (FileNotFoundError, json.JSONDecodeError):
            _fronteira_cache[chave] = []
    return _fronteira_cache[chave]


def _simplificar(geom, alvo=4000):
    """Encolhe uma fronteira para ~`alvo` bytes: tira ilhas com menos de 1%
    da maior parte e simplifica com tolerância crescente até caber. É um
    traço a zoom <= 11, o detalhe fino não conta."""
    def compacto(g):
        return len(json.dumps(g, separators=(",", ":")))
    if not geom or compacto(geom) <= alvo:
        return geom
    try:
        from shapely.geometry import shape, mapping, MultiPolygon
    except ImportError:
        return geom
    forma = shape(geom)
    if isinstance(forma, MultiPolygon) and len(forma.geoms) > 4:
        maior = max(p.area for p in forma.geoms)
        grandes = [p for p in forma.geoms if p.area >= maior * 0.01]
        forma = MultiPolygon(grandes) if len(grandes) > 1 else grandes[0]
    s = mapping(forma)
    for tol in (0.002, 0.004, 0.006, 0.01):
        if compacto(s) <= alvo:
            break
        s = mapping(forma.simplify(tol, preserve_topology=True))
    return s


def fronteira_de(cc, nivel, nome):
    """Geometria GeoJSON (dict) da fronteira do lugar, ou None."""
    trio = FRONTEIRA_FILES.get((cc, nivel))
    if not trio:
        return None
    base, rel, prop = trio
    for feat in _geojson_features(base, rel):
        if (feat.get("properties") or {}).get(prop) == nome:
            return _simplificar(feat.get("geometry"))
    return None


def key_de(cc, nivel, nome):
    """<key> do ficheiro de um lugar, base do nome regioes/<key>.html|json e
    do regiaoHref no front-end.

    PT mantém c-/d- (uma centena de ficheiros e todos os links do histórico,
    perfis e club.html já assim; mudar isso partia bookmarks). País:
    pais-<ccl>, a convenção que as pais-*.html já usam. Estrangeiro fora do
    nível país: <ccl>-r- (região/nível 2) e <ccl>-z- (zona/nível 3), com o cc
    a desambiguar nomes repetidos entre países (Madrid província vs Madrid
    município)."""
    ccl = cc.lower()
    if nivel == "pais":
        return f"pais-{ccl}"
    if cc == "PT":
        return ("c-" if nivel == "concelho" else "d-") + slugify(nome)
    pref = "z-" if nivel in ("concelho", "zona", "municipio") else "r-"
    return f"{ccl}-{pref}{slugify(nome)}"


def centro_de(snapshot, cc, nivel, nome):
    """[x, y] em tiles (zoom do club.json) do centro da união do clube neste
    lugar, para o botão "ver no mapa" da página de lugar saltar o club.html.
    None quando não há: país (grande de mais, o club.html também o exclui) ou
    lugar sem entrada em club_regioes.uniao.centros. Mesmas chaves que o
    centroDe() do club.html."""
    if nivel == "pais":
        return None
    centros = ((snapshot.get("uniao") or {}).get("centros")) or {}
    ccl = cc.lower()
    if nivel in ("distrito", "regiao"):
        chave = f"distrito|{nome}" if cc == "PT" else f"region|{ccl}|{nome}"
    else:  # concelho / zona
        chave = f"concelho|{nome}" if cc == "PT" else f"municipio|{ccl}|{nome}"
    return centros.get(chave)


def regioes_ativas(club_regioes):
    """{nivel: set(nomes)} das regiões PT com pelo menos um atleta a >0."""
    fora = {n: set() for n in NIVEIS}
    for info in club_regioes.get("atletas", {}).values():
        for nivel in NIVEIS:
            for nome, n in (info.get(CHAVE_BUCKET[nivel]) or {}).items():
                if n > 0:
                    fora[nivel].add(nome)
    return fora


def _ordena_ranking(pares):
    pares.sort(key=lambda t: (-t[1],
               ATLETAS_ORDEM.index(t[0]) if t[0] in ATLETAS_ORDEM else 99))
    return pares


def ranking_de(club_regioes, nivel, nome):
    """[(atleta, captured), ...] ordenado desc; empate pela ordem canónica.
    Só atletas com captured > 0."""
    b = CHAVE_BUCKET[nivel]
    pares = [(atleta, (info.get(b) or {}).get(nome, 0))
             for atleta, info in club_regioes.get("atletas", {}).items()]
    return _ordena_ranking([(a, n) for a, n in pares if n > 0])


# --- estrangeiro ------------------------------------------------------------

def ativas_estrangeiro(club_regioes):
    """{ccl: {"regiao": set(nomes), "zona": set(nomes)}} do estrangeiro com
    pelo menos um atleta a >0. ccl minúsculo, como no club_regioes.json."""
    fora = {}
    for info in club_regioes.get("atletas", {}).values():
        for nivel, bucket in BUCKET_ATLETA_ESTR.items():
            for ccl, regs in (info.get(bucket) or {}).items():
                for nome, n in regs.items():
                    if n > 0:
                        fora.setdefault(ccl, {"regiao": set(), "zona": set()})[nivel].add(nome)
    return fora


def parent_map_estrangeiro(foreign_muni_path):
    """{municipio: província/Land/région} a partir do properties.parent do
    ficheiro recortado foreign_muni/<CC>.geojson. {} se o ficheiro faltar."""
    try:
        with open(foreign_muni_path, encoding="utf-8") as f:
            geo = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}
    return {ft["properties"].get("region"): ft["properties"].get("parent")
            for ft in geo.get("features", [])}


def construir_estrangeiro(ccl, nivel, nome, snapshot, stats, adjacency,
                          ativas_estr, parent):
    """Dict de uma região (nivel "regiao") ou zona (nivel "zona") estrangeira,
    mesma forma que construir() mais cc / pai_key / avo_key. `parent` = nome da
    província que contém a zona (parent_map_estrangeiro), None para regiões."""
    cc = ccl.upper()
    ba = BUCKET_ATLETA_ESTR[nivel]
    skey = ("by_region_" if nivel == "regiao" else "by_municipio_") + ccl
    adjbkt = (ADJ_REGIAO if nivel == "regiao" else ADJ_ZONA).get(ccl)

    total = (stats.get(skey, {}).get(nome) or {})
    z14 = (total.get("z14") or {}).get("total")
    z17 = (total.get("z17") or {}).get("total")

    uni_b = snapshot.get("uniao") or {}
    uni = ((uni_b.get(ba) or {}).get(ccl) or {}).get(nome, 0)
    uni_pct = round(100 * uni / z17, 2) if z17 else None
    exc = (((uni_b.get("exclusivos") or {}).get(ba) or {}).get(ccl) or {}).get(nome, {})

    pares = [(atleta, ((info.get(ba) or {}).get(ccl) or {}).get(nome, 0))
             for atleta, info in snapshot.get("atletas", {}).items()]
    ranking = [
        {"nome": a, "captured": n, "exclusivos": exc.get(a, 0),
         "pct": round(100 * n / z17, 2) if z17 else None}
        for a, n in _ordena_ranking([(a, n) for a, n in pares if n > 0])
    ]

    viz = []
    pagina_de = ativas_estr.get(ccl, {}).get(nivel, set())
    for vn in (adjacency.get(adjbkt, {}).get(nome, {}) or {}).get("neighbors", []) if adjbkt else []:
        viz.append({"nome": vn, "key": key_de(cc, nivel, vn), "tem_pagina": vn in pagina_de})

    pais_key, pais_nome = key_de(cc, "pais", cc), PAIS_NOME.get(cc, cc)
    if nivel == "regiao":
        pai_key, pai_nome, avo_key, avo_nome = pais_key, pais_nome, None, None
    else:
        pai_key = key_de(cc, "regiao", parent) if parent else pais_key
        pai_nome = parent or pais_nome
        avo_key, avo_nome = pais_key, pais_nome

    return {
        "key": key_de(cc, nivel, nome),
        "cc": cc,
        "nivel": nivel,
        "regiao": nome,
        "pai_key": pai_key,
        "pai_nome": pai_nome,
        "avo_key": avo_key,
        "avo_nome": avo_nome,
        "totais": {"z14": z14, "z17": z17},
        "uniao": {"z17": uni, "pct": uni_pct},
        "centro": centro_de(snapshot, cc, nivel, nome),
        "fronteira": fronteira_de(cc, nivel, nome),
        "ranking": ranking,
        "vizinhos": viz,
    }


def construir_pais(cc, snapshot, stats, adjacency, paises_com_pagina):
    """Dict de uma página de país (nivel 'pais'). Ranking por atleta do bucket
    `country`, união de uniao.by_pais, exclusivos, vizinhos de
    adjacency['paises']. As sub-regiões (distritos PT / províncias
    estrangeiras) vêm do regioes_index.json por pai_key, como os concelhos de
    um distrito, não vão aqui."""
    ccl = cc.lower()
    pais_stats = stats.get(f"country_{ccl}") or {}
    z14 = (pais_stats.get("z14") or {}).get("total")
    z17 = (pais_stats.get("z17") or {}).get("total")

    uni_b = snapshot.get("uniao") or {}
    uni = (uni_b.get("by_pais") or {}).get(cc, 0)
    uni_pct = round(100 * uni / z17, 2) if z17 else None
    exc = ((uni_b.get("exclusivos") or {}).get("by_pais") or {}).get(cc, {})

    pares = [(atleta, (info.get("country") or {}).get(cc, 0))
             for atleta, info in snapshot.get("atletas", {}).items()]
    ranking = [
        {"nome": a, "captured": n, "exclusivos": exc.get(a, 0),
         "pct": round(100 * n / z17, 2) if z17 else None}
        for a, n in _ordena_ranking([(a, n) for a, n in pares if n > 0])
    ]

    viz = []
    for vn in (adjacency.get("paises", {}).get(cc, {}) or {}).get("neighbors", []):
        viz.append({"nome": PAIS_NOME.get(vn, vn), "key": f"pais-{vn.lower()}",
                    "tem_pagina": vn in paises_com_pagina})

    return {
        "key": f"pais-{ccl}",
        "cc": cc,
        "nivel": "pais",
        "regiao": PAIS_NOME.get(cc, cc),
        "pai_key": None,
        "pai_nome": None,
        "avo_key": None,
        "avo_nome": None,
        "totais": {"z14": z14, "z17": z17},
        "uniao": {"z17": uni, "pct": uni_pct},
        "centro": None,
        "fronteira": None,
        "ranking": ranking,
        "vizinhos": viz,
    }


def _distrito_pai(concelhos_geojson_path, nome):
    """distrito (property `parent`) de um concelho, para o cabeçalho."""
    try:
        with open(concelhos_geojson_path, encoding="utf-8") as f:
            geo = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return None
    for feat in geo.get("features", []):
        if feat["properties"].get("NAME_2") == nome:
            return feat["properties"].get("parent")
    return None


def construir(nivel, nome, snapshot_atual, stats, adjacency,
              ativas, concelhos_geojson_path):
    """Dict final de uma região. `ativas` = regioes_ativas(snapshot_atual)
    para saber que vizinhos têm página."""
    total = (stats.get(CHAVE_STATS[nivel], {}).get(nome) or {})
    z14 = (total.get("z14") or {}).get("total")
    z17 = (total.get("z17") or {}).get("total")

    # união do clube: squadratinhos cobertos por qualquer membro, sem duplicar
    # partilhados (classify_club.classify_uniao). É a métrica de "actividade"
    # do índice de regiões, o total da região (z17) só diz o tamanho.
    uni_b = snapshot_atual.get("uniao") or {}
    uni = (uni_b.get(CHAVE_BUCKET[nivel]) or {}).get(nome, 0)
    uni_pct = round(100 * uni / z17, 2) if z17 else None
    # exclusivos por atleta: squadratinhos que mais nenhum membro tem aqui.
    exc = ((uni_b.get("exclusivos") or {}).get(CHAVE_BUCKET[nivel]) or {}).get(nome, {})

    rank = ranking_de(snapshot_atual, nivel, nome)
    ranking = [
        {"nome": a, "captured": n, "exclusivos": exc.get(a, 0),
         "pct": round(100 * n / z17, 2) if z17 else None}
        for a, n in rank
    ]

    viz = []
    for vn in (adjacency.get(CHAVE_ADJ[nivel], {}).get(nome, {}) or {}).get("neighbors", []):
        viz.append({"nome": vn, "key": key_de("PT", nivel, vn),
                    "tem_pagina": vn in ativas[nivel]})

    # hierarquia acima, uniforme com o estrangeiro: pai_key/pai_nome e
    # avo_key/avo_nome. Concelho -> distrito -> Portugal; distrito -> Portugal.
    pai = _distrito_pai(concelhos_geojson_path, nome) if nivel == "concelho" else None
    if nivel == "concelho" and pai:
        pai_key, pai_nome = key_de("PT", "distrito", pai), pai
        avo_key, avo_nome = "pais-pt", "Portugal"
    else:  # distrito (ou concelho sem distrito conhecido, não devia acontecer)
        pai_key, pai_nome = "pais-pt", "Portugal"
        avo_key, avo_nome = None, None

    # `key` fica só para o escrever() saber o nome do ficheiro, não vai para o
    # JSON (é o próprio nome do ficheiro).
    return {
        "key": key_de("PT", nivel, nome),
        "cc": "PT",
        "nivel": nivel,
        "regiao": nome,
        "pai_key": pai_key,
        "pai_nome": pai_nome,
        "avo_key": avo_key,
        "avo_nome": avo_nome,
        "totais": {"z14": z14, "z17": z17},
        "uniao": {"z17": uni, "pct": uni_pct},
        "centro": centro_de(snapshot_atual, "PT", nivel, nome),
        "fronteira": fronteira_de("PT", nivel, nome),
        "ranking": ranking,
        "vizinhos": viz,
    }


def escrever(out_dir, regiao_dict, gerado):
    d = {k: v for k, v in regiao_dict.items() if k != "key"}
    d["gerado"] = gerado
    os.makedirs(os.path.join(out_dir, "regioes"), exist_ok=True)
    caminho = os.path.join(out_dir, "regioes", regiao_dict["key"] + ".json")
    with open(caminho, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, separators=(",", ":"))
    return caminho


def linha_indice(reg, disputadas):
    """Resumo de um lugar para o regioes_index.json (PT, estrangeiro e país).
    `reg` = dict de construir()/construir_estrangeiro()/construir_pais();
    `disputadas` = {(cc, nivel, nome)} com evento de troca real."""
    rk = reg["ranking"]
    cc = reg.get("cc", "PT")
    return {
        "key": reg["key"],
        "cc": cc,
        "nivel": reg["nivel"],
        "regiao": reg["regiao"],
        "pai": reg.get("pai_nome"),
        "pai_key": reg.get("pai_key"),
        "uniao": reg["uniao"]["z17"],
        "uniao_pct": reg["uniao"]["pct"],
        "total": (reg.get("totais") or {}).get("z17"),
        "lider": rk[0]["nome"] if rk else None,
        "n": len(rk),
        "disp": (cc, reg["nivel"], reg["regiao"]) in disputadas,
    }


def escrever_indice(out_dir, linhas, gerado):
    """data/regioes_index.json, a lista completa das regiões com actividade,
    para a página regioes/index.html (uma passagem, sem buscar 100 ficheiros)."""
    with open(os.path.join(out_dir, "regioes_index.json"), "w", encoding="utf-8") as f:
        json.dump({"gerado": gerado, "regioes": linhas},
                  f, ensure_ascii=False, separators=(",", ":"))


def disputadas_de(eventos):
    """{(cc, nivel, regiao)} das regiões com ultrapassagem ou novo líder."""
    return {(e.get("cc", "PT"), e["nivel"], e["regiao"]) for e in (eventos or [])
            if e.get("tipo") in ("ultrapassagem", "novo_lider")}
