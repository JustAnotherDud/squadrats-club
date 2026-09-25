"""Classificação por concelho/distrito/região dos squares de todos os
atletas do clube, data/club_regioes.json. Lê o club.json da mesma corrida,
sem pedidos de rede.

Escreve dois blocos: "atletas" (captured por região, por atleta) e "uniao"
(squadratinhos que o clube cobre por região, partilhados contados uma vez;
usado como número e ordenação do regioes/index.html via regioes.py). Os
totais (denominador) são os mesmos para toda a gente, já em stats.json (via
grid_totals.json, ver build_analise.py): o frontend combina os dois.

Uso: py classify_club.py [pasta_saida]
"""
import argparse
import datetime
import json
import os

from atletas import ATLETAS
from classify import Classifier
from kml_parse import tile_bounds

HERE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(os.path.dirname(HERE), "data")
REFDATA_DIR = os.path.join(HERE, "refdata")

ZOOM = 17  # club.json só tem squadratinhos (ver fetch_club_squares.py)


def classify_uniao(classifier, squares, atletas):
    """União do clube: cada squadratinho de club.json vale 1, sem repetir os
    partilhados (club.json já traz cada (x,y) uma só vez, com o bitmask de
    quem o tem). Ignora mask 0 por segurança, embora fetch_club_squares nunca
    escreva nenhum. É o número que diz "actividade do clube nesta região", ao
    contrário do total da região (só tamanho) ou do capturado pelo líder (um
    atleta só).

    `exclusivos`: por concelho/distrito/país/região/município, quantos
    squadratinhos cada atleta tem que mais nenhum membro do clube tem (bitmask
    com um único bit). `by_pais`: união por país (PT, ES, ...). `by_region`:
    união por região estrangeira (província ES, land DE, região MA), cc
    minúsculo -> nome -> n; o equivalente ao by_distrito fora de PT.
    `by_municipio`: o mesmo um nível abaixo (município/cercle), o equivalente
    ao by_concelho fora de PT, para as páginas de zona estrangeira. `atletas`
    = nomes por ordem de bit."""
    by_distrito, by_concelho, by_pais = {}, {}, {}
    by_region = {}  # cc -> {regiao: n}, estrangeiro
    by_municipio = {}  # cc -> {municipio: n}, estrangeiro
    exc_distrito, exc_concelho, exc_pais = {}, {}, {}  # regiao/cc -> {atleta: n}
    exc_region = {}  # cc -> {regiao: {atleta: n}}, estrangeiro
    exc_municipio = {}  # cc -> {municipio: {atleta: n}}, estrangeiro
    # centróide dos squares de cada região, para o club.html poder saltar o
    # mapa até lá quando se carrega numa linha do leaderboard (senão uma
    # região estrangeira com 1 square é impossível de encontrar). chave ->
    # [somaX, somaY, n]; no fim vira [x, y] médio, em tile z17.
    acc = {}

    def _centro(chave, x, y):
        a = acc.setdefault(chave, [0, 0, 0])
        a[0] += x; a[1] += y; a[2] += 1
    # países com ficheiro de município no disco (após clip.py, só a zona
    # visitada + 10 km): um square lá com região mas sem município = recorte
    # curto, precisa de correr o clip outra vez.
    muni_countries_geo = ({c for c, _ in classifier.foreign_muni.names}
                          if classifier.foreign_muni else set())
    clip_misses = {}          # {cc: n} região sem município num país com ficheiro
    sem_dados_regiao = {}     # {cc: n} país detetado por contorno, sem geometria de região
    for x, y, mask in squares:
        if not mask:
            continue
        info = classifier.classify(tile_bounds(x, y, ZOOM))
        solo = None
        if mask & (mask - 1) == 0:  # potência de 2 -> um só dono
            i = mask.bit_length() - 1
            if 0 <= i < len(atletas):
                solo = atletas[i]

        cc = info["country"]
        if cc:
            by_pais[cc] = by_pais.get(cc, 0) + 1
            if solo:
                mp = exc_pais.setdefault(cc, {})
                mp[solo] = mp.get(solo, 0) + 1

        if not info["in_portugal"]:
            reg = info["region"]
            if cc and not reg and cc not in classifier._paises_com_regiao:
                sem_dados_regiao[cc] = sem_dados_regiao.get(cc, 0) + 1
            if cc and reg:
                # cc minúsculo, como o by_region por atleta (classify_athlete)
                mr = by_region.setdefault(cc.lower(), {})
                mr[reg] = mr.get(reg, 0) + 1
                _centro(f"region|{cc.lower()}|{reg}", x, y)
                if solo:
                    er = exc_region.setdefault(cc.lower(), {}).setdefault(reg, {})
                    er[solo] = er.get(solo, 0) + 1
                if not info["municipio"] and cc in muni_countries_geo:
                    clip_misses[cc] = clip_misses.get(cc, 0) + 1
            if cc and info["municipio"]:
                mm = by_municipio.setdefault(cc.lower(), {})
                mm[info["municipio"]] = mm.get(info["municipio"], 0) + 1
                _centro(f"municipio|{cc.lower()}|{info['municipio']}", x, y)
                if solo:
                    em = exc_municipio.setdefault(cc.lower(), {}).setdefault(info["municipio"], {})
                    em[solo] = em.get(solo, 0) + 1
            continue
        d, c = info["district"], info["concelho"]
        if d:
            by_distrito[d] = by_distrito.get(d, 0) + 1
            _centro(f"distrito|{d}", x, y)
        if c:
            by_concelho[c] = by_concelho.get(c, 0) + 1
            _centro(f"concelho|{c}", x, y)
        if solo:
            if d:
                md = exc_distrito.setdefault(d, {})
                md[solo] = md.get(solo, 0) + 1
            if c:
                mc = exc_concelho.setdefault(c, {})
                mc[solo] = mc.get(solo, 0) + 1
    centros = {k: [round(sx / n), round(sy / n)] for k, (sx, sy, n) in acc.items()}
    return {
        "by_distrito": by_distrito, "by_concelho": by_concelho,
        "by_pais": by_pais, "by_region": by_region, "by_municipio": by_municipio,
        "exclusivos": {"by_distrito": exc_distrito, "by_concelho": exc_concelho,
                       "by_pais": exc_pais, "by_region": exc_region,
                       "by_municipio": exc_municipio},
        "centros": centros,
    }, clip_misses, sem_dados_regiao


