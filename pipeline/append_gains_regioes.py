"""Passo do run_all.py: mantém data/gains_regioes.json.

Faz o diff dos snapshots consecutivos de club_regioes.json ainda não
cobertos (anda só nesses dias no histórico de origin/data). Sem
classificação nova, o club_regioes.json já traz o breakdown por região.
Idempotente entre os 6 runs/dia: recomputa o(s) dia(s) do topo e reescreve.

Fallback shallow (mesmo padrão do append_regioes.py): se o git log de
origin/data não der histórico, compara só o topo vs o snapshot novo.

Uso: py append_gains_regioes.py [pasta_saida]
"""
import argparse
import json
import os
import subprocess
from datetime import datetime, timezone

import eventos
import gains_regioes

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
DATA_DIR = os.path.join(REPO, "data")


def _carrega(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def main(out_dir):
    novo = _carrega(os.path.join(out_dir, "club_regioes.json"))
    if not novo:
        print("append_gains_regioes: sem club_regioes.json novo, nada a fazer")
        return
    hoje = datetime.fromisoformat(novo["atualizado"].replace("Z", "+00:00")).date().isoformat()

    existente = gains_regioes.carregar(out_dir)
    por_data = {x["data"]: x for x in existente["dias"]}
    ultimo = max(por_data, default=gains_regioes.DESDE)

    try:
        # com o último snapshot antes de `ultimo`: o dia `ultimo` (que pode ser
        # hoje) recalcula-se todo, não só com a primeira corrida que teve ganhos
        snaps, saltados = eventos.snapshots_por_dia(REPO, "origin/data", desde=ultimo,
                                                    com_anterior=True)
    except Exception as e:
        print(f"append_gains_regioes: histórico de origin/data indisponível ({e})")
        snaps, saltados = {}, []
    if saltados:
        # aqui o fallback shallow não escreve datas erradas (só evita mexer no
        # que já lá está), por isso basta o aviso; ver append_events para o
        # tratamento estrito do mesmo padrão.
        print(f"append_gains_regioes: {len(saltados)} snapshot(s) do histórico ilegível(is)")
    snaps[hoje] = novo
    dias = [d for d in sorted(snaps) if d <= hoje]

    # Checkout shallow (sem `snapshots_por_dia`): só se ADICIONA `hoje` se for
    # um dia ainda não coberto. O topo de origin/data pode ser um snapshot de
    # hoje mais cedo (2.º run do dia), usá-lo como baseline daria um delta
    # intra-dia que substituiria a entrada certa do dia. Nesse caso não se
    # toca no que já lá está; o run seguinte com histórico (--depth=500 no
    # workflow) recomputa em condições.
    if len(dias) < 2 and hoje not in por_data:
        raw = subprocess.run(
            ["git", "-C", REPO, "show", "origin/data:data/club_regioes.json"],
            capture_output=True, text=True, encoding="utf-8",
        )
        if raw.returncode == 0:
            try:
                snaps = {"_prev": json.loads(raw.stdout), hoje: novo}
                dias = ["_prev", hoje]
                print("append_gains_regioes: sem histórico, só topo de origin/data vs novo")
            except json.JSONDecodeError:
                pass

    novos = 0
    prev = None
    for d in dias:
        if prev is not None:
            g = gains_regioes.diff_snapshots(snaps[prev], snaps[d])
            data_key = hoje if d == "_prev" else d
            if g:
                por_data[data_key] = {"data": data_key, "atletas": g}
                novos += 1
            elif data_key != hoje or d != "_prev":
                # dia passado que deixou de ter ganho (re-scan): remove.
                # No fallback shallow não se apaga nada.
                por_data.pop(data_key, None)
        prev = d

    gerado = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    dias_final = [por_data[k] for k in sorted(por_data)]
    gains_regioes.escrever(out_dir, dias_final, gerado)
    print(f"append_gains_regioes: {novos} dia(s) recomputado(s), {len(dias_final)} no total")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("out_dir", nargs="?", default=DATA_DIR)
    a = p.parse_args()
    os.makedirs(a.out_dir, exist_ok=True)
    main(a.out_dir)
