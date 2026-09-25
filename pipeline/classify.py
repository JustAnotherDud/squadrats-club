"""Classifica squares (o polígono do tile, não só o centro) em concelho e
distrito de Portugal, e, quando houver geometria disponível, região
estrangeira (ex: província espanhola). Sem geometria de região para o país,
mas com `outlines_path` (Natural Earth, refdata/outlines/europe.geojson),
devolve pelo menos country=<CC> com region=None: o square passa a aparecer
no mapa/club com bandeira e "sem dados por região". Sem nada, fica tudo None
(in_portugal=False, country=None, region=None).

Critério: maior área de intersecção ganha, sem limiar mínimo (não é
"maioria" >50%). Um square costeiro com 60% mar / 40% terra continua a
contar para o único candidato com alguma área, não fica por classificar só
por não ter maioria absoluta. Em terra firme dá o mesmo resultado que exigir
maioria, porque só há um candidato relevante na prática; a diferença só
aparece na costa/fronteira, que é exactamente onde interessa não ter buracos.

Se o tile não intersecta terra nenhuma (ex: 100% rio/mar, travessia de
ponte, ferry), aplica-se um fallback de proximidade dentro de
COASTAL_BUFFER_DEG: ganha o candidato geometricamente mais próximo, **PT ou
estrangeiro, sem preferência por nenhum dos dois**, só assim uma travessia
do Tejo continua a contar para Lisboa/Almada sem reintroduzir o viés que
motivou tirar isto do caminho principal (ver abaixo). Fora do buffer, fica
genuinamente sem classificação (ex: square em pleno oceano).

O concelho tem o mesmo problema à escala interna: um square do Tejo não
intersecta nenhum concelho, tal como não intersecta nenhum distrito. Por
isso tem o mesmo fallback, mas restrito a dentro de Portugal (nunca escolhe
um concelho espanhol), sempre que é usado, `classify()` devolve a distância
em `concelho_fallback_deg`, para quem consumir conseguir separar dois casos
com a mesma cara (concelho ausente por intersecção nula): fendas de poucos
metros entre `distritos_pt.geojson`/`concelhos_pt.geojson` (artefacto de
dados, duas fontes desenhadas independentemente) de água genuína a
centenas de metros/km da margem (Tejo, lagoas). O mesmo vale a nível de
país em `country_fallback_deg`, e `on_land=False` sinaliza sempre que o
tile não tinha nenhuma área de terra dentro de si, ganhasse quem ganhasse
a seguir.

Substituiu o critério antigo (centro do tile, point-in-polygon com fallback
de "mais próximo" só do lado de Portugal): esse fallback tinha um viés,
só Portugal tinha a tolerância de distância, o que empurrava squares
ambíguos perto da raia terrestre para PT mesmo sem estarem dentro de nenhum
polígono português. Aqui o fallback só entra quando NADA intersecta o tile
na fronteira terrestre há sempre terra (de um lado ou do outro) dentro do
tile, por isso o caso nem chega a este ramo; e quando chega (água), compete
os dois lados em pé de igualdade.
"""
import glob
import json
import os
from shapely.geometry import shape
from shapely.strtree import STRtree
from shapely.validation import make_valid

COASTAL_BUFFER_DEG = 0.05  # limite do fallback de proximidade (~5,5 km), só quando nada intersecta


def _clean(geom):
    if not geom.is_valid:
        geom = make_valid(geom)
    return geom


class _Layer:
    def __init__(self, names, geoms):
        self.names = names
        self.geoms = geoms
        self.tree = STRtree(geoms)

    def best_match(self, tile_poly):
        """Candidato com maior área de intersecção com `tile_poly`.

        Devolve (nome, área), (None, 0.0) se nada intersecta. Sem fallback
        de "mais próximo": se a resposta é (None, 0.0), é porque o tile não
        toca em nenhuma geometria conhecida desta camada, não porque falhou
        a encontrar alguma."""
        best_name, best_area = None, 0.0
        for idx in self.tree.query(tile_poly, predicate="intersects"):
            area = tile_poly.intersection(self.geoms[idx]).area
            if area > best_area:
                best_name, best_area = self.names[idx], area
        return best_name, best_area

    def nearest(self, tile_poly):
        """Geometria conhecida mais próxima de `tile_poly` (nome, distância).

        Só para o fallback de "nada intersecta", best_match já cobre o caso
        normal. STRtree.nearest é sempre determinístico (o geometricamente
        mais próximo), ao contrário de `query(...)[0]` (ordem arbitrária)."""
        idx = self.tree.nearest(tile_poly)
        if idx is None:
            return None, float("inf")
        geom = self.geoms[idx]
        return self.names[idx], geom.distance(tile_poly)


