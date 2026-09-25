"""Totais simples (sem breakdown por concelho/distrito) para todos os atletas
do clube, publica data/squadrats.json, consumido pelo folha-do-clube da mesma
forma que o prs.json. Repos não acoplados: aqui só se escreve o ficheiro,
não se toca no folha-do-clube.

Falha alto se algum UID devolver 500 ou se squadrats/squadratinhos não
baterem com o `size` do servidor, nunca publica o último valor bom em
silêncio (ver tiles_fetch.py).

Uso: py fetch_club_totais.py [pasta_saida]
"""
import argparse
import datetime
import json
import os

import daily_gains
from atletas import ATHLETES, known_squadratinhos
from tiles_fetch import GEOMETRY_LAYERS, scan_athlete, squares_validados

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_DIR = os.path.dirname(HERE)
DATA_DIR = os.path.join(REPO_DIR, "data")


def fetch_totals(uid, known=None):
    """Devolve None se o probe de tiles_fetch.py confirmar que este UID não
    mudou, o chamador tem de reaproveitar a entrada anterior."""
    resultado = scan_athlete(uid, known_squadratinhos=known)
    if resultado is None:
        return None
    geometries, counts = resultado

    totals = dict(counts)
    for name in GEOMETRY_LAYERS:
        totals[name] = len(squares_validados(geometries, name, uid))
    return totals


def main(out_dir):
    # lido uma vez, no início: o "dia" dos ganhos não pode virar a meio de
    # uma corrida que atravesse a meia-noite UTC
    inicio = datetime.datetime.now(datetime.timezone.utc)
    result = {
        "atualizado": inicio.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "atletas": {},
    }

    # totais já publicados: base do probe e do "reaproveitar"
    known = known_squadratinhos(out_dir)
    anteriores = {}
    try:
        with open(os.path.join(out_dir, "squadrats.json"), encoding="utf-8") as f:
            anteriores = json.load(f).get("atletas", {})
    except (FileNotFoundError, json.JSONDecodeError):
        pass

    for name, uid in ATHLETES.items():
        print(f"a varrer {name} ({uid})...")
        totals = fetch_totals(uid, known.get(uid))
        if totals is None:
            totals = anteriores.get(name)
            if totals is None:
                # known só tem UIDs com entrada anterior neste ficheiro
                raise RuntimeError(
                    f"'{name}': probe disse 'sem alterações' mas não há publicação "
                    f"anterior para reaproveitar, inconsistência entre known_squadratinhos "
                    f"e o squadrats.json carregado."
                )
            print(f"{name}: sem alterações, a reaproveitar a publicação anterior")
        result["atletas"][name] = totals
        print(f"{name}: {result['atletas'][name]}")

    out_path = os.path.join(out_dir, "squadrats.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"escrito: {out_path}")

    # base = ultimo_total guardado no próprio daily_gains.json (ver daily_gains.py)
    delta = daily_gains.actualizar(out_dir, result["atletas"], hoje_iso=inicio.date().isoformat())
    if delta:
        print(f"ganhos desde a última corrida: {delta}")
    else:
        print("ganhos desde a última corrida: nenhum")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("out_dir", nargs="?", default=DATA_DIR)
    args = parser.parse_args()
    os.makedirs(args.out_dir, exist_ok=True)
    main(args.out_dir)
