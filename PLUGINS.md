# Criando plugins

Estenda o garimpeiro **sem tocar no core**: jogue um `.py` na pasta `plugins/` e ele
é descoberto sozinho. Dois tipos: **fonte** (traz vagas) e **painel** (seção no app).

Regras: arquivos começando com `_` são ignorados (use pra templates). Um plugin que dá
erro é **pulado** (não derruba a rodada). Ative/desative pelo `META["enabled"]`.

---

## 1. Plugin de FONTE (traz vagas de um site/API)

Crie `plugins/minha_fonte.py`:

```python
from sources import Job

META = {"name": "Minha Fonte", "type": "source", "enabled": True}

def fetch(cfg, log):
    # cfg = dict do config.yaml ; log(msg, level="INFO"|"WARN"|"ERROR")
    import requests
    vagas = []
    try:
        r = requests.get("https://api.exemplo.com/jobs?q=designer", timeout=30)
        r.raise_for_status()
        for d in r.json().get("results", []):
            vagas.append(Job(
                source=META["name"],
                title=d["titulo"],
                company=d.get("empresa", ""),
                url=d["link"],
                location=d.get("cidade", ""),
                remote=bool(d.get("remoto")),
                description=d.get("descricao", "")[:1500],
                posted=d.get("data", ""),     # ISO yyyy-mm-dd se tiver
                freela=bool(d.get("freela")),  # True => aba Freelas
            ))
    except Exception as exc:
        log(f"  [{META['name']}] falha: {exc}", level="WARN")
    log(f"  [{META['name']}] {len(vagas)} vagas")
    return vagas
```

Pronto. O core cuida do resto: **dedup, filtro de escopo, score IA, painel e Telegram**.
Os campos do `Job` (de `sources.py`): `source, title, company, url, location, remote,
description, posted, freela`. Só `title`/`url` são realmente essenciais.

> Atalho: copie `plugins/_template_fonte.py` (já vem pronto).

---

## 2. Plugin de PAINEL (uma seção no app)

Crie `plugins/meu_widget.py`:

```python
META = {"name": "Meu Widget", "type": "panel", "enabled": True}

def panel_html(cfg):
    # retorne HTML auto-contido. Use as classes do app: group, grp, grid, card, resumo.
    return """
      <section class="group">
        <h2 class="grp">📌 Links úteis</h2>
        <div class="grid">
          <article class="card">
            <div class="card-head"><h3 class="title">LinkedIn Jobs</h3></div>
            <p class="resumo">Atalhos e dicas que eu reuso.</p>
          </article>
        </div>
      </section>
    """
```

A seção aparece no fim do painel. Pode trazer `<style>`/`<script>` inline se precisar.

> Exemplo pronto: `plugins/exemplo_painel.py`.

---

## 3. Testar

```bash
python garimpeiro.py once      # roda a coleta (inclui seus plugins)
python garimpeiro.py serve     # vê o painel em http://localhost:8765
```

No log você vê `Fonte (plugin): Minha Fonte` e a contagem. Se o plugin falhar, aparece
um WARN e a rodada continua.

---

## 4. Boas práticas / segurança

- **Sem segredos no plugin.** Leia chaves de `cfg`/ambiente, nunca hardcode.
- **Timeout em toda requisição** (`requests.get(..., timeout=30)`).
- **Respeite os sites**: poucas requisições, sem burlar login/anti-bot de terceiros.
- **Erros**: use `log(..., level="WARN")` e retorne `[]` em falha — não levante exceção.
- **Compartilhe**: virou útil? Abra um PR (veja `CONTRIBUTING.md`). Plugins de fonte/painel
  são a forma mais fácil de contribuir.

---

## 5. Referência rápida

| Tipo | META.type | Função | Retorna |
|------|-----------|--------|---------|
| Fonte | `"source"` | `fetch(cfg, log)` | `list[Job]` |
| Painel | `"panel"` | `panel_html(cfg)` | `str` (HTML) |

Loader: `plugin_loader.py`. Wiring: `main.coletar` (fontes) e `main()` → `report.gerar_html`
(painéis).
