"""Busca e descodifica os vector tiles da Squadrats para um atleta (UID Firebase),
substituindo o export manual de KML.

Endpoint não documentado, sem API pública, ver a secção "Vector-tile endpoint
usage rules" do README para o que se descobriu do formato e para as regras de
uso: User-Agent identificável, concorrência baixa, nunca publicar tiles em bruto.
"""
import gzip
import json
import math
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import mapbox_vector_tile
import requests
from shapely.geometry import Polygon, box
from shapely.ops import unary_union
from shapely.validation import make_valid

from kml_parse import reconstruct_squares

USER_AGENT = "squadrats-club-sync/1.0 (+github.com/JustAnotherDud/squadrats-club)"
# Concorrência baixa de propósito (servidor de terceiros). Não subir sem medir
# se aparecem 500s ou lentidão.
DISCOVERY_CONCURRENCY = 4
FETCH_CONCURRENCY = 6
REQUEST_TIMEOUT = 15

# camadas cuja geometria é reconstruída em squares individuais
GEOMETRY_LAYERS = {"squadrats": 14, "squadratinhos": 17}
# camadas de troféu. O `size` não significa o mesmo nas duas (ver README):
# yard = squares do maior cluster fechado; ubersquadrat = o N do NxN.
TROPHY_LAYERS = [
    "yard", "yardinho", "ubersquadrat", "ubersquadratinho",
]

# Descoberta em cascata: começa em z4 sobre o mundo habitado e só desce dentro
# dos tiles com cobertura. Assim não é preciso manter um bbox por atleta.
WORLD_BBOX = (-180.0, -60.0, 180.0, 75.0)
DISCOVERY_LEVELS = (4, 7, 10)

# O servidor devolve a geometria exacta a qualquer zoom (só recortada a um
# bbox maior); testado até z7, perde squares a partir de z4. z10 deixa margem
# e pede 16x menos tiles do que z12.
FETCH_ZOOM = 10

# Cache de cobertura: os tiles z10 onde cada UID tem squares, para saltar a
# descoberta na corrida seguinte. Se o atleta capturar numa zona nova, a
# reconstrução deixa de bater com o `size` do servidor e corre-se a descoberta
# completa, que refaz a cache. Guarda só coordenadas z10 (nunca tiles em
# bruto), mais grosseiras do que o club.json já publica.
COVERAGE_CACHE_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "scan_cache.json"
)


def _read_coverage_cache():
    try:
        with open(COVERAGE_CACHE_PATH, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _write_coverage_cache(uid, tiles, probe_tile=None):
    cache = _read_coverage_cache()
    entry = {
        "bbox": list(WORLD_BBOX),
        "discovery_levels": list(DISCOVERY_LEVELS),
        "fetch_zoom": FETCH_ZOOM,
        "coarse_zoom": DISCOVERY_LEVELS[-1],
        "tiles": sorted(list(t) for t in tiles),
    }
    if probe_tile is not None:
        entry["probe_tile"] = list(probe_tile)
    elif uid in cache and "probe_tile" in cache[uid]:
        entry["probe_tile"] = cache[uid]["probe_tile"]  # preserva o que já lá estava
    cache[uid] = entry
    os.makedirs(os.path.dirname(COVERAGE_CACHE_PATH), exist_ok=True)
    with open(COVERAGE_CACHE_PATH, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, separators=(",", ":"))


def deg2num(lon, lat, z):
    n = 2 ** z
    x = int((lon + 180.0) / 360.0 * n)
    r = math.radians(lat)
    y = int((1.0 - math.log(math.tan(r) + 1 / math.cos(r)) / math.pi) / 2.0 * n)
    return x, y


def tile_to_lonlat(gx, gy, z):
    """Canto NW, como kml_parse._tile_nw, mas aceita coordenadas fracionárias."""
    n = 2 ** z
    lon = gx / n * 360.0 - 180.0
    lat = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * gy / n))))
    return lon, lat


def tile_url(uid, z, x, y):
    ts = int(time.time() * 1000)  # o servidor ignora-o, mas é a chave de cache do URL
    return f"https://tiles1.squadrats.com/{uid}/trophies/{ts}/{z}/{x}/{y}.pbf"


class SquadratsHttpError(RuntimeError):
    """UID inválido (500): falhar alto em vez de devolver o último valor bom."""


