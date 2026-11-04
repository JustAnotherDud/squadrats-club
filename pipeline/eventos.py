"""Detecção de eventos do clube a partir de snapshots de club_regioes.json.

Um "evento" é uma mudança digna de nota no ranking por região (concelho ou
distrito, só PT), ou um marco de totais. Consumido pelo append_events.py.

O feed é RECALCULADO por dia (ver append_events): em cada run, os dias que o
walk cobre são apagados e regenerados do último snapshot do dia anterior vs o
último do dia. Não há chave de idempotência, nem estado que sobreviva entre runs.

`detectar` devolve eventos "planos" (um por tipo); `combinar` junta-os por
(data, cc, nivel, regiao, quem) numa entrada com `partes`, que é o formato de
events.json (ver `detectar_dia`).

Tipos (partes):
  - ultrapassagem      X passou Y: antes X tinha ESTRITAMENTE menos que Y (Y presente,
                       X pode estar ausente), agora tem estritamente mais. Empate nunca
                       é ultrapassagem, nem à entrada (empate -> à frente) nem à saída
                       (à frente -> empate). Quem sai de um empate para a frente não
                       gera evento: o desempate por ordem canónica é só de apresentação.
  - novo_lider         mudou o 1º da região (e havia 1º antes), absorve o par
                       (novo_lider, ex_lider), esse não sai também como ultrapassagem
  - primeira_presenca  X capturou o 1º squadratinho numa região que JÁ tinha
                       outro atleta (juntou-se a um board existente)
  - marco              X cruzou um patamar de squadratinhos (só para cima)
"""
import os

# patamares por nível: concelho arranca em 25 (~1 km² coberto), distrito
# mais alto porque acumula mais. Só cruzados para cima.
MARCOS = {
    "concelho": [25, 50, 100, 250, 500, 1000],
    "distrito": [50, 100, 250, 500, 1000, 2500],
}

# marcos de squadratinhos TOTAIS, fora do contexto de uma região (feed tratado
# como notícias). Números muito maiores que os regionais, poucos disparos por
# ano. MARCOS_TOTAL = por atleta (squadrats.json); MARCOS_CLUBE = união do
# clube (soma de club_regioes.uniao.by_pais). Só squadratinhos, não squadrats.
MARCOS_TOTAL = [1000, 2500, 5000, 7500, 10000, 15000, 20000, 30000, 50000, 75000, 100000]
MARCOS_CLUBE = [5000, 10000, 25000, 50000, 100000, 250000]

ATLETAS_ORDEM = ["Zé", "Xeira", "Carolina", "Inês S.", "Pedro"]

DESDE = "2026-07-26"  # 1.º dia com club.json

# atividades partilhadas (um grava, o outro recebe a mesma atividade): ver
# carregar_partilhadas
PARTILHADAS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "atividades_partilhadas.json")

# correcções de snapshots publicados (histórico da branch data não se reescreve)
CORRECOES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "correcoes_snapshots.json")


def carregar_correcoes(path=CORRECOES):
    """{sha: {atleta: sha_correcto}} de correcoes_snapshots.json, sem "motivo".

    Formato do ficheiro: {sha: {atleta: sha_correcto, ..., "motivo": "..."}}.
    No snapshot `sha`, a entrada de `atleta` em "atletas" passa a ser a do
    snapshot `sha_correcto` (mesmo ficheiro). Serve para dados publicados que
    a fonte depois desmentiu (ex. atividade apagada pelo atleta): todos os
    passos que lêem o histórico vêem o valor corrigido. Só o bloco "atletas";
    agregados como `uniao` do club_regioes.json ficam como estão. SHAs
    completos, para não haver ambiguidade. Sem ficheiro: {}."""
    import json
    import re

    try:
        with open(path, encoding="utf-8") as f:
            raw = json.load(f)
    except FileNotFoundError:
        return {}
    sha_ok = re.compile(r"[0-9a-f]{40}")
    out = {}
    for sha, por_atleta in raw.items():
        subs = {a: s for a, s in por_atleta.items() if a != "motivo"}
        for s in (sha, *subs.values()):
            if not sha_ok.fullmatch(s):
                raise ValueError(f"{path}: '{s}' não é um SHA completo")
        if subs:
            out[sha] = subs
    return out


