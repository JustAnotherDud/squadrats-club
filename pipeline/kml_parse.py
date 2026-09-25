"""Geometria da grelha XYZ do Squadrats: conversão lon/lat <-> tile e
reconstrução dos squares individuais (x, y, zoom) a partir de um polígono.
O nome vem do tempo em que o pipeline lia KML.
"""
import math

# zoom XYZ correspondente a cada categoria do squadrats.com
ZOOM_BY_TYPE = {
    "squadrats": 14,
    "squadratinhos": 17,
}


def lonlat_to_tile(lon, lat, z):
    n = 2 ** z
    x = int((lon + 180.0) / 360.0 * n)
    lat_rad = math.radians(lat)
    y = int((1.0 - math.asinh(math.tan(lat_rad)) / math.pi) / 2.0 * n)
    return x, y


def _tile_nw(x, y, z):
    """Canto NW (lon, lat) do tile x/y no zoom z, convenção XYZ standard."""
    n = 2 ** z
    lon = x / n * 360.0 - 180.0
    lat = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * y / n))))
    return lon, lat


def tile_center(x, y, z):
    lon1, lat1 = _tile_nw(x, y, z)
    lon2, lat2 = _tile_nw(x + 1, y + 1, z)
    return (lon1 + lon2) / 2, (lat1 + lat2) / 2


def tile_bounds(x, y, z):
    """Polígono (shapely box) da área coberta pelo tile x/y/zoom."""
    from shapely.geometry import box

    lon1, lat1 = _tile_nw(x, y, z)
    lon2, lat2 = _tile_nw(x + 1, y + 1, z)
    return box(min(lon1, lon2), min(lat1, lat2), max(lon1, lon2), max(lat1, lat2))


def reconstruct_squares(geom, zoom):
    """(x, y, lon, lat) dos tiles cujo centro cai dentro do polígono. Varre a
    bbox de cada componente em separado: a bbox de tudo junto seria enorme.
    """
    from shapely.geometry import Point
    from shapely.prepared import prep

    components = list(geom.geoms) if hasattr(geom, "geoms") else [geom]

    squares = []
    for part in components:
        minlon, minlat, maxlon, maxlat = part.bounds
        x0, y1 = lonlat_to_tile(minlon, minlat, zoom)
        x1, y0 = lonlat_to_tile(maxlon, maxlat, zoom)
        xlo, xhi = min(x0, x1) - 1, max(x0, x1) + 1
        ylo, yhi = min(y0, y1) - 1, max(y0, y1) + 1

        prepared = prep(part)
        for x in range(xlo, xhi + 1):
            for y in range(ylo, yhi + 1):
                cx, cy = tile_center(x, y, zoom)
                if prepared.contains(Point(cx, cy)):
                    squares.append((x, y, cx, cy))
    return squares
