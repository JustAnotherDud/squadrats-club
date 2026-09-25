"""Análise pessoal (analise.html) de UM uid: classifica cada square por
concelho/distrito e escreve tile_info_*.json, stats.json, trophies.json e
suggestions.json. Para actualizar tudo, usar run_all.py.

Uso:
  py build_analise.py --uid <firebase_uid> [pasta_saida]
"""
import argparse
import json
import os
import sys

from kml_parse import reconstruct_squares, tile_bounds, ZOOM_BY_TYPE
from classify import Classifier

HERE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(os.path.dirname(HERE), "data")
REFDATA_DIR = os.path.join(HERE, "refdata")  # fronteiras não-simplificadas, só para classificação


def run_from_tiles(uid, out_dir, bbox=None):
    """Varre o uid nos vector tiles (tiles_fetch.py) e escreve os ficheiros."""
    from atletas import known_squadratinhos
    from tiles_fetch import scan_athlete

    kwargs = {"bbox": bbox} if bbox else {}
    known = known_squadratinhos(out_dir).get(uid)
    resultado = scan_athlete(uid, with_trophy_geometry=True, known_squadratinhos=known, **kwargs)
    if resultado is None:
        # sem alterações: os ficheiros publicados já estão no out_dir
        print(f"UID '{uid}': sem alterações desde a última publicação, a manter ficheiros existentes")
        return {}
    geoms, counts, trophies = resultado

    if "squadrats" not in geoms:
        raise RuntimeError(
            f"UID '{uid}': nenhum square 'squadrats' encontrado na área varrida, "
            f"varrimento incompleto ou atleta sem dados. A abortar sem tocar em ficheiros de saída."
        )
    write_trophies(trophies, counts, out_dir)
    return run_from_geoms(geoms, out_dir, counts=counts)


# grelha a que cada troféu pertence, o mapa mostra os do zoom activo
TROPHY_GRID = {
    "squadrats": ["yard", "ubersquadrat"],
    "squadratinhos": ["yardinho", "ubersquadratinho"],
}


