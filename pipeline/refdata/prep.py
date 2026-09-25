"""Reduz o peso dos geojson de fronteiras, de forma reprodutível.

Três transformações, nenhuma toca na fonte (GADM 4.1, ver README) nem a vai
buscar: só reprocessa o que já está commitado.

  1. refdata/ (verdade da classificação): arredonda coordenadas a 6 casas
     decimais (~0,1 m) e minifica. Lossless para o classify.py: um square
     z17 tem ~150 m de lado e a atribuição é por maior área de intersecção,
     um desvio de 0,1 m não muda a que região um square pertence (testado:
     0 flips em ~310 mil tiles de fronteira dos municípios que o clube tocou).
     GADM guarda 15 casas decimais (precisão de nanómetro), é pura gordura.

  2. data/ (cópias só para o analise.html DESENHAR): derivadas de refdata/,
     simplificação Douglas-Peucker + 5 casas decimais. O mapa desenha isto a
     zoom de país, não se vê a diferença; nunca classifica com estes
     ficheiros. Mesmo padrão que o data/distritos_pt.geojson (45 KB) já usava,
     agora aplicado a tudo. Nota: a simplificação é por polígono, não
     topológica: dois municípios vizinhos podem ficar com um vão sub-pixel
     na fronteira partilhada; invisível ao desenhar, e a classificação não
     usa estes ficheiros.

  3. outlines/europe.geojson: contornos de país (Natural Earth Admin 0, 1:50m,
     DOMÍNIO PÚBLICO), Europa, muito simplificados (~2 km). Só para DETETAR o
     país de um square capturado num país sem dados de região (ver
     classify.py: cai aqui antes de devolver country=None). Este é o único
     ficheiro que o prep vai buscar à fonte (`--fetch-outlines`), porque é
     domínio público e a Natural Earth é versionada e estável.

Uso:
  py prep.py                reescreve todos os ficheiros da tabela abaixo
  py prep.py --check        não escreve; sai 1 se algum ficheiro no disco não
                            for igual ao que o prep produziria
  py prep.py --fetch-outlines
                            (re)gera outlines/europe.geojson da Natural Earth

Dependências: shapely (já em requirements.txt).
"""
import argparse
import json
import os
import sys
import urllib.request

from shapely import simplify  # shapely>=2 (função de topo)
from shapely.geometry import mapping, shape
from shapely.validation import make_valid

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))

# 1 grau de latitude ~= 111 km; chega para converter a tolerância de metros
# em graus (a longitude encolhe com a latitude, mas a esta escala e para
# desenhar não interessa).
DEG_PER_M = 1.0 / 111_000.0

# Cada linha: ficheiro de saída (relativo ao repo), fonte (None = in-place),
# casas decimais, simplificação em metros (0 = nenhuma).
#
# refdata/*  -> in-place, 6 dp, sem simplificar  (verdade da classificação)
# data/*     -> derivado de refdata, 5 dp, simplificado  (só desenho)
JOBS = [
    # --- refdata: só arredondar + minificar ---
    ("pipeline/refdata/distritos_pt.geojson", None, 6, 0),
    ("pipeline/refdata/concelhos_pt.geojson", None, 6, 0),
    ("pipeline/refdata/foreign/ES.geojson", None, 6, 0),
    ("pipeline/refdata/foreign/DE.geojson", None, 6, 0),
    ("pipeline/refdata/foreign/MA.geojson", None, 6, 0),
    ("pipeline/refdata/foreign/AD.geojson", None, 6, 0),
    ("pipeline/refdata/foreign_muni/DE.geojson", None, 6, 0),
    ("pipeline/refdata/foreign_muni/ES.geojson", None, 6, 0),
    ("pipeline/refdata/foreign_muni/MA.geojson", None, 6, 0),

    # --- data: cópias de desenho, derivadas de refdata ---
    # tolerâncias calibradas para ~= às versões simplificadas à mão que já
    # existiam (data/distritos_pt 44 KB, data/provincias_es 284 KB) e para os
    # ficheiros de milhares de municípios caberem em <1 MB minificados.
    ("data/concelhos_pt.geojson",  "pipeline/refdata/concelhos_pt.geojson",      5,  250),
    ("data/distritos_pt.geojson",  "pipeline/refdata/distritos_pt.geojson",      5, 1000),
    ("data/provincias_es.geojson", "pipeline/refdata/foreign/ES.geojson",        5,  500),
    ("data/laender_de.geojson",    "pipeline/refdata/foreign/DE.geojson",        5,  200),
    ("data/regioes_ma.geojson",    "pipeline/refdata/foreign/MA.geojson",        5,  150),
    ("data/paroquias_ad.geojson",  "pipeline/refdata/foreign/AD.geojson",        5,   50),
    ("data/municipios_de.geojson", "pipeline/refdata/foreign_muni/DE.geojson",   5, 1500),
    ("data/municipios_es.geojson", "pipeline/refdata/foreign_muni/ES.geojson",   5, 1500),
    ("data/cercles_ma.geojson",    "pipeline/refdata/foreign_muni/MA.geojson",   5,  400),
]

# Os contornos de país para DESENHAR (data/*_outline.geojson) NÃO estão aqui de
# propósito: são desenhados uma vez, nunca se regeneram, e simplificar-em-cima-
# de-si não é idempotente (o --check acusaria sempre diferença). O
# morocco_outline (82 mil vértices) e o andorra_outline foram reduzidos uma vez
# à mão; os outros já eram leves.

