"""One-off: calcula o total de tiles (zoom14/17) que existem em cada concelho/
distrito/país de Portugal e em cada região de qualquer país estrangeiro com
fronteiras em refdata/foreign/*.geojson, usando o MESMO critério de
atribuição do classify.py (maior área de intersecção do tile, sem limiar
mínimo; se nada intersecta, fallback de proximidade simétrico PT/estrangeiro
dentro de COASTAL_BUFFER_DEG).

Corre uma vez, commita o output (pipeline/refdata/grid_totals.json). O build_analise.py
NUNCA recalcula isto, só conta capturados contra estes totais estáticos.

Paralelizado com multiprocessing. Os candidatos de todos os países vão num
varrimento só por zoom, para nenhuma célula ser classificada duas vezes.

Uso: py compute_grid_totals.py
"""
import json
import multiprocessing as mp
import os
import time
import sys
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from kml_parse import lonlat_to_tile, tile_bounds
from classify import Classifier

HERE = os.path.dirname(os.path.abspath(__file__))
REFDATA_DIR = os.path.join(HERE, "refdata")
ZOOMS = [14, 17]

# deixa 2 núcleos de fora de propósito, a máquina continua utilizável
# durante o cálculo, não trava tudo o resto
N_WORKERS = max(1, (os.cpu_count() or 4) - 2)


def candidate_cells_for_geom(geom, zoom):
    """Todas as (x, y) cuja bbox de tile intersecta a bbox do polígono, com
    margem de 1 tile, sobre-inclui (será filtrado por classify() a seguir),
    mas nunca omite uma célula real."""
    minlon, minlat, maxlon, maxlat = geom.bounds
    x0, y1 = lonlat_to_tile(minlon, minlat, zoom)
    x1, y0 = lonlat_to_tile(maxlon, maxlat, zoom)
    xlo, xhi = min(x0, x1) - 1, max(x0, x1) + 1
    ylo, yhi = min(y0, y1) - 1, max(y0, y1) + 1
    for x in range(xlo, xhi + 1):
        for y in range(ylo, yhi + 1):
            yield x, y


def _build_classifier():
    return Classifier(
        os.path.join(REFDATA_DIR, "distritos_pt.geojson"),
        os.path.join(REFDATA_DIR, "concelhos_pt.geojson"),
        foreign_dir=os.path.join(REFDATA_DIR, "foreign"),
        # sem isto self.foreign fica None e o fallback de proximidade
        # (classify.py) deixa de competir com o estrangeiro, PT ganha todos
        # os empates da fronteira/costa por omissão (bug encontrado 2026-08-06).
        foreign_muni_dir=os.path.join(REFDATA_DIR, "foreign_muni"),
    )


# processo-worker: cada um constrói a sua própria Classifier UMA vez (não por
# célula), global de propósito, é o padrão exigido pelo multiprocessing com
# spawn (Windows não usa fork; cada worker reimporta o módulo do zero, por
# isso _init_worker tem de ser uma função de topo, não uma closure).
_classifier_worker = None


def _init_worker():
    global _classifier_worker
    _classifier_worker = _build_classifier()


def _classify_chunk(args):
    """Classifica um bloco de células candidatas, devolve contagens já
    agregadas (não a lista de resultados crus, para milhões de células,
    devolver um dict por bloco é muito mais leve do que devolver tudo)."""
    zoom, cells = args
    by_concelho, by_distrito = {}, {}
    total_pt = 0
    by_country_region = {}  # {country: {region: count}}
    total_by_country = {}   # {country: count}
    by_country_municipio = {}  # {country: {municipio: count}} -- só países com foreign_muni
    for x, y in cells:
        info = _classifier_worker.classify(tile_bounds(x, y, zoom))
        if info["in_portugal"]:
            total_pt += 1
            by_concelho[info["concelho"]] = by_concelho.get(info["concelho"], 0) + 1
            by_distrito[info["district"]] = by_distrito.get(info["district"], 0) + 1
        elif info["country"] and info["region"]:
            cc = info["country"]
            total_by_country[cc] = total_by_country.get(cc, 0) + 1
            by_country_region.setdefault(cc, {})
            by_country_region[cc][info["region"]] = by_country_region[cc].get(info["region"], 0) + 1
            if info["municipio"]:
                by_country_municipio.setdefault(cc, {})
                by_country_municipio[cc][info["municipio"]] = by_country_municipio[cc].get(info["municipio"], 0) + 1
    return by_concelho, by_distrito, total_pt, by_country_region, total_by_country, by_country_municipio


