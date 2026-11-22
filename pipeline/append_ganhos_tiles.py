"""Passo do run_all.py: mantém data/ganhos_tiles/<AAAA-MM-DD>.json, os
squadratinhos (z17) que cada atleta ganhou em cada dia. Alimenta o deep-link
club.html#ganhos=... (clicar numa linha do Diário).

Ganho de um atleta num dia = squadratinhos com o bit dele ligado no último
snapshot do dia (UTC) e desligado no último snapshot antes desse dia, lidos do
histórico de data/club.json em origin/data (campo `squares` = [x, y, mask]; o
bit de cada atleta segue a ordem de `atletas`). Mesma atribuição de dia que o
gains_regioes. Um atleta que não está no snapshot anterior (1.ª aparição) não
tem ganho, como no daily_gains. Os squares que já eram de outro membro contam.

Idempotente entre os runs do dia: recomputa o dia mais recente que já existe e
os seguintes. Sem a pasta, reconstrói tudo desde o 1.º snapshot (backfill).
Um dia sem ganhos não tem ficheiro (e um ficheiro que deixou de ter ganhos é
apagado).

Validação: a contagem de cada (dia, atleta) é comparada com o `squadratinhos`
do daily_gains.json. Diferenças só vão para o log, nada se força: o daily_gains
é o delta líquido (leva as perdas de um re-scan) e não leva as correcções de
correcoes_snapshots.json.

Fallback shallow (mesmo padrão do append_gains_regioes.py): sem histórico,
compara o topo de origin/data com o club.json novo, só para o dia de hoje.
"""
import json
import os
import re
import subprocess
from datetime import datetime

import eventos
from util import load_json

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)

PASTA = "ganhos_tiles"
DESDE = eventos.DESDE
_FICHEIRO = re.compile(r"(\d{4}-\d\d-\d\d)\.json")


def ganhos_entre(ant, novo):
    """{nome: [[x, y], ...]} (ordenado): squares com o bit do atleta ligado em
    `novo` e desligado em `ant` (dois club.json). Só atletas presentes nos dois."""
    bits_ant = {a["nome"]: i for i, a in enumerate(ant.get("atletas", []))}
    bits_novo = {a["nome"]: i for i, a in enumerate(novo.get("atletas", []))}
    antes = {(x, y): m for x, y, m in ant.get("squares", [])}
    fora = {}
    for x, y, m in novo.get("squares", []):
        am = antes.get((x, y), 0)
        for nome, i in bits_novo.items():
            j = bits_ant.get(nome)
            if j is not None and (m >> i) & 1 and not (am >> j) & 1:
                fora.setdefault(nome, []).append([x, y])
    return {n: sorted(v) for n, v in fora.items()}


def _escrever(pasta, data, zoom, atletas):
    os.makedirs(pasta, exist_ok=True)
    with open(os.path.join(pasta, f"{data}.json"), "w", encoding="utf-8") as f:
        json.dump({"data": data, "zoom": zoom, "atletas": atletas},
                  f, ensure_ascii=False, separators=(",", ":"))


def _validar(out_dir, contagens):
    """Compara {data: {nome: n_tiles}} com o daily_gains.json e imprime as
    diferenças. Devolve a lista [(data, nome, diario, tiles)]."""
    dg = load_json(os.path.join(out_dir, "daily_gains.json")) or {}
    diario = {d["data"]: {n: (g.get("squadratinhos") or 0) for n, g in d.get("atletas", {}).items()}
              for d in dg.get("dias", [])}
    difs = []
    for data in sorted(contagens):
        for nome in sorted(set(contagens[data]) | set(diario.get(data, {}))):
            a, b = diario.get(data, {}).get(nome, 0), contagens[data].get(nome, 0)
            if a != b:
                difs.append((data, nome, a, b))
    for data, nome, a, b in difs:
        print(f"append_ganhos_tiles: DIFERENÇA {data} {nome}: diário={a} tiles={b}")
    return difs


def main(out_dir):
    novo = load_json(os.path.join(out_dir, "club.json"))
    if not novo:
        print("append_ganhos_tiles: sem club.json novo, nada a fazer")
        return
    hoje = datetime.fromisoformat(novo["atualizado"]).date().isoformat()
    zoom = novo.get("zoom", 17)

    pasta = os.path.join(out_dir, PASTA)
    existentes = {m.group(1) for f in (os.listdir(pasta) if os.path.isdir(pasta) else [])
                  if (m := _FICHEIRO.fullmatch(f))}
    ultimo = max(existentes, default=DESDE)

    try:
        # com o último snapshot antes de `ultimo`: o dia `ultimo` (que pode ser
        # hoje) recalcula-se todo. As correcções por omissão aplicam-se.
        snaps, saltados = eventos.snapshots_por_dia(REPO, "origin/data", desde=ultimo,
                                                    com_anterior=True, path="data/club.json")
    except Exception as e:
        print(f"append_ganhos_tiles: histórico de origin/data indisponível ({e})")
        snaps, saltados = {}, []
    if saltados:
        print(f"append_ganhos_tiles: AVISO, {len(saltados)} snapshot(s) do histórico "
              "ilegível(is); um dia pode ter colapsado no anterior")
    snaps[hoje] = novo
    dias = [d for d in sorted(snaps) if d <= hoje]

    # Checkout shallow: só se ADICIONA `hoje` se ainda não estiver coberto (o
    # topo de origin/data pode ser um snapshot de hoje mais cedo, usá-lo como
    # base daria um delta intra-dia). Mesmo raciocínio do append_gains_regioes.
    shallow = False
    if len(dias) < 2 and hoje not in existentes:
        raw = subprocess.run(
            ["git", "-C", REPO, "show", "origin/data:data/club.json"],
            capture_output=True, stdin=subprocess.DEVNULL, text=True, encoding="utf-8",
        )
        if raw.returncode == 0:
            try:
                snaps = {"_prev": json.loads(raw.stdout), hoje: novo}
                dias = ["_prev", hoje]
                shallow = True
                print("append_ganhos_tiles: sem histórico, só topo de origin/data vs novo")
            except json.JSONDecodeError:
                pass

    contagens = {}
    for prev, d in zip(dias, dias[1:]):
        g = ganhos_entre(snaps[prev], snaps[d])
        data = hoje if d == "_prev" else d
        contagens[data] = {n: len(v) for n, v in g.items()}
        if g:
            _escrever(pasta, data, zoom, g)
        elif not shallow:
            # dia que deixou de ter ganhos (re-scan, correcção): sem ficheiro
            try:
                os.remove(os.path.join(pasta, f"{data}.json"))
            except FileNotFoundError:
                pass

    difs = _validar(out_dir, contagens)
    n_ficheiros = len([f for f in os.listdir(pasta) if _FICHEIRO.fullmatch(f)]) if os.path.isdir(pasta) else 0
    print(f"append_ganhos_tiles: {len(contagens)} dia(s) recomputado(s), {n_ficheiros} ficheiro(s) "
          f"em {PASTA}/, {len(difs)} diferença(s) face ao daily_gains")