# --- outlines/europe.geojson: Natural Earth Admin 0, para DETETAR país ---
NE_URL = ("https://raw.githubusercontent.com/nvkelso/natural-earth-vector/"
          "master/geojson/ne_50m_admin_0_countries.geojson")
NE_TOL_M, NE_DP = 2000, 4
# Natural Earth mete -99 no ISO_A2 de uns quantos (bug conhecido); força-se.
NE_ISO_OVERRIDE = {"France": "FR", "Norway": "NO", "Kosovo": "XK"}
OUTLINES_PATH = "pipeline/refdata/outlines/europe.geojson"


def _fetch_outlines():
    """(re)gera outlines/europe.geojson da Natural Earth. Único ficheiro que o
    prep vai buscar à fonte: é domínio público e a NE é versionada/estável."""
    raw = urllib.request.urlopen(NE_URL, timeout=60).read()
    doc = json.loads(raw)
    tol = NE_TOL_M * DEG_PER_M
    feats = []
    for f in doc["features"]:
        if f["properties"].get("CONTINENT") != "Europe":
            continue
        p = f["properties"]
        cc = next((p[k].upper() for k in ("ISO_A2", "ISO_A2_EH")
                   if p.get(k) and p[k] != "-99" and len(p[k]) == 2 and p[k].isalpha()),
                  NE_ISO_OVERRIDE.get(p.get("NAME")))
        if not cc:
            raise SystemExit(f"prep --fetch-outlines: sem ISO A2 para {p.get('NAME')}")
        g = make_valid(shape(f["geometry"]))
        gs = simplify(g, tol, preserve_topology=True)
        if not gs.is_valid:
            gs = make_valid(gs)
        gj = json.loads(json.dumps(mapping(gs)))
        gj["coordinates"] = _round(gj["coordinates"], NE_DP)
        feats.append({"type": "Feature",
                      "properties": {"country": cc, "nome": p.get("NAME_PT") or p["NAME"]},
                      "geometry": gj})
    feats.sort(key=lambda x: x["properties"]["country"])
    body = json.dumps({"type": "FeatureCollection", "features": feats},
                      ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    out = os.path.join(REPO, OUTLINES_PATH)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "wb") as fh:
        fh.write(body)
    print(f"  {OUTLINES_PATH}: {len(feats)} países, {len(body)/1024:.0f} KB")


def _round(obj, dp):
    if isinstance(obj, float):
        return round(obj, dp)
    if isinstance(obj, list):
        return [_round(x, dp) for x in obj]
    return obj


def _iter_geoms(doc):
    """Devolve (setter, geometry_dict) para cada geometria do doc, seja o doc
    uma FeatureCollection, um Feature, ou uma geometria à solta."""
    t = doc.get("type")
    if t == "FeatureCollection":
        for feat in doc["features"]:
            yield (lambda g, f=feat: f.__setitem__("geometry", g)), feat["geometry"]
    elif t == "Feature":
        yield (lambda g: doc.__setitem__("geometry", g)), doc["geometry"]
    else:  # geometria à solta
        yield (lambda g: doc.update(g)), doc


def _transform_doc(doc, dp, simplify_m):
    tol = simplify_m * DEG_PER_M
    n_vazio = 0
    for setter, geom in _iter_geoms(doc):
        if tol > 0:
            g = shape(geom)
            if not g.is_valid:
                g = make_valid(g)
            gs = simplify(g, tol, preserve_topology=True)
            if not gs.is_valid:
                gs = make_valid(gs)
            if gs.is_empty:
                # não deixar cair uma feature: fica a geometria original,
                # só arredondada
                n_vazio += 1
            else:
                geom = json.loads(json.dumps(mapping(gs)))
        geom["coordinates"] = _round(geom["coordinates"], dp)
        setter(geom)
    return n_vazio


def _produce(out_rel, src_rel, dp, simplify_m):
    src = os.path.join(REPO, src_rel or out_rel)
    with open(src, encoding="utf-8") as f:
        doc = json.load(f)
    n_feats_antes = len(doc.get("features", [1]))
    n_vazio = _transform_doc(doc, dp, simplify_m)
    assert len(doc.get("features", [1])) == n_feats_antes, "perdeu features"
    body = json.dumps(doc, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return body, n_vazio


def main(check):
    falhou = False
    for out_rel, src_rel, dp, simplify_m in JOBS:
        out = os.path.join(REPO, out_rel)
        antes = os.path.getsize(out) if os.path.exists(out) else 0
        body, n_vazio = _produce(out_rel, src_rel, dp, simplify_m)
        aviso = f"  ({n_vazio} feature(s) ficariam vazias, mantida a geometria original)" if n_vazio else ""
        if check:
            atual = open(out, "rb").read() if os.path.exists(out) else b""
            estado = "OK" if atual == body else "DIFERE"
            if atual != body:
                falhou = True
            print(f"  [{estado}] {out_rel}{aviso}")
        else:
            with open(out, "wb") as f:
                f.write(body)
            print(f"  {antes/1024:8.0f} KB -> {len(body)/1024:8.0f} KB  {out_rel}{aviso}")
    if check and falhou:
        print("\nprep --check: ficheiros no disco não batem com o prep. Correr `py prep.py`.")
        return 1
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true",
                    help="não escreve; sai 1 se algo no disco divergir do prep")
    ap.add_argument("--fetch-outlines", action="store_true",
                    help="(re)gera outlines/europe.geojson da Natural Earth")
    args = ap.parse_args()
    if args.fetch_outlines:
        _fetch_outlines()
        sys.exit(0)
    sys.exit(main(args.check))