def write_trophies(trophies, counts, out_dir):
    """data/trophies.json, geometria das formas de troféu (yard/über), para o
    mapa as poder desenhar como camadas opcionais."""
    from shapely.geometry import MultiPolygon, mapping

    def simplificar(geom):
        # mesma razão do sort dos tile_info: a ordem dos polígonos dentro de um
        # MultiPolygon não é estável entre plataformas
        if isinstance(geom, MultiPolygon):
            geom = MultiPolygon(sorted(geom.geoms, key=lambda p: p.bounds))
        # a grelha é ortogonal: simplificar tira vértices redundantes das
        # bordas clipadas sem mexer no desenho
        g = geom.simplify(1e-6, preserve_topology=True)
        geo = mapping(g)

        def arred(o):
            if isinstance(o[0], (int, float)):
                return [round(c, 6) for c in o]
            return [arred(c) for c in o]

        return {**geo, "coordinates": arred(geo["coordinates"])}

    out = {}
    for grelha, camadas in TROPHY_GRID.items():
        bloco = {}
        for nome in camadas:
            if nome not in trophies:
                continue
            bloco[nome] = {"size": counts.get(nome), "geometry": simplificar(trophies[nome])}
        if bloco:
            out[grelha] = bloco

    path = os.path.join(out_dir, "trophies.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, separators=(",", ":"))
    print(f"trophies -> {path}")


def write_suggestions(visitados_por_grelha, counts, out_dir):
    """data/suggestions.json, o que falta para o próximo übersquadrat.

    Antes de sugerir seja o que for, `verify_rules` confirma que as nossas
    regras reproduzem o yard e o übersquadrat que o servidor reporta. Se
    divergirem, aborta: uma sugestão calculada com regras erradas parece
    rigorosa e não é.
    """
    from suggestions import verify_rules, proximo_ubersquadrat, melhor_ligacao, corredores

    out = {}
    for grelha, (visitados, zoom) in visitados_por_grelha.items():
        yard_name, uber_name = TROPHY_GRID[grelha]
        esperado_yard, esperado_uber = counts.get(yard_name), counts.get(uber_name)
        if esperado_yard is None or esperado_uber is None:
            continue
        verify_rules(visitados, esperado_yard, esperado_uber, grelha)

        bloco = {
            "zoom": zoom,
            "ligacao": melhor_ligacao(visitados),
            "corredores": corredores(visitados),
        }

        s = proximo_ubersquadrat(visitados, esperado_uber)
        if s is not None:
            cx, cy = s["canto"]
            bloco["uber"] = {
                "atual": esperado_uber,
                "alvo": s["n_alvo"],
                "faltam": s["faltam"],
                "canto": {"x": cx, "y": cy},
                "squares": [{"x": x, "y": y} for x, y in s["squares_em_falta"]],
            }
        out[grelha] = bloco

    path = os.path.join(out_dir, "suggestions.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, separators=(",", ":"))
    print(f"suggestions -> {path}")


def run_from_geoms(geoms, out_dir, counts=None):
    classifier = Classifier(
        os.path.join(REFDATA_DIR, "distritos_pt.geojson"),
        os.path.join(REFDATA_DIR, "concelhos_pt.geojson"),
        foreign_dir=os.path.join(REFDATA_DIR, "foreign"),
        foreign_muni_dir=os.path.join(REFDATA_DIR, "foreign_muni"),
        outlines_path=os.path.join(REFDATA_DIR, "outlines", "europe.geojson"),
    )

    with open(os.path.join(REFDATA_DIR, "grid_totals.json"), encoding="utf-8") as f:
        grid_totals = json.load(f)

    zkey_by_type = {"squadrats": "z14", "squadratinhos": "z17"}

    summary = {}
    visitados_por_grelha = {}
    # países estrangeiros com total conhecido (grid_totals já tem country_XX/
    # by_region_XX, ver compute_grid_totals.py), descoberto a partir das
    # chaves do próprio grid_totals, não de uma lista fixa: um país novo lá
    # aparece aqui sozinho, sem tocar neste ficheiro.
    paises_com_total = sorted({
        k[len("country_"):].upper() for k in grid_totals if k.startswith("country_") and k != "country_pt"
    })
    # mesmo princípio, para o nível concelho/município equivalente, hoje só
    # ES (grid_totals["by_municipio_es"]), descoberto pelas chaves, não por
    # uma lista fixa.
    paises_com_municipio = sorted({
        k[len("by_municipio_"):].upper() for k in grid_totals if k.startswith("by_municipio_")
    })
    stats = {"by_concelho": {}, "by_distrito": {}, "country_pt": {}, "foreign": {}}
    for cc in paises_com_total:
        stats[f"country_{cc.lower()}"] = {}
        stats[f"by_region_{cc.lower()}"] = {}
    for cc in paises_com_municipio:
        stats[f"by_municipio_{cc.lower()}"] = {}
    total_squares = 0
    not_on_land = 0
    fallback_events = []  # squares resolvidos por proximidade (país e/ou concelho), não por área

    # países que TÊM geometria de município no disco (após o clip da
    # refdata/clip.py, isto é só a zona já visitada + 10 km). Se um square
    # cair num destes países com região mas sem município, o clip ficou curto.
    muni_countries_geo = ({cc for cc, _ in classifier.foreign_muni.names}
                          if classifier.foreign_muni else set())
    clip_misses_total = {}  # {cc: n} acumulado nas duas grelhas, para o aviso

    for type_name, zoom in ZOOM_BY_TYPE.items():
        if type_name not in geoms:
            print(f"aviso: camada '{type_name}' não encontrada", file=sys.stderr)
            continue

        declared_size, geom = geoms[type_name]
        squares = reconstruct_squares(geom, zoom)

        if declared_size is not None and len(squares) != declared_size:
            # nunca publicar dados que não batam com o total do servidor
            raise RuntimeError(
                f"{type_name}, reconstruídos {len(squares)}, declarados {declared_size} "
                f"(diferença indica varrimento incompleto ou bug de geometria)"
            )

        out = []
        by_concelho_captured, by_distrito_captured = {}, {}
        by_foreign_captured = {}  # {country: {region: count}}
        by_foreign_municipio_captured = {}  # {country: {municipio: count}}
        by_country_nodata = {}  # {country: count}: país detetado por contorno, sem dados de região
        muni_clip_misses = {}   # {country: count}: tem ficheiro de município mas o clip não apanhou o square
        unclassified_foreign = 0
        pt_captured = foreign_captured = 0
        for x, y, lon, lat in squares:
            info = classifier.classify(tile_bounds(x, y, zoom))
            out.append({
                "x": x, "y": y, "zoom": zoom,
                "lon": round(lon, 6), "lat": round(lat, 6),
                "in_portugal": info["in_portugal"],
                "district": info["district"],
                "concelho": info["concelho"],
                "country": info["country"],
                "region": info["region"],
                "municipio": info["municipio"],
            })
            total_squares += 1
            if not info["on_land"]:
                not_on_land += 1

            for level, deg in (
                ("country", info["country_fallback_deg"]),
                ("concelho", info["concelho_fallback_deg"]),
            ):
                if deg is not None:
                    fallback_events.append({
                        "x": x, "y": y, "zoom": zoom,
                        "lon": round(lon, 6), "lat": round(lat, 6),
                        "level": level,
                        "resolved_to": info["concelho"] if level == "concelho"
                                       else (info["district"] if info["in_portugal"] else f"{info['country']}/{info['region']}"),
                        "distance_deg": round(deg, 6),
                        "distance_m_approx": round(deg * 111_000),  # aproximado, sem correcção de latitude
                    })

            if info["in_portugal"]:
                pt_captured += 1
                by_concelho_captured[info["concelho"]] = by_concelho_captured.get(info["concelho"], 0) + 1
                by_distrito_captured[info["district"]] = by_distrito_captured.get(info["district"], 0) + 1
            else:
                foreign_captured += 1
                cc = info["country"]
                if cc and info["region"]:
                    by_foreign_captured.setdefault(cc, {})
                    by_foreign_captured[cc][info["region"]] = (
                        by_foreign_captured[cc].get(info["region"], 0) + 1
                    )
                    if info["municipio"]:
                        by_foreign_municipio_captured.setdefault(cc, {})
                        by_foreign_municipio_captured[cc][info["municipio"]] = (
                            by_foreign_municipio_captured[cc].get(info["municipio"], 0) + 1
                        )
                    elif cc in muni_countries_geo:
                        # há ficheiro de município para este país mas nenhum
                        # apanhou o square: o clip (buffer 10 km) ficou curto
                        muni_clip_misses[cc] = muni_clip_misses.get(cc, 0) + 1
                elif cc:
                    # país detetado por contorno (Natural Earth), sem geometria
                    # de região: aparece no mapa/club com bandeira e "sem dados"
                    by_country_nodata[cc] = by_country_nodata.get(cc, 0) + 1
                else:
                    # nem contorno apanhou (fora da Europa, ou pleno oceano)
                    unclassified_foreign += 1

        visitados_por_grelha[type_name] = ({(s["x"], s["y"]) for s in out}, zoom)

        # ordem estável: a de `reconstruct_squares` varia com a plataforma/versão
        # do shapely, e sem isto o `git diff --quiet` do workflow via sempre
        # diferença e comitava todos os dias mesmo sem squares novos
        out.sort(key=lambda s: (s["x"], s["y"]))

        out_path = os.path.join(out_dir, f"tile_info_{type_name}.json")
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False, separators=(",", ":"))

        summary[type_name] = {
            "total": len(out),
            "in_portugal": pt_captured,
        }
        print(f"{type_name}: {len(out)} squares -> {out_path}")

        zkey = zkey_by_type[type_name]

        def pct(captured, total):
            return round(100.0 * captured / total, 2) if total else 0.0

        for name, total_info in grid_totals["by_concelho"].items():
            total = total_info.get(zkey, 0)
            captured = by_concelho_captured.get(name, 0)
            stats["by_concelho"].setdefault(name, {})[zkey] = {
                "captured": captured, "total": total, "pct": pct(captured, total),
            }
        for name, total_info in grid_totals["by_distrito"].items():
            total = total_info.get(zkey, 0)
            captured = by_distrito_captured.get(name, 0)
            stats["by_distrito"].setdefault(name, {})[zkey] = {
                "captured": captured, "total": total, "pct": pct(captured, total),
            }

        pt_total = grid_totals["country_pt"].get(zkey, 0)
        stats["country_pt"][zkey] = {
            "captured": pt_captured, "total": pt_total, "pct": pct(pt_captured, pt_total),
        }

        for cc in paises_com_total:
            captured_by_region = by_foreign_captured.get(cc, {})
            for name, total_info in grid_totals.get(f"by_region_{cc.lower()}", {}).items():
                total = total_info.get(zkey, 0)
                captured = captured_by_region.get(name, 0)
                stats[f"by_region_{cc.lower()}"].setdefault(name, {})[zkey] = {
                    "captured": captured, "total": total, "pct": pct(captured, total),
                }
            total_pais = grid_totals.get(f"country_{cc.lower()}", {}).get(zkey, 0)
            captured_pais = sum(captured_by_region.values())
            stats[f"country_{cc.lower()}"][zkey] = {
                "captured": captured_pais, "total": total_pais or None,
                "pct": pct(captured_pais, total_pais) if total_pais else None,
            }

        for cc in paises_com_municipio:
            captured_by_municipio = by_foreign_municipio_captured.get(cc, {})
            for name, total_info in grid_totals.get(f"by_municipio_{cc.lower()}", {}).items():
                total = total_info.get(zkey, 0)
                captured = captured_by_municipio.get(name, 0)
                stats[f"by_municipio_{cc.lower()}"].setdefault(name, {})[zkey] = {
                    "captured": captured, "total": total, "pct": pct(captured, total),
                }
        stats["foreign"][zkey] = {**by_foreign_captured, "unclassified": unclassified_foreign}
        if by_country_nodata:
            stats["foreign"][zkey]["by_country_nodata"] = by_country_nodata
        if muni_clip_misses:
            stats["foreign"][zkey]["muni_clip_misses"] = muni_clip_misses
            for cc, n in muni_clip_misses.items():
                clip_misses_total[cc] = clip_misses_total.get(cc, 0) + n

    if counts:
        write_suggestions(visitados_por_grelha, counts, out_dir)

    stats_path = os.path.join(out_dir, "stats.json")
    with open(stats_path, "w", encoding="utf-8") as f:
        json.dump(stats, f, ensure_ascii=False, separators=(",", ":"))
    print(f"stats -> {stats_path}")

    # diagnóstico só no log: squares fora de terra e resolvidos por proximidade
    print(f"classificação: {not_on_land}/{total_squares} squares não estão em terra "
          f"nenhuma (resolvidos por proximidade ou sem classificação); "
          f"{len(fallback_events)} campos (país/concelho) resolvidos por proximidade")

    if clip_misses_total:
        detalhe = ", ".join(f"{cc}: {n}" for cc, n in sorted(clip_misses_total.items()))
        print(f"AVISO: {detalhe} square(s) num país COM ficheiro de município mas "
              f"fora do recorte de 10 km, correr `py pipeline/refdata/clip.py "
              f"{' '.join(sorted(clip_misses_total))}` para acrescentar as zonas novas "
              f"(ver stats.foreign.*.muni_clip_misses)")

    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--uid", dest="uid", required=True, help="Firebase UID do atleta")
    parser.add_argument("out_dir", nargs="?", default=DATA_DIR)
    args = parser.parse_args()

    print(
        "AVISO: a correr build_analise.py directamente, só actualiza a análise pessoal "
        "(tile_info_*.json/stats.json/trophies.json). squadrats.json/club.json/"
        "daily_gains.json (folha-do-clube, club.html) ficam por actualizar. "
        "Para tudo: `py run_all.py` ou `gh workflow run fetch-map-data.yml`.",
        file=sys.stderr,
    )

    os.makedirs(args.out_dir, exist_ok=True)
    result = run_from_tiles(args.uid, args.out_dir)
    print(json.dumps(result, indent=2, ensure_ascii=False))
