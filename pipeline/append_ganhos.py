"""Passo do run_all.py: recalcula data/ganhos.json do zero a cada corrida
(janelas de ganho de squadratinhos, ver ganhos.py).

Recompute total, não incremental: o histórico de squadrats.json na branch
`data` já é a fonte de verdade completa, por isso recalcular tudo a cada
corrida dá sempre o mesmo resultado correcto, sem estado próprio a poder
desalinhar. Precisa do histórico completo da branch (o workflow faz o
fetch sem --depth). Custo: um `git show` por commit de squadrats.json.
"""
import json
import os
from datetime import datetime, timezone

import eventos
import ganhos

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)


def main(out_dir):
    novo_path = os.path.join(out_dir, "squadrats.json")
    if not os.path.exists(novo_path):
        print("append_ganhos: sem squadrats.json novo, nada a fazer")
        return
    with open(novo_path, encoding="utf-8") as f:
        hoje = json.load(f)

    # histórico publicado + o snapshot desta corrida (ainda não commitado),
    # mesmo princípio do "hoje" no append_events.py
    snaps, _ = eventos.snapshots_commits(REPO, "origin/data", "data/squadrats.json")
    hoje_ts = datetime.fromisoformat(hoje["atualizado"].replace("Z", "+00:00"))
    snaps.append((hoje_ts, hoje))
    snaps.sort(key=lambda p: p[0])

    janelas = ganhos.deltas_squadratinhos(snaps)
    resultado = [
        {"atleta": j["atleta"], "inicio": j["inicio"].strftime("%Y-%m-%dT%H:%M:%SZ"),
         "fim": j["fim"].strftime("%Y-%m-%dT%H:%M:%SZ"), "ganho": j["ganho"]}
        for j in janelas
    ]

    out = {
        "gerado": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "janelas": resultado,
    }
    caminho = os.path.join(out_dir, "ganhos.json")
    with open(caminho, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, separators=(",", ":"))

    print(f"append_ganhos: {len(resultado)} janela(s) de ganho -> ganhos.json")
