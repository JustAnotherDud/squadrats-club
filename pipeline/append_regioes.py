"""Passo do run_all.py: reescreve data/regioes/<key>.json.

Recomputa ranking/totais/união/vizinhos de cada região activa a partir do
club_regioes.json novo. Idempotente: escreve o estado actual, sem histórico
acumulado. O workflow faz mirror da pasta, portanto uma região que deixou de
ter actividade desaparece sozinha.
"""
import os
from datetime import datetime, timezone

import regioes
from util import iso_utc, load_json

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
# só se usa para o lookup concelho -> distrito (properties.parent), geometria
# nenhuma; lê da fonte de precisão (refdata), não da cópia simplificada de
# data/ que agora só serve para o analise.html desenhar.
CONCELHOS_GEO = os.path.join(HERE, "refdata", "concelhos_pt.geojson")
FOREIGN_MUNI_DIR = os.path.join(HERE, "refdata", "foreign_muni")


def main(out_dir):
    novo = load_json(os.path.join(out_dir, "club_regioes.json"))
    if not novo:
        print("append_regioes: sem club_regioes.json novo, nada a fazer")
        return

    ativas = regioes.regioes_ativas(novo)
    # as fronteiras (regioes.fronteira_de) saem das cópias simplificadas em
    # data/*.geojson, que ficam ao lado dos JSON de saída
    regioes.DATA_GEOJSON_DIR = out_dir
    stats = load_json(os.path.join(out_dir, "stats.json")) or {}
    adjacency = load_json(os.path.join(REPO, "data", "adjacency.json")) or {}
    gerado = iso_utc(datetime.now(timezone.utc))

    # "disputada" no índice = evento de troca real (ultrapassagem / novo
    # líder), igual ao historico.html e ao regiao.js. O events.json já está
    # escrito neste ponto, o append_events corre antes deste passo.
    disputadas = regioes.disputadas_de(
        (load_json(os.path.join(out_dir, "events.json")) or {}).get("eventos", []))

    indice = []
    n = 0
    for nivel in regioes.NIVEIS:
        for nome in sorted(ativas[nivel]):
            reg = regioes.construir(nivel, nome, novo, stats, adjacency,
                                    ativas, CONCELHOS_GEO)
            regioes.escrever(out_dir, reg, gerado)
            indice.append(regioes.linha_indice(reg, disputadas))
            n += 1

    # estrangeiro: província/Land/région (regiao) e município/cercle (zona).
    ativas_estr = regioes.ativas_estrangeiro(novo)
    ne = 0
    for ccl, niveis in sorted(ativas_estr.items()):
        pmap = regioes.parent_map_estrangeiro(
            os.path.join(FOREIGN_MUNI_DIR, f"{ccl.upper()}.geojson"))
        for nivel in ("regiao", "zona"):
            for nome in sorted(niveis[nivel]):
                reg = regioes.construir_estrangeiro(
                    ccl, nivel, nome, novo, stats, adjacency, ativas_estr,
                    pmap.get(nome))
                regioes.escrever(out_dir, reg, gerado)
                indice.append(regioes.linha_indice(reg, disputadas))
                ne += 1

    # país: PT + cada estrangeiro com actividade (uniao.by_pais). As
    # sub-regiões vêm do índice por pai_key, não vão no ficheiro de país.
    paises = sorted((novo.get("uniao") or {}).get("by_pais") or {})
    for cc in paises:
        reg = regioes.construir_pais(cc, novo, stats, adjacency, set(paises))
        regioes.escrever(out_dir, reg, gerado)
        indice.append(regioes.linha_indice(reg, disputadas))

    regioes.escrever_indice(out_dir, indice, gerado)
    print(f"append_regioes: {n} PT + {ne} estrangeiras + {len(paises)} países, "
          f"{len(disputadas)} disputadas -> regioes_index.json")
