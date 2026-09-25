"""append_gains_regioes com duas corridas no mesmo dia, ambas com ganhos."""
import json
import os

import append_gains_regioes
from test_append_events import _publicar, repo  # noqa: F401 (fixture)


def _snap(atualizado, a, b):
    return {"atualizado": atualizado,
            "atletas": {"A": {"by_concelho": {"Lisboa": a}, "by_distrito": {"Lisboa": a}},
                        "B": {"by_concelho": {"Lisboa": b}, "by_distrito": {"Lisboa": b}}}}


def _correr(repo, snap, monkeypatch):
    monkeypatch.setattr(append_gains_regioes, "REPO", repo)
    with open(os.path.join(repo, "data", "club_regioes.json"), "w", encoding="utf-8") as f:
        json.dump(snap, f)
    append_gains_regioes.main(os.path.join(repo, "data"))
    with open(os.path.join(repo, "data", "gains_regioes.json"), encoding="utf-8") as f:
        return {d["data"]: d["atletas"] for d in json.load(f)["dias"]}


def test_segunda_corrida_do_dia_com_ganhos(repo, monkeypatch):  # noqa: F811
    _publicar(repo, "2026-09-08T22:50:00Z", {"club_regioes.json": _snap("2026-09-08T22:50:00Z", 10, 20),
                                              "gains_regioes.json": {"gerado": None, "dias": []}})
    # 1.ª corrida do dia: A ganha 12
    dias = _correr(repo, _snap("2026-09-09T19:41:00Z", 22, 20), monkeypatch)
    assert dias["2026-09-09"] == {"A": {"concelho": {"Lisboa": 12}, "distrito": {"Lisboa": 12}}}
    _publicar(repo, "2026-09-09T19:42:00Z", {})

    # 2.ª corrida do mesmo dia: B ganha 102; o dia tem de ter os dois
    dias = _correr(repo, _snap("2026-09-09T22:37:00Z", 22, 122), monkeypatch)
    assert dias["2026-09-09"] == {"A": {"concelho": {"Lisboa": 12}, "distrito": {"Lisboa": 12}},
                                  "B": {"concelho": {"Lisboa": 102}, "distrito": {"Lisboa": 102}}}
