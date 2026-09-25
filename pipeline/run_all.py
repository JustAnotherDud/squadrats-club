"""Orquestrador do pipeline: corre todos os passos no mesmo processo, para
cada atleta ser varrido do Squadrats uma vez só (a cache vive em
tiles_fetch.scan_athlete). Só os três primeiros passos tocam a rede.

Uso: py run_all.py [pasta_saida]
"""
import argparse
import os
import sys
import time

import append_events
import append_gains_regioes
import append_ganhos
import append_regioes
import build_analise
import build_profiles
import classify_club
import fetch_club_squares
import fetch_club_totais
from atletas import JOSE_UID

HERE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(os.path.dirname(HERE), "data")


def main(out_dir):
    inicio = time.time()
    passos = [
        ("análise pessoal", lambda: build_analise.run_from_tiles(JOSE_UID, out_dir)),
        ("totais do clube", lambda: fetch_club_totais.main(out_dir)),
        ("squares do club", lambda: fetch_club_squares.main(out_dir)),
        # depende do club.json escrito no passo anterior (mesma corrida),
        # não volta a varrer o Squadrats, só classifica os squares já ali
        ("regiões do club", lambda: classify_club.main(out_dir)),
        # compara o club_regioes.json anterior (origin/data) com o novo e faz
        # append dos eventos novos a events.json, idempotente entre runs do dia
        ("eventos do club", lambda: append_events.main(out_dir)),
        # janelas de ganho de squadratinhos entre corridas consecutivas do
        # pipeline (data/ganhos.json), recompute total a cada corrida
        ("ganhos (janelas)", lambda: append_ganhos.main(out_dir)),
        # páginas por região: reescreve ranking/totais/união/vizinhos de cada
        # região activa a partir do snapshot novo (data/regioes/<key>.json)
        ("regiões (páginas)", lambda: append_regioes.main(out_dir)),
        # diff club_regioes.json (ontem vs hoje) -> ganhos de squadratinhos
        # por concelho/distrito, por dia (data/gains_regioes.json). Sem
        # classificação nova, o breakdown já está no club_regioes.json
        ("ganhos por região", lambda: append_gains_regioes.main(out_dir)),
        # junta squadrats.json + club.json + club_regioes.json + daily_gains.json
        # + gains_regioes.json + stats.json num perfil por atleta, sem rede
        ("perfis por atleta", lambda: build_profiles.main(out_dir)),
    ]
    for nome, fn in passos:
        t = time.time()
        print(f"\n=== {nome} ===", flush=True)
        fn()
        print(f"--- {nome}: {time.time() - t:.0f}s", flush=True)

    print(f"\ntotal: {time.time() - inicio:.0f}s")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("out_dir", nargs="?", default=DATA_DIR)
    args = parser.parse_args()
    os.makedirs(args.out_dir, exist_ok=True)
    sys.exit(main(args.out_dir))
