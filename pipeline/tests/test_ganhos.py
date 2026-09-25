"""Testes de ganhos.py: deltas entre snapshots consecutivos de
squadrats.json. A leitura do git (eventos.snapshots_commits) fica de fora.

Correr: py -m pytest
"""
from datetime import datetime, timezone

from ganhos import deltas_squadratinhos


def _dt(s):
    return datetime.fromisoformat(s).replace(tzinfo=timezone.utc)


def _snap(ts, **atletas):
    return (_dt(ts), {"atualizado": ts, "atletas": {n: {"squadratinhos": v} for n, v in atletas.items()}})


def test_ganho_positivo_vira_janela():
    snaps = [_snap("2026-09-10T08:00:00", Ze=100), _snap("2026-09-10T12:00:00", Ze=142)]
    janelas = deltas_squadratinhos(snaps)
    assert len(janelas) == 1
    assert janelas[0] == {"atleta": "Ze", "inicio": _dt("2026-09-10T08:00:00"),
                          "fim": _dt("2026-09-10T12:00:00"), "ganho": 42}


def test_sem_ganho_nao_gera_janela():
    snaps = [_snap("2026-09-10T08:00:00", Ze=100), _snap("2026-09-10T12:00:00", Ze=100)]
    assert deltas_squadratinhos(snaps) == []


def test_atleta_novo_no_snapshot_nao_rebenta():
    # Carolina não existia no snapshot anterior: total_velho = 0, ganho = total novo
    snaps = [_snap("2026-09-10T08:00:00"), _snap("2026-09-10T12:00:00", Carolina=5)]
    janelas = deltas_squadratinhos(snaps)
    assert janelas == [{"atleta": "Carolina", "inicio": _dt("2026-09-10T08:00:00"),
                        "fim": _dt("2026-09-10T12:00:00"), "ganho": 5}]


def test_varios_pares_consecutivos():
    snaps = [_snap("2026-09-10T00:00:00", Ze=100), _snap("2026-09-10T08:00:00", Ze=100),
             _snap("2026-09-10T16:00:00", Ze=130)]
    janelas = deltas_squadratinhos(snaps)
    assert len(janelas) == 1  # o par sem ganho fica de fora
    assert janelas[0]["inicio"] == _dt("2026-09-10T08:00:00")
    assert janelas[0]["ganho"] == 30
