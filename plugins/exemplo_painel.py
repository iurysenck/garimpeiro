"""Plugin de exemplo — adiciona uma seção no painel.

Copie este arquivo, mude o META e o panel_html(). Pronto: aparece no app.
Plugins de PAINEL injetam HTML auto-contido (use as classes do app: group/grp/grid/card).
Para criar uma FONTE de vagas, veja plugins/_template_fonte.py.
"""

META = {"name": "Exemplo Painel", "type": "panel", "enabled": True}


def panel_html(cfg) -> str:
    # Recebe o config (dict) — dá pra ler chaves suas. Retorne HTML (string).
    return """
      <section class="group">
        <h2 class="grp">🔌 Plugin de exemplo</h2>
        <div class="grid">
          <article class="card">
            <div class="card-head"><h3 class="title">Funciona!</h3></div>
            <p class="resumo">Esta seção veio de plugins/exemplo_painel.py.
            Edite o panel_html() ou crie novos plugins na pasta plugins/.</p>
          </article>
        </div>
      </section>
    """
