# -*- coding: utf-8 -*-
"""Harness de regressão: compara o comportamento actual com tests/baseline.json.

    python tests/harness.py           # compara com a baseline
    python tests/harness.py --update  # regrava a baseline

Sem rede para o Squadrats: um servidor falso responde aos pedidos de tiles com
vector tiles sintéticos (três atletas fictícios, três corridas em dias
seguidos). O pipeline corre numa cópia temporária do repo, com um git próprio
a fazer de branch `data`, por isso os ficheiros do repo não são tocados. O
site corre no Edge (Playwright) servido dessa cópia; só o Leaflet vem do CDN.
Saídas grandes ficam como contagem + hash.
"""
import difflib
import gzip
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
BASELINE = Path(__file__).parent / "baseline.json"
RAW = "https://raw.githubusercontent.com/JustAnotherDud/squadrats-club/"
SITE = "http://squadrats.test/"

ATLETAS = {"Ana": "uid-ana", "Bruno": "uid-bruno", "Célia": "uid-celia"}


def tile17(lon, lat):
    import math
    n = 2 ** 17
    r = math.radians(lat)
    return int((lon + 180) / 360 * n), int((1 - math.asinh(math.tan(r)) / math.pi) / 2 * n)


def bloco(lon, lat, w, h, dx=0, dy=0):
    x0, y0 = tile17(lon, lat)
    return {(x0 + dx + i, y0 + dy + j) for i in range(w) for j in range(h)}


LISBOA, AMADORA, SEVILHA, PARIS = (-9.14, 38.72), (-9.23, 38.755), (-5.99, 37.39), (2.35, 48.85)

# squares z17 de cada atleta em cada corrida (cumulativos, como no Squadrats)
R1 = {
    "Ana": bloco(*LISBOA, 14, 14) | bloco(*AMADORA, 4, 4),
    "Bruno": bloco(*LISBOA, 8, 8, 10, 10) | bloco(*AMADORA, 3, 3, 6, 0),
    "Célia": bloco(*LISBOA, 6, 6, -20, 5) | bloco(*SEVILHA, 5, 5),
}
R2 = dict(R1, Bruno=R1["Bruno"] | bloco(*AMADORA, 7, 7, 6, 3))
R3 = dict(R2, Ana=R2["Ana"] | bloco(*LISBOA, 1, 3, 14, 0), Célia=R2["Célia"] | bloco(*PARIS, 3, 3))
CORRIDAS = [("2026-09-01T10:07:00Z", R1), ("2026-09-02T13:07:00Z", R2), ("2026-09-03T15:07:00Z", R3)]
AGORA_SITE = "2026-09-03T16:00:00Z"


# --- servidor falso de tiles (corre dentro do subprocesso do pipeline) ---

def _fechados(vis):
    return {s for s in vis if all((s[0] + a, s[1] + b) in vis for a, b in ((1, 0), (-1, 0), (0, 1), (0, -1)))}


def _maior_cluster(vis):
    resto, melhor = set(_fechados(vis)), set()
    while resto:
        comp, fila = set(), [min(resto)]
        resto.discard(fila[0])
        while fila:
            x, y = fila.pop()
            comp.add((x, y))
            for v in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
                if v in resto:
                    resto.discard(v)
                    fila.append(v)
        if len(comp) > len(melhor) or (len(comp) == len(melhor) and min(comp) < min(melhor)):
            melhor = comp
    return melhor


def _maior_quadrado(vis):
    dp, n, canto = {}, 0, None
    for x, y in sorted(vis):
        v = 1 + min(dp.get((x - 1, y), 0), dp.get((x, y - 1), 0), dp.get((x - 1, y - 1), 0))
        dp[(x, y)] = v
        if v > n:
            n, canto = v, (x, y)
    return {(canto[0] - i, canto[1] - j) for i in range(n) for j in range(n)} if n else set()


def _camadas(sq17):
    sq14 = {(x >> 3, y >> 3) for x, y in sq17}
    return {
        "squadratinhos": (17, sq17, len(sq17)),
        "squadrats": (14, sq14, len(sq14)),
        "yardinho": (17, _maior_cluster(sq17), len(_maior_cluster(sq17))),
        "yard": (14, _maior_cluster(sq14), len(_maior_cluster(sq14))),
        "ubersquadratinho": (17, _maior_quadrado(sq17), int(len(_maior_quadrado(sq17)) ** 0.5)),
        "ubersquadrat": (14, _maior_quadrado(sq14), int(len(_maior_quadrado(sq14)) ** 0.5)),
    }


