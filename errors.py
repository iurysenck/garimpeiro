"""Rastreio de erros + diagnóstico + alerta no Telegram.

Cada erro conhecido vira (categoria, causa, ação) — você sabe na hora o que fazer.
Erros não catalogados ainda são capturados como "Desconhecido" (com traceback no
errors.log). O ErrorTracker junta tudo da rodada; enviar_alerta_erros manda um
resumo agrupado no Telegram só quando há algo a reportar.
"""
from __future__ import annotations

import html
import os
import re
from dataclasses import dataclass, field

import requests

_TG_API = "https://api.telegram.org/bot{token}/sendMessage"
_TG_LIMIT = 3800

# (regex no texto do erro, categoria, causa curta, o que fazer)
_DIAGS: list[tuple[str, str, str, str]] = [
    (
        r"healthcheck|0 resultados em|scraper pode ter quebrado",
        "Fonte sem retorno",
        "Uma fonte vem vazia há várias rodadas — o scraper dela pode ter quebrado.",
        "Veja qual fonte no log. Se for logada, rode login_nodriver.py. Se o site mudou o HTML, o seletor precisa de ajuste.",
    ),
    (
        r"sem sess|token não capturado|token não veio|sessão expir|relogar",
        "Sessão",
        "Login de um site logado caiu (token/cookie expirou).",
        "Rode  python login_nodriver.py  e logue no site. A sessão fica em .nddata.",
    ),
    (
        r"failed to connect|connection refused|cannot connect|profile.*lock|singletonlock|nodriver",
        "Chrome",
        "Chrome do perfil .nddata travado ou preso.",
        "Mate o Chrome do perfil e limpe o lock: kill do processo com '.nddata' no cmdline + apague .nddata/Singleton*.",
    ),
    (
        r"\b429\b|quota|rate.?limit|resource_exhausted",
        "Cota Gemini",
        "Estourou a cota grátis do Gemini (15 req/min).",
        "Espere ~1 min. Se repetir, baixe gemini_batch_size ou max_per_term no config.yaml.",
    ),
    (
        r"gemini_api_key|api[_ ]?key|invalid.*key|api key not",
        "Chave Gemini",
        "Chave do Gemini ausente ou inválida.",
        "Confira GEMINI_API_KEY no arquivo .env.",
    ),
    (
        r"telegram_bot_token|telegram_chat_id|chat not found|bot.*token|unauthorized.*bot",
        "Telegram",
        "Token ou chat do Telegram ausente/errado.",
        "Confira TELEGRAM_BOT_TOKEN e TELEGRAM_CHAT_ID no .env.",
    ),
    (
        r"timed out|timeout|connectionerror|max retries|nameresolution|getaddrinfo|connection reset",
        "Rede",
        "Falha de rede ao acessar uma fonte.",
        "Provável instabilidade passageira. Confira a internet — a próxima rodada tenta de novo.",
    ),
    (
        r"no such column|no such table|database is locked|sqlite|disk i/o",
        "Banco (SQLite)",
        "Problema no vagas.db.",
        "Se 'locked', feche outra instância rodando. Se faltar coluna/tabela, apague vagas.db (perde só o histórico de dedup).",
    ),
    (
        r"\b403\b|forbidden|captcha|cloudflare|datadome|access denied|blocked",
        "Bloqueio anti-bot",
        "Um site bloqueou o acesso.",
        "Reduza frequência/volume dessa fonte no config.yaml. Pode precisar relogar via login_nodriver.py.",
    ),
    (
        r"\b401\b|unauthorized|expired token",
        "Autenticação",
        "Uma fonte recusou a autenticação.",
        "Token/cookie expirou. Rode login_nodriver.py para a fonte logada.",
    ),
    (
        r"\b5\d\d\b|server error|bad gateway|service unavailable",
        "Servidor da fonte",
        "O site da fonte respondeu com erro (5xx).",
        "Problema do lado deles. Costuma resolver sozinho na próxima rodada.",
    ),
]


def diagnosticar(msg: str) -> tuple[str, str, str]:
    """Devolve (categoria, causa, ação) para uma mensagem de erro."""
    for pat, cat, causa, acao in _DIAGS:
        if re.search(pat, msg, re.I):
            return cat, causa, acao
    return (
        "Desconhecido",
        "Erro não catalogado.",
        "Veja o traceback completo em errors.log e, se recorrente, adicione um padrão em errors.py (_DIAGS).",
    )


_FONTE_RE = re.compile(r"\s*\[([^\]]+)\]")


def _fonte_de(msg: str) -> str:
    m = _FONTE_RE.match(msg)
    return m.group(1) if m else ""


