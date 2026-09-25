"""Janelas de ganho de squadratinhos entre snapshots consecutivos de
squadrats.json, resolução por CORRIDA do pipeline, não por dia (ao
contrário de eventos.snapshots_por_dia, que fica só com o último snapshot
de cada dia UTC: aqui a resolução fina é o ponto todo).

Consumido por append_ganhos.py (passo do run_all.py).

Uma "janela de ganho" é [inicio, fim] = os "atualizado" de dois snapshots
consecutivos de squadrats.json, para um atleta com ganho > 0 de
squadratinhos nesse intervalo.
"""


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