class Classifier:
    def __init__(self, distritos_path, concelhos_path, foreign_dir=None,
                 foreign_muni_dir=None, outlines_path=None):
        with open(distritos_path, encoding="utf-8") as f:
            distritos = json.load(f)
        with open(concelhos_path, encoding="utf-8") as f:
            concelhos = json.load(f)

        d_names = [feat["properties"]["district"] for feat in distritos["features"]]
        d_geoms = [_clean(shape(feat["geometry"])) for feat in distritos["features"]]
        self.distritos = _Layer(d_names, d_geoms)

        c_names = [feat["properties"]["NAME_2"] for feat in concelhos["features"]]
        c_geoms = [_clean(shape(feat["geometry"])) for feat in concelhos["features"]]
        self.concelhos = _Layer(c_names, c_geoms)

        # regiões estrangeiras: um ficheiro por país em refdata/foreign/*.geojson,
        # cada feature com properties.country (ex: "ES") + properties.region
        # (ex: "Asturias"). Adicionar um país novo = só adicionar um ficheiro,
        # zero alterações de código.
        self.foreign = self._load_foreign(foreign_dir)

        # município estrangeiro, mesmo princípio mas nível mais fino
        # (refdata/foreign_muni/<CC>.geojson, recortado pelo clip.py). Nomes
        # duplicados já vêm desambiguados no ficheiro.
        self.foreign_muni = self._load_foreign(foreign_muni_dir)

        # contornos de país (Natural Earth, refdata/outlines/europe.geojson):
        # último recurso para DAR PAÍS a um square capturado num país sem
        # ficheiro de região. Sem isto, esse square ficava country=None e
        # sumia da vista (contava só em stats.foreign.unclassified). Aqui
        # passa a country=<CC>, region=None: aparece no mapa/club com bandeira
        # e "sem dados por região", à espera que se construa a divisão fina
        # (ver clip.py). Precisão de km, chega para "que país".
        self.outlines = None
        if outlines_path and os.path.isfile(outlines_path):
            with open(outlines_path, encoding="utf-8") as f:
                oc = json.load(f)
            names = [(feat["properties"]["country"], feat["properties"].get("nome"))
                     for feat in oc["features"]]
            geoms = [_clean(shape(feat["geometry"])) for feat in oc["features"]]
            self.outlines = _Layer(names, geoms) if geoms else None

        # países que já têm geometria de região (foreign/*.geojson) + PT: o
        # contorno de país nunca os classifica, é só para os que faltam.
        self._paises_com_regiao = {"PT"}
        if self.foreign is not None:
            self._paises_com_regiao |= {cc for cc, _ in self.foreign.names}

    @staticmethod
    def _load_foreign(dir_path):
        if not dir_path or not os.path.isdir(dir_path):
            return None
        labels, geoms = [], []
        for path in sorted(glob.glob(os.path.join(dir_path, "*.geojson"))):
            with open(path, encoding="utf-8") as f:
                fc = json.load(f)
            for feat in fc["features"]:
                labels.append((feat["properties"]["country"], feat["properties"]["region"]))
                geoms.append(_clean(shape(feat["geometry"])))
        return _Layer(labels, geoms) if geoms else None

    def _concelho(self, tile_poly):
        """Concelho por área; se nada intersecta, fallback de proximidade
        dentro de COASTAL_BUFFER_DEG (nunca cruza fronteira, só chamado
        quando o país já é PT). Devolve (nome, fallback_deg), fallback_deg
        é None quando resolvido por área OU quando nada está perto o
        suficiente (concelho fica None nesse caso, buraco genuíno)."""
        concelho, area = self.concelhos.best_match(tile_poly)
        if area > 0.0:
            return concelho, None
        name, dist = self.concelhos.nearest(tile_poly)
        if dist <= COASTAL_BUFFER_DEG:
            return name, dist
        return None, None

    def _foreign_municipio(self, country, tile_poly):
        """Município/concelho equivalente estrangeiro, quando há fonte para
        esse país (refdata/foreign_muni/*.geojson).

        Se nada intersecta, fallback de proximidade dentro de
        COASTAL_BUFFER_DEG, mas SÓ a municípios do MESMO país (o `country` já
        foi resolvido pela camada de região): assim não cruza fronteira, e
        apanha os squares na orla marítima logo a seguir ao limite terrestre
        de um município costeiro (a praia/porto de València, p.ex.), como o
        `_concelho` faz em PT."""
        if self.foreign_muni is None:
            return None
        label, area = self.foreign_muni.best_match(tile_poly)
        if label is not None and area > 0.0:
            muni_country, muni_name = label
            return muni_name if muni_country == country else None
        near, dist = self.foreign_muni.nearest(tile_poly)
        if near is not None and dist <= COASTAL_BUFFER_DEG and near[0] == country:
            return near[1]
        return None

    def classify(self, tile_poly):
        """`tile_poly`: polígono shapely do square (ver kml_parse.tile_bounds).

        País: distrito PT vs região estrangeira, ganha quem tiver mais área
        do tile dentro de si, sem limiar. Se nada intersecta (tile 100% em
        água), cai no fallback de proximidade: o candidato mais próximo,
        PT ou estrangeiro sem preferência, só dentro de COASTAL_BUFFER_DEG.

        Concelho segue o mesmo padrão, mas só dentro de PT (ver `_concelho`).

        Além dos campos habituais, devolve sempre:
        - on_land: False se o tile não tinha nenhuma área de terra dentro
          de si (ganhou quem ganhou a seguir por proximidade, ou ficou sem
          classificação), conta quantos squares capturados não estão
          fisicamente em terra.
        - country_fallback_deg / concelho_fallback_deg: distância usada
          quando esse nível foi resolvido por proximidade, None quando foi
          por área (ou quando ficou sem classificação)."""
        district, d_area = self.distritos.best_match(tile_poly)

        foreign_label, f_area = (None, 0.0)
        if self.foreign is not None:
            foreign_label, f_area = self.foreign.best_match(tile_poly)

        on_land = d_area > 0.0 or f_area > 0.0

        # Nenhuma região conhecida apanha o tile: antes de desistir, ver se
        # cai dentro de um contorno de país (Natural Earth). Só para países
        # SEM camada de região própria: em PT/ES/DE/MA/AD a geometria fina é
        # que manda, e um tile sobre água ali deve ir ao fallback de
        # proximidade, não ao contorno grosso.
        if self.outlines is not None and d_area == 0.0 and f_area == 0.0:
            lbl, o_area = self.outlines.best_match(tile_poly)
            if lbl and o_area > 0.0 and lbl[0] not in self._paises_com_regiao:
                return {
                    "in_portugal": False, "district": None, "concelho": None,
                    "country": lbl[0], "region": None, "municipio": None,
                    "on_land": True, "country_fallback_deg": None,
                    "concelho_fallback_deg": None,
                }

        if not on_land:
            d_name, d_dist = self.distritos.nearest(tile_poly)
            f_name, f_dist = (None, float("inf"))
            if self.foreign is not None:
                f_name, f_dist = self.foreign.nearest(tile_poly)

            if min(d_dist, f_dist) > COASTAL_BUFFER_DEG:
                # nada perto o suficiente, genuinamente sem classificação
                # (ex: square em pleno oceano)
                return {
                    "in_portugal": False, "district": None, "concelho": None,
                    "country": None, "region": None, "municipio": None,
                    "on_land": False, "country_fallback_deg": None, "concelho_fallback_deg": None,
                }

            if d_dist <= f_dist:
                concelho, concelho_fallback_deg = self._concelho(tile_poly)
                return {
                    "in_portugal": True, "district": d_name, "concelho": concelho,
                    "country": "PT", "region": None, "municipio": None,
                    "on_land": False, "country_fallback_deg": d_dist,
                    "concelho_fallback_deg": concelho_fallback_deg,
                }

            country, region = f_name
            return {
                "in_portugal": False, "district": None, "concelho": None,
                "country": country, "region": region,
                "municipio": self._foreign_municipio(country, tile_poly),
                "on_land": False, "country_fallback_deg": f_dist, "concelho_fallback_deg": None,
            }

        if d_area >= f_area:
            concelho, concelho_fallback_deg = self._concelho(tile_poly)
            return {
                "in_portugal": True, "district": district, "concelho": concelho,
                "country": "PT", "region": None, "municipio": None,
                "on_land": True, "country_fallback_deg": None,
                "concelho_fallback_deg": concelho_fallback_deg,
            }

        country, region = foreign_label
        return {
            "in_portugal": False, "district": None, "concelho": None,
            "municipio": self._foreign_municipio(country, tile_poly),
            "country": country, "region": region,
            "on_land": True, "country_fallback_deg": None, "concelho_fallback_deg": None,
        }