@dataclass
class ErrorEntry:
    nivel: str  # ERROR | WARN
    msg: str
    fonte: str
    categoria: str
    causa: str
    acao: str


@dataclass
class ErrorTracker:
    entries: list[ErrorEntry] = field(default_factory=list)

    def add(self, msg: str, nivel: str = "ERROR", fonte: str = "") -> ErrorEntry:
        cat, causa, acao = diagnosticar(msg)
        ent = ErrorEntry(nivel, msg.strip(), fonte or _fonte_de(msg) or "-", cat, causa, acao)
        self.entries.append(ent)
        return ent

    def has(self) -> bool:
        return bool(self.entries)

    @property
    def n_errors(self) -> int:
        return sum(1 for e in self.entries if e.nivel == "ERROR")

    @property
    def n_warns(self) -> int:
        return sum(1 for e in self.entries if e.nivel == "WARN")


def _chunk(blocos: list[str]) -> list[str]:
    partes, msg = [], ""
    for b in blocos:
        if len(msg) + len(b) > _TG_LIMIT:
            partes.append(msg)
            msg = ""
        msg += b
    if msg:
        partes.append(msg)
    return partes


def issue_url(repo: str, tracker: "ErrorTracker") -> str:
    """Monta um link de 'novo issue' no GitHub já preenchido com os erros da rodada."""
    import urllib.parse

    repo = (repo or "").strip().strip("/")
    if not repo:
        return ""
    cats = sorted({e.categoria for e in tracker.entries})
    titulo = f"[erro] {', '.join(cats)[:60]}"
    linhas = ["Erros da rodada (gerado automaticamente):", ""]
    for e in tracker.entries[:20]:
        linhas.append(f"- **{e.categoria}** ({e.nivel}) {e.fonte}: {e.msg[:160]}")
        linhas.append(f"  - sugestão: {e.acao}")
    linhas += ["", "Ambiente: (preencha SO/Python se possível)"]
    corpo = "\n".join(linhas)
    q = urllib.parse.urlencode({"labels": "bug", "title": titulo, "body": corpo})
    return f"https://github.com/{repo}/issues/new?{q}"


def enviar_alerta_erros(
    tracker: ErrorTracker, log, gerado_em: str = "", github_repo: str = ""
) -> None:
    """Manda no Telegram um resumo dos erros/avisos da rodada, agrupado por categoria."""
    if not tracker.has():
        return
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat_id:
        log("  [Telegram] sem token/chat — não dá pra alertar erros", level="WARN")
        return

    e = html.escape
    # agrupa por categoria (1 ação por categoria, junta as fontes afetadas)
    grupos: dict[str, dict] = {}
    for ent in tracker.entries:
        g = grupos.setdefault(
            ent.categoria,
            {"causa": ent.causa, "acao": ent.acao, "fontes": set(), "n": 0, "pior": "WARN"},
        )
        g["n"] += 1
        if ent.fonte and ent.fonte != "-":
            g["fontes"].add(ent.fonte)
        if ent.nivel == "ERROR":
            g["pior"] = "ERROR"

    quando = f" · {e(gerado_em)}" if gerado_em else ""
    head = (
        f"🚨 <b>Garimpeiro — {tracker.n_errors} erro(s), "
        f"{tracker.n_warns} aviso(s)</b>{quando}\n"
        "➖➖➖➖➖➖➖➖➖➖\n"
    )
    blocos = [head]
    for cat, g in grupos.items():
        icone = "⛔" if g["pior"] == "ERROR" else "⚠️"
        fontes = (" · " + ", ".join(sorted(g["fontes"]))) if g["fontes"] else ""
        blocos.append(
            f"\n{icone} <b>{e(cat)}</b> ({g['n']}){e(fontes)}\n"
            f"• {e(g['causa'])}\n"
            f"🔧 <i>{e(g['acao'])}</i>\n"
        )
    blocos.append("\n📄 Detalhes e traceback em <code>errors.log</code>.")
    _iu = issue_url(github_repo, tracker)
    if _iu:
        blocos.append(f'\n🐛 <a href="{e(_iu)}">Reportar no GitHub (1 clique)</a>')

    url = _TG_API.format(token=token)
    for parte in _chunk(blocos):
        try:
            r = requests.post(
                url,
                json={
                    "chat_id": chat_id,
                    "text": parte,
                    "parse_mode": "HTML",
                    "disable_web_page_preview": True,
                },
                timeout=30,
            )
            r.raise_for_status()
        except Exception as exc:  # noqa: BLE001
            log(f"  [Telegram] falha ao enviar alerta de erro: {exc}", level="WARN")
            return
    log(f"  [Telegram] alerta de erro enviado ({len(tracker.entries)} item(ns))")