def carregar_partilhadas(path=PARTILHADAS):
    """[{data, atletas, regioes?, motivo?}, ...] de atividades_partilhadas.json. Sem ficheiro: [].

    Formato de cada entrada: "data" (YYYY-MM-DD), "atletas" (lista de nomes),
    "regioes" (opcional, nomes de concelho/distrito), "motivo" (texto livre).
    Exemplo: {"data": "2026-10-03", "atletas": ["Zé", "Pedro"],
    "regioes": ["Alcanena"], "motivo": "Zé gravou, Pedro recebeu"}.

    Uma atividade gravada por um atleta e recebida por outro dá as mesmas tiles
    aos dois, mas os snapshots podem apanhá-los em runs diferentes, e a
    diferença parece uma ultrapassagem. Cada entrada suprime, nesse `data`, os
    eventos novo_lider/ultrapassagem entre `atletas` (quem e sobre ambos na
    lista), em `regioes` (nomes de concelho/distrito) ou em todas se omitido.
    Mais campos (ex. "motivo") são ignorados."""
    import json

    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return []


def snapshots_commits(repo, branch, path, desde=None, com_anterior=False, correcoes=None):
    """(snaps, saltados). `snaps` = [(datetime, dict), ...] em ordem
    cronológica, um por commit de `path` na branch (o dict tem de ter
    "atualizado").

    `correcoes` ({sha: {atleta: sha_correcto}}, por omissão o
    correcoes_snapshots.json, ver carregar_correcoes) é aplicado a cada
    snapshot lido. Uma correcção que não dê para aplicar levanta RuntimeError,
    antes isso que publicar o valor que se quis corrigir.

    `desde` (YYYY-MM-DD) limita a leitura aos commits desse dia em diante. Com
    `com_anterior=True` junta também o último commit antes de `desde`, a base
    para comparar o próprio dia `desde`.

    `saltados` = [(sha, motivo), ...] dos commits que não deu para ler (blob em
    falta num checkout shallow, ou JSON inesperado). Levanta RuntimeError se
    havia commits e nenhum deu para ler. Sem commits devolve ([], []).
    """
    import json
    import subprocess
    from collections import Counter
    from datetime import datetime

    def git(*args):
        return subprocess.run(["git", "-C", repo, *args], capture_output=True, stdin=subprocess.DEVNULL,
                              text=True, encoding="utf-8")

    def log(*args):
        r = git("log", branch, "--format=%H", *args, "--", path)
        r.check_returncode()
        return r.stdout.split()

    shas = log(f"--since={desde}T00:00:00Z") if desde else log()
    if desde and com_anterior:
        shas += log("-1", f"--before={desde}T00:00:00Z")

    if correcoes is None:
        correcoes = carregar_correcoes()
    correctos = {}  # sha_correcto -> "atletas" desse snapshot, lido uma vez

    def corrigir(sha, d):
        for atl, sha_ok in correcoes.get(sha, {}).items():
            if sha_ok not in correctos:
                r = git("show", f"{sha_ok}:{path}")
                if r.returncode != 0:
                    raise RuntimeError(
                        f"correcção de {sha[:8]} ({atl}): {path} ilegível em {sha_ok[:8]}")
                correctos[sha_ok] = json.loads(r.stdout).get("atletas", {})
            if atl in correctos[sha_ok]:
                d.setdefault("atletas", {})[atl] = correctos[sha_ok][atl]
            else:
                d.get("atletas", {}).pop(atl, None)

    snaps, saltados = [], []
    for sha in shas:
        r = git("show", f"{sha}:{path}")
        if r.returncode != 0:
            err = " ".join((r.stderr or "").split())[:120]
            saltados.append((sha, f"git show falhou: {err}" if err else "blob em falta (checkout shallow?)"))
            continue
        try:
            d = json.loads(r.stdout)
            ts = datetime.fromisoformat(d["atualizado"])
        except Exception as e:
            saltados.append((sha, f"{path} inesperado: {type(e).__name__}: {e}"))
            continue
        corrigir(sha, d)
        snaps.append((ts, d))

    if saltados:
        resumo = Counter(m for _, m in saltados)
        print(f"snapshots de {path}: {len(saltados)}/{len(shas)} commit(s) saltado(s), "
              + "; ".join(f"{n}x {m}" for m, n in resumo.most_common()))
    if shas and not snaps:
        raise RuntimeError(
            f"snapshots de {path}: {len(shas)} commit(s) em {branch}, nenhum legível. "
            "Clone shallow demais? (o workflow faz `git fetch origin data` completo)."
        )
    snaps.sort(key=lambda p: p[0])
    return snaps, saltados


