"""Janelas de ganho de squadratinhos entre snapshots consecutivos de
squadrats.json, resolução por CORRIDA do pipeline, não por dia (ao
contrário de eventos.snapshots_por_dia, que fica só com o último snapshot
de cada dia UTC: aqui a resolução fina é o ponto todo).

Consumido por append_ganhos.py (passo do run_all.py).

Uma "janela de ganho" é [inicio, fim] = os "atualizado" de dois snapshots
consecutivos de squadrats.json, para um atleta com ganho > 0 de
squadratinhos nesse intervalo.
"""
import json
import subprocess
from datetime import datetime


def _iso(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def snapshots_todos(repo, branch="origin/data", path="data/squadrats.json"):
    """[(datetime, dict), ...] em ordem cronológica, um por commit (cada
    commit é uma corrida). Salta e avisa commits ilegíveis; levanta
    RuntimeError se nenhum for legível."""
    args = ["git", "-C", repo, "log", branch, "--format=%H", "--reverse", "--", path]
    shas = subprocess.run(args, capture_output=True, text=True,
                          encoding="utf-8", check=True).stdout.split()

    snaps, saltados = [], []
    for sha in shas:
        r = subprocess.run(["git", "-C", repo, "show", f"{sha}:{path}"],
                           capture_output=True, text=True, encoding="utf-8")
        if r.returncode != 0:
            saltados.append((sha, "blob em falta (checkout shallow?)"))
            continue
        try:
            d = json.loads(r.stdout)
            ts = _iso(d["atualizado"])
        except Exception as e:
            saltados.append((sha, f"squadrats.json inesperado: {type(e).__name__}: {e}"))
            continue
        snaps.append((ts, d))

    if saltados:
        from collections import Counter
        resumo = Counter(m for _, m in saltados)
        print(f"snapshots_todos: {len(saltados)}/{len(shas)} commit(s) saltado(s), "
              + "; ".join(f"{n}x {m}" for m, n in resumo.most_common()))
    if shas and not snaps:
        raise RuntimeError(
            f"snapshots_todos: {len(shas)} commit(s) de {path} em {branch}, "
            "nenhum legível. Clone shallow demais? "
            "(o workflow faz `git fetch origin data --depth=500`)."
        )
    snaps.sort(key=lambda p: p[0])
    return snaps


def deltas_squadratinhos(snaps):
    """[{"atleta", "inicio", "fim", "ganho"}, ...]: ganho de squadratinhos
    por atleta entre snapshots consecutivos, só onde ganho > 0."""
    janelas = []
    for (t0, d0), (t1, d1) in zip(snaps, snaps[1:]):
        antes, depois = d0.get("atletas", {}), d1.get("atletas", {})
        for nome, info in depois.items():
            total_novo = info.get("squadratinhos", 0)
            total_velho = (antes.get(nome) or {}).get("squadratinhos", 0)
            ganho = total_novo - total_velho
            if ganho > 0:
                janelas.append({"atleta": nome, "inicio": t0, "fim": t1, "ganho": ganho})
    return janelas