def instalar_servidor_falso(estado, contagem):
    """Substitui requests.Session.request: responde aos URLs de tiles1.squadrats.com
    com MVT sintéticos a partir de `estado` ({uid: set de squares z17})."""
    import mapbox_vector_tile
    import requests
    from shapely.geometry import box

    camadas = {uid: _camadas(sq) for uid, sq in estado.items()}

    class Resp:
        def __init__(self, status, content=b""):
            self.status_code, self.content = status, content

        def raise_for_status(self):
            if self.status_code >= 400:
                raise requests.HTTPError(str(self.status_code))

    def pedido(self, method, url, **kw):
        m = re.fullmatch(r"https://tiles1\.squadrats\.com/([^/]+)/trophies/\d+/(\d+)/(\d+)/(\d+)\.pbf", url)
        if not m:
            raise AssertionError(f"pedido de rede inesperado: {url}")
        uid, z, tx, ty = m.group(1), int(m.group(2)), int(m.group(3)), int(m.group(4))
        contagem[f"z{z}"] = contagem.get(f"z{z}", 0) + 1
        if uid not in camadas:
            return Resp(500)
        layers = []
        for nome, (zg, squares, size) in camadas[uid].items():
            k = zg - z  # squares da grelha zg por lado de tile
            dentro = sorted(s for s in squares if (s[0] >> k, s[1] >> k) == (tx, ty))
            if not dentro:
                continue
            if z != 10:  # descoberta: basta haver conteúdo
                feats = [{"geometry": box(0, 0, 16, 16), "properties": {}}]
            else:
                lado = 4096 >> k
                feats = [{"geometry": box((x - (tx << k)) * lado, (y - (ty << k)) * lado,
                                          (x - (tx << k) + 1) * lado, (y - (ty << k) + 1) * lado),
                          "properties": {"size": size}} for x, y in dentro]
            layers.append({"name": nome, "features": feats})
        if not layers:
            return Resp(204)
        pbf = mapbox_vector_tile.encode(layers, default_options={"extents": 4096, "y_coord_down": True})
        return Resp(200, gzip.compress(pbf, mtime=0))

    requests.sessions.Session.request = pedido


def correr_pipeline(copia, agora, estado_json):
    """Modo interno (subprocesso): uma corrida do workflow na cópia."""
    from freezegun import freeze_time

    estado = {ATLETAS[n]: {tuple(s) for s in sq} for n, sq in json.loads(estado_json).items()}
    contagem = {}
    instalar_servidor_falso(estado, contagem)
    sys.path.insert(0, str(Path(copia) / "pipeline"))
    with freeze_time(agora):
        import run_all
        run_all.main(str(Path(copia) / "data"))
        import gen_lugar_stubs
        import gen_profile_stubs
        gen_profile_stubs.main(copia)
        gen_lugar_stubs.main(copia, str(Path(copia) / "data"))
    print("PEDIDOS " + json.dumps(dict(sorted(contagem.items()))))


# --- resumo e comparação ---

def resumo(v):
    """Valores pequenos ficam como estão; grandes passam a contagem + hash."""
    s = v if isinstance(v, str) else json.dumps(v, ensure_ascii=False, sort_keys=True)
    if len(s) <= 160:
        return v
    n = len(v) if isinstance(v, (list, dict)) else s.count("\n") + 1
    return {"n": n, "sha": hashlib.sha256(s.encode("utf-8")).hexdigest()[:16]}


def resumo_ficheiro(p):
    texto = p.read_text(encoding="utf-8")
    if p.suffix == ".json":
        d = json.loads(texto)
        return {k: resumo(v) for k, v in d.items()} if isinstance(d, dict) else resumo(d)
    return resumo(texto)


def git(copia, *args, env=None):
    return subprocess.run(["git", "-C", str(copia), *args], check=True, capture_output=True,
                          text=True, env={**os.environ, **(env or {})}).stdout.strip()


def ficheiros_dados():
    """FILES/PROFILES_DIR/REGIOES_DIR tal como o workflow os define."""
    wf = (RAIZ / ".github/workflows/fetch-map-data.yml").read_text(encoding="utf-8")
    files = re.search(r'^\s*FILES:\s*"([^"]+)"', wf, re.M).group(1).split()
    dirs = [re.search(rf'^\s*{k}:\s*"([^"]+)"', wf, re.M).group(1) for k in ("PROFILES_DIR", "REGIOES_DIR")]
    return files, dirs


