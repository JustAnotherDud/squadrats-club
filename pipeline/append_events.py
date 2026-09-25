"""Passo do run_all.py: acrescenta a data/events.json os eventos dos dias
ainda não cobertos, sem reprocessar o histórico todo.

Trabalha por DIA UTC: quando o pipeline esteve parado vários dias, cada dia
em falta fica com os seus eventos, não colapsa tudo no dia da recuperação.

O snapshot "de hoje" é o club_regioes.json acabado de gerar (ainda não
commitado); os dias anteriores vêm do histórico de `origin/data`.

Append idempotente: a chave de cada evento é por dia (eventos.chave), por
isso os 6 runs do mesmo dia não duplicam nada.

Uso: py append_events.py [pasta_saida]
"""
import argparse
import json
import os
import subprocess
from datetime import datetime, timezone

import eventos

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
DATA_DIR = os.path.join(REPO, "data")


def _n_commits_club_regioes(branch="origin/data"):
    """Quantos commits de data/club_regioes.json existem em `branch`. 0 se a
    ref ou o ficheiro ainda não existem lá. Serve para distinguir 'nunca
    houve snapshot' (primeiro run, normal) de 'o histórico devia estar cá'
    (checkout shallow, anomalia)."""
    r = subprocess.run(
        ["git", "-C", REPO, "log", branch, "--format=%H", "--", "data/club_regioes.json"],
        capture_output=True, text=True, encoding="utf-8",
    )
    return len(r.stdout.split()) if r.returncode == 0 else 0