def snapshots_por_dia(repo, branch="origin/data", desde=None,
                      path="data/club_regioes.json", com_anterior=False):
    """(por_dia, saltados): {data_utc: dict} com o último snapshot de cada dia
    UTC (ver snapshots_commits). Um commit saltado no meio do histórico faz um
    dia colapsar no anterior; quem chama decide o que fazer com `saltados`."""
    snaps, saltados = snapshots_commits(repo, branch, path, desde, com_anterior)
    return {ts.date().isoformat(): d for ts, d in snaps}, saltados


def _idx(nome):
    return ATLETAS_ORDEM.index(nome) if nome in ATLETAS_ORDEM else 99


def niveis_de(club_regioes):
    """{(cc, nivel, regiao): {atleta: captured}}.

    Hoje só lê os buckets PT (by_concelho/by_distrito), por isso cc é sempre
    "PT". O cc está na chave desde já para a detecção estrangeira ser um
    switch e não uma mudança de forma: quando ligar, by_region entra como
    nivel "distrito" e by_municipio como "concelho" (os MARCOS e o frase()
    do front-end servem os dois), com o cc a separar nomes iguais entre
    países."""
    out = {}
    for nome, info in club_regioes.get("atletas", {}).items():
        for reg, n in (info.get("by_concelho") or {}).items():
            out.setdefault(("PT", "concelho", reg), {})[nome] = n
        for reg, n in (info.get("by_distrito") or {}).items():
            out.setdefault(("PT", "distrito", reg), {})[nome] = n
    return out


def ranking(counts):
    """Lista de atletas com captured > 0, do maior para o menor.
    Empate desempata pela ordem canónica (mesma do bitmask/cores)."""
    presentes = [(n, c) for n, c in counts.items() if c > 0]
    presentes.sort(key=lambda t: (-t[1], _idx(t[0])))
    return [n for n, _ in presentes]


def _cruzado(patamares, antes, agora):
    """O patamar mais alto cruzado entre `antes` e `agora` (None se nenhum).
    Num sync grande (20 -> 55) cruzam-se 25 e 50 de uma vez, mas o 50 já
    implica o 25, o evento pequeno é redundante no feed."""
    cruzados = [T for T in patamares if antes < T <= agora]
    return max(cruzados) if cruzados else None


def _passou(x, y, ca, cb):
    """x passou y: antes x tinha estritamente menos que y (y presente), agora estritamente mais."""
    return ca.get(x, 0) < ca.get(y, 0) and cb.get(x, 0) > cb.get(y, 0)


def detectar(anterior, atual, data, partilhadas=()):
    """Eventos ao passar de `anterior` -> `atual` (dois club_regioes.json).
    `data` é a data (YYYY-MM-DD, UTC) a que o evento fica atribuído.

    Devolve eventos PLANOS (um por tipo; para o formato de events.json ver
    detectar_dia): {data, nivel, cc, regiao, tipo, quem, sobre, valores}.
    `sobre` = quem foi passado / ex-líder (None quando não se aplica).
    `partilhadas` = carregar_partilhadas(); suprime passou/novo_lider entre
    atletas de uma atividade partilhada nesse dia.
    `valores` = [quem, sobre] na ultrapassagem; [patamar, contagem] no marco;
                [contagem] nos restantes.
    """
    eventos = []
    na, nb = niveis_de(anterior), niveis_de(atual)

    # Atleta que entra no roster não gera eventos no 1.º snapshot em que
    # aparece, senão "passava" toda a gente num dia só.
    estreantes = (set((atual or {}).get("atletas", {}))
                  - set((anterior or {}).get("atletas", {})))

    for chave, cb in nb.items():
        cc, nivel, reg = chave
        ca = na.get(chave, {})
        ra = ranking(ca)
        rb = ranking(cb)

        # --- marcos (independentes do ranking), só o patamar mais alto/dia ---
        for atl, agora in cb.items():
            T = _cruzado(MARCOS.get(nivel, []), ca.get(atl, 0), agora)
            if T is not None:
                eventos.append(_ev(data, cc, nivel, reg, "marco", atl, None, [T, agora]))

        if ra == rb:
            continue

        # --- novo líder (havia líder antes e mudou) ---
        par_lideranca = None
        if ra and rb and ra[0] != rb[0]:
            novo, ex = rb[0], ra[0]
            if _passou(novo, ex, ca, cb):
                par_lideranca = (novo, ex)
                eventos.append(_ev(data, cc, nivel, reg, "novo_lider", novo, ex,
                                   [cb.get(novo, 0), cb.get(ex, 0)]))

        # --- ultrapassagens (pares que trocaram), menos o par da liderança ---
        for x in rb:
            for y in rb:
                if (x, y) != par_lideranca and _passou(x, y, ca, cb):
                    eventos.append(_ev(data, cc, nivel, reg, "ultrapassagem", x, y,
                                       [cb[x], cb[y]]))

        # --- primeira presença (região que já tinha outro atleta) ---
        for n in rb:
            if ca.get(n, 0) == 0 and len(ra) >= 1:
                eventos.append(_ev(data, cc, nivel, reg, "primeira_presenca", n, None,
                                   [cb.get(n, 0)]))

    def partilhado(e):
        return any(p["data"] == data and {e["quem"], e["sobre"]} <= set(p["atletas"])
                   and e["regiao"] in (p.get("regioes") or [e["regiao"]])
                   for p in partilhadas)

    return [
        e for e in eventos
        if e["quem"] not in estreantes
        and not (e["tipo"] in ("novo_lider", "ultrapassagem") and partilhado(e))
    ]