def publicar(copia, agora, files, dirs):
    """Commit dos dados na ref origin/data, só se houver diferença (como o workflow)."""
    caminhos = [f for f in files if (copia / f).exists()]
    for d in dirs:
        caminhos += sorted(str(p.relative_to(copia)).replace("\\", "/") for p in (copia / d).glob("*.json"))
    env = {"GIT_INDEX_FILE": str(copia / ".git" / "index-data"), "GIT_AUTHOR_DATE": agora,
           "GIT_COMMITTER_DATE": agora}
    git(copia, "read-tree", "--empty", env=env)
    git(copia, "add", "-f", *caminhos, env=env)
    tree = git(copia, "write-tree", env=env)
    try:
        pai = git(copia, "rev-parse", "refs/remotes/origin/data")
    except subprocess.CalledProcessError:
        pai = None
    if pai and git(copia, "rev-parse", pai + "^{tree}") == tree:
        return False
    commit = git(copia, "commit-tree", tree, *(["-p", pai] if pai else []), "-m", "dados", env=env)
    git(copia, "update-ref", "refs/remotes/origin/data", commit)
    return True


def casos_pipeline(copia):
    files, dirs = ficheiros_dados()
    out = {}
    for i, (agora, estado) in enumerate(CORRIDAS, 1):
        r = subprocess.run(
            [sys.executable, __file__, "--correr", str(copia), agora,
             json.dumps({n: sorted(s) for n, s in estado.items()})],
            capture_output=True, text=True, encoding="utf-8",
            env={**os.environ, "ATHLETES_JSON": json.dumps(ATLETAS), "PYTHONHASHSEED": "0",
                 "PYTHONIOENCODING": "utf-8"})
        (copia / f"corrida{i}.log").write_text(r.stdout + r.stderr, encoding="utf-8")
        if r.returncode:
            raise SystemExit(f"corrida {i} falhou:\n{(r.stdout + r.stderr)[-3000:]}")
        pedidos = json.loads(r.stdout.rsplit("PEDIDOS ", 1)[1])
        publicou = publicar(copia, agora, files, dirs)
        saidas = {}
        for f in files:
            if (copia / f).exists():
                saidas[f] = resumo_ficheiro(copia / f)
        for d in dirs + ["atletas", "lugares"]:
            for p in sorted((copia / d).glob("*.json" if d.startswith("data") else "*.html")):
                if p.name == "index.html" and d == "lugares":
                    continue  # feito à mão, não é saída do pipeline
                saidas[str(p.relative_to(copia)).replace("\\", "/")] = resumo_ficheiro(p)
        out[f"corrida {i} ({agora})"] = {"pedidos": pedidos, "publicou": publicou, "saidas": saidas}
    return out


# --- site ---

