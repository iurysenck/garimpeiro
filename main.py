"""Garimpeiro de vagas — orquestrador.

Fluxo de uma rodada:
  1. Busca vagas em todas as fontes ativas (Gupy + JobSpy)
  2. Filtra por escopo (RJ + remoto)
  3. Remove as já vistas (dedup via SQLite)
  4. Pontua as novas com IA (Gemini)
  5. Salva todas as novas no banco (não reaparecem)
  6. Gera HTML + manda top no Telegram (só as com score >= min_score)

NÃO se candidata a nada. Apenas leitura e ranqueamento.
"""
from __future__ import annotations

import datetime
import json
import re
import sys
import traceback
from pathlib import Path

import yaml
from dotenv import load_dotenv

import matcher
import report
import tracker
from errors import ErrorTracker, enviar_alerta_erros
from plugin_loader import load_plugins
from sources import (
    Job,
    fetch_gupy,
    fetch_jobspy,
    fetch_trampos,
    in_scope,
    is_pcd_exclusive,
)

try:
    from sources_logged import (
        fetch_99freelas_logged,
        fetch_catho_applies,
        fetch_jobbol,
        fetch_vagas_logged,
        fetch_workana_logged,
    )
except Exception:  # nodriver opcional
    fetch_vagas_logged = None
    fetch_catho_applies = None
    fetch_workana_logged = None
    fetch_99freelas_logged = None
    fetch_jobbol = None
from store import Store

BASE = Path(__file__).resolve().parent
LOG_PATH = BASE / "garimpo.log"
ERR_PATH = BASE / "errors.log"
DB_PATH = BASE / "vagas.db"
HEALTH_PATH = BASE / "source_health.json"
ZERO_STREAK_ALERTA = 2  # nº de rodadas seguidas com 0 resultados que dispara aviso

# Detecção automática de nível pelo texto (quando o chamador não passa level=).
_ERR_RE = re.compile(
    r"ERRO FATAL|falh(a|ou)|traceback|exception|no such column|database is locked|\berror\b",
    re.I,
)
_WARN_RE = re.compile(
    r"sem sess|ausente|expir|pulando|não capturado|não veio|\b429\b|quota|rate.?limit|"
    r"timed out|timeout|forbidden|blocked|captcha|unauthorized",
    re.I,
)


def _auto_level(msg: str) -> str:
    if _ERR_RE.search(msg):
        return "ERROR"
    if _WARN_RE.search(msg):
        return "WARN"
    return "INFO"


class Logger:
    """Log com níveis. Espelha WARN/ERROR no errors.log (com a ação de correção)
    e registra no ErrorTracker para o alerta do Telegram."""

    def __init__(self, log_path: Path, err_path: Path, tracker_obj: ErrorTracker):
        self._fh = open(log_path, "a", encoding="utf-8")  # noqa: SIM115
        self._efh = open(err_path, "a", encoding="utf-8")  # noqa: SIM115
        self._tracker = tracker_obj

    def __call__(self, msg: str, level: str | None = None) -> None:
        lvl = level or _auto_level(msg)
        ts = f"{datetime.datetime.now():%Y-%m-%d %H:%M:%S}"
        line = f"{ts} | {lvl:<5} | {msg}"
        print(line)
        self._fh.write(line + "\n")
        self._fh.flush()
        if lvl in ("WARN", "ERROR"):
            ent = self._tracker.add(msg, nivel=lvl)
            self._efh.write(
                f"{ts} | {lvl:<5} | [{ent.categoria}] {msg.strip()}\n"
                f"        -> {ent.acao}\n"
            )
            self._efh.flush()

    def erro_fatal(self, exc: BaseException) -> None:
        """Loga erro fatal + grava traceback completo no errors.log."""
        self(f"ERRO FATAL: {exc!r}", level="ERROR")
        ts = f"{datetime.datetime.now():%Y-%m-%d %H:%M:%S}"
        tb = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
        self._efh.write(f"{ts} | TRACE | {tb}\n")
        self._efh.flush()

    def close(self) -> None:
        self._fh.close()
        self._efh.close()


