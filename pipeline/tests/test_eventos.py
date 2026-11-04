"""Testes do eventos.detectar, sobretudo a guarda de estreia de atleta.

O append (run_all.py) nunca exercita essa guarda hoje: os 5 atletas já estão
todos no roster. Estes testes garantem que a guarda não apodrece até alguém
acrescentar um atleta ao ATHLETES_JSON.

Correr: py -m pytest
"""
import eventos


def _snap(atletas):
    """atletas: {nome: {concelho: {reg: n}, distrito: {reg: n}}} -> club_regioes-shaped."""
    return {"atletas": {
        nome: {"by_concelho": v.get("concelho", {}), "by_distrito": v.get("distrito", {})}
        for nome, v in atletas.items()
    }}


def _tipos(evs, quem=None):
    return sorted(e["tipo"] for e in evs if quem is None or e["quem"] == quem)


# --- guarda de estreia -------------------------------------------------------

def test_estreante_nao_gera_eventos():
    """Atleta novo aparece com squares em várias regiões: zero eventos para ele."""
    ant = _snap({
        "Zé":    {"concelho": {"Rio Maior": 40}, "distrito": {"Santarém": 40}},
        "Xeira": {"concelho": {"Rio Maior": 10}, "distrito": {"Santarém": 10}},
    })
    novo = _snap({
        "Zé":    {"concelho": {"Rio Maior": 40}, "distrito": {"Santarém": 40}},
        "Xeira": {"concelho": {"Rio Maior": 10}, "distrito": {"Santarém": 10}},
        "Pedro": {"concelho": {"Rio Maior": 99, "Peniche": 30},
                  "distrito": {"Santarém": 99, "Leiria": 30}},
    })
    evs = eventos.detectar(ant, novo, "2026-08-01")
    assert _tipos(evs, "Pedro") == []
    assert all(e["quem"] != "Pedro" and e["sobre"] != "Pedro" for e in evs)


def test_estreante_nao_e_passado_por_estabelecido():
    """Um atleta estabelecido não 'ultrapassa' quem acabou de aparecer abaixo dele."""
    ant = _snap({"Zé": {"concelho": {"Rio Maior": 40}}})
    novo = _snap({
        "Zé":    {"concelho": {"Rio Maior": 41}},
        "Pedro": {"concelho": {"Rio Maior": 5}},
    })
    evs = eventos.detectar(ant, novo, "2026-08-01")
    assert "ultrapassagem" not in _tipos(evs)


def test_marco_de_estabelecido_sobrevive_a_estreia_de_outro():
    """A guarda só apanha o estreante, o marco genuíno de outro atleta fica."""
    ant = _snap({"Zé": {"concelho": {"Rio Maior": 40}, "distrito": {"Santarém": 40}}})
    novo = _snap({
        "Zé":    {"concelho": {"Rio Maior": 55}, "distrito": {"Santarém": 55}},
        "Pedro": {"concelho": {"Rio Maior": 99}, "distrito": {"Santarém": 99}},
    })
    evs = eventos.detectar(ant, novo, "2026-08-01")
    marcos_ze = [e for e in evs if e["tipo"] == "marco" and e["quem"] == "Zé"]
    assert {e["valores"][0] for e in marcos_ze} == {50}  # cruzou 50 (25 já era antes)
    assert _tipos(evs, "Pedro") == []


# --- comportamento base (rede de regressão) --------------------------------

def test_ultrapassagem_entre_estabelecidos():
    ant = _snap({"Zé": {"concelho": {"Óbidos": 8}}, "Carolina": {"concelho": {"Óbidos": 5}}})
    novo = _snap({"Zé": {"concelho": {"Óbidos": 8}}, "Carolina": {"concelho": {"Óbidos": 12}}})
    evs = eventos.detectar(ant, novo, "2026-09-05")
    # Carolina passou o Zé no topo -> conta como novo_lider, não ultrapassagem
    assert _tipos(evs) == ["novo_lider"]
    e = evs[0]
    assert e["quem"] == "Carolina" and e["sobre"] == "Zé"
    assert e["cc"] == "PT"  # niveis_de só lê buckets PT por agora


# --- marcos de totais (squadratinhos do atleta / união do clube) -----------

def test_marco_total_do_atleta():
    a = {"Zé": 4800, "Xeira": 6100}
    b = {"Zé": 5050, "Xeira": 6100}
    evs = eventos.detectar_totais(a, b, None, None, "2026-09-10")
    assert len(evs) == 1
    e = evs[0]
    assert e["tipo"] == "marco_total" and e["quem"] == "Zé"
    assert e["valores"] == [5000, 5050] and e["regiao"] is None