def casos_site(copia):
    from playwright.sync_api import sync_playwright

    lugares = sorted(p.name for p in (copia / "lugares").glob("*.html"))
    amostra = []
    for pref in ("c-", "d-", "pais-pt", "es-r-", "es-z-", "pais-es"):
        amostra += [n for n in lugares if n.startswith(pref)][:1]
    paginas = ["index.html", "club.html", "analise.html", "historico.html", "ganhos.html",
               "lugares/index.html", "atletas/index.html", "atletas/ana.html", "atletas/celia.html"]
    paginas += [f"lugares/{n}" for n in amostra]
    png = bytes.fromhex("89504e470d0a1a0a0000000d4948445200000001000000010806000000"
                        "1f15c4890000000d49444154789c6360000002000154a24f5d0000000049454e44ae426082")

    def servir(route):
        try:
            return _servir(route)
        except Exception as e:  # uma rota por resolver pendura a página
            route.fulfill(status=500, body=repr(e))

    def _servir(route):
        url = route.request.url.split("#")[0].split("?")[0]
        if url.startswith(SITE):
            rel = url[len(SITE):] or "index.html"
            if rel.endswith("/"):
                rel += "index.html"
        elif url.startswith((RAW + "data/data/", RAW + "main/data/")):
            rel = "data/" + url[len(RAW):].split("/", 2)[2]
        elif "arcgisonline.com" in url:
            return route.fulfill(status=200, content_type="image/png", body=png)
        elif url.startswith("https://cdnjs.cloudflare.com/"):
            return route.continue_()
        else:
            return route.fulfill(status=404, body="")
        p = copia / rel
        if not p.is_file():
            return route.fulfill(status=404, body="")
        tipos = {".html": "text/html", ".js": "application/javascript", ".css": "text/css",
                 ".json": "application/json", ".geojson": "application/json", ".svg": "image/svg+xml"}
        return route.fulfill(status=200, body=p.read_bytes(),
                             content_type=tipos.get(p.suffix, "application/octet-stream"))

    def estado(page):
        return page.evaluate("""() => ({
            titulo: document.title,
            texto: document.body.innerText.replace(/\\s+/g, ' ').trim(),
            svg: document.querySelectorAll('path.leaflet-interactive').length,
            canvas: document.querySelectorAll('canvas').length,
            links: [...document.querySelectorAll('a[href]')].map(a => a.getAttribute('href')),
        })""")

    out = {}
    with sync_playwright() as pw:
        browser = pw.chromium.launch(channel=os.environ.get("HARNESS_BROWSER", "msedge") or None)
        for pag in paginas:
            ctx = browser.new_context(viewport={"width": 390, "height": 844}, locale="pt-PT",
                                      timezone_id="Europe/Lisbon", service_workers="block")
            page = ctx.new_page()
            page.clock.set_fixed_time(AGORA_SITE)
            erros = []
            page.on("pageerror", lambda e: erros.append(str(e)))
            page.on("console", lambda m: m.type in ("error", "warning") and erros.append(m.text))
            page.route("**/*", servir)
            page.goto(SITE + pag)
            page.wait_for_load_state("networkidle")
            page.wait_for_timeout(300)
            r = {"inicial": {k: resumo(v) for k, v in estado(page).items()}}
            if pag == "club.html":
                page.click("#painel-cabeca")
                page.wait_for_timeout(200)
                r["painel aberto"] = resumo(estado(page)["texto"])
            if pag == "analise.html":
                page.click('#topbar .seg-visao button[data-val="distritos"]')
                page.wait_for_timeout(200)
                r["vista região"] = {k: resumo(v) for k, v in estado(page).items()}
            r["erros"] = erros
            out[pag] = r
            ctx.close()
        browser.close()
    return out


def casos_pytest():
    r = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider"],
                       cwd=RAIZ, capture_output=True, text=True, encoding="utf-8")
    return r.stdout.strip().splitlines()[-1].split(" in ")[0]


def copiar_repo(destino):
    listados = subprocess.run(["git", "-C", str(RAIZ), "ls-files", "-co", "--exclude-standard"],
                              check=True, capture_output=True, text=True).stdout.split("\n")
    for rel in filter(None, listados):
        if rel.startswith(("tests/", ".github/")):
            continue
        origem = RAIZ / rel
        if origem.is_file():
            (destino / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(origem, destino / rel)
    git(destino, "init", "-q")
    # branch `data` já existe em produção; aqui começa vazia
    datas = {"GIT_AUTHOR_DATE": "2026-08-31T00:00:00Z", "GIT_COMMITTER_DATE": "2026-08-31T00:00:00Z"}
    arvore_vazia = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"
    git(destino, "update-ref", "refs/remotes/origin/data",
        git(destino, "commit-tree", arvore_vazia, "-m", "início", env=datas))


def main():
    if sys.argv[1:2] == ["--correr"]:
        return correr_pipeline(*sys.argv[2:5])
    atualizar = "--update" in sys.argv
    with tempfile.TemporaryDirectory(prefix="squadrats-harness-") as tmp:
        copia = Path(tmp)
        copiar_repo(copia)
        atual = {"pytest": casos_pytest(), "pipeline": casos_pipeline(copia), "site": casos_site(copia)}
    novo = json.dumps(atual, ensure_ascii=False, indent=1, sort_keys=True)
    if atualizar or not BASELINE.exists():
        BASELINE.write_text(novo + "\n", encoding="utf-8")
        print(f"baseline gravada: {BASELINE}")
        return 0
    antigo = BASELINE.read_text(encoding="utf-8").rstrip("\n")
    if antigo == novo:
        print("OK: igual à baseline")
        return 0
    sys.stdout.writelines(difflib.unified_diff(antigo.splitlines(True), novo.splitlines(True),
                                               "baseline.json", "actual"))
    print("\nDIFERENTE da baseline")
    return 1


if __name__ == "__main__":
    sys.exit(main())