_thread_local = threading.local()


def _thread_session():
    """Uma requests.Session por thread: a Session não é garantidamente
    thread-safe."""
    session = getattr(_thread_local, "session", None)
    if session is None:
        session = requests.Session()
        _thread_local.session = session
    return session


def fetch_tile(uid, z, x, y):
    resp = _thread_session().get(
        tile_url(uid, z, x, y),
        headers={"User-Agent": USER_AGENT},
        timeout=REQUEST_TIMEOUT,
    )
    if resp.status_code == 204:
        return None  # tile sem cobertura, normal, não é erro
    if resp.status_code == 500:
        raise SquadratsHttpError(f"UID inválido ou erro do servidor para {uid} em {z}/{x}/{y}")
    resp.raise_for_status()

    data = resp.content
    # às vezes vem gzip sem Content-Encoding; confirmar pelos magic bytes
    if data[:2] == b"\x1f\x8b":
        data = gzip.decompress(data)
    # y_coord_down=True: Y cresce para baixo, como no XYZ. Sem isto cada tile
    # fica espelhado; a contagem bate na mesma, só as posições ficam erradas.
    return mapbox_vector_tile.decode(data, default_options={"y_coord_down": True})


def _project_geometry(geom, z, x, y, extent):
    """Devolve uma lista de polígonos (lon/lat), normalmente 1, mas o recorte
    ao tile pode dividir a forma em mais do que uma parte."""
    rings = geom["coordinates"] if geom["type"] == "Polygon" else [
        ring for poly in geom["coordinates"] for ring in poly
    ]
    raw = Polygon(rings[0], rings[1:])
    if not raw.is_valid:
        raw = make_valid(raw)

    # O MVT traz um buffer à volta do tile que repete a área do vizinho. Sem
    # recortar ao tile nominal, a união engorda e a contagem de squares sobe.
    tile_box = box(0, 0, extent, extent)
    clipped = raw.intersection(tile_box)
    if clipped.is_empty:
        return []

    # o recorte pode dar GeometryCollection; só interessam as partes com área
    if clipped.geom_type in ("Polygon", "MultiPolygon"):
        raw_parts = clipped.geoms if clipped.geom_type == "MultiPolygon" else [clipped]
    else:
        raw_parts = [g for g in getattr(clipped, "geoms", [clipped]) if g.geom_type == "Polygon"]
    parts = [p for p in raw_parts if not p.is_empty and p.area > 0]
    projected = []
    for part in parts:
        ext_ring = [tile_to_lonlat(x + px / extent, y + py / extent, z) for px, py in part.exterior.coords]
        hole_rings = [
            [tile_to_lonlat(x + px / extent, y + py / extent, z) for px, py in interior.coords]
            for interior in part.interiors
        ]
        poly = Polygon(ext_ring, hole_rings)
        projected.append(poly if poly.is_valid else make_valid(poly))
    return projected


def _fetch_batch(uid, z, candidates):
    """Devolve o subconjunto de `candidates` (x, y) com cobertura (200) a este zoom."""
    covered = []
    with ThreadPoolExecutor(max_workers=DISCOVERY_CONCURRENCY) as pool:
        futures = {pool.submit(fetch_tile, uid, z, x, y): (x, y) for x, y in candidates}
        for fut, xy in futures.items():
            if fut.result() is not None:
                covered.append(xy)
    return covered


def discover_coverage(uid):
    """Descoberta em cascata, devolve os tiles (x, y) com cobertura no último
    zoom de DISCOVERY_LEVELS. Cada nível só explora os filhos dos tiles com
    cobertura no anterior, por isso o custo cresce com a cobertura real."""
    levels = DISCOVERY_LEVELS
    lon_min, lat_min, lon_max, lat_max = WORLD_BBOX
    z0 = levels[0]
    x0, y1 = deg2num(lon_min, lat_min, z0)
    x1, y0 = deg2num(lon_max, lat_max, z0)
    xlo, xhi = min(x0, x1), max(x0, x1)
    ylo, yhi = min(y0, y1), max(y0, y1)
    current = [(x, y) for x in range(xlo, xhi + 1) for y in range(ylo, yhi + 1)]

    for i, z in enumerate(levels):
        hits = _fetch_batch(uid, z, current)
        print(f"descoberta z{z}: {len(hits)}/{len(current)} tiles com cobertura")
        if i == len(levels) - 1:
            return hits
        next_z = levels[i + 1]
        factor = 2 ** (next_z - z)
        current = [
            (hx * factor + dx, hy * factor + dy)
            for hx, hy in hits
            for dx in range(factor) for dy in range(factor)
        ]
    return current