def test_marco_total_so_o_patamar_mais_alto():
    """Um salto grande (backlog de sync) cruza 5000 e 7500 de uma vez: só sai
    o 7500, e o colapso confirma."""
    evs = eventos.detectar_totais({"Zé": 4900}, {"Zé": 7600}, None, None, "2026-09-10")
    assert [e["valores"][0] for e in evs] == [7500]


def test_marco_clube_uniao():
    evs = eventos.detectar_totais({}, {}, 9800, 10200, "2026-09-10")
    assert len(evs) == 1
    assert evs[0]["tipo"] == "marco_clube" and evs[0]["quem"] is None
    assert evs[0]["valores"] == [10000, 10200]


def test_marco_total_estreante_nao_gera():
    evs = eventos.detectar_totais({"Zé": 4900}, {"Zé": 5100, "Novo": 5200}, None, None, "2026-09-10")
    assert {e["quem"] for e in evs} == {"Zé"}  # "Novo" não gera nada


def _entrada(regiao, nivel="concelho", quem="Zé", cc="PT", data="2026-09-10"):
    return {"data": data, "nivel": nivel, "cc": cc, "regiao": regiao, "quem": quem,
            "partes": [{"tipo": "marco", "valores": [25]}], "contagem": 30}


def test_ordenar_feed_totais_no_topo_e_distrito_antes_de_concelho():
    totais = [{"data": "2026-09-10", "cc": None, "nivel": "total", "regiao": None,
               "tipo": t, "quem": q, "sobre": None, "valores": [1, 2]}
              for t, q in (("marco_total", "Zé"), ("marco_clube", None))]
    baralhado = [
        _entrada("Arouca"), totais[0],
        _entrada("Porto", nivel="distrito"),
        _entrada("Espinho", cc="ES"),
        totais[1],
        _entrada("Aveiro", nivel="distrito"),
        _entrada("Arouca", quem="Pedro"),
        _entrada("Amadora", data="2026-09-09"),
    ]
    ordem = [(e.get("tipo") or (e["cc"], e["nivel"], e["regiao"], e["quem"]))
             for e in eventos.ordenar_feed(baralhado)]
    assert ordem == [
        ("PT", "concelho", "Amadora", "Zé"),   # dia anterior primeiro (o site inverte)
        "marco_clube", "marco_total",           # totais no topo do dia
        ("ES", "concelho", "Espinho", "Zé"),    # por país
        ("PT", "distrito", "Aveiro", "Zé"),     # distrito antes de concelho
        ("PT", "distrito", "Porto", "Zé"),
        ("PT", "concelho", "Arouca", "Zé"),     # mesma região: ordem dos atletas
        ("PT", "concelho", "Arouca", "Pedro"),
    ]


def test_ultrapassagem_fora_do_topo():
    ant = _snap({
        "Zé":    {"distrito": {"Leiria": 100}},
        "Xeira": {"distrito": {"Leiria": 20}},
        "Pedro": {"distrito": {"Leiria": 15}},
    })
    novo = _snap({
        "Zé":    {"distrito": {"Leiria": 100}},
        "Xeira": {"distrito": {"Leiria": 20}},
        "Pedro": {"distrito": {"Leiria": 25}},
    })
    evs = eventos.detectar(ant, novo, "2026-09-05")
    assert _tipos(evs) == ["ultrapassagem"]
    assert evs[0]["quem"] == "Pedro" and evs[0]["sobre"] == "Xeira"


def test_ordem_igual_nao_gera_ultrapassagem():
    ant = _snap({"Zé": {"concelho": {"Arouca": 10}}, "Pedro": {"concelho": {"Arouca": 5}}})
    novo = _snap({"Zé": {"concelho": {"Arouca": 20}}, "Pedro": {"concelho": {"Arouca": 8}}})
    evs = eventos.detectar(ant, novo, "2026-09-06")
    assert "ultrapassagem" not in _tipos(evs)
    assert "novo_lider" not in _tipos(evs)


