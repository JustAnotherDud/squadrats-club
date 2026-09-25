"""tiles_fetch._scan_athlete no caminho da descoberta completa, com tiles falsos
(já descodificados, sem rede)."""
import json

import pytest

import tiles_fetch


def _quadrado(px, lado):
    return {"type": "Polygon",
            "coordinates": [[[px, 0], [px + lado, 0], [px + lado, lado], [px, lado], [px, 0]]]}


def _camada(quadrados, lado, size):
    return {"extent": 4096,
            "features": [{"geometry": _quadrado(px, lado), "properties": {"size": size}}
                         for px in quadrados]}


# dois tiles z10 vizinhos: o primeiro só tem squadrats (sem squadratinhos),
# o segundo tem as duas camadas
TILES = {
    (500, 390): {"squadrats": _camada([0], 256, 2)},
    (501, 390): {"squadrats": _camada([0], 256, 2), "squadratinhos": _camada([0], 32, 1)},
}


@pytest.fixture
def servidor(tmp_path, monkeypatch):
    pedidos = []

    def fetch_tile(uid, z, x, y):
        pedidos.append((z, x, y))
        k = 10 - z
        if z == 10:
            return TILES.get((x, y))
        return {"squadrats": {}} if any((tx >> k, ty >> k) == (x, y) for tx, ty in TILES) else None

    monkeypatch.setattr(tiles_fetch, "fetch_tile", fetch_tile)
    monkeypatch.setattr(tiles_fetch, "COVERAGE_CACHE_PATH", str(tmp_path / "scan_cache.json"))
    return pedidos


def _cache(uid):
    with open(tiles_fetch.COVERAGE_CACHE_PATH, encoding="utf-8") as f:
        return json.load(f)[uid]


def test_probe_tile_tem_squadratinhos(servidor):
    geometries, _, _ = tiles_fetch._scan_athlete("u")
    assert geometries["squadratinhos"][0] == 1
    assert _cache("u")["probe_tile"] == [501, 390]
    # a corrida seguinte confirma "sem alterações" com 1 pedido
    servidor.clear()
    assert tiles_fetch._scan_athlete("u", known_squadratinhos=1) is None
    assert servidor == [(10, 501, 390)]
