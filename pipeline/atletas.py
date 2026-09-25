"""Lista única dos atletas do clube.

Os dados (nome → firebase UID) vêm do env `ATHLETES_JSON`, não do código. No
CI vem de um secret; localmente, exportar à mão:

    export ATHLETES_JSON='{"Nome A": "uid...", "Nome B": "uid..."}'

A ORDEM das entradas é contrato: fetch_club_squares.py atribui o bit N do
bitmask dos squares partilhados ao N-ésimo atleta (bit 0 = primeiro, e por
aí fora) e club.html assume a mesma ordem nas cores. Não reordenar sem
regenerar data/club.json.
"""
import json
import os

_raw = os.environ.get("ATHLETES_JSON", "").strip()
if not _raw:
    raise RuntimeError(
        "ATHLETES_JSON não definido. Esperado: JSON {nome: firebase_uid, ...}, "
        "na ordem que fixa os bits do bitmask (ver docstring). No CI vem de um "
        "secret; localmente exportar à mão."
    )
try:
    ATHLETES: dict[str, str] = json.loads(_raw)
except json.JSONDecodeError as e:
    raise RuntimeError(f"ATHLETES_JSON não é JSON válido: {e}") from e
if not ATHLETES:
    raise RuntimeError("ATHLETES_JSON está vazio.")

# mesma ordem que ATHLETES (o dict preserva a ordem de inserção do JSON),
# usada onde a ordem importa (bitmask em fetch_club_squares.py, cores em
# club.html)
ATLETAS = list(ATHLETES.items())

# primeiro atleta na ordem = dono do mapa detalhado (run_all.py), mesma
# convenção do bit 0
JOSE_UID = next(iter(ATHLETES.values()))


def known_squadratinhos(out_dir):
    """{uid: último total de squadratinhos publicado}, lido do squadrats.json
    do out_dir, para o probe de tiles_fetch.scan_athlete.

    Squadratinhos é a grelha mais fina: qualquer captura nova noutra camada
    passa por um squadratinho novo. Por isso esta contagem chega para saber
    se algo mudou. Atleta sem entrada fica de fora e leva o scan completo."""
    path = os.path.join(out_dir, "squadrats.json")
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}
    return {
        ATHLETES[nome]: info["squadratinhos"]
        for nome, info in data.get("atletas", {}).items()
        if nome in ATHLETES and "squadratinhos" in info
    }