def test_primeira_presenca_nao_e_suprimida_por_movimento_forte():
    """Quem chega a uma região nova E assume a liderança no mesmo dia fica com
    as duas partes (detectar não esconde nada; a combinação trata de juntar)."""
    ant = _snap({
        "Xeira": {"concelho": {"Espinho": 30}},
        "Zé":    {"concelho": {"Porto": 5}},
    })
    novo = _snap({
        "Xeira": {"concelho": {"Espinho": 30}},
        "Zé":    {"concelho": {"Espinho": 40, "Porto": 5}},
    })
    evs = eventos.detectar(ant, novo, "2026-09-04")
    tipos = _tipos(evs, "Zé")
    assert "novo_lider" in tipos and "primeira_presenca" in tipos


# --- marcos: só o patamar mais alto por dia/região/atleta -----------------

def test_um_sync_cruza_dois_patamares_gera_so_o_mais_alto():
    """20 -> 55 cruza 25 e 50 no mesmo sync, só sai o 50 (implica o 25)."""
    ant = _snap({"Zé": {"concelho": {"Rio Maior": 20}}})
    novo = _snap({"Zé": {"concelho": {"Rio Maior": 55}}})
    evs = eventos.detectar(ant, novo, "2026-08-04")
    marcos = [e for e in evs if e["tipo"] == "marco"]
    assert len(marcos) == 1
    assert marcos[0]["valores"] == [50, 55]


# --- ultrapassagem: só por contagem estritamente maior -----------------------

def _c(**n):
    return _snap({k: {"concelho": {"Alcanena": v}} for k, v in n.items()})


def test_empate_nao_gera_passou():
    # Zé sobe para empatar com o Pedro (que desempata melhor? não: Zé vem antes na ordem)
    evs = eventos.detectar(_c(Zé=1, Pedro=2), _c(Zé=2, Pedro=2), "2026-10-03")
    assert _tipos(evs) == []
    # quem estava à frente e passa a empatar também não
    evs = eventos.detectar(_c(Zé=2, Pedro=3), _c(Zé=2, Pedro=2), "2026-10-03")
    assert _tipos(evs) == []


def test_saida_de_empate_para_a_frente_nao_gera_passou():
    assert _tipos(eventos.detectar(_c(Zé=5, Pedro=5), _c(Zé=6, Pedro=5), "2026-10-03")) == []


def test_ultrapassagem_estrita_gera():
    ant, novo = _c(Xeira=9, Zé=5, Pedro=3), _c(Xeira=9, Zé=5, Pedro=6)
    evs = eventos.detectar(ant, novo, "2026-10-03")
    assert [(e["tipo"], e["quem"], e["sobre"]) for e in evs] == [("ultrapassagem", "Pedro", "Zé")]


def test_atividade_partilhada_nao_gera():
    ant, novo = _c(Xeira=9, Pedro=7, Zé=5), _c(Xeira=9, Pedro=7, Zé=8)
    assert _tipos(eventos.detectar(ant, novo, "2026-10-03")) == ["ultrapassagem"]
    p = [{"data": "2026-10-03", "atletas": ["Zé", "Pedro"], "regioes": ["Alcanena"]}]
    assert eventos.detectar(ant, novo, "2026-10-03", p) == []
    # outro dia, outra região ou outro atleta: não suprime
    assert eventos.detectar(ant, novo, "2026-10-04", p)
    assert eventos.detectar(ant, novo, "2026-10-03", [{**p[0], "regioes": ["Porto de Mós"]}])
    assert eventos.detectar(ant, novo, "2026-10-03", [{**p[0], "atletas": ["Zé", "Xeira"]}])


def test_caso_real_03_out_zero_eventos():
    """Zé e Pedro entram juntos (0 -> 2 e 0 -> 13) com Inês S. já em 12 em Alcanena."""
    ant = _snap({"Inês S.": {"concelho": {"Alcanena": 12}}, "Zé": {}, "Pedro": {}})
    novo = _snap({"Inês S.": {"concelho": {"Alcanena": 12}},
                  "Zé": {"concelho": {"Alcanena": 2, "Porto de Mós": 13}},
                  "Pedro": {"concelho": {"Alcanena": 2, "Porto de Mós": 13}}})
    partilhadas = [{"data": "2026-10-03", "atletas": ["Zé", "Pedro"],
                    "regioes": ["Alcanena", "Porto de Mós"]}]
    for p in ((), partilhadas):  # a correção 1 chega; a lista também não estraga
        evs = eventos.detectar(ant, novo, "2026-10-03", p)
        assert not [e for e in evs if e["tipo"] in ("ultrapassagem", "novo_lider")]


# --- combinar: uma entrada por (data, cc, nivel, regiao, quem) ----------------