def classify_athlete(classifier, squares):
    by_distrito, by_concelho = {}, {}
    by_region, by_municipio = {}, {}  # cc minúsculo -> nome -> contagem
    country_totais = {}

    for x, y in squares:
        poly = tile_bounds(x, y, ZOOM)
        info = classifier.classify(poly)
        country = info["country"]
        if country:
            country_totais[country] = country_totais.get(country, 0) + 1

        if info["in_portugal"]:
            if info["district"]:
                by_distrito[info["district"]] = by_distrito.get(info["district"], 0) + 1
            if info["concelho"]:
                by_concelho[info["concelho"]] = by_concelho.get(info["concelho"], 0) + 1
        elif country:
            cc = country.lower()
            if info["region"]:
                by_region.setdefault(cc, {})
                by_region[cc][info["region"]] = by_region[cc].get(info["region"], 0) + 1
            if info["municipio"]:
                by_municipio.setdefault(cc, {})
                by_municipio[cc][info["municipio"]] = by_municipio[cc].get(info["municipio"], 0) + 1

    return {
        "country": country_totais,
        "by_distrito": by_distrito,
        "by_concelho": by_concelho,
        "by_region": by_region,
        "by_municipio": by_municipio,
    }


def main(out_dir):
    with open(os.path.join(out_dir, "club.json"), encoding="utf-8") as f:
        club = json.load(f)

    classifier = Classifier(
        os.path.join(REFDATA_DIR, "distritos_pt.geojson"),
        os.path.join(REFDATA_DIR, "concelhos_pt.geojson"),
        foreign_dir=os.path.join(REFDATA_DIR, "foreign"),
        foreign_muni_dir=os.path.join(REFDATA_DIR, "foreign_muni"),
        outlines_path=os.path.join(REFDATA_DIR, "outlines", "europe.geojson"),
    )

    squares_por_atleta = {nome: [] for nome, _uid in ATLETAS}
    for x, y, mask in club["squares"]:
        for i, (nome, _uid) in enumerate(ATLETAS):
            if mask & (1 << i):
                squares_por_atleta[nome].append((x, y))

    atletas_out = {}
    for nome, squares in squares_por_atleta.items():
        atletas_out[nome] = classify_athlete(classifier, squares)
        print(f"{nome}: {len(squares)} squares classificados")

    uniao, clip_misses, sem_dados_regiao = classify_uniao(
        classifier, club["squares"], [nome for nome, _uid in ATLETAS])
    print(f"união: {len(club['squares'])} squares distintos classificados")
    if clip_misses:
        detalhe = ", ".join(f"{cc}: {n}" for cc, n in sorted(clip_misses.items()))
        print(f"AVISO: {detalhe} square(s) num país COM ficheiro de município mas "
              f"fora do recorte de 10 km, correr `py pipeline/refdata/clip.py "
              f"{' '.join(sorted(clip_misses))}` (ver README, secção do clip)")
    if sem_dados_regiao:
        detalhe = ", ".join(f"{cc}: {n}" for cc, n in sorted(sem_dados_regiao.items()))
        print(f"AVISO: {detalhe} square(s) num país sem geometria de região, "
              f"preparar refdata/foreign/<CC>.geojson (ver README)")

    # avisos: o site mostra-os a quem não lê os logs. Só entra se houver algo.
    avisos = {}
    if clip_misses:
        avisos["clip_misses"] = dict(sorted(clip_misses.items()))
    if sem_dados_regiao:
        avisos["sem_dados_regiao"] = dict(sorted(sem_dados_regiao.items()))

    resultado = {
        "atualizado": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "zoom": club["zoom"],
        "atletas": atletas_out,
        "uniao": uniao,
    }
    if avisos:
        resultado["avisos"] = avisos
    out_path = os.path.join(out_dir, "club_regioes.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(resultado, f, ensure_ascii=False, separators=(",", ":"))
    print(f"escrito: {out_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("out_dir", nargs="?", default=DATA_DIR)
    args = parser.parse_args()
    os.makedirs(args.out_dir, exist_ok=True)
    main(args.out_dir)
