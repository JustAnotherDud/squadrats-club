"""Ganhos diários por atleta, mantém data/daily_gains.json actualizado.

O ficheiro é auto-contido: além dos dias, guarda `ultimo_total` (os totais
absolutos da última corrida observada). O ganho de uma corrida é o delta
contra esse `ultimo_total`, acumulado na entrada do dia corrente.

Não consulta o git: no CI o checkout do main é shallow.

Efeitos de acumular contra `ultimo_total` em vez de comparar dias:
- 2 corridas no mesmo dia somam o que cada uma trouxe de novo; correr duas
  vezes sem dados novos não muda nada (delta zero), por isso é idempotente
  na prática.
- Se uma corrida gerar dados mas falhar antes do commit, o `ultimo_total`
  fica atrasado e a corrida seguinte recupera o que ficou por contar, em
  vez de o perder.

Atleta que aparece pela primeira vez não conta como "ganho", o total dele
inteiro apareceria como um pico só por ter sido acrescentado ao ATHLETES.
"""
import json
import os
from datetime import datetime, timezone

CAMPOS = ["squadrats", "squadratinhos", "yard", "yardinho",
          "ubersquadrat", "ubersquadratinho"]


def calcular_delta(antes, agora):
    """{atleta: {campo: delta}}, só campos que mudaram, só atletas com
    baseline (os novos entram no baseline sem gerar ganho)."""
    ganhos = {}
    for nome, valores in agora.items():
        if not antes or nome not in antes:
            continue
        base = antes[nome]
        delta = {}
        for c in CAMPOS:
            d_valor = (valores.get(c) or 0) - (base.get(c) or 0)
            if d_valor:
                delta[c] = d_valor
        if delta:
            ganhos[nome] = delta
    return ganhos


def _somar(destino, novo):
    """Acumula `novo` em `destino` ({atleta: {campo: delta}}), campo a campo,
    removendo campos que voltem a zero."""
    resultado = {n: dict(v) for n, v in destino.items()}
    for nome, campos in novo.items():
        alvo = resultado.setdefault(nome, {})
        for c, v in campos.items():
            total = alvo.get(c, 0) + v
            if total:
                alvo[c] = total
            else:
                alvo.pop(c, None)
        if not alvo:
            resultado.pop(nome, None)
    return resultado


def actualizar(data_dir, atletas_agora, hoje_iso=None):
    """Acumula na entrada do dia corrente o que mudou desde a última corrida.
    Devolve o delta desta corrida ({} se nada mudou)."""
    hoje_iso = hoje_iso or datetime.now(timezone.utc).date().isoformat()
    path = os.path.join(data_dir, "daily_gains.json")

    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            actual = json.load(f)
    else:
        actual = {"gerado": None, "ultimo_total": None, "dias": []}
    actual.setdefault("dias", [])
    actual.setdefault("ultimo_total", None)

    delta = calcular_delta(actual["ultimo_total"], atletas_agora)

    if delta:
        dias = {d["data"]: d["atletas"] for d in actual["dias"]}
        dias[hoje_iso] = _somar(dias.get(hoje_iso, {}), delta)
        if not dias[hoje_iso]:
            dias.pop(hoje_iso)
        actual["dias"] = [{"data": d, "atletas": dias[d]} for d in sorted(dias)]

    actual["ultimo_total"] = atletas_agora
    actual["gerado"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    with open(path, "w", encoding="utf-8") as f:
        json.dump(actual, f, ensure_ascii=False, separators=(",", ":"))
    return delta