def _entradas(ant, novo, data="2026-11-04"):
    return eventos.detectar_dia(ant, novo, data)


def _partes(entrada):
    return [p["tipo"] for p in entrada["partes"]]


def test_combina_estreia_marco_e_ultrapassagem():
    """O caso real de Matosinhos (04 nov): estreia + marco 25 + passa o Pedro."""
    ant = _snap({"Pedro": {"concelho": {"Matosinhos": 12}}, "Zé": {"concelho": {"Porto": 5}}})
    novo = _snap({"Pedro": {"concelho": {"Matosinhos": 12}},
                  "Zé": {"concelho": {"Matosinhos": 26, "Porto": 5}}})
    (e,) = _entradas(ant, novo)
    assert (e["quem"], e["regiao"], e["nivel"], e["cc"]) == ("Zé", "Matosinhos", "concelho", "PT")
    # Zé (26) passa o Pedro (12) e assume o topo: novo_lider em vez de ultrapassagem
    assert _partes(e) == ["primeira_presenca", "marco", "novo_lider"]
    assert e["partes"][1]["valores"] == [25]
    assert e["partes"][2] == {"tipo": "novo_lider", "sobre": "Pedro", "valores": [12]}
    assert e["contagem"] == 26


def test_estreia_que_entra_acima_de_um_patamar_tem_marco():
    ant = _snap({"Xeira": {"concelho": {"Maia": 60}}, "Zé": {"concelho": {"Porto": 5}}})
    novo = _snap({"Xeira": {"concelho": {"Maia": 60}}, "Zé": {"concelho": {"Maia": 44, "Porto": 5}}})
    (e,) = _entradas(ant, novo)
    assert _partes(e) == ["primeira_presenca", "marco"]
    assert e["partes"][1]["valores"] == [25] and e["contagem"] == 44


def test_varias_ultrapassagens_numa_parte_so():
    ant = _snap({"Xeira": {"concelho": {"Arouca": 90}}, "Pedro": {"concelho": {"Arouca": 20}},
                 "Carolina": {"concelho": {"Arouca": 15}}, "Zé": {"concelho": {"Arouca": 10}}})
    novo = _snap({"Xeira": {"concelho": {"Arouca": 90}}, "Pedro": {"concelho": {"Arouca": 20}},
                  "Carolina": {"concelho": {"Arouca": 15}}, "Zé": {"concelho": {"Arouca": 22}}})
    (e,) = _entradas(ant, novo)
    assert e["partes"] == [{"tipo": "ultrapassagem", "sobre": ["Pedro", "Carolina"],
                            "valores": [20, 15]}]
    assert e["contagem"] == 22


def test_concelho_e_distrito_ficam_em_entradas_separadas():
    ant = _snap({"Xeira": {"concelho": {"Gaia": 300}, "distrito": {"Porto": 300}},
                 "Zé": {"concelho": {"Gaia": 90}, "distrito": {"Porto": 90}}})
    novo = _snap({"Xeira": {"concelho": {"Gaia": 300}, "distrito": {"Porto": 300}},
                  "Zé": {"concelho": {"Gaia": 110}, "distrito": {"Porto": 110}}})
    evs = _entradas(ant, novo)
    assert [(e["nivel"], e["regiao"], e["contagem"]) for e in evs] == \
        [("distrito", "Porto", 110), ("concelho", "Gaia", 110)]  # distrito primeiro
    assert all(_partes(e) == ["marco"] and e["partes"][0]["valores"] == [100] for e in evs)


def test_migrar_planos_formato_antigo():
    """Eventos planos já publicados (antes do 1.º club_regioes.json) passam ao formato novo."""
    base = {"data": "2026-08-04", "cc": "PT", "nivel": "concelho", "regiao": "Rio Maior"}
    planos = [
        {**base, "tipo": "primeira_presenca", "quem": "Zé", "sobre": None, "valores": [16]},
        {**base, "tipo": "marco", "quem": "Zé", "sobre": None, "valores": [25, 44]},
        {**base, "tipo": "ultrapassagem", "quem": "Zé", "sobre": "Pedro", "valores": [44, 30]},
    ]
    (e,) = eventos.migrar_planos(planos)
    assert _partes(e) == ["primeira_presenca", "marco", "ultrapassagem"]
    assert e["contagem"] == 44
    assert e["partes"][2] == {"tipo": "ultrapassagem", "sobre": ["Pedro"], "valores": [30]}
