# Contribuindo

Obrigado! Dá pra contribuir sem ser dev — até reportar uma fonte que quebrou ajuda.

## Reportar um problema (1 clique)
- No painel: rodapé → **"Reportar um problema"** (abre o issue já com o contexto).
- No Telegram: o alerta de erro tem o botão **"Reportar no GitHub"** (já preenchido).
- Ou abra um issue pelos templates (Bug / Ideia).

## Rodar localmente
```bash
python -m venv .venv && . .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python garimpeiro.py setup      # escolhe áreas, fontes, modo
python garimpeiro.py once       # testa uma coleta
python garimpeiro.py serve      # vê o painel em localhost:8765
```

## Criar um PLUGIN (sem tocar no core)
Tudo em `plugins/` é descoberto automaticamente. Dois tipos:

**Fonte de vagas** — copie `plugins/_template_fonte.py` para `plugins/minha_fonte.py`:
```python
from sources import Job
META = {"name": "Minha Fonte", "type": "source", "enabled": True}
def fetch(cfg, log) -> list[Job]:
    return [Job(source="Minha Fonte", title="...", company="...", url="...")]
```

**Seção no painel** — veja `plugins/exemplo_painel.py`:
```python
META = {"name": "Meu Widget", "type": "panel", "enabled": True}
def panel_html(cfg) -> str:
    return "<section class='group'><h2 class='grp'>...</h2>...</section>"
```

Um plugin que dá erro é só pulado (não quebra a rodada). Dedup, IA e painel
funcionam de graça para fontes-plugin.

## Abrir um PR
1. Fork → branch → mude → teste (`once`).
2. **Nunca** comite segredos/PII (`.env`, `config.yaml`, `perfil.md`).
3. Abra o PR (template aparece sozinho).

## Estilo
Python: PEP 8, nomes claros, funções pequenas. Sem dependências pesadas novas
sem necessidade. Comentários em PT-BR são bem-vindos.
