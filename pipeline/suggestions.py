"""Sugestões de progresso (o que falta para o próximo übersquadrat) + o guard
que garante que sabemos reproduzir as regras da Squadrats antes de as usar
para sugerir seja o que for.

verify_rules confirma em cada corrida que as regras batem com o `size` do
servidor (yard e übersquadrat, nas duas grelhas).
"""
from collections import deque

VIZINHOS4 = [(1, 0), (-1, 0), (0, 1), (0, -1)]


def viz4(s):
    return [(s[0] + dx, s[1] + dy) for dx, dy in VIZINHOS4]


def fechados(visitados):
    """Square fechado = visitado E com os 4 vizinhos cardinais visitados."""
    return {s for s in visitados if all(v in visitados for v in viz4(s))}


def clusters_fechados(visitados):
    """Squares fechados agrupados em componentes 4-conexas."""
    porver, clusters = fechados(visitados), []
    while porver:
        raiz = porver.pop()
        comp, fila = {raiz}, deque([raiz])
        while fila:
            x, y = fila.popleft()
            for dx, dy in VIZINHOS4:
                v = (x + dx, y + dy)
                if v in porver:
                    porver.remove(v)
                    comp.add(v)
                    fila.append(v)
        clusters.append(comp)
    return clusters


def maior_uber(visitados):
    """DP clássico do "maior quadrado cheio": dp[x,y] = lado do maior
    quadrado com canto inferior-direito em (x,y)."""
    dp, melhor, canto = {}, 0, None
    for (x, y) in sorted(visitados):
        v = 1 + min(dp.get((x - 1, y), 0), dp.get((x, y - 1), 0), dp.get((x - 1, y - 1), 0))
        dp[(x, y)] = v
        if v > melhor:
            melhor, canto = v, (x, y)
    return melhor, canto


def verify_rules(visitados, esperado_yard, esperado_uber, label):
    """Se isto falhar, não sabemos reproduzir as regras da Squadrats e as
    sugestões seriam inventadas. Falhar alto."""
    clusters = clusters_fechados(visitados)
    maior_yard = max((len(c) for c in clusters), default=0)
    uber, _ = maior_uber(visitados)
    if maior_yard != esperado_yard or uber != esperado_uber:
        raise RuntimeError(
            f"suggestions.py: não reproduzimos as regras da Squadrats para '{label}', "
            f"yard calculado={maior_yard} (servidor diz {esperado_yard}), "
            f"übersquadrat calculado={uber} (servidor diz {esperado_uber}). "
            f"A abortar sem publicar sugestões (seriam inventadas)."
        )


class _Dsu:
    def __init__(self):
        self.pai, self.peso = {}, {}

    def add(self, no, peso):
        if no not in self.pai:
            self.pai[no], self.peso[no] = no, peso

    def find(self, no):
        while self.pai[no] != no:
            self.pai[no] = self.pai[self.pai[no]]
            no = self.pai[no]
        return no

    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.pai[rb] = ra
            self.peso[ra] += self.peso[rb]

    def maior(self):
        return max((self.peso[r] for r in self.pai if self.find(r) == r), default=0)


def _candidatos_ligacao(visitados, tam, comp_id):
    """Para cada square vazio adjacente a algo visitado, vê que fechados nascem
    ao capturá-lo sozinho e a que cluster(es) existentes eles se colam
    (union-find). Devolve TODOS os candidatos com algum ganho, filtrar,
    ordenar e cortar ao top-N fica para quem chama.

    Capturar um square só pode mudar o estado "fechado" dele próprio e dos 4
    vizinhos, nada mais longe depende dele, por isso não é preciso
    recalcular os clusters todos por candidato.
    """
    fech = fechados(visitados)
    candidatos = {v for s in visitados for v in viz4(s) if v not in visitados}

    resultados = []
    for c in candidatos:
        novos = set()
        for s in [c] + viz4(c):
            if s in fech or (s != c and s not in visitados):
                continue
            if all(v in visitados or v == c for v in viz4(s)):
                novos.add(s)
        if not novos:
            continue

        dsu = _Dsu()
        for s in novos:
            dsu.add(("novo", s), 1)
        for s in novos:
            for v in viz4(s):
                if v in novos:
                    dsu.union(("novo", s), ("novo", v))
                elif v in comp_id:
                    i = comp_id[v]
                    dsu.add(("comp", i), tam[i])
                    dsu.union(("novo", s), ("comp", i))

        resultados.append((c, dsu.maior()))
    return resultados


def melhor_ligacao(visitados, top=8):
    """Que square, capturado sozinho, faz o yard crescer mais?

    Muitos clusters fechados secundários estão a um ou dois squares de colar
    ao yard principal, é isso que estas ligações procuram.
    """
    comps = clusters_fechados(visitados)
    comp_id = {s: i for i, c in enumerate(comps) for s in c}
    tam = [len(c) for c in comps]
    yard_atual = max(tam, default=0)

    resultados = []
    for (x, y), maior in _candidatos_ligacao(visitados, tam, comp_id):
        novo_yard = max(yard_atual, maior)
        if novo_yard > yard_atual:
            resultados.append({"x": x, "y": y, "novo_yard": novo_yard,
                               "ganho": novo_yard - yard_atual})

    resultados.sort(key=lambda r: (-r["ganho"], r["x"], r["y"]))
    return {"yard_atual": yard_atual, "melhores": resultados[:top]}