def _ev(data, cc, nivel, reg, tipo, quem, sobre, valores):
    return {
        "data": data,
        "nivel": nivel,
        "cc": cc,
        "regiao": reg,
        "tipo": tipo,
        "quem": quem,
        "sobre": sobre,
        "valores": valores,
    }


TIPOS_TOTAIS = ("marco_total", "marco_clube")


def totais_sqi(squadrats):
    """{atleta: squadratinhos} de um snapshot de squadrats.json."""
    return {n: (v or {}).get("squadratinhos", 0)
            for n, v in (squadrats or {}).get("atletas", {}).items()}


def uniao_clube(club_regioes):
    """União do clube = soma dos squadratinhos que ≥1 membro tem, por país
    (club_regioes.uniao.by_pais). None se o bloco não existir."""
    by = ((club_regioes or {}).get("uniao") or {}).get("by_pais") or {}
    return sum(by.values()) if by else None


def detectar_totais(sq_ant, sq_hoje, uni_ant, uni_hoje, data):
    """Marcos de squadratinhos TOTAIS ao passar de um snapshot para o seguinte.
    `sq_*` = {atleta: squadratinhos} (de squadrats.json); `uni_*` = int, a
    união do clube (ou None se indisponível). Eventos sem região:
      marco_total  um atleta cruzou um patamar de MARCOS_TOTAL (quem = atleta)
      marco_clube  a união do clube cruzou um patamar de MARCOS_CLUBE (quem = None)
    Um atleta que aparece pela 1.ª vez no snapshot não gera marco (mesma guarda
    de estreante do detectar()).
    """
    out = []
    estreantes = set(sq_hoje) - set(sq_ant)
    for atl, agora in sq_hoje.items():
        if atl in estreantes:
            continue
        T = _cruzado(MARCOS_TOTAL, sq_ant.get(atl, 0), agora)
        if T is not None:
            out.append({"data": data, "cc": None, "nivel": "total",
                        "regiao": None, "tipo": "marco_total", "quem": atl,
                        "sobre": None, "valores": [T, agora]})
    if uni_ant is not None and uni_hoje is not None:
        T = _cruzado(MARCOS_CLUBE, uni_ant, uni_hoje)
        if T is not None:
            out.append({"data": data, "cc": None, "nivel": "total",
                        "regiao": None, "tipo": "marco_clube", "quem": None,
                        "sobre": None, "valores": [T, uni_hoje]})
    return out


# ordem das partes dentro de uma entrada regional (a ordem em que se lê a frase:
# estreia, o marco que fez, quem passou, e por fim a liderança)
ORDEM_PARTE = ["primeira_presenca", "marco", "ultrapassagem", "novo_lider"]