def _merge(acc, part):
    by_concelho, by_distrito, total_pt, by_country_region, total_by_country, by_country_municipio = part
    for k, v in by_concelho.items():
        acc["by_concelho"][k] = acc["by_concelho"].get(k, 0) + v
    for k, v in by_distrito.items():
        acc["by_distrito"][k] = acc["by_distrito"].get(k, 0) + v
    acc["total_pt"] += total_pt
    for cc, regions in by_country_region.items():
        acc["by_country_region"].setdefault(cc, {})
        for r, v in regions.items():
            acc["by_country_region"][cc][r] = acc["by_country_region"][cc].get(r, 0) + v
    for cc, v in total_by_country.items():
        acc["total_by_country"][cc] = acc["total_by_country"].get(cc, 0) + v
    for cc, munis in by_country_municipio.items():
        acc["by_country_municipio"].setdefault(cc, {})
        for m, v in munis.items():
            acc["by_country_municipio"][cc][m] = acc["by_country_municipio"][cc].get(m, 0) + v


def main():
    classifier = _build_classifier()  # só para montar os candidatos e para a validação no fim

    paises_estrangeiros = sorted({country for country, _region in classifier.foreign.names})
    # países com fonte de município (refdata/foreign_muni/*.geojson), hoje
    # só ES. SEMPRE um subconjunto de paises_estrangeiros: sem entrada ao
    # nível região (refdata/foreign/), classify.py nunca atribui esse país
    # a square nenhum, e o município nunca seria usado por muito que exista
    # o ficheiro (ex: refdata/foreign_muni/DE.geojson está lá, arrumado
    # para o futuro, mas a Alemanha não tem refdata/foreign/DE.geojson
    # ainda, filtrado aqui de propósito, para não varrer os municípios
    # dela à toa).
    paises_com_municipio = sorted({
        country for country, _region in classifier.foreign_muni.names
        if country in paises_estrangeiros
    }) if classifier.foreign_muni is not None else []
    ignorados = sorted({country for country, _region in classifier.foreign_muni.names} - set(paises_com_municipio)) \
        if classifier.foreign_muni is not None else []
    if ignorados:
        print(f"município ignorado (sem nível região ainda): {ignorados}", file=sys.stderr)
    print(f"países estrangeiros com fronteiras: {paises_estrangeiros}", file=sys.stderr)
    print(f"países com município: {paises_com_municipio}", file=sys.stderr)
    print(f"a usar {N_WORKERS} processos (de {os.cpu_count()} núcleos)", file=sys.stderr)

    result = {
        "generated": date.today().isoformat(),
        "method": "maior-area-de-intersecao, sem limiar; fallback de proximidade simetrico PT/estrangeiro se nada intersecta (classify.py)",
        "by_concelho": {},
        "by_distrito": {},
        "country_pt": {},
    }
    for cc in paises_estrangeiros:
        result[f"country_{cc.lower()}"] = {}
        result[f"by_region_{cc.lower()}"] = {}
    for cc in paises_com_municipio:
        result[f"by_municipio_{cc.lower()}"] = {}

    for zoom in ZOOMS:
        print(f"--- zoom {zoom} ---", file=sys.stderr)

        # candidatos UNIFICADOS: concelhos de PT + todas as regiões
        # estrangeiras + todos os municípios estrangeiros, num só
        # varrimento, uma célula é classificada no máximo 1 vez, mesmo
        # perto de fronteiras onde os candidate-sets se sobrepõem.
        candidates = set()
        for geom in classifier.concelhos.geoms:
            candidates.update(candidate_cells_for_geom(geom, zoom))
        for geom in classifier.foreign.geoms:
            candidates.update(candidate_cells_for_geom(geom, zoom))
        if classifier.foreign_muni is not None:
            for (country, _region), geom in zip(classifier.foreign_muni.names, classifier.foreign_muni.geoms):
                if country in paises_com_municipio:
                    candidates.update(candidate_cells_for_geom(geom, zoom))
        candidates = list(candidates)
        print(f"células candidatas (unificado): {len(candidates)}", file=sys.stderr)

        # blocos pequenos-o-bastante para balancear entre workers (um worker
        # lento no fim não trava os outros), grandes-o-bastante para o
        # overhead de IPC não pesar
        chunk_size = max(2000, len(candidates) // (N_WORKERS * 8))
        chunks = [candidates[i:i + chunk_size] for i in range(0, len(candidates), chunk_size)]
        tasks = [(zoom, chunk) for chunk in chunks]
        print(f"{len(chunks)} blocos de ~{chunk_size} células", file=sys.stderr)

        acc = {
            "by_concelho": {}, "by_distrito": {}, "total_pt": 0,
            "by_country_region": {}, "total_by_country": {}, "by_country_municipio": {},
        }
        t_inicio = time.time()
        with mp.Pool(N_WORKERS, initializer=_init_worker) as pool:
            done = 0
            for part in pool.imap_unordered(_classify_chunk, tasks):
                _merge(acc, part)
                done += 1
                decorrido = time.time() - t_inicio
                por_bloco = decorrido / done
                restam = (len(tasks) - done) * por_bloco
                print(f"  blocos: {done}/{len(tasks)}, {decorrido:.0f}s decorridos, "
                      f"~{restam:.0f}s a faltar", file=sys.stderr)

        result["country_pt"][f"z{zoom}"] = acc["total_pt"]
        for name, count in acc["by_concelho"].items():
            result["by_concelho"].setdefault(name, {})[f"z{zoom}"] = count
        for name, count in acc["by_distrito"].items():
            result["by_distrito"].setdefault(name, {})[f"z{zoom}"] = count
        print(f"zoom {zoom}: total PT = {acc['total_pt']}", file=sys.stderr)

        for cc in paises_estrangeiros:
            total_pais = acc["total_by_country"].get(cc, 0)
            result[f"country_{cc.lower()}"][f"z{zoom}"] = total_pais
            for name, count in acc["by_country_region"].get(cc, {}).items():
                result[f"by_region_{cc.lower()}"].setdefault(name, {})[f"z{zoom}"] = count
            print(f"zoom {zoom}: total {cc} = {total_pais}", file=sys.stderr)

        for cc in paises_com_municipio:
            munis = acc["by_country_municipio"].get(cc, {})
            for name, count in munis.items():
                result[f"by_municipio_{cc.lower()}"].setdefault(name, {})[f"z{zoom}"] = count
            print(f"zoom {zoom}: {len(munis)} municípios {cc} com total", file=sys.stderr)

    out_path = os.path.join(REFDATA_DIR, "grid_totals.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"escrito: {out_path}")

    # validação: Rio Maior tem de dar os números confirmados. Dependem do
    # critério do classify.py; mudar a regra muda-os sem ser bug.
    rm = result["by_concelho"].get("Rio Maior", {})
    print(f"Rio Maior: z14={rm.get('z14')} (esperado 78), z17={rm.get('z17')} (esperado 4873)")
    assert rm.get("z14") == 78, f"Rio Maior z14 devia ser 78, é {rm.get('z14')}"
    assert rm.get("z17") == 4873, f"Rio Maior z17 devia ser 4873, é {rm.get('z17')}"
    print("validação Rio Maior: OK")

    all_concelho_names = {f["properties"]["NAME_2"] for f in json.load(
        open(os.path.join(REFDATA_DIR, "concelhos_pt.geojson"), encoding="utf-8")
    )["features"]}
    missing = all_concelho_names - set(result["by_concelho"].keys())
    assert not missing, f"concelhos sem total nenhum (bug de nomes?): {missing}"
    assert len(result["by_concelho"]) == 308, f"esperados 308 concelhos, há {len(result['by_concelho'])}"
    print(f"validação 308 concelhos: OK")

    for cc in paises_estrangeiros:
        nomes_regiao = {region for (country, region) in classifier.foreign.names if country == cc}
        chave = f"by_region_{cc.lower()}"
        faltam = nomes_regiao - set(result[chave].keys())
        assert not faltam, f"regiões {cc} sem total nenhum (bug de nomes?): {faltam}"
        assert len(result[chave]) == len(nomes_regiao), (
            f"esperadas {len(nomes_regiao)} regiões {cc}, há {len(result[chave])}"
        )
        print(f"validação {len(nomes_regiao)} regiões {cc}: OK")

    for cc in paises_com_municipio:
        nomes_municipio = {m for (country, m) in classifier.foreign_muni.names if country == cc}
        chave = f"by_municipio_{cc.lower()}"
        faltam = nomes_municipio - set(result[chave].keys())
        # aviso, não assert: municípios minúsculos podem legitimamente perder
        # TODAS as células z14 (1609m) para um vizinho maior que partilha a
        # mesma célula, a regra é "maior área de intersecção", sem limiar.
        # Não acontece com as 52 províncias (grandes de mais para isto), mas
        # com 8132 municípios é esperado haver alguns. z17 (201m) não devia
        # ter este problema, é fino a mais para isso ser comum.
        if faltam:
            print(f"aviso: {len(faltam)}/{len(nomes_municipio)} municípios {cc} sem total nenhum "
                  f"em nenhum zoom (provavelmente minúsculos, perderam sempre para um vizinho maior): "
                  f"{sorted(faltam)[:10]}{'...' if len(faltam) > 10 else ''}")
        print(f"município {cc}: {len(result[chave])}/{len(nomes_municipio)} com total em pelo menos 1 zoom")


if __name__ == "__main__":
    main()
