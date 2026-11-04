"""Regenera o events.json inteiro desde eventos.DESDE com o método novo
(entradas combinadas, ver eventos.combinar). Uso único, a correr à mão:

    python pipeline/regenerar_events.py <events.json de saída> [--atual <events.json actual>]

Não toca em git nem em data/: só lê `origin/data` e escreve o ficheiro dado.

- Dias com par de snapshots de club_regioes.json em origin/data: recalculados
  (último snapshot do dia anterior vs último do dia, como o append_events).
- Dias até ao 1.º snapshot de club_regioes.json (reconstruídos do club.json, não
  dá para recalcular): os eventos planos de `--atual` convertidos com
  eventos.migrar_planos.
- Marcos de totais: recalculados onde houver squadrats.json; os já publicados
  de dias não recalculáveis ficam como estão.
"""
import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone

import append_events
import eventos
from util import iso_utc


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("saida")
    ap.add_argument("--atual", help="events.json actual (formato antigo), para os dias que não se recalculam")
    a = ap.parse_args()
    repo = append_events.REPO

    por_dia, saltados = eventos.snapshots_por_dia(repo, "origin/data", desde=eventos.DESDE)
    sq_por_dia, _ = eventos.snapshots_por_dia(repo, "origin/data", desde=eventos.DESDE,
                                              path="data/squadrats.json")
    dias = sorted(por_dia)
    if len(dias) < 2:
        sys.exit("regenerar_events: histórico de origin/data insuficiente")
    hoje = dias[-1]
    novos, datas = append_events.calcular(dias, por_dia, sq_por_dia, hoje)
    if saltados:
        print(f"AVISO: {len(saltados)} snapshot(s) ilegível(is) no histórico")

    legado = []
    if a.atual:
        with open(a.atual, encoding="utf-8") as f:
            antigos = json.load(f)["eventos"]
        # tudo o que o walk não regenera: dias sem par de snapshots (>= 1.º dia
        # do histórico fica de fora do walk, é o dia-base)
        for e in antigos:
            if e["data"] in datas:
                continue
            legado.append(e)
        regionais = [e for e in legado if e["tipo"] not in eventos.TIPOS_TOTAIS and "partes" not in e]
        resto = [e for e in legado if e not in regionais]
        legado = eventos.migrar_planos(regionais) + resto
        print(f"dias não recalculáveis: {len({e['data'] for e in legado})} "
              f"({min((e['data'] for e in legado), default='-')}..{max((e['data'] for e in legado), default='-')}), "
              f"{len(regionais)} evento(s) plano(s) -> {len(eventos.migrar_planos(regionais))} entrada(s)")

    out = {"gerado": iso_utc(datetime.now(timezone.utc)), "desde": eventos.DESDE,
           "eventos": eventos.ordenar_feed(legado + novos)}
    os.makedirs(os.path.dirname(os.path.abspath(a.saida)), exist_ok=True)
    with open(a.saida, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, separators=(",", ":"))
    print(f"{len(out['eventos'])} evento(s) em {a.saida} (recalculados: {len(novos)}, "
          f"dias {min(datas)}..{max(datas)})")


if __name__ == "__main__":
    main()
