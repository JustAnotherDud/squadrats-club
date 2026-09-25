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


# --- identidade inclui o país -------------------------------------------------

def test_chave_separa_por_pais():
    """Dois eventos iguais em tudo menos o cc não colapsam no append."""
    base = {"data": "2026-09-05", "nivel": "distrito", "regiao": "Madrid",
            "tipo": "primeira_presenca", "quem": "Zé", "sobre": None, "valores": [3]}
    pt = {**base, "cc": "PT"}
    es = {**base, "cc": "ES"}
    assert eventos.chave(pt) != eventos.chave(es)


def test_colapsar_marcos_nao_mistura_paises():
    """Um marco 50 em Madrid/ES e um marco 25 em Madrid/PT no mesmo dia: cada
    um sobrevive, não é o 50 a absorver o 25 do outro país."""
    evs = [
        {"data": "2026-09-05", "cc": "ES", "nivel": "distrito", "regiao": "Madrid",
         "tipo": "marco", "quem": "Zé", "sobre": None, "valores": [50, 60]},
        {"data": "2026-09-05", "cc": "PT", "nivel": "distrito", "regiao": "Madrid",
         "tipo": "marco", "quem": "Zé", "sobre": None, "valores": [25, 30]},
    ]
    out = eventos.colapsar_marcos(evs)
    assert {(e["cc"], e["valores"][0]) for e in out} == {("ES", 50), ("PT", 25)}


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


def test_ordenar_feed_marcos_de_totais_no_topo_do_dia():
    ev = lambda tipo, **kw: {"data": "2026-09-10", "nivel": kw.get("nivel", "concelho"),
        "regiao": kw.get("regiao"), "cc": kw.get("cc"), "tipo": tipo,
        "quem": kw.get("quem", "Zé"), "sobre": kw.get("sobre"), "valores": [1, 2]}
    baralhado = [
        ev("marco", regiao="Arouca", cc="PT"),
        ev("marco_total", nivel="total"),
        ev("novo_lider", regiao="Arouca", cc="PT", sobre="Pedro"),
        ev("marco_clube", nivel="total", quem=None),
    ]
    tipos = [e["tipo"] for e in eventos.ordenar_feed(baralhado)]
    assert tipos[:2] == ["marco_clube", "marco_total"]  # totais primeiro
    assert tipos[2:] == ["novo_lider", "marco"]         # regionais a seguir, na ordem normal


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


def test_primeira_presenca_suprimida_quando_ha_movimento_forte():
    """Quem chega a uma região nova E passa alguém no mesmo dia não sai com
    duas frases, fica só a ultrapassagem/novo_lider. (Zé já está no roster,
    com actividade noutra região, não é estreante.)"""
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
    assert "novo_lider" in tipos
    assert "primeira_presenca" not in tipos  # não repete o mesmo movimento


# --- marcos: só o patamar mais alto por dia/região/atleta -----------------

def test_um_sync_cruza_dois_patamares_gera_so_o_mais_alto():
    """20 -> 55 cruza 25 e 50 no mesmo sync, só sai o 50 (implica o 25)."""
    ant = _snap({"Zé": {"concelho": {"Rio Maior": 20}}})
    novo = _snap({"Zé": {"concelho": {"Rio Maior": 55}}})
    evs = eventos.detectar(ant, novo, "2026-08-04")
    marcos = [e for e in evs if e["tipo"] == "marco"]
    assert len(marcos) == 1
    assert marcos[0]["valores"] == [50, 55]


def test_colapsar_marcos_entre_runs_do_mesmo_dia():
    """Runs sucessivos acrescentaram marco 25 e depois marco 50 em separado,
    colapsar_marcos fica só com o 50, sem tocar nos outros tipos."""
    evs = [
        {"data": "2026-08-04", "nivel": "concelho", "regiao": "Rio Maior",
         "tipo": "marco", "quem": "Zé", "sobre": None, "valores": [25, 40]},
        {"data": "2026-08-04", "nivel": "concelho", "regiao": "Rio Maior",
         "tipo": "marco", "quem": "Zé", "sobre": None, "valores": [50, 55]},
        {"data": "2026-08-04", "nivel": "concelho", "regiao": "Peniche",
         "tipo": "ultrapassagem", "quem": "Zé", "sobre": "Pedro", "valores": [70, 65]},
        {"data": "2026-08-05", "nivel": "concelho", "regiao": "Rio Maior",
         "tipo": "marco", "quem": "Zé", "sobre": None, "valores": [25, 30]},
    ]
    out = eventos.colapsar_marcos(evs)
    marcos_rm = [e for e in out if e["tipo"] == "marco" and e["regiao"] == "Rio Maior"
                 and e["data"] == "2026-08-04"]
    assert [e["valores"][0] for e in marcos_rm] == [50]
    assert any(e["tipo"] == "ultrapassagem" for e in out)      # outros tipos intactos
    assert any(e["data"] == "2026-08-05" for e in out)         # outros dias intactos


def test_ordenar_feed_movimento_antes_do_marco():
    """Dentro de uma região/dia: novo_lider < ultrapassagem < primeira_presenca
    < marco."""
    def ev(tipo, regiao="Arouca"):
        return {"data": "2026-08-04", "nivel": "concelho", "regiao": regiao,
                "tipo": tipo, "quem": "Zé", "sobre": "Pedro" if "passa" in tipo else None,
                "valores": [1]}
    baralhado = [ev("marco"), ev("primeira_presenca"), ev("novo_lider"), ev("ultrapassagem")]
    ordem = [e["tipo"] for e in eventos.ordenar_feed(baralhado)]
    assert ordem == ["novo_lider", "ultrapassagem", "primeira_presenca", "marco"]
