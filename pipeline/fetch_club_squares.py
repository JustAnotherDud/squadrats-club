"""Squadratinhos de todos os atletas num ficheiro só, data/club.json.

Cada square sai como [x, y, mask], em que mask é o bitmask de quem o tem
(bit 0 = primeiro atleta de ATHLETES_JSON). Assim os squares partilhados não
se repetem. Só z17: a z14 quase tudo é partilhado.

Uso: py fetch_club_squares.py [pasta_saida]
"""
import argparse
import datetime
import json
import os

from atletas import ATLETAS, known_squadratinhos
from kml_parse import reconstruct_squares
from slugs import slugify
from tiles_fetch import scan_athlete

HERE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(os.path.dirname(HERE), "data")

CAMADA = "squadratinhos"
ZOOM = 17


def squares_de(uid, known=None, anteriores_squares=None, bit=None):
    """Conjunto de (x, y) do atleta, validado contra o `size` do servidor.

    Se o probe de tiles_fetch.py confirmar "sem alterações", reaproveita o
    conjunto anterior deste atleta a partir do bitmask já publicado em
    club.json, filtrado pelo bit dele, `anteriores_squares` traz todos os
    atletas juntos."""
    resultado = scan_athlete(uid, known_squadratinhos=known)
    if resultado is None:
        return {(x, y) for x, y, m in (anteriores_squares or []) if m & bit}
    geometries, _ = resultado
    if CAMADA not in geometries:
        # zero é aceite, mas também é o que um UID errado devolve, por isso avisa
        print(f"ATENÇÃO: UID '{uid}' devolveu 0 squares em '{CAMADA}', confirma se o UID está certo (squadrats.com/map/{uid}/17)")
        return set()

    declared_size, geom = geometries[CAMADA]
    squares = {(x, y) for x, y, _lon, _lat in reconstruct_squares(geom, ZOOM)}
    if declared_size is None or len(squares) != declared_size:
        raise RuntimeError(
            f"UID '{uid}': {CAMADA}, reconstruídos {len(squares)}, servidor diz "
            f"{declared_size}. Varrimento incompleto ou bug de geometria, a abortar "
            f"sem publicar club.json."
        )
    return squares


def main(out_dir):
    known = known_squadratinhos(out_dir)
    anteriores_squares = []
    try:
        with open(os.path.join(out_dir, "club.json"), encoding="utf-8") as f:
            anteriores_squares = json.load(f).get("squares", [])
    except (FileNotFoundError, json.JSONDecodeError):
        pass

    por_atleta = {}
    for i, (nome, uid) in enumerate(ATLETAS):
        print(f"a varrer {nome} ({uid})...")
        por_atleta[nome] = squares_de(uid, known.get(uid), anteriores_squares, 1 << i)
        print(f"{nome}: {len(por_atleta[nome])} squadratinhos")

    mascaras = {}
    for i, (nome, _uid) in enumerate(ATLETAS):
        for s in por_atleta[nome]:
            mascaras[s] = mascaras.get(s, 0) | (1 << i)

    # exclusivo = mask com um bit só, e esse bit é o do atleta
    atletas_out = []
    for i, (nome, _uid) in enumerate(ATLETAS):
        bit = 1 << i
        exclusivos = sum(1 for m in mascaras.values() if m == bit)
        atletas_out.append({
            "nome": nome,
            "slug": slugify(nome),  # liga o club.html a /atletas/<slug>.html
            "total": len(por_atleta[nome]),
            "exclusivos": exclusivos,
            "partilhados": len(por_atleta[nome]) - exclusivos,
        })

    # quantos squares por combinação, a legenda mostra isto sem ter de contar
    por_mask = {}
    for m in mascaras.values():
        por_mask[m] = por_mask.get(m, 0) + 1

    resultado = {
        "atualizado": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "zoom": ZOOM,
        "atletas": atletas_out,
        "por_mask": {str(k): v for k, v in sorted(por_mask.items())},
        "squares": [[x, y, m] for (x, y), m in sorted(mascaras.items())],
    }

    out_path = os.path.join(out_dir, "club.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(resultado, f, ensure_ascii=False, separators=(",", ":"))
    print(f"{len(mascaras)} squares distintos -> {out_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("out_dir", nargs="?", default=DATA_DIR)
    args = parser.parse_args()
    os.makedirs(args.out_dir, exist_ok=True)
    main(args.out_dir)
