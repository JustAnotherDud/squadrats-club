"""append_events com duas corridas no mesmo dia, a primeira já com evento.

Usa um repo git temporário a fazer de origin/data.
"""
import json
import os
import subprocess

import pytest

import append_events


def _snap(atualizado, a, b):
    """club_regioes.json mínimo: dois atletas num concelho."""
    return {"atualizado": atualizado,
            "atletas": {"A": {"by_concelho": {"Lisboa": a}, "by_distrito": {}},
                        "B": {"by_concelho": {"Lisboa": b}, "by_distrito": {}}}}


def _publicar(repo, quando, ficheiros):
    for nome, conteudo in ficheiros.items():
        with open(os.path.join(repo, "data", nome), "w", encoding="utf-8") as f:
            json.dump(conteudo, f)
    env = {**os.environ, "GIT_AUTHOR_DATE": quando, "GIT_COMMITTER_DATE": quando}
    subprocess.run(["git", "-C", repo, "add", "-f", "data"], check=True)
    subprocess.run(["git", "-C", repo, "commit", "-qm", quando], check=True, env=env)
    subprocess.run(["git", "-C", repo, "update-ref", "refs/remotes/origin/data", "HEAD"], check=True)


@pytest.fixture
def repo(tmp_path, monkeypatch):
    r = str(tmp_path)
    subprocess.run(["git", "init", "-q", r], check=True)
    subprocess.run(["git", "-C", r, "config", "user.email", "t@t"], check=True)
    subprocess.run(["git", "-C", r, "config", "user.name", "t"], check=True)
    os.makedirs(os.path.join(r, "data"))
    monkeypatch.setattr(append_events, "REPO", r)
    return r


def _correr(repo, snap):
    with open(os.path.join(repo, "data", "club_regioes.json"), "w", encoding="utf-8") as f:
        json.dump(snap, f)
    append_events.main(os.path.join(repo, "data"))
    with open(os.path.join(repo, "data", "events.json"), encoding="utf-8") as f:
        return json.load(f)["eventos"]


def test_segunda_corrida_do_dia_com_evento_na_primeira(repo):
    # dia anterior: A lidera
    _publicar(repo, "2026-09-24T20:10:00Z", {
        "club_regioes.json": _snap("2026-09-24T20:07:00Z", 30, 10),
        "events.json": {"gerado": None, "desde": "2026-07-26",
                        "eventos": [{"data": "2026-09-20", "nivel": "concelho", "cc": "PT",
                                     "regiao": "Lisboa", "tipo": "marco", "quem": "A",
                                     "sobre": None, "valores": [25, 30]}]}})

    # 1.ª corrida do dia: B passa A -> evento com a data de hoje
    evs = _correr(repo, _snap("2026-09-25T06:07:00Z", 30, 40))
    assert [e["tipo"] for e in evs if e["data"] == "2026-09-25"] == ["novo_lider", "marco"]
    _publicar(repo, "2026-09-25T06:10:00Z", {})

    # 2.ª corrida do mesmo dia: B continua a subir; não aborta nem duplica
    evs2 = _correr(repo, _snap("2026-09-25T14:34:00Z", 30, 55))
    assert [e for e in evs2 if e["data"] == "2026-09-25" and e["tipo"] == "novo_lider"] == \
        [e for e in evs if e["data"] == "2026-09-25" and e["tipo"] == "novo_lider"]
    assert [e["valores"][0] for e in evs2 if e["tipo"] == "marco" and e["data"] == "2026-09-25"] == [50]


def test_dia_sem_commits_antes_de_ultimo(repo):
    # o último snapshot anterior é de dois dias antes: também serve de base
    _publicar(repo, "2026-09-23T20:10:00Z", {
        "club_regioes.json": _snap("2026-09-23T20:07:00Z", 30, 10),
        "events.json": {"gerado": None, "desde": "2026-07-26", "eventos": []}})
    _correr(repo, _snap("2026-09-25T06:07:00Z", 30, 40))
    _publicar(repo, "2026-09-25T06:10:00Z", {})
    evs = _correr(repo, _snap("2026-09-25T14:34:00Z", 30, 41))
    assert any(e["tipo"] == "novo_lider" and e["data"] == "2026-09-25" for e in evs)
