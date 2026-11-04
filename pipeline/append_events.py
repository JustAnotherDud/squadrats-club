"""Passo do run_all.py: actualiza data/events.json com os eventos dos dias
ainda não fechados, sem reprocessar o histórico todo.

Trabalha por DIA UTC: quando o pipeline esteve parado vários dias, cada dia
em falta fica com os seus eventos, não colapsa tudo no dia da recuperação.

O snapshot "de hoje" é o club_regioes.json acabado de gerar (ainda não
commitado); os dias anteriores vêm do histórico de `origin/data`.

RECALCULA em vez de acrescentar: os dias que o walk cobre (de `ultimo`, o dia do
último evento, até hoje) são apagados do events.json e regenerados de raiz,
comparando o último snapshot do dia anterior com o último do dia. Assim os
6 runs do mesmo dia deixam só o estado do fim do dia (valores e combinação de
estreia/marco/ultrapassagem incluídos), e não há chave de idempotência. Dias
anteriores a `ultimo` não se tocam.
"""
import json
import os
import subprocess
from datetime import datetime, timezone

import eventos
from util import iso_utc

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)


def _n_commits_club_regioes(branch="origin/data"):
    """Quantos commits de data/club_regioes.json existem em `branch`. 0 se a
    ref ou o ficheiro ainda não existem lá. Serve para distinguir 'nunca
    houve snapshot' (primeiro run, normal) de 'o histórico devia estar cá'
    (checkout shallow, anomalia)."""
    r = subprocess.run(
        ["git", "-C", REPO, "log", branch, "--format=%H", "--", "data/club_regioes.json"],
        capture_output=True, stdin=subprocess.DEVNULL, text=True, encoding="utf-8",
    )
    return len(r.stdout.split()) if r.returncode == 0 else 0


def _resumo(ev):
    """Uma linha por evento, para o log do run."""
    if "partes" not in ev:
        return f"{ev['data']} {ev['tipo']} {ev.get('quem')} {ev['valores']}"
    partes = "+".join(p["tipo"] for p in ev["partes"])
    return f"{ev['data']} {ev['nivel']} {ev['regiao']}: {ev['quem']} {partes} ({ev['contagem']})"


def calcular(dias, por_dia, sq_por_dia, hoje, partilhadas=None):
    """(eventos, datas) de todos os pares de dias consecutivos em `dias`: o
    último snapshot do dia anterior vs o último do dia. `datas` = os dias a que
    os eventos ficam atribuídos (os que o walk regenera). Eventos regionais já
    combinados (eventos.detectar_dia) e marcos de totais."""
    if partilhadas is None:
        partilhadas = eventos.carregar_partilhadas()
    novos, datas = [], set()
    for ontem, dia in zip(dias, dias[1:]):
        data_ev = dia if dia != "_prev" else hoje
        datas.add(data_ev)
        novos += eventos.detectar_dia(por_dia[ontem], por_dia[dia], data_ev, partilhadas)
        if ontem in sq_por_dia and dia in sq_por_dia:
            novos += eventos.detectar_totais(
                eventos.totais_sqi(sq_por_dia[ontem]), eventos.totais_sqi(sq_por_dia[dia]),
                eventos.uniao_clube(por_dia[ontem]), eventos.uniao_clube(por_dia[dia]), data_ev)
    return novos, datas


def main(out_dir):
    novo_path = os.path.join(out_dir, "club_regioes.json")
    if not os.path.exists(novo_path):
        print("append_events: sem club_regioes.json novo, nada a fazer")
        return
    with open(novo_path, encoding="utf-8") as f:
        novo = json.load(f)
    hoje = datetime.fromisoformat(novo["atualizado"]).date().isoformat()

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
                capture_output=True, stdin=subprocess.DEVNULL, text=True, encoding="utf-8", check=True,
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
                capture_output=True, stdin=subprocess.DEVNULL, text=True, encoding="utf-8", check=True).stdout)
        except Exception:
            pass

    novos, regenerados = [], set()
    if len(dias) >= 2:
        novos, regenerados = calcular(dias, por_dia, sq_por_dia, hoje)

    # só se apagam os dias que acabaram de ser regenerados: sem par (ex. o dia
    # `ultimo` é o 1.º do histórico, sem base) ficam como estão, nunca se perde
    # um dia sem o poder refazer
    velhos = [e for e in atual["eventos"] if e["data"] in regenerados]
    if ultimo not in regenerados and any(e["data"] == ultimo for e in atual["eventos"]):
        print(f"append_events: AVISO, o dia {ultimo} não foi recalculado (sem snapshot base); mantido")
    mantidos = [e for e in atual["eventos"] if e["data"] not in regenerados]
    if novos or velhos:
        atual["eventos"] = eventos.ordenar_feed(mantidos + novos)
        antes = {json.dumps(e, sort_keys=True) for e in velhos}
        mudou = [e for e in novos if json.dumps(e, sort_keys=True) not in antes]
        print(f"append_events: {len(regenerados)} dia(s) recalculado(s) "
              f"({min(regenerados)}..{max(regenerados)}), {len(velhos)} -> {len(novos)} evento(s), "
              f"{len(mudou)} novo(s)/alterado(s)")
        for ev in mudou:
            print("  " + _resumo(ev))
    else:
        print("append_events: sem eventos novos")

    atual["gerado"] = iso_utc(datetime.now(timezone.utc))
    with open(events_path, "w", encoding="utf-8") as f:
        json.dump(atual, f, ensure_ascii=False, separators=(",", ":"))
