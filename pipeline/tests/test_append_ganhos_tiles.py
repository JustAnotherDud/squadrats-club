"""append_ganhos_tiles: diff de bits entre snapshots do club.json, atribuição
de dia, idempotência e correcções. Repo git temporário a fazer de origin/data."""
import json
import os
import subprocess

import pytest

import append_ganhos_tiles as agt
import eventos
from test_append_events import _publicar, repo  # noqa: F401 (fixture)


def _club(atualizado, squares, nomes=("A", "B")):
    """club.json mínimo; `squares` = {(x, y): mask}."""
    return {"atualizado": atualizado, "zoom": 17,
            "atletas": [{"nome": n, "slug": n.lower()} for n in nomes],
            "squares": [[x, y, m] for (x, y), m in sorted(squares.items())]}


def _ler(repo, dia):
    p = os.path.join(repo, "data", "ganhos_tiles", f"{dia}.json")
    if not os.path.exists(p):
        return None
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def _correr(repo, snap, monkeypatch, daily=None):
    monkeypatch.setattr(agt, "REPO", repo)
    out = os.path.join(repo, "data")
    with open(os.path.join(out, "club.json"), "w", encoding="utf-8") as f:
        json.dump(snap, f)
    with open(os.path.join(out, "daily_gains.json"), "w", encoding="utf-8") as f:
        json.dump(daily or {"dias": []}, f)
    agt.main(out)


def test_ganhos_entre_so_bits_novos_e_partilhados_contam():
    ant = _club("2026-09-01T10:00:00Z", {(1, 1): 0b01, (2, 2): 0b10})
    novo = _club("2026-09-02T10:00:00Z", {
        (1, 1): 0b11,   # B apanhou um square que já era de A: conta como ganho de B
        (2, 2): 0b10,   # sem mudança
        (3, 3): 0b01,   # A, square novo
        (4, 4): 0b11,   # os dois, square novo
    })
    assert agt.ganhos_entre(ant, novo) == {"A": [[3, 3], [4, 4]], "B": [[1, 1], [4, 4]]}


def test_ganhos_entre_perdas_nao_contam_e_estreante_nao_tem_ganho():
    ant = _club("2026-09-01T10:00:00Z", {(1, 1): 0b01}, nomes=("A",))
    novo = _club("2026-09-02T10:00:00Z", {(1, 1): 0b00, (5, 5): 0b10}, nomes=("A", "B"))
    # A perdeu o (1,1) (re-scan): não é ganho; B é novo no roster: sem baseline
    assert agt.ganhos_entre(ant, novo) == {}


def test_ganhos_entre_usa_o_bit_de_cada_snapshot_pelo_nome():
    ant = _club("2026-09-01T10:00:00Z", {(1, 1): 0b01}, nomes=("A", "B"))
    novo = _club("2026-09-02T10:00:00Z", {(1, 1): 0b10, (2, 2): 0b01}, nomes=("B", "A"))
    # ordem trocada: no novo o bit 0 é o B e o bit 1 é o A. O (1,1) continua a ser
    # do A (sem ganho, apesar de a máscara ter mudado); o (2,2) é ganho do B
    assert agt.ganhos_entre(ant, novo) == {"B": [[2, 2]]}


def test_dia_atribuido_ao_ultimo_snapshot_do_dia_utc(repo, monkeypatch):  # noqa: F811
    _publicar(repo, "2026-09-01T22:00:00Z", {"club.json": _club("2026-09-01T22:00:00Z", {(1, 1): 0b01})})
    # dois runs a 02/09: o primeiro ganha 1 square, o segundo mais um; o dia fica com os dois
    _publicar(repo, "2026-09-02T06:00:00Z", {"club.json": _club("2026-09-02T06:00:00Z", {(1, 1): 0b01, (2, 2): 0b01})})
    _correr(repo, _club("2026-09-02T18:00:00Z", {(1, 1): 0b01, (2, 2): 0b01, (3, 3): 0b10}), monkeypatch)
    assert _ler(repo, "2026-09-02") == {"data": "2026-09-02", "zoom": 17,
                                        "atletas": {"A": [[2, 2]], "B": [[3, 3]]}}
    assert _ler(repo, "2026-09-01") is None  # 1.º snapshot: sem baseline, sem ganhos


