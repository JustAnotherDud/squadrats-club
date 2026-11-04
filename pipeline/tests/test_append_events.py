"""append_events: o dia é recalculado a cada run, o events.json reflete o fim do dia.

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


def _snap3(atualizado, **conc):
    """club_regioes.json mínimo: {atleta: {concelho: n}}."""
    return {"atualizado": atualizado,
            "atletas": {n: {"by_concelho": c, "by_distrito": {}} for n, c in conc.items()}}


ANTIGO = {"data": "2026-09-20", "nivel": "concelho", "cc": "PT", "regiao": "Lisboa",
          "quem": "A", "partes": [{"tipo": "marco", "valores": [25]}], "contagem": 30}


def _events(partes_eventos=(ANTIGO,)):
    return {"gerado": None, "desde": "2026-07-26", "eventos": list(partes_eventos)}


def _dia(evs, data):
    return [e for e in evs if e["data"] == data]


def _publicar(repo, quando, ficheiros):
    for nome, conteudo in ficheiros.items():
        with open(os.path.join(repo, "data", nome), "w", encoding="utf-8") as f:
            json.dump(conteudo, f)
    env = {**os.environ, "GIT_AUTHOR_DATE": quando, "GIT_COMMITTER_DATE": quando}
    subprocess.run(["git", "-C", repo, "add", "-f", "data"], check=True, stdin=subprocess.DEVNULL, capture_output=True)
    subprocess.run(["git", "-C", repo, "commit", "-qm", quando], check=True, env=env, stdin=subprocess.DEVNULL, capture_output=True)
    subprocess.run(["git", "-C", repo, "update-ref", "refs/remotes/origin/data", "HEAD"], check=True, stdin=subprocess.DEVNULL, capture_output=True)


@pytest.fixture
def repo(tmp_path, monkeypatch):
    r = str(tmp_path)
    subprocess.run(["git", "init", "-q", r], check=True, stdin=subprocess.DEVNULL, capture_output=True)
    subprocess.run(["git", "-C", r, "config", "user.email", "t@t"], check=True, stdin=subprocess.DEVNULL, capture_output=True)
    subprocess.run(["git", "-C", r, "config", "user.name", "t"], check=True, stdin=subprocess.DEVNULL, capture_output=True)
    os.makedirs(os.path.join(r, "data"))
    monkeypatch.setattr(append_events, "REPO", r)
    return r


def _correr(repo, snap):
    with open(os.path.join(repo, "data", "club_regioes.json"), "w", encoding="utf-8") as f:
        json.dump(snap, f)
    append_events.main(os.path.join(repo, "data"))
    with open(os.path.join(repo, "data", "events.json"), encoding="utf-8") as f:
        return json.load(f)["eventos"]


def test_dois_runs_no_mesmo_dia_o_segundo_muda_os_valores(repo):
    """1.º run: B cruza o 25. 2.º run: B sobe a 55, cruza o 50 e passa o A.
    O events.json fica só com o fim do dia: nada do 1.º run sobrevive."""
    _publicar(repo, "2026-09-24T20:10:00Z", {
        "club_regioes.json": _snap("2026-09-24T20:07:00Z", 30, 10),
        "events.json": _events()})

    evs = _correr(repo, _snap("2026-09-25T06:07:00Z", 30, 26))
    (e1,) = _dia(evs, "2026-09-25")
    assert e1["quem"] == "B" and e1["contagem"] == 26
    assert e1["partes"] == [{"tipo": "marco", "valores": [25]}]
    _publicar(repo, "2026-09-25T06:10:00Z", {})

    evs2 = _correr(repo, _snap("2026-09-25T14:34:00Z", 30, 55))
    (e2,) = _dia(evs2, "2026-09-25")
    assert e2["contagem"] == 55
    assert e2["partes"] == [{"tipo": "marco", "valores": [50]},
                            {"tipo": "novo_lider", "sobre": "A", "valores": [30]}]
    assert _dia(evs2, "2026-09-20") == [ANTIGO]   # dias anteriores não se tocam


def test_run_repetido_sem_mudancas_e_idempotente(repo):
    _publicar(repo, "2026-09-24T20:10:00Z", {
        "club_regioes.json": _snap("2026-09-24T20:07:00Z", 30, 10),
        "events.json": _events()})
    novo = _snap("2026-09-25T06:07:00Z", 30, 40)
    evs = _correr(repo, novo)
    _publicar(repo, "2026-09-25T06:10:00Z", {})
    assert _correr(repo, {**novo, "atualizado": "2026-09-25T14:07:00Z"}) == evs


def test_estreia_num_run_e_ultrapassagem_noutro_uma_so_entrada(repo):
    """C estreia-se em Lisboa de manhã; à tarde passa o B. Uma só entrada com as duas partes."""
    _publicar(repo, "2026-09-24T20:10:00Z", {
        "club_regioes.json": _snap3("2026-09-24T20:07:00Z",
                                    A={"Lisboa": 30}, B={"Lisboa": 20}, C={"Porto": 5}),
        "events.json": _events()})

    evs = _correr(repo, _snap3("2026-09-25T06:07:00Z",
                               A={"Lisboa": 30}, B={"Lisboa": 20}, C={"Porto": 5, "Lisboa": 3}))
    (e1,) = _dia(evs, "2026-09-25")
    assert [p["tipo"] for p in e1["partes"]] == ["primeira_presenca"]
    _publicar(repo, "2026-09-25T06:10:00Z", {})

    evs = _correr(repo, _snap3("2026-09-25T14:07:00Z",
                               A={"Lisboa": 30}, B={"Lisboa": 20}, C={"Porto": 5, "Lisboa": 22}))
    (e2,) = _dia(evs, "2026-09-25")
    assert (e2["quem"], e2["regiao"], e2["contagem"]) == ("C", "Lisboa", 22)
    assert e2["partes"] == [{"tipo": "primeira_presenca"},
                            {"tipo": "ultrapassagem", "sobre": ["B"], "valores": [20]}]


def test_estreia_que_ja_entra_acima_de_um_patamar(repo):
    _publicar(repo, "2026-09-24T20:10:00Z", {
        "club_regioes.json": _snap3("2026-09-24T20:07:00Z",
                                    A={"Lisboa": 90}, C={"Porto": 5}),
        "events.json": _events()})
    evs = _correr(repo, _snap3("2026-09-25T06:07:00Z",
                               A={"Lisboa": 90}, C={"Porto": 5, "Lisboa": 30}))
    (e,) = _dia(evs, "2026-09-25")
    assert e["partes"] == [{"tipo": "primeira_presenca"}, {"tipo": "marco", "valores": [25]}]
    assert e["contagem"] == 30


def test_dia_sem_commits_antes_de_ultimo(repo):
    # o último snapshot anterior é de dois dias antes: também serve de base
    _publicar(repo, "2026-09-23T20:10:00Z", {
        "club_regioes.json": _snap("2026-09-23T20:07:00Z", 30, 10),
        "events.json": _events([])})
    _correr(repo, _snap("2026-09-25T06:07:00Z", 30, 40))
    _publicar(repo, "2026-09-25T06:10:00Z", {})
    evs = _correr(repo, _snap("2026-09-25T14:34:00Z", 30, 41))
    assert any(e["data"] == "2026-09-25" and "novo_lider" in [p["tipo"] for p in e["partes"]]
               for e in evs)


def test_historico_inacessivel_com_eventos_aborta(repo):
    """events.json não vazio e nada em origin/data: ANOMALIA, não se escreve nada."""
    with open(os.path.join(repo, "data", "events.json"), "w", encoding="utf-8") as f:
        json.dump(_events(), f)
    with pytest.raises(SystemExit, match="ANOMALIA"):
        _correr(repo, _snap("2026-09-25T06:07:00Z", 30, 40))
    with open(os.path.join(repo, "data", "events.json"), encoding="utf-8") as f:
        assert json.load(f)["eventos"] == [ANTIGO]