def load_config() -> dict:
    with open(BASE / "config.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f)


def coletar(cfg: dict, log) -> tuple[list[Job], dict[str, int]]:
    """Coleta de todas as fontes ativas. Devolve (vagas, contagem_por_fonte).
    A contagem alimenta o healthcheck (fonte que zera por N rodadas = alerta)."""
    terms = cfg["search_terms"]
    max_per = cfg["max_per_term"]
    srcs = cfg.get("sources", {})
    jobs: list[Job] = []
    counts: dict[str, int] = {}

    if srcs.get("gupy"):
        log("Fonte: Gupy")
        r = fetch_gupy(terms, max_per, log)
        counts["Gupy"] = len(r)
        jobs += r
    if srcs.get("jobspy"):
        log("Fonte: JobSpy (Indeed/LinkedIn/Google)")
        r = fetch_jobspy(
            terms,
            cfg["jobspy_sites"],
            cfg["location_full"],
            cfg.get("hours_old", 0),
            max_per,
            log,
        )
        counts["JobSpy"] = len(r)
        jobs += r
    if srcs.get("trampos"):
        log("Fonte: Trampos.co (criativo)")
        r = fetch_trampos(
            cfg.get("trampos_categories", []), cfg.get("trampos_max_pages", 3), log
        )
        counts["Trampos"] = len(r)
        jobs += r
    if srcs.get("vagas_logado") and fetch_vagas_logged:
        log("Fonte: Vagas.com (logado, nodriver)")
        r = fetch_vagas_logged(cfg.get("vagas_logado_max_pages", 4), log)
        counts["Vagas.com"] = len(r)
        jobs += r
    if srcs.get("workana_logado") and fetch_workana_logged:
        log("Fonte: Workana (freela, logado)")
        r = fetch_workana_logged(
            cfg.get("workana_categories", ["design-multimedia"]),
            cfg.get("workana_max_pages", 3),
            log,
        )
        counts["Workana"] = len(r)
        jobs += r
    if srcs.get("freelas99_logado") and fetch_99freelas_logged:
        log("Fonte: 99freelas (freela, logado)")
        r = fetch_99freelas_logged(cfg.get("freelas99_max_pages", 3), log)
        counts["99freelas"] = len(r)
        jobs += r
    if srcs.get("jobbol") and fetch_jobbol:
        log("Fonte: Jobbol (agregador, nodriver)")
        r = fetch_jobbol(
            cfg.get("jobbol_cargos", []), cfg.get("jobbol_max_pages", 2), log
        )
        counts["Jobbol"] = len(r)
        jobs += r

    # Fontes via plugin (pasta plugins/). Cada plugin que dá erro é só pulado.
    psources, _ = load_plugins(BASE, log)
    for meta, fetch in psources:
        nome = meta.get("name", "plugin")
        log(f"Fonte (plugin): {nome}")
        try:
            r = fetch(cfg, log) or []
        except Exception as exc:  # noqa: BLE001
            log(f"  [Plugin {nome}] falha: {exc}")
            r = []
        counts[nome] = len(r)
        jobs += r
    return jobs, counts


def checar_saude_fontes(counts: dict[str, int], log) -> None:
    """Healthcheck: se uma fonte vier 0 por N rodadas seguidas, avisa (WARN ->
    entra no alerta do Telegram). Estado persistido em source_health.json."""
    try:
        estado = (
            json.loads(HEALTH_PATH.read_text(encoding="utf-8"))
            if HEALTH_PATH.exists()
            else {}
        )
    except Exception:  # noqa: BLE001
        estado = {}
    agora = datetime.datetime.now().isoformat(timespec="seconds")
    for fonte, n in counts.items():
        info = estado.get(fonte, {})
        info["zero_streak"] = info.get("zero_streak", 0) + 1 if n == 0 else 0
        info["last_count"] = n
        info["last_run"] = agora
        estado[fonte] = info
        if info["zero_streak"] >= ZERO_STREAK_ALERTA:
            log(
                f"  [Healthcheck] Fonte {fonte}: 0 resultados em "
                f"{info['zero_streak']} rodadas seguidas — scraper pode ter quebrado",
                level="WARN",
            )
    try:
        HEALTH_PATH.write_text(
            json.dumps(estado, ensure_ascii=False, indent=1), encoding="utf-8"
        )
    except Exception as exc:  # noqa: BLE001
        log(f"  [Healthcheck] não salvou estado: {exc}", level="WARN")


def main() -> int:
    load_dotenv(BASE / ".env")
    err_tracker = ErrorTracker()
    log = Logger(LOG_PATH, ERR_PATH, err_tracker)
    inicio = datetime.datetime.now()
    github_repo = ""
    log("=" * 60)
    log("Iniciando rodada do garimpeiro")

    try:
        cfg = load_config()
        github_repo = cfg.get("github_repo", "")
        perfil = (BASE / "perfil.md").read_text(encoding="utf-8")
        store = Store(str(DB_PATH))

        brutas, counts = coletar(cfg, log)
        log(f"Total bruto coletado: {len(brutas)}")
        checar_saude_fontes(counts, log)

        no_escopo = [
            j
            for j in brutas
            if in_scope(j, cfg["accepted_states"], cfg["include_remote"])
        ]
        log(f"Dentro do escopo (RJ + remoto): {len(no_escopo)}")

        # Exclui vagas reservadas a PcD (candidato não elegível)
        if cfg.get("exclude_pcd", True):
            antes = len(no_escopo)
            no_escopo = [j for j in no_escopo if not is_pcd_exclusive(j)]
            log(f"Removidas vagas PcD: {antes - len(no_escopo)}")

        # Exclui por palavras no título (ex: estágio)
        bloqueio = [k.lower() for k in cfg.get("exclude_title_keywords", [])]
        if bloqueio:
            antes = len(no_escopo)
            no_escopo = [
                j for j in no_escopo if not any(b in j.title.lower() for b in bloqueio)
            ]
            log(f"Removidas por palavra no título: {antes - len(no_escopo)}")

        novas = store.filter_new(no_escopo)
        log(f"Novas (não vistas antes): {len(novas)}")

        if novas:
            log("Avaliando com IA...")
            matcher.score_jobs(
                novas, perfil, cfg["gemini_model"], cfg["gemini_batch_size"], log
            )
            store.save_all(novas)  # marca todas como vistas

        min_score = cfg["min_score"]
        relevantes = [j for j in novas if j.score >= min_score]
        relevantes.sort(key=lambda j: j.score, reverse=True)
        log(f"Relevantes (score >= {min_score}): {len(relevantes)}")

        out = cfg.get("output", {})
        gerado_em = f"{inicio:%d/%m/%Y %H:%M}"
        # Painel cumulativo: tudo relevante dos últimos 30 dias, novas marcadas
        dashboard = store.recent_relevant(min_score, 30)
        new_uids = {j.uid for j in relevantes}

        # Link público do painel: Vercel (estável) ou, se vazio, o túnel Cloudflare.
        painel_url = cfg.get("painel_url", "").strip()
        if not painel_url:
            tunnel_file = BASE / "tunnel_url.txt"
            painel_url = (
                tunnel_file.read_text(encoding="utf-8").strip()
                if tunnel_file.exists()
                else ""
            )

        # Tracking de candidaturas (planilha do email-notf.gs + Catho logado)
        candidaturas = tracker.buscar_candidaturas(cfg.get("tracker_csv_url", ""), log)
        if cfg.get("sources", {}).get("catho_logado") and fetch_catho_applies:
            candidaturas = fetch_catho_applies(log) + candidaturas
        # Vagas já marcadas como aplicadas (aba Aplicadas)
        applied_uids = tracker.buscar_aplicadas(cfg.get("applied_csv_url", ""), log)
        bot_user = report.obter_username_bot(log)

        # Painéis via plugin (seções extras no app)
        _, ppanels = load_plugins(BASE, log)
        plugin_html = ""
        for meta, panel_html in ppanels:
            try:
                plugin_html += panel_html(cfg) or ""
            except Exception as exc:  # noqa: BLE001
                log(f"  [Plugin {meta.get('name','?')}] painel falhou: {exc}", level="WARN")

        if out.get("html"):
            html_path = BASE / out.get("html_path", "public/index.html")
            html_path.parent.mkdir(parents=True, exist_ok=True)
            report.gerar_html(
                dashboard,
                str(html_path),
                gerado_em,
                new_uids,
                candidaturas,
                applied_uids,
                bot_user,
                cfg.get("webapp_url", ""),
                cfg.get("sync_token", ""),
                cfg.get("brand", "Vagas"),
                cfg.get("github_repo", ""),
                plugin_html,
            )
            (html_path.parent / "version.json").write_text(
                json.dumps(
                    {"build": gerado_em, "vagas": len(dashboard), "novas": len(new_uids)},
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            log(f"HTML gerado: {html_path} ({len(dashboard)} vagas no painel)")
        if out.get("telegram") and relevantes:
            report.enviar_telegram(
                relevantes,
                out.get("telegram_top_n", 10),
                log,
                painel_url=painel_url,
                total_painel=len(dashboard),
            )
        # Follow-up: cutuca candidaturas paradas sem resposta
        if out.get("telegram"):
            report.enviar_followup(candidaturas, log, painel_url=painel_url)

        removidas = store.purge_old(60)
        if removidas:
            log(f"Limpeza: {removidas} registros antigos removidos")
        log(f"Banco total: {store.count()} vagas memorizadas")
        store.close()

        dur = (datetime.datetime.now() - inicio).total_seconds()
        log(f"Rodada concluída em {dur:.0f}s")
        if err_tracker.has():
            log(
                f"Rodada teve {err_tracker.n_errors} erro(s) e "
                f"{err_tracker.n_warns} aviso(s) — ver errors.log"
            )
        return 1 if err_tracker.n_errors else 0
    except Exception as exc:  # noqa: BLE001
        log.erro_fatal(exc)
        return 1
    finally:
        # Alerta no Telegram se algo deu errado (erro fatal, fonte caída, etc.)
        try:
            enviar_alerta_erros(
                err_tracker, log, f"{inicio:%d/%m/%Y %H:%M}", github_repo
            )
        except Exception as exc:  # noqa: BLE001
            log(f"  [Telegram] alerta de erro falhou: {exc}", level="WARN")
        log.close()


if __name__ == "__main__":
    sys.exit(main())