def test_idempotente_e_recalcula_o_dia_existente(repo, monkeypatch):  # noqa: F811
    _publicar(repo, "2026-09-01T22:00:00Z", {"club.json": _club("2026-09-01T22:00:00Z", {(1, 1): 0b01})})
    s1 = _club("2026-09-02T06:00:00Z", {(1, 1): 0b01, (2, 2): 0b01})
    _correr(repo, s1, monkeypatch)
    antes = _ler(repo, "2026-09-02")
    _correr(repo, s1, monkeypatch)  # mesma corrida outra vez: nada muda
    assert _ler(repo, "2026-09-02") == antes
    _publicar(repo, "2026-09-02T06:01:00Z", {"club.json": s1})

    # 2.ª corrida do dia com mais um ganho: o ficheiro existente é recalculado, não acrescentado
    s2 = _club("2026-09-02T18:00:00Z", {(1, 1): 0b01, (2, 2): 0b01, (3, 3): 0b01})
    _correr(repo, s2, monkeypatch)
    assert _ler(repo, "2026-09-02")["atletas"] == {"A": [[2, 2], [3, 3]]}

    # o dia deixa de ter ganhos (re-scan): o ficheiro desaparece
    _publicar(repo, "2026-09-02T18:01:00Z", {"club.json": s2})
    _correr(repo, _club("2026-09-02T23:00:00Z", {(1, 1): 0b01}), monkeypatch)
    assert _ler(repo, "2026-09-02") is None


def test_dia_sem_ganhos_nao_gera_ficheiro(repo, monkeypatch):  # noqa: F811
    s = {(1, 1): 0b01}
    _publicar(repo, "2026-09-01T22:00:00Z", {"club.json": _club("2026-09-01T22:00:00Z", s)})
    _correr(repo, _club("2026-09-02T10:00:00Z", s), monkeypatch)
    assert not os.path.isdir(os.path.join(repo, "data", "ganhos_tiles")) or \
        os.listdir(os.path.join(repo, "data", "ganhos_tiles")) == []


def test_diferenca_face_ao_daily_gains_so_vai_para_o_log(repo, monkeypatch, capsys):  # noqa: F811
    _publicar(repo, "2026-09-01T22:00:00Z", {"club.json": _club("2026-09-01T22:00:00Z", {(1, 1): 0b01})})
    daily = {"dias": [{"data": "2026-09-02", "atletas": {"A": {"squadratinhos": 5}}}]}
    _correr(repo, _club("2026-09-02T10:00:00Z", {(1, 1): 0b01, (2, 2): 0b01}), monkeypatch, daily)
    assert "DIFERENÇA 2026-09-02 A: diário=5 tiles=1" in capsys.readouterr().out
    assert _ler(repo, "2026-09-02")["atletas"] == {"A": [[2, 2]]}  # nada forçado


def test_correccoes_aplicam_se_ao_club_json(repo, monkeypatch):  # noqa: F811
    """Um snapshot publicado com ganhos falsos de A (o square 9,9) usa os
    squares de A do snapshot seguinte, como o correcoes_snapshots.json faz."""
    def sha():
        return subprocess.run(["git", "-C", repo, "rev-parse", "HEAD"], capture_output=True,
                              text=True, check=True, stdin=subprocess.DEVNULL).stdout.strip()

    _publicar(repo, "2026-09-01T22:00:00Z", {"club.json": _club("2026-09-01T22:00:00Z", {(1, 1): 0b01})})
    _publicar(repo, "2026-09-02T10:00:00Z", {"club.json": _club(
        "2026-09-02T10:00:00Z", {(1, 1): 0b11, (9, 9): 0b01, (8, 8): 0b01})})
    falso = sha()
    # snapshot seguinte: a atividade falsa foi apagada; B continua com o (1,1)
    _publicar(repo, "2026-09-03T10:00:00Z", {"club.json": _club(
        "2026-09-03T10:00:00Z", {(1, 1): 0b11, (8, 8): 0b01})})
    certo = sha()

    snaps, _ = eventos.snapshots_commits(repo, "origin/data", "data/club.json",
                                         correcoes={falso: {"A": certo}})
    assert dict(((x, y), m) for x, y, m in snaps[1][1]["squares"]) == {(1, 1): 0b11, (8, 8): 0b01}

    monkeypatch.setattr(eventos, "carregar_correcoes", lambda path=eventos.CORRECOES: {falso: {"A": certo}})
    _correr(repo, _club("2026-09-03T18:00:00Z", {(1, 1): 0b11, (8, 8): 0b01}), monkeypatch)
    # 02/09 sem o (9,9) falso, e 03/09 não "perde" nem "ganha" nada por causa dele
    assert _ler(repo, "2026-09-02")["atletas"] == {"A": [[8, 8]], "B": [[1, 1]]}
    assert _ler(repo, "2026-09-03") is None