def corredores(visitados, quantos=6, custo_max=80):
    """Quanto custa ligar cada cluster fechado ao yard, e por onde.

    O `melhor_ligacao` só olha para capturas isoladas e por isso nunca vê mais
    do que +4 ou +5. Os saltos grandes estão nos clusters já fechados que estão
    ao lado, ligar um cluster de 29 ao yard pode custar 2 squares e valer +34.

    Um square só fecha com os 4 vizinhos visitados, por isso o corredor precisa
    de largura e não é uma linha: custa mais do que a distância. Dijkstra sobre
    posições, em que entrar numa posição custa os squares por capturar da sua
    cruz. Esse custo por nó sobrestima (nós vizinhos partilham células), por
    isso no fim reconstrói-se o caminho e conta-se a união real.

    O ganho publicado vem sempre de recalcular os clusters com os squares
    adicionados, nunca de aritmética sobre os tamanhos.
    """
    import heapq

    comps = sorted(clusters_fechados(visitados), key=len, reverse=True)
    if len(comps) < 2:
        return []
    yard, yard_tam = comps[0], len(comps[0])

    def cruz(p):
        return [p] + viz4(p)

    def custo(p):
        return sum(1 for c in cruz(p) if c not in visitados)

    def ligar(destino):
        xs = [p[0] for p in yard | destino]
        ys = [p[1] for p in yard | destino]
        x0, x1, y0, y1 = min(xs) - 4, max(xs) + 4, min(ys) - 4, max(ys) + 4
        dist, antes, fila = {}, {}, []
        for p in yard:
            dist[p] = 0
            heapq.heappush(fila, (0, p))
        fim = None
        while fila:
            d, p = heapq.heappop(fila)
            if d > dist.get(p, float("inf")):
                continue
            if p in destino:
                fim = p
                break
            # o corte tem de ser folgado: `d` soma o custo de cada nó como se
            # nada fosse partilhado, e a união real do caminho é bastante
            # menor. Cortar em custo_max aqui matava os corredores longos,
            # justamente os que valem mais. Filtra-se pela união, lá abaixo.
            if d > custo_max * 4:
                break
            for q in viz4(p):
                if not (x0 <= q[0] <= x1 and y0 <= q[1] <= y1):
                    continue
                nd = d + custo(q)
                if nd < dist.get(q, float("inf")):
                    dist[q], antes[q] = nd, p
                    heapq.heappush(fila, (nd, q))
        if fim is None:
            return None
        caminho, p = [], fim
        while p is not None:
            caminho.append(p)
            p = antes.get(p)
        uniao = set()
        for p in caminho:
            uniao |= {c for c in cruz(p) if c not in visitados}
        return uniao

    achados = []
    # só os maiores: há 144 clusters em squadratinhos e a esmagadora maioria
    # são um square isolado, que não vale a pena ligar a nada
    for alvo in comps[1:9]:
        uniao = ligar(alvo)
        if uniao is None or not uniao or len(uniao) > custo_max:
            continue
        novo = max(len(c) for c in clusters_fechados(visitados | uniao))
        if novo <= yard_tam:
            continue
        achados.append({
            "alvo": len(alvo),
            "custo": len(uniao),
            "novo_yard": novo,
            "ganho": novo - yard_tam,
            "squares": [{"x": x, "y": y} for x, y in sorted(uniao)],
        })

    # por ganho, não por custo: ordenar por custo enche a lista de clusters de
    # 1 square colados ao yard, que custam pouco e não valem nada
    achados.sort(key=lambda a: (-a["ganho"], a["custo"]))
    return achados[:quantos]


def proximo_ubersquadrat(visitados, n_atual, margem=2):
    """Para o alvo N = n_atual+1, encontra a janela NxN com menos squares em
    falta. Prefix-sum sobre a bbox dos visitados (+ margem) para não ter de
    testar janela a janela em O(N²)."""
    n = n_atual + 1
    xs = [x for x, y in visitados]
    ys = [y for x, y in visitados]
    x0, x1 = min(xs) - margem, max(xs) + margem
    y0, y1 = min(ys) - margem, max(ys) + margem
    w, h = x1 - x0 + 2, y1 - y0 + 2  # +1 p/ prefix sum, +1 p/ folga

    grid = [[0] * w for _ in range(h)]
    for x, y in visitados:
        if x0 <= x <= x1 and y0 <= y <= y1:
            grid[y - y0 + 1][x - x0 + 1] = 1

    prefix = [[0] * w for _ in range(h)]
    for yy in range(1, h):
        for xx in range(1, w):
            prefix[yy][xx] = (grid[yy][xx] + prefix[yy - 1][xx]
                               + prefix[yy][xx - 1] - prefix[yy - 1][xx - 1])

    def soma(x_ini, y_ini, tam):
        x_fim, y_fim = x_ini + tam, y_ini + tam
        if x_fim >= w or y_fim >= h:
            return -1  # fora da grelha (prefix não cobre), ignorar
        return (prefix[y_fim][x_fim] - prefix[y_ini][x_fim]
                - prefix[y_fim][x_ini] + prefix[y_ini][x_ini])

    melhor_falta, melhor_janela = n * n + 1, None
    for yy in range(0, h - n):
        for xx in range(0, w - n):
            capturados = soma(xx, yy, n)
            if capturados < 0:
                continue
            falta = n * n - capturados
            if 0 < falta < melhor_falta:
                melhor_falta = falta
                melhor_janela = (xx, yy)

    if melhor_janela is None:
        return None

    xx, yy = melhor_janela
    x_ini, y_ini = xx + x0, yy + y0
    faltam = [
        (x_ini + dx, y_ini + dy)
        for dx in range(n) for dy in range(n)
        if (x_ini + dx, y_ini + dy) not in visitados
    ]
    return {"n_alvo": n, "faltam": melhor_falta, "squares_em_falta": faltam,
            "canto": (x_ini, y_ini)}
