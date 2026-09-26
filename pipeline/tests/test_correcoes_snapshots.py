"""Testes das correcções de snapshots (eventos.carregar_correcoes e a sua
aplicação em snapshots_commits), num repo git temporário com uma branch a
fazer de `data`.

Fixture: o caso da Xeira de 25/09, uma atividade falsa (+146) publicada em
dois runs e apagada antes do run seguinte, que só mostra +3. Os dois
snapshots falsos passam a usar a entrada da Xeira do snapshot seguinte.

Correr: py -m pytest
"""
import json
import subprocess

import pytest

import eventos
import gains_regioes
from ganhos import deltas_squadratinhos


def _git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t",
                           *args], capture_output=True, text=True, encoding="utf-8",
                          check=True).stdout.strip()


def _commit(repo, ficheiros, data):
    for rel, d in ficheiros.items():
        p = repo / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
        _git(repo, "add", rel)
    _git(repo, "commit", "-q", "-m", "snap", "--date", data)
    return _git(repo, "rev-parse", "HEAD")


def _regioes(conc):
    return {"by_concelho": conc, "by_distrito": {"Santarém": sum(conc.values())}}


# (atualizado, Xeira squadrats.json, Xeira club_regioes.json, Carolina squadratinhos)
RUNS = [
    ("2026-09-25T06:07:24Z", {"squadrats": 471, "squadratinhos": 6052, "yardinho": 145},
     {"Entroncamento": 20, "Torres Novas": 17}, 1079),
    ("2026-09-25T18:12:33Z", {"squadrats": 482, "squadratinhos": 6198, "yardinho": 146},
     {"Entroncamento": 28, "Torres Novas": 55, "Golegã": 33, "Santarém": 67}, 1081),
    ("2026-09-25T20:25:16Z", {"squadrats": 482, "squadratinhos": 6198, "yardinho": 146},
     {"Entroncamento": 28, "Torres Novas": 55, "Golegã": 33, "Santarém": 67}, 1081),
    ("2026-09-26T06:06:22Z", {"squadrats": 471, "squadratinhos": 6055, "yardinho": 145},
     {"Entroncamento": 23, "Torres Novas": 17}, 1081),
]


@pytest.fixture
def repo(tmp_path):
    """(repo, shas): um commit por run com squadrats.json e club_regioes.json,
    como na branch data."""
    r = tmp_path / "repo"
    r.mkdir()
    _git(r, "init", "-q", "-b", "data")
    shas = []
    for ts, sq, conc, carolina in RUNS:
        shas.append(_commit(r, {
            "data/squadrats.json": {"atualizado": ts, "atletas": {
                "Xeira": sq, "Carolina": {"squadratinhos": carolina}}},
            "data/club_regioes.json": {"atualizado": ts, "atletas": {
                "Xeira": _regioes(conc), "Carolina": _regioes({"Lisboa": carolina})}},
        }, ts))
    return r, shas


def _correcoes(shas):
    return {shas[1]: {"Xeira": shas[3]}, shas[2]: {"Xeira": shas[3]}}


def test_sem_correcoes_os_snapshots_ficam_como_publicados(repo):
    r, _ = repo
    snaps, _ = eventos.snapshots_commits(str(r), "data", "data/squadrats.json", correcoes={})
    janelas = deltas_squadratinhos(snaps)
    assert [(j["atleta"], j["ganho"]) for j in janelas] == [("Xeira", 146), ("Carolina", 2)]


def test_correcao_substitui_so_o_atleta_indicado(repo):
    r, shas = repo
    snaps, _ = eventos.snapshots_commits(str(r), "data", "data/squadrats.json",
                                         correcoes=_correcoes(shas))
    assert [d["atletas"]["Xeira"]["squadratinhos"] for _, d in snaps] == [6052, 6055, 6055, 6055]
    # a Carolina dos snapshots corrigidos é a publicada, não a do snapshot correcto
    assert [d["atletas"]["Carolina"]["squadratinhos"] for _, d in snaps] == [1079, 1081, 1081, 1081]
    janelas = deltas_squadratinhos(snaps)
    assert [(j["atleta"], j["inicio"].isoformat(), j["ganho"]) for j in janelas] == [
        ("Xeira", "2026-09-25T06:07:24+00:00", 3), ("Carolina", "2026-09-25T06:07:24+00:00", 2)]


def test_correcao_vale_para_qualquer_ficheiro_do_historico(repo):
    r, shas = repo
    snaps, _ = eventos.snapshots_commits(str(r), "data", "data/club_regioes.json",
                                         correcoes=_correcoes(shas))
    por_dia = {ts.date().isoformat(): d for ts, d in snaps}
    ganho = gains_regioes.diff_snapshots(snaps[0][1], por_dia["2026-09-25"])
    assert ganho["Xeira"] == {"concelho": {"Entroncamento": 3}, "distrito": {"Santarém": 3}}
    evs = eventos.detectar(snaps[0][1], por_dia["2026-09-25"], "2026-09-25")
    assert [e for e in evs if e["quem"] == "Xeira"] == []


def test_atleta_ausente_no_snapshot_correcto_sai(repo):
    r, shas = repo
    snaps, _ = eventos.snapshots_commits(str(r), "data", "data/squadrats.json",
                                         correcoes={shas[1]: {"Pedro": shas[3]}})
    assert "Pedro" not in snaps[1][1]["atletas"]


def test_snapshot_correcto_ilegivel_rebenta(repo):
    r, shas = repo
    with pytest.raises(RuntimeError, match="ilegível"):
        eventos.snapshots_commits(str(r), "data", "data/squadrats.json",
                                  correcoes={shas[1]: {"Xeira": "0" * 40}})


def test_carregar_correcoes(tmp_path):
    sha, ok = "a" * 40, "b" * 40
    p = tmp_path / "c.json"
    p.write_text(json.dumps({sha: {"Xeira": ok, "motivo": "atividade apagada"}}), encoding="utf-8")
    assert eventos.carregar_correcoes(str(p)) == {sha: {"Xeira": ok}}
    assert eventos.carregar_correcoes(str(tmp_path / "nao-existe.json")) == {}
    p.write_text(json.dumps({"abc1234": {"Xeira": ok}}), encoding="utf-8")
    with pytest.raises(ValueError, match="SHA completo"):
        eventos.carregar_correcoes(str(p))


def test_ficheiro_do_repo_e_valido():
    assert eventos.carregar_correcoes()  # formato válido e não vazio