def main(out_dir):
    novo_path = os.path.join(out_dir, "club_regioes.json")
    if not os.path.exists(novo_path):
        print("append_events: sem club_regioes.json novo, nada a fazer")
        return
    with open(novo_path, encoding="utf-8") as f:
        novo = json.load(f)
    hoje = datetime.fromisoformat(
        novo["atualizado"].replace("Z", "+00:00")
    ).date().isoformat()

    events_path = os.path.join(out_dir, "events.json")
    try:
        with open(events_path, encoding="utf-8") as f:
            atual = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        atual = {"gerado": None, "desde": eventos.DESDE, "eventos": []}
    atual.setdefault("eventos", [])
    atual.setdefault("desde", eventos.DESDE)

    ultimo = max((e["data"] for e in atual["eventos"]), default=eventos.DESDE)

    # walk dia-a-dia sobre o histórico de origin/data, a partir do último
    # snapshot antes de `ultimo`: o dia `ultimo` pode ser hoje e precisa de base
    saltados = []
    try:
        por_dia, saltados = eventos.snapshots_por_dia(REPO, "origin/data", desde=ultimo,
                                                      com_anterior=True)
    except Exception as e:
        print(f"append_events: histórico de origin/data indisponível ({e})")
        por_dia = {}
    por_dia[hoje] = novo  # o run actual manda no seu próprio dia
    dias = [d for d in sorted(por_dia) if d <= hoje]

    # Só temos o snapshot de hoje. Duas situações MUITO diferentes:
    #   - events.json ainda vazio  -> primeiro run / arranque. Não há histórico
    #     de eventos a proteger; compara só o topo de origin/data com o novo
    #     (1 par, tudo em `hoje`).
    #   - events.json já com eventos -> já publicámos snapshots antes, logo o
    #     histórico DEVIA estar acessível e não está: checkout shallow demais,
    #     branch reescrita, ou blobs em falta. Abortar: o fallback do topo
    #     atribuiria dias de mudanças todos a hoje, com datas erradas, e o run
    #     passava como sucesso. Antes um job vermelho (que se cura sozinho no
    #     run seguinte) do que um feed silenciosamente errado.
    if len(dias) < 2:
        if atual["eventos"]:
            n_commits = _n_commits_club_regioes()
            raise SystemExit(
                "append_events: ANOMALIA, origin/data devia trazer o histórico de "
                f"club_regioes.json e não traz (ultimo={ultimo}, hoje={hoje}; "
                f"{n_commits} commit(s) do ficheiro na branch, {len(saltados)} ilegível(is); "
                f"events.json com {len(atual['eventos'])} evento(s)). "
                "Checkout shallow demais? O workflow faz `git fetch origin data` completo. "
                "Abortado para não escrever eventos com datas erradas."
            )
        try:
            raw = subprocess.run(
                ["git", "-C", REPO, "show", "origin/data:data/club_regioes.json"],
                capture_output=True, text=True, encoding="utf-8", check=True,
            ).stdout
            por_dia = {"_prev": json.loads(raw), hoje: novo}
            dias = ["_prev", hoje]
            print("append_events: arranque (events.json vazio), a comparar só topo de origin/data vs novo")
        except Exception:
            print("append_events: arranque sem snapshot anterior, só actualiza 'gerado'")

    # histórico lido em parte (uns commits ilegíveis, mas >=2 dias no total):
    # não aborta: um único commit corrompido lá atrás não deve travar o
    # pipeline diário para sempre, mas fica dito, pode ter colapsado um dia.
    if saltados and len(dias) >= 2:
        print(f"append_events: AVISO, {len(saltados)} snapshot(s) do histórico "
              "ilegível(is); um dia pode ter colapsado no anterior (ver snapshots_por_dia acima)")

    # marcos de totais (squadratinhos do atleta e união do clube): snapshots do
    # squadrats.json pelo mesmo walk; a união vem dos club_regioes.json que já
    # temos em por_dia. Lenient: se o histórico do squadrats.json não estiver
    # acessível, salta os marcos de totais, não aborta.
    sq_novo_path = os.path.join(out_dir, "squadrats.json")
    sq_por_dia = {}
    try:
        sq_por_dia, _ = eventos.snapshots_por_dia(
            REPO, "origin/data", desde=ultimo, path="data/squadrats.json", com_anterior=True)
    except Exception as e:
        print(f"append_events: histórico de squadrats.json indisponível, sem marcos de totais ({e})")
    if os.path.exists(sq_novo_path):
        with open(sq_novo_path, encoding="utf-8") as f:
            sq_por_dia[hoje] = json.load(f)
    if "_prev" in dias:
        try:
            sq_por_dia["_prev"] = json.loads(subprocess.run(
                ["git", "-C", REPO, "show", "origin/data:data/squadrats.json"],
                capture_output=True, text=True, encoding="utf-8", check=True).stdout)
        except Exception:
            pass

    novos = []
    if len(dias) >= 2:
        ja = {eventos.chave(e) for e in atual["eventos"]}
        for ontem, dia in zip(dias, dias[1:]):
            data_ev = dia if dia != "_prev" else hoje
            for ev in eventos.detectar(por_dia[ontem], por_dia[dia], data_ev):
                k = eventos.chave(ev)
                if k not in ja:
                    ja.add(k)
                    novos.append(ev)
            if ontem in sq_por_dia and dia in sq_por_dia:
                for ev in eventos.detectar_totais(
                        eventos.totais_sqi(sq_por_dia[ontem]), eventos.totais_sqi(sq_por_dia[dia]),
                        eventos.uniao_clube(por_dia[ontem]), eventos.uniao_clube(por_dia[dia]), data_ev):
                    k = eventos.chave(ev)
                    if k not in ja:
                        ja.add(k)
                        novos.append(ev)

    if novos:
        atual["eventos"].extend(novos)
        # colapsa marcos redundantes (25 quando já há 50 no mesmo dia/região/
        # atleta, de um sync grande ou de runs sucessivos) e reordena p/ o feed
        atual["eventos"] = eventos.ordenar_feed(eventos.colapsar_marcos(atual["eventos"]))
        print(f"append_events: +{len(novos)} evento(s)")
        for ev in novos:
            print(f"  {ev['data']} {ev['nivel']} {ev['regiao']}: {ev['tipo']} "
                  f"{ev['quem']}" + (f" > {ev['sobre']}" if ev["sobre"] else ""))
    else:
        print("append_events: sem eventos novos")

    atual["gerado"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    with open(events_path, "w", encoding="utf-8") as f:
        json.dump(atual, f, ensure_ascii=False, separators=(",", ":"))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("out_dir", nargs="?", default=DATA_DIR)
    args = parser.parse_args()
    os.makedirs(args.out_dir, exist_ok=True)
    main(args.out_dir)