_CACHE = {}


def scan_athlete(uid, with_trophy_geometry=False, known_squadratinhos=None):
    """Varre o atleta uma vez por processo (três consumidores partilham o
    resultado, ver run_all.py) e devolve conforme o que o chamador pediu.

    `known_squadratinhos`: último total publicado. Se o probe de 1 pedido
    confirmar que não mudou, devolve None e o chamador reaproveita a
    publicação anterior.
    """
    if uid not in _CACHE:
        _CACHE[uid] = _scan_athlete(uid, known_squadratinhos)
    else:
        print(f"{uid}: já varrido neste processo, a reutilizar")

    resultado = _CACHE[uid]
    if resultado is None:
        return None
    geometries, counts, trophies = resultado
    if with_trophy_geometry:
        return geometries, counts, trophies
    return geometries, counts


def _children(tiles, factor):
    return [(cx * factor + dx, cy * factor + dy)
            for cx, cy in tiles
            for dx in range(factor) for dy in range(factor)]


def _fetch_missing(uid, zoom, candidates, results):
    """Busca os `candidates` que ainda não estão em `results` e acumula lá
    ({(x, y): decoded|None})."""
    to_fetch = [xy for xy in candidates if xy not in results]
    with ThreadPoolExecutor(max_workers=FETCH_CONCURRENCY) as pool:
        futures = {pool.submit(fetch_tile, uid, zoom, x, y): (x, y) for x, y in to_fetch}
        for fut, xy in futures.items():
            results[xy] = fut.result()


def _assemble_layers(results):
    """Projecta e une os tiles descodificados nas camadas finais, devolve
    (geometries, counts, trophies)."""
    polys_by_layer = {name: [] for name in [*GEOMETRY_LAYERS, *TROPHY_LAYERS]}
    size_by_layer = {}

    for (x, y), decoded in results.items():
        if decoded is None:
            continue
        for layer_name, layer in decoded.items():
            if layer_name not in GEOMETRY_LAYERS and layer_name not in TROPHY_LAYERS:
                continue  # ex: squadratsoutline
            for feat in layer["features"]:
                size = feat["properties"].get("size")
                if size is not None and layer_name not in size_by_layer:
                    size_by_layer[layer_name] = size  # total global, igual em todos os tiles
                polys_by_layer[layer_name].extend(
                    _project_geometry(feat["geometry"], FETCH_ZOOM, x, y, layer["extent"])
                )

    geometries = {}
    for name in GEOMETRY_LAYERS:
        if not polys_by_layer[name]:
            continue
        merged = unary_union(polys_by_layer[name])
        geometries[name] = (size_by_layer.get(name), merged)

    counts = {name: size_by_layer[name] for name in TROPHY_LAYERS if name in size_by_layer}

    trophies = {name: unary_union(polys_by_layer[name])
                for name in TROPHY_LAYERS if polys_by_layer[name]}
    return geometries, counts, trophies


def squares_validados(geometries, name, uid):
    """Squares (x, y, lon, lat) da camada, validados contra o `size` do
    servidor. Camada ausente dá [] com aviso: é também o que um UID errado
    devolve (204 em todos os tiles)."""
    if name not in geometries:
        print(f"ATENÇÃO: UID '{uid}' devolveu 0 squares em '{name}', confirma se o UID está certo (squadrats.com/map/{uid}/17)")
        return []
    declared, geom = geometries[name]
    squares = reconstruct_squares(geom, GEOMETRY_LAYERS[name])
    if declared is None or len(squares) != declared:
        raise RuntimeError(
            f"UID '{uid}': {name}, reconstruídos {len(squares)}, servidor diz "
            f"{declared}. Varrimento incompleto ou bug de geometria, a abortar sem publicar."
        )
    return squares


def _coverage_complete(geometries):
    """True se a reconstrução bate com o `size` do servidor em todas as
    camadas presentes, ou seja, a cache de cobertura apanhou tudo."""
    if not geometries:
        return False
    for name, zoom in GEOMETRY_LAYERS.items():
        if name not in geometries:
            continue
        declared, geom = geometries[name]
        if declared is None or len(reconstruct_squares(geom, zoom)) != declared:
            return False
    return True


