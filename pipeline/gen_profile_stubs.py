"""Gera os stubs HTML dos perfis: atletas/<slug>.html (um por atleta) +
atletas/index.html (lista). Cada stub é só casca, carrega ../shared.js e
perfil.js, que fazem o resto lendo data/atletas/<slug>.json da branch `data`.

Corre no fetch-map-data.yml e só commita para o `main` se o conjunto de
atletas tiver mudado (stubs mudam ~nunca; é o mesmo padrão do heartbeat).
Também apaga stubs de atletas que já não estão em ATHLETES_JSON.

Uso: py gen_profile_stubs.py [pasta_repo]
"""
import argparse
import os

from atletas import ATHLETES
from gen_lugar_stubs import cabeca
from slugs import slug_map

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_DIR = os.path.dirname(HERE)

STUB = cabeca("{nome}", "perfil.css") + """<body>
<main id="perfil" data-slug="{slug}">
  <p class="perfil-estado">A carregar o perfil de {nome}…</p>
</main>
<script src="../nav.js"></script>
<script src="../shared.js"></script>
<script src="perfil.js"></script>
</body>
</html>
"""

INDICE = cabeca("Perfis", "perfil.css") + """<body>
<main id="perfil-indice">
  <h1>Perfis do clube</h1>
  <ul class="perfil-lista">
{itens}
  </ul>
  <p class="perfil-nota">Um perfil por atleta, com contagens, ganhos diários,
  sobreposição de squadratinhos e posição por região. Dados actualizados 6×/dia
  pelo mesmo processo que gera o <a href="../club.html">mapa do clube</a>.</p>
</main>
<script src="../nav.js"></script>
<script src="../shared.js"></script>
<script src="perfil.js"></script>
</body>
</html>
"""


def main(repo_dir):
    destino = os.path.join(repo_dir, "atletas")
    os.makedirs(destino, exist_ok=True)
    slugs = slug_map(ATHLETES.keys())

    escritos = set()
    for nome, slug in slugs.items():
        caminho = os.path.join(destino, f"{slug}.html")
        with open(caminho, "w", encoding="utf-8", newline="\n") as f:
            f.write(STUB.format(nome=nome, slug=slug))
        escritos.add(f"{slug}.html")
        print(f"stub: atletas/{slug}.html")

    itens = "\n".join(
        f'    <li><a href="{slug}.html" data-slug="{slug}">'
        f'<span class="perfil-cor" data-nome="{nome}"></span>{nome}</a></li>'
        for nome, slug in slugs.items()
    )
    with open(os.path.join(destino, "index.html"), "w", encoding="utf-8", newline="\n") as f:
        f.write(INDICE.format(itens=itens))
    escritos.add("index.html")
    print("stub: atletas/index.html")

    # limpar stubs de atletas removidos (mantém perfil.js/perfil.css e tudo o
    # resto que não seja um .html gerado aqui)
    for ficheiro in os.listdir(destino):
        if ficheiro.endswith(".html") and ficheiro not in escritos:
            os.remove(os.path.join(destino, ficheiro))
            print(f"removido (atleta já não está em ATHLETES_JSON): atletas/{ficheiro}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("repo_dir", nargs="?", default=REPO_DIR)
    args = parser.parse_args()
    main(args.repo_dir)