def combinar(planos, atual):
    """Junta eventos planos (saída de detectar) por (data, cc, nivel, regiao,
    quem) numa entrada:

        {data, nivel, cc, regiao, quem, partes: [...], contagem}

    `partes` = [{tipo, sobre?, valores?}] sempre na ordem de ORDEM_PARTE:
      primeira_presenca  {tipo}
      marco              {tipo, valores: [patamar]}
      ultrapassagem      {tipo, sobre: [superados], valores: [contagem de cada um]}
                         (várias no dia/região juntam-se numa parte; os superados
                         por ordem de contagem final, o mais próximo primeiro)
      novo_lider         {tipo, sobre: ex_lider, valores: [contagem do ex-líder]}
    `contagem` = squadratinhos de `quem` na região no fim do dia (em `atual`,
    o club_regioes.json do fim do dia). A ordem das entradas é a de ordenar_feed."""
    fim = niveis_de(atual)
    grupos = {}
    for e in planos:
        k = (e["data"], e["cc"], e["nivel"], e["regiao"], e["quem"])
        grupos.setdefault(k, []).append(e)
    out = []
    for (data, cc, nivel, reg, quem), evs in grupos.items():
        contagens = fim.get((cc, nivel, reg), {})
        partes = []
        if any(e["tipo"] == "primeira_presenca" for e in evs):
            partes.append({"tipo": "primeira_presenca"})
        marcos = [e["valores"][0] for e in evs if e["tipo"] == "marco"]
        if marcos:
            partes.append({"tipo": "marco", "valores": [max(marcos)]})
        sobre = {e["sobre"] for e in evs if e["tipo"] == "ultrapassagem"}
        if sobre:
            sobre = sorted(sobre, key=lambda n: (-contagens.get(n, 0), _idx(n)))
            partes.append({"tipo": "ultrapassagem", "sobre": sobre,
                           "valores": [contagens.get(n, 0) for n in sobre]})
        for e in evs:
            if e["tipo"] == "novo_lider":
                partes.append({"tipo": "novo_lider", "sobre": e["sobre"],
                               "valores": [contagens.get(e["sobre"], 0)]})
        out.append({"data": data, "nivel": nivel, "cc": cc, "regiao": reg,
                    "quem": quem, "partes": partes, "contagem": contagens.get(quem, 0)})
    return ordenar_feed(out)


def detectar_dia(anterior, atual, data, partilhadas=()):
    """Entradas regionais (formato de events.json) de `anterior` -> `atual`."""
    return combinar(detectar(anterior, atual, data, partilhadas), atual)


def migrar_planos(planos):
    """Converte eventos planos já publicados (formato antigo do events.json,
    sem `partes`) no formato novo. Serve para os dias que não dá para recalcular
    (antes do 1.º club_regioes.json no histórico, reconstruídos do club.json).
    A contagem final não está guardada: sai do maior valor que os eventos do
    dia registaram para cada atleta (as contagens só sobem)."""
    fim = {}  # (data, cc, nivel, regiao) -> {atleta: contagem}
    for e in planos:
        c = fim.setdefault((e["data"], e["cc"], e["nivel"], e["regiao"]), {})
        v = e["valores"]
        vistos = [(e["quem"], v[1] if e["tipo"] == "marco" else v[0])]
        if e["tipo"] in ("ultrapassagem", "novo_lider"):
            vistos.append((e["sobre"], v[1]))
        for n, x in vistos:
            c[n] = max(c.get(n, 0), x)
    out = []
    for (data, cc, nivel, reg), contagens in fim.items():
        chave = "by_concelho" if nivel == "concelho" else "by_distrito"
        atual = {"atletas": {n: {chave: {reg: x}} for n, x in contagens.items()}}
        dia = [e for e in planos
               if (e["data"], e["cc"], e["nivel"], e["regiao"]) == (data, cc, nivel, reg)]
        out.extend(combinar(dia, atual))
    return ordenar_feed(out)


_NIVEL_ORDEM = {"distrito": 0, "concelho": 1}
_TOTAL_ORDEM = {"marco_clube": 0, "marco_total": 1}


def ordenar_feed(evs):
    """Ordena para o feed: dia asc (o site inverte); dentro do dia os marcos de
    totais primeiro (clube antes de atleta), depois as entradas regionais
    agrupadas por país, nível (distrito antes de concelho) e região."""
    def k(e):
        if e.get("tipo") in TIPOS_TOTAIS:
            return (e["data"], 0, _TOTAL_ORDEM[e["tipo"]], "", "", _idx(e.get("quem")))
        return (e["data"], 1, e.get("cc") or "", _NIVEL_ORDEM.get(e["nivel"], 9),
                e.get("regiao") or "", _idx(e.get("quem")))
    return sorted(evs, key=k)