def _serve_para_probe(decoded):
    """True se o tile tem a camada squadratinhos com `size`. Um tile pode ter
    squadrats sem squadratinhos, e como probe_tile deixava o probe sempre
    inconclusivo."""
    if decoded is None or "squadratinhos" not in decoded:
        return False
    return any(f["properties"].get("size") is not None
               for f in decoded["squadratinhos"]["features"])


def _probe_sem_alteracoes(uid, probe_tile, known_squadratinhos):
    """1 pedido a um tile conhecido: lê o total global de squadratinhos e
    compara com `known_squadratinhos`. Igualdade estrita, porque apagar uma
    actividade pode fazer o total descer. Em caso de dúvida devolve False
    (scan completo)."""
    x, y = probe_tile
    try:
        decoded = fetch_tile(uid, FETCH_ZOOM, x, y)
    except SquadratsHttpError:
        return False
    if decoded is None or "squadratinhos" not in decoded:
        return False
    for feat in decoded["squadratinhos"]["features"]:
        size = feat["properties"].get("size")
        if size is not None:
            return size == known_squadratinhos
    return False


def _scan_athlete(uid, known_squadratinhos=None):
    """Devolve (geometries, counts, trophies) ou None se o probe confirmar
    que nada mudou.
    - geometries: {layer: (size, shapely_geom)} para squadrats/squadratinhos
    - counts: {layer: size} para as camadas de troféu
    - trophies: {layer: shapely_geom}

    Usa a cobertura z10 de data/scan_cache.json; se a reconstrução não bater
    com o `size` do servidor, faz a descoberta completa sem repetir tiles.
    """
    coarse_zoom = DISCOVERY_LEVELS[-1]
    factor = 2 ** (FETCH_ZOOM - coarse_zoom)
    results = {}

    entry = _read_coverage_cache().get(uid)
    cache_applicable = (
        entry is not None
        and entry.get("bbox") == list(WORLD_BBOX)
        and entry.get("discovery_levels") == list(DISCOVERY_LEVELS)
        and entry.get("fetch_zoom") == FETCH_ZOOM
    )
    if cache_applicable and known_squadratinhos is not None and entry.get("probe_tile"):
        probe_tile = tuple(entry["probe_tile"])
        if _probe_sem_alteracoes(uid, probe_tile, known_squadratinhos):
            print(f"{uid}: probe confirma squadratinhos={known_squadratinhos} sem alteração, "
                  f"a saltar scan completo (1 pedido em vez de dezenas/centenas)")
            return None
        print(f"{uid}: probe indica alteração (ou inconclusivo), a continuar com o scan normal")

    if cache_applicable:
        cached_coarse = [tuple(t) for t in entry["tiles"]]
        candidates = _children(cached_coarse, factor)
        print(f"cobertura em cache: {len(cached_coarse)} tiles z{coarse_zoom}, "
              f"a buscar {len(candidates)} tiles z{FETCH_ZOOM} sem descoberta...")
        _fetch_missing(uid, FETCH_ZOOM, candidates, results)
        geometries, counts, trophies = _assemble_layers(results)
        if _coverage_complete(geometries):
            # refresca o probe_tile (sem pedidos extra) para a próxima corrida
            probe_tile = next((xy for xy, d in results.items() if _serve_para_probe(d)), None)
            _write_coverage_cache(uid, cached_coarse, probe_tile)
            return geometries, counts, trophies
        print("cache de cobertura desatualizada (reconstrução não bate com o size "
              "do servidor, squares numa zona nova?), descoberta completa...")

    coarse_covered = discover_coverage(uid)
    candidates = _children(coarse_covered, factor)
    print(f"a buscar {len(candidates)} tiles z{FETCH_ZOOM}...")
    _fetch_missing(uid, FETCH_ZOOM, candidates, results)
    geometries, counts, trophies = _assemble_layers(results)

    # cobertura real = tiles de coarse_zoom com conteúdo no fetch fino
    with_data = {(x // factor, y // factor) for (x, y), d in results.items() if d is not None}
    probe_tile = next((xy for xy, d in results.items() if d is not None), None)
    _write_coverage_cache(uid, with_data, probe_tile)
    return geometries, counts, trophies
