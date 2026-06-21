#!/usr/bin/env python3
"""Instalador web local do Garimpeiro — 2 telas (Essencial + Personalizar), no navegador.

`python garimpeiro.py setup --web` sobe um servidor HTTP em 127.0.0.1 (apenas
local), abre o navegador e grava `config.yaml` + `.env`. O assistente de
terminal (`setup` sem `--web`) continua como fallback universal para servidores
sem tela (Oracle/RPi/Docker/CI) — cross-platform.

Segurança por design:
  - Liga somente em 127.0.0.1 (nunca exposto na rede).
  - Token anti-CSRF (gerado a cada execução) exigido no POST.
  - Valida o cabeçalho Host (só localhost/127.0.0.1).
  - A única chamada externa possível é "Detectar Telegram" — opcional, sob
    clique, com o token do próprio usuário. Nada mais sai do computador.
  - Segredos (chaves) nunca são logados no terminal.
"""
from __future__ import annotations

import http.server
import json
import secrets
import socket
import socketserver
import threading
import time
import unicodedata
import urllib.parse
import urllib.request
import webbrowser

import garimpeiro as g  # BASE, CONFIG, ENVFILE, PERFIL, escrever_config
import geo
import presets

# Repo oficial p/ "Reportar problema". Editável no instalador e no config.yaml.
DEFAULT_REPO = "iurysenck/garimpeiro"

_AI_LABELS = {
    "gemini": "Gemini (Google) — grátis, sem plano pago",
    "openai": "OpenAI (GPT) — chave paga",
    "anthropic": "Anthropic (Claude) — chave paga",
    "ollama": "Ollama — roda local no seu PC, grátis, sem chave",
}

_TOKEN = ""  # anti-CSRF da sessão (preenchido em run())


# --------------------------------------------------------------- util de rede
def _lan_ip() -> str:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))  # só resolve a rota; UDP não envia pacote
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:  # noqa: BLE001
        return "127.0.0.1"


def _fold(s: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFKD", (s or "").lower()) if not unicodedata.combining(c)
    ).strip()


# ----------------------------------------------------------- leitura p/ prefill
def _read_env() -> dict[str, str]:
    out: dict[str, str] = {}
    if g.ENVFILE.exists():
        for line in g.ENVFILE.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                k, _, v = line.partition("=")
                out[k.strip()] = v.strip()
    return out


def _read_cfg() -> dict:
    if not g.CONFIG.exists():
        return {}
    try:
        import yaml

        return yaml.safe_load(g.CONFIG.read_text(encoding="utf-8")) or {}
    except Exception:  # noqa: BLE001
        return {}


def _state_code_from(estados: list[str]) -> str:
    alvo = {_fold(e) for e in estados}
    for code, name in geo.BR_STATES:
        if _fold(code) in alvo or _fold(name) in alvo:
            return code
    return "RJ"


def _prefill() -> dict:
    cfg = _read_cfg()
    env = _read_env()
    src = cfg.get("sources", {}) if isinstance(cfg.get("sources"), dict) else {}
    estados = [str(s) for s in (cfg.get("accepted_states") or []) if str(s).strip()]
    return {
        "cidade": cfg.get("location", "Rio de Janeiro"),
        "state_code": _state_code_from(estados) if estados else "RJ",
        "remoto": bool(cfg.get("include_remote", True)),
        "pcd": not bool(cfg.get("exclude_pcd", True)),
        "brand": cfg.get("brand", "Vagas"),
        "logadas": bool(src.get("vagas_logado") or src.get("catho_logado") or src.get("jobbol")),
        "headless": env.get("GARIMPO_HEADLESS", "").strip().lower() in ("1", "true", "yes", "on"),
        "github_repo": cfg.get("github_repo") or DEFAULT_REPO,
        "run_at": cfg.get("run_at", "08:00,20:00"),
        "ai_provider": (cfg.get("ai_provider") or "gemini").lower(),
        "ai_model": cfg.get("ai_model", ""),
        "ollama_host": cfg.get("ollama_host", "http://localhost:11434"),
        "gemini": env.get("GEMINI_API_KEY", ""),
        "openai": env.get("OPENAI_API_KEY", ""),
        "anthropic": env.get("ANTHROPIC_API_KEY", ""),
        "tg_tok": env.get("TELEGRAM_BOT_TOKEN", ""),
        "tg_chat": env.get("TELEGRAM_CHAT_ID", ""),
    }


# ----------------------------------------------------------------- gravação
def _salvar(dados: dict) -> dict:
    nomes = [n for n in dados.get("areas", []) if n in presets.PRESETS]
    if not nomes:
        nomes = ["design"]
    bloco = presets.montar(nomes)
    for t in [x.strip() for x in str(dados.get("extra", "")).split(",") if x.strip()]:
        if t not in bloco["search_terms"]:
            bloco["search_terms"].append(t)

    country = (dados.get("country") or "BR").strip().upper()
    scode = (dados.get("state_code") or "").strip()
    if scode in ("", "__OUTRO__"):
        outro = (dados.get("state_other") or "").strip()
        estados = [outro] if outro else []
    else:
        estados = geo.state_variants(country, scode)
    cidade = (dados.get("cidade") or "").strip() or "Brasil"
    estado_compat = estados[0] if estados else cidade

    remoto = bool(dados.get("remoto", True))
    exclude_pcd = not bool(dados.get("pcd", False))
    brand = (dados.get("brand") or "Vagas").strip()
    logadas = bool(dados.get("logadas", False))
    github_repo = (dados.get("github_repo") or "").strip().strip("/")
    run_at = (dados.get("run_at") or "08:00,20:00").strip()

    ai_provider = (dados.get("ai_provider") or "gemini").lower()
    if ai_provider not in _AI_LABELS:
        ai_provider = "gemini"
    ai_model = (dados.get("ai_model") or "").strip()
    ollama_host = (dados.get("ollama_host") or "http://localhost:11434").strip()

    headless = bool(dados.get("headless", False))

    gem = (dados.get("gemini") or "").strip()
    openai_key = (dados.get("openai_key") or "").strip()
    anthropic_key = (dados.get("anthropic_key") or "").strip()
    tg_tok = (dados.get("tg_tok") or "").strip()
    tg_chat = (dados.get("tg_chat") or "").strip() if tg_tok else ""

    g.ENVFILE.write_text(
        f"GEMINI_API_KEY={gem}\n"
        f"OPENAI_API_KEY={openai_key}\n"
        f"ANTHROPIC_API_KEY={anthropic_key}\n"
        f"TELEGRAM_BOT_TOKEN={tg_tok}\n"
        f"TELEGRAM_CHAT_ID={tg_chat}\n"
        f"GARIMPO_HEADLESS={'true' if headless else 'false'}\n",
        encoding="utf-8",
    )
    if not g.PERFIL.exists():
        exemplo = g.BASE / "perfil.example.md"
        if exemplo.exists():
            g.PERFIL.write_text(exemplo.read_text(encoding="utf-8"), encoding="utf-8")

    g.escrever_config(
        bloco, cidade, estado_compat, remoto, logadas, bool(tg_tok), brand,
        github_repo=github_repo, run_at=run_at, estados=estados or None,
        exclude_pcd=exclude_pcd, ai_provider=ai_provider, ai_model=ai_model,
        ollama_host=ollama_host,
    )

    tem_ia = bool(
        (ai_provider == "gemini" and gem)
        or (ai_provider == "openai" and openai_key)
        or (ai_provider == "anthropic" and anthropic_key)
        or (ai_provider == "ollama")
    )
    sites = ["Gupy", "Indeed", "LinkedIn", "Google (JobSpy)", "Trampos.co"]
    if logadas:
        sites += ["Vagas.com", "Catho", "Workana", "99freelas", "Jobbol"]
    return {"ok": True, "sites": sites, "termos": len(bloco["search_terms"]),
            "estados": estados, "logadas": logadas, "ai": ai_provider, "tem_ia": tem_ia}


# ----------------------------------------------- helper opcional do Telegram
def _tg_check(token: str) -> dict:
    token = (token or "").strip()
    if not token or "/" in token or len(token) > 100:
        return {"ok": False, "erro": "token vazio ou inválido"}
    base = "https://api.telegram.org/bot" + urllib.parse.quote(token, safe=":")
    try:
        with urllib.request.urlopen(base + "/getMe", timeout=10) as r:
            me = json.load(r)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "erro": f"não consegui falar com o Telegram ({exc})"}
    if not me.get("ok"):
        return {"ok": False, "erro": "token recusado pelo Telegram"}
    bot = me.get("result", {}).get("username", "")
    chat = None
    try:
        with urllib.request.urlopen(base + "/getUpdates?limit=10", timeout=10) as r:
            up = json.load(r)
        for u in reversed(up.get("result", [])):
            msg = u.get("message") or u.get("channel_post") or {}
            cid = msg.get("chat", {}).get("id")
            if cid:
                chat = str(cid)
                break
    except Exception:  # noqa: BLE001
        pass
    return {"ok": True, "bot": bot, "chat_id": chat}


# --------------------------------------------------------------------- página
def _esc(s: str) -> str:
    return (
        str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
    )


def _areas_html(selecionadas: set[str]) -> str:
    out = []
    for nome, p in presets.PRESETS.items():
        chk = " checked" if nome in selecionadas else ""
        out.append(
            f'<label class="opt"><input type="checkbox" name="area" value="{_esc(nome)}"{chk}>'
            f'<span class="optk">{_esc(nome)}</span><span class="optl">{_esc(p["label"])}</span></label>'
        )
    return "\n".join(out)


def _country_options() -> str:
    return "\n".join(
        f'<option value="{_esc(c["code"])}"{" selected" if c["code"]=="BR" else ""}>{_esc(c["name"])}</option>'
        for c in geo.countries()
    )


def _state_options(country: str = "BR", selected: str = "RJ") -> str:
    opts = [
        f'<option value="{_esc(s["code"])}"{" selected" if s["code"]==selected else ""}>'
        f'{_esc(s["name"])} ({_esc(s["code"])})</option>'
        for s in geo.states(country)
    ]
    opts.append('<option value="__OUTRO__">Outro / não listado…</option>')
    return "\n".join(opts)


def _ai_options(selected: str) -> str:
    return "\n".join(
        f'<option value="{k}"{" selected" if k==selected else ""}>{_esc(v)}</option>'
        for k, v in _AI_LABELS.items()
    )


def build_page(token: str) -> str:
    pf = _prefill()
    return (
        _PAGE.replace("__TOKEN__", token)
        .replace("__AREAS__", _areas_html({"design"}))
        .replace("__COUNTRIES__", _country_options())
        .replace("__STATES__", _state_options("BR", pf["state_code"]))
        .replace("__AIOPTS__", _ai_options(pf["ai_provider"]))
        .replace("__CIDADE__", _esc(pf["cidade"]))
        .replace("__BRAND__", _esc(pf["brand"]))
        .replace("__GITHUB__", _esc(pf["github_repo"]))
        .replace("__RUNAT__", _esc(pf["run_at"]))
        .replace("__AIMODEL__", _esc(pf["ai_model"]))
        .replace("__OLLAMAHOST__", _esc(pf["ollama_host"]))
        .replace("__GEMINI__", _esc(pf["gemini"]))
        .replace("__OPENAI__", _esc(pf["openai"]))
        .replace("__ANTHROPIC__", _esc(pf["anthropic"]))
        .replace("__TGTOK__", _esc(pf["tg_tok"]))
        .replace("__TGCHAT__", _esc(pf["tg_chat"]))
        .replace("__LANIP__", _esc(_lan_ip()))
        .replace("__REMOTO__", " checked" if pf["remoto"] else "")
        .replace("__PCD__", " checked" if pf["pcd"] else "")
        .replace("__LOGADAS__", " checked" if pf["logadas"] else "")
        .replace("__HEADLESS__", " checked" if pf["headless"] else "")
    )


# --------------------------------------------------------------------- servidor
def _make_handler(httpd_ref: dict):
    class Handler(http.server.BaseHTTPRequestHandler):
        def _host_ok(self) -> bool:
            host = (self.headers.get("Host") or "").split(":")[0]
            return host in ("localhost", "127.0.0.1", "")

        def do_GET(self):  # noqa: N802
            if not self._host_ok():
                self.send_error(403)
                return
            path = self.path.split("?")[0]
            if path == "/states":  # geo read-only (sem segredo, sem token)
                q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
                cc = (q.get("country", ["BR"])[0] or "BR").upper()
                self._json({"states": geo.states(cc)}, 200)
                return
            if path == "/cities":  # municípios do IBGE p/ o datalist (read-only)
                q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
                uf = (q.get("uf", [""])[0] or "").upper()
                self._json({"cities": geo.cities(uf)}, 200)
                return
            if path not in ("/", "/index.html"):
                self.send_error(404)
                return
            body = build_page(_TOKEN).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self):  # noqa: N802
            if not self._host_ok() or self.headers.get("X-Setup-Token") != _TOKEN:
                self.send_error(403)
                return
            try:
                n = int(self.headers.get("Content-Length", "0"))
                dados = json.loads(self.rfile.read(n).decode("utf-8") or "{}")
                if self.path == "/tg_check":
                    self._json(_tg_check(dados.get("token", "")), 200)
                    return
                if self.path == "/save":
                    self._json(_salvar(dados), 200)
                    httpd = httpd_ref.get("srv")
                    if httpd:
                        threading.Thread(
                            target=lambda: (time.sleep(1.0), httpd.shutdown()), daemon=True
                        ).start()
                    return
            except Exception as exc:  # noqa: BLE001
                self._json({"ok": False, "erro": str(exc)}, 400)
                return
            self.send_error(404)

        def _json(self, obj: dict, code: int) -> None:
            body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_args):  # silencia logs (evita vazar segredos)
            return

    return Handler


def run(port: int = 8799) -> int:
    global _TOKEN
    _TOKEN = secrets.token_urlsafe(18)

    httpd_ref: dict = {}
    handler = _make_handler(httpd_ref)
    socketserver.TCPServer.allow_reuse_address = True

    httpd = None
    for p in range(port, port + 20):
        try:
            httpd = socketserver.TCPServer(("127.0.0.1", p), handler)
            port = p
            break
        except OSError:
            continue
    if httpd is None:
        print("Nao achei porta livre p/ o instalador web. Rode sem --web (terminal).")
        return 1
    httpd_ref["srv"] = httpd

    url = f"http://127.0.0.1:{port}/"
    print("Instalador web do Garimpeiro")
    print(f"  Abra no navegador:  {url}")
    print("  (So local, 127.0.0.1. Ao salvar, o servidor fecha sozinho. Ctrl+C cancela.)")
    try:
        webbrowser.open(url)
    except Exception:  # noqa: BLE001
        pass
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nCancelado.")
    finally:
        httpd.server_close()
    print("Instalador encerrado. Proximo: python garimpeiro.py perfil  (melhora a nota da IA)")
    return 0


# ------------------------------------------------------------------- template
_PAGE = """<!doctype html>
<html lang="pt-br"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Garimpeiro · Instalador</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@400;500;600;700&family=Syne:wght@700;800&display=swap" rel="stylesheet">
<style>
  :root{--bg:#080809;--text:#f1f1f4;--muted:#9a9aa6;--line:rgba(255,255,255,.10);
    --a1:#6366f1;--a2:#7c83ff;--accent:#6366f1;--accentd:#4f46e5;
    --grad:linear-gradient(180deg,#5b62e6,#4b51c9);
    --brandgrad:linear-gradient(135deg,#ff3366,#6366f1);--panel:#101016}
  *{box-sizing:border-box}
  *{scrollbar-width:thin;scrollbar-color:rgba(124,131,255,.5) transparent}
  *::-webkit-scrollbar{width:10px;height:10px}
  *::-webkit-scrollbar-track{background:transparent}
  *::-webkit-scrollbar-thumb{background:rgba(124,131,255,.35);border-radius:8px;border:2px solid transparent;background-clip:content-box}
  *::-webkit-scrollbar-thumb:hover{background:rgba(124,131,255,.6);background-clip:content-box}
  body{margin:0;background:var(--bg);color:var(--text);font-family:'Space Grotesk',system-ui,sans-serif;
    line-height:1.5;padding:26px 16px 40px}
  .glow{position:fixed;width:480px;height:480px;border-radius:50%;filter:blur(90px);opacity:.10;z-index:-1;
    background:radial-gradient(circle,#4f46e5,transparent 70%);top:-170px;left:-130px;pointer-events:none}
  .glow2{position:fixed;width:420px;height:420px;border-radius:50%;filter:blur(90px);opacity:.08;z-index:-1;
    background:radial-gradient(circle,#6366f1,transparent 70%);bottom:-170px;right:-130px;pointer-events:none}
  .wrap{max-width:680px;margin:0 auto}
  h1{font-family:'Syne',sans-serif;font-size:clamp(1.6rem,1rem + 3vw,2.3rem);margin:0;letter-spacing:-.02em}
  h1 b{background:var(--grad);-webkit-background-clip:text;background-clip:text;-webkit-text-fill-color:transparent}
  .steps{display:flex;gap:6px;margin:16px 0 18px}
  .steps i{flex:1;height:4px;border-radius:3px;background:rgba(255,255,255,.10);transition:background .3s}
  .steps i.on{background:var(--accent)}
  .steps i.cur{background:var(--a2);box-shadow:0 0 10px rgba(124,131,255,.5)}
  .stepnum{font-size:.76rem;color:var(--muted);margin-bottom:6px}
  .card{position:relative;border-radius:18px;padding:20px 22px;
    background:radial-gradient(135% 90% at 22% 0%,rgba(255,255,255,.11),rgba(255,255,255,.028) 56%);
    border:1px solid var(--line);backdrop-filter:blur(8px) saturate(1.6);-webkit-backdrop-filter:blur(8px) saturate(1.6);
    box-shadow:0 8px 30px rgba(0,0,0,.30),inset 0 1px 0 rgba(255,255,255,.20)}
  .screen{display:none;animation:fade .25s ease}
  .screen.on{display:block}
  @keyframes fade{from{opacity:0;transform:translateY(6px)}to{opacity:1;transform:none}}
  .blk{margin-top:22px;padding-top:20px;border-top:1px solid var(--line)}
  .blk:first-child{margin-top:0;padding-top:0;border-top:0}
  h2{font-family:'Syne',sans-serif;font-size:1.12rem;margin:0 0 6px}
  h2 small{font-weight:400;font-size:.72rem;color:var(--muted)}
  .why{color:var(--muted);font-size:.84rem;line-height:1.6;margin:0 0 14px;border-left:2px solid var(--a2);padding-left:12px}
  .why b{color:var(--text)}
  .grid{display:grid;grid-template-columns:1fr 1fr;gap:12px}
  @media(max-width:560px){.grid{grid-template-columns:1fr}}
  label.field{display:block;font-size:.78rem;color:var(--muted);margin-bottom:2px}
  .field span{display:block;margin-bottom:5px}
  input[type=text],input[type=password],select{width:100%;background:rgba(0,0,0,.25);border:1px solid var(--line);
    border-radius:10px;color:var(--text);font:inherit;font-size:.9rem;padding:10px 12px;outline:none;transition:border-color .2s}
  input:focus,select:focus{border-color:var(--a2)}
  select{appearance:none;cursor:pointer}
  select option{background:#13131a;color:#f1f1f4}
  .areas{display:grid;grid-template-columns:1fr 1fr;gap:8px;max-height:42vh;overflow:auto;padding-right:4px}
  @media(max-width:560px){.areas{grid-template-columns:1fr}}
  .opt{display:flex;align-items:baseline;gap:8px;background:rgba(0,0,0,.2);border:1px solid var(--line);
    border-radius:11px;padding:8px 11px;cursor:pointer;transition:border-color .2s}
  .opt:hover{border-color:var(--a2)}
  .opt input{margin:0;accent-color:var(--a1)}
  .optk{font-weight:600;font-size:.8rem}
  .optl{color:var(--muted);font-size:.7rem;flex:1}
  .toggle{display:flex;align-items:center;gap:10px;font-size:.86rem;color:var(--text);cursor:pointer;margin-top:10px}
  .toggle input{width:18px;height:18px;accent-color:var(--a1)}
  .btnrow{display:flex;flex-wrap:wrap;gap:8px;margin-top:10px}
  .lk{display:inline-flex;align-items:center;gap:6px;text-decoration:none;font-size:.78rem;color:var(--text);
    border:1px solid var(--line);border-radius:9px;padding:8px 13px;background:rgba(255,255,255,.04);cursor:pointer;transition:border-color .2s}
  .lk:hover{border-color:var(--a2)}
  .lk.brand{border-color:transparent;background:var(--grad);font-weight:600}
  .tag{font-size:.76rem;color:var(--muted);margin-top:7px;min-height:1em}
  .tag.ok{color:#34d399} .tag.bad{color:#ff6b75}
  .access .arow{display:flex;align-items:center;justify-content:space-between;gap:10px;flex-wrap:wrap;
    border-top:1px solid rgba(255,255,255,.06);padding:11px 0}
  .access .arow:first-child{border-top:0;padding-top:2px}
  .arow .k{font-size:.83rem;font-weight:600}
  .arow .k small{display:block;color:var(--muted);font-weight:400;font-size:.72rem}
  .url{font-family:ui-monospace,Menlo,monospace;font-size:.8rem;background:rgba(0,0,0,.3);border:1px solid var(--line);border-radius:8px;padding:6px 10px}
  .cpy{cursor:pointer;border:1px solid var(--line);background:rgba(255,255,255,.04);color:var(--text);border-radius:8px;padding:6px 10px;font:inherit;font-size:.76rem}
  .cpy:hover{border-color:var(--a2)}
  .nav{display:flex;justify-content:space-between;gap:10px;margin-top:20px}
  .nav button{border:0;border-radius:12px;cursor:pointer;font-family:'Syne',sans-serif;font-weight:700;font-size:.95rem;padding:13px 20px;transition:transform .15s,filter .2s}
  .secondary{background:rgba(255,255,255,.06);color:var(--text);border:1px solid var(--line)!important}
  .secondary:hover{border-color:var(--a2)!important}
  .primary{background:var(--grad);color:#fff;box-shadow:0 10px 26px rgba(99,102,241,.32);flex:1}
  .primary:hover{transform:translateY(-2px);filter:brightness(1.08)}
  .primary:disabled{opacity:.6;transform:none}
  .err{color:#ff6b75;font-size:.82rem;margin-top:8px;min-height:1em;text-align:center}
  .done{text-align:center}
  .done ul{text-align:left;max-width:480px;margin:14px auto;color:var(--muted);font-size:.85rem;line-height:1.85}
  .done code{background:rgba(255,255,255,.08);padding:2px 7px;border-radius:6px;font-size:.82rem;color:var(--text)}
  code{background:rgba(255,255,255,.08);padding:1px 6px;border-radius:6px;font-size:.84em}
  small.muted{color:var(--muted)}
  .sec{display:flex;gap:10px;align-items:flex-start;margin-top:14px;padding:11px 13px;border-radius:12px;
    background:rgba(52,211,153,.07);border:1px solid rgba(52,211,153,.22);font-size:.79rem;color:#cbd5cf;line-height:1.6}
  .sec b{color:#9fe9c9}
  /* preview fiel do header do painel */
  .bprev{margin-top:12px;border:1px solid var(--line);border-radius:14px;overflow:hidden;background:#0b0b10}
  .bprev .pvtop{display:flex;align-items:center;gap:9px;padding:14px 16px 6px}
  .bprev .pvbrand{font-family:'Syne',sans-serif;font-weight:800;font-size:1.4rem;letter-spacing:-.01em}
  .bprev .pvbrand2{background:var(--brandgrad);-webkit-background-clip:text;background-clip:text;-webkit-text-fill-color:transparent}
  .bprev .pvsub{color:var(--muted);font-size:.72rem;margin-left:auto}
  .bprev .pvtabs{display:flex;gap:18px;padding:8px 16px 0;border-bottom:1px solid var(--line)}
  .bprev .pvtab{font-size:.78rem;color:var(--muted);padding-bottom:9px;font-weight:600}
  .bprev .pvtab.on{color:#fff;box-shadow:inset 0 -2px 0 #ff3366}
  .bprev .pvtag{font-size:.68rem;color:var(--muted);padding:10px 16px}
</style></head>
<body>
<div class="glow"></div><div class="glow2"></div>
<div class="wrap">
  <h1>Garimpeiro<b>.</b> setup</h1>
  <div class="steps" id="steps"></div>

  <div class="card" id="card">
    <!-- TELA 1: ESSENCIAL -->
    <section class="screen on" data-screen="1">
      <div class="stepnum">Essencial · passo 1 de 2</div>

      <div class="blk">
        <h2>O que você procura</h2>
        <p class="why">Marque uma ou mais <b>áreas</b> — cada uma vira termos de busca. É a única coisa obrigatória.</p>
        <div class="areas">__AREAS__</div>
        <label class="field" style="margin-top:12px"><span>Termos extras (vírgula, opcional)</span>
          <input type="text" id="extra" placeholder="ex: brand designer, colorista, editor de vídeo"></label>
      </div>

      <div class="blk">
        <h2>Onde</h2>
        <p class="why">Escolha <b>país</b> e <b>estado</b> na lista — eu já lido com sigla e acentos (ex.: <code>São Paulo</code> casa "Sao Paulo" e "SP").</p>
        <div class="grid">
          <label class="field"><span>País</span><select id="country">__COUNTRIES__</select></label>
          <label class="field"><span>Estado / província</span><select id="state">__STATES__</select></label>
        </div>
        <label class="field" id="otherwrap" style="display:none;margin-top:10px"><span>Qual estado/região? (digite)</span>
          <input type="text" id="state_other" placeholder="ex: Lisboa, Buenos Aires..."></label>
        <label class="field" style="margin-top:10px"><span>Cidade-base</span>
          <input type="text" id="cidade" value="__CIDADE__" list="cidlist" placeholder="ex: Rio de Janeiro"></label>
        <datalist id="cidlist"></datalist>
        <label class="toggle"><input type="checkbox" id="remoto"__REMOTO__> Incluir vagas remotas</label>
      </div>

      <div class="blk">
        <h2>A IA que dá a nota <small>(opcional)</small></h2>
        <p class="why">A IA lê seu <b>perfil</b> e dá nota 0–10 a cada vaga, com resumo e até uma mensagem de candidatura pronta. <b>Sem chave funciona</b> (nota neutra). <b>Gemini é grátis</b> e não precisa de plano pago.</p>
        <label class="field"><span>Provedor de IA</span><select id="ai_provider">__AIOPTS__</select></label>
        <div class="aibox" data-ai="gemini" style="margin-top:10px">
          <label class="field"><span>GEMINI_API_KEY</span><input type="password" id="gemini" value="__GEMINI__" placeholder="cole aqui (opcional)"></label>
          <div class="btnrow"><a class="lk brand" href="https://aistudio.google.com/apikey" target="_blank" rel="noopener">Pegar chave Gemini (grátis)</a></div>
        </div>
        <div class="aibox" data-ai="openai" style="display:none;margin-top:10px">
          <label class="field"><span>OPENAI_API_KEY</span><input type="password" id="openai_key" value="__OPENAI__" placeholder="cole aqui"></label>
          <div class="btnrow"><a class="lk" href="https://platform.openai.com/api-keys" target="_blank" rel="noopener">Pegar chave OpenAI</a></div>
        </div>
        <div class="aibox" data-ai="anthropic" style="display:none;margin-top:10px">
          <label class="field"><span>ANTHROPIC_API_KEY</span><input type="password" id="anthropic_key" value="__ANTHROPIC__" placeholder="cole aqui"></label>
          <div class="btnrow"><a class="lk" href="https://console.anthropic.com/settings/keys" target="_blank" rel="noopener">Pegar chave Anthropic</a></div>
        </div>
        <div class="aibox" data-ai="ollama" style="display:none;margin-top:10px">
          <label class="field"><span>Host do Ollama</span><input type="text" id="ollama_host" value="__OLLAMAHOST__" placeholder="http://localhost:11434"></label>
          <p class="why" style="margin-top:10px;border-color:var(--line)">Ollama roda modelos <b>no seu PC</b>, de graça e sem chave. Instale em <b>ollama.com</b> e rode <code>ollama pull llama3.1</code>.</p>
        </div>
        <label class="field" style="margin-top:8px"><span>Modelo (opcional — vazio = padrão do provedor)</span>
          <input type="text" id="ai_model" value="__AIMODEL__" placeholder="ex: gemini-2.0-flash"></label>
        <div class="sec"><span>🔒</span><div><b>Segurança:</b> as chaves vão só pro arquivo <code>.env</code> (no <code>.gitignore</code>) — nunca sobem pro GitHub nem saem do seu PC. Este instalador roda só em <code>127.0.0.1</code>.</div></div>
        <p class="why" style="margin-top:12px;border-color:var(--a2)"><b>Dica que mais melhora a nota:</b> escrever sobre você e o trabalho que quer. Faça depois do setup (não toma tempo agora) com <code>python garimpeiro.py perfil</code> — um editor guiado.</p>
      </div>
    </section>

    <!-- TELA 2: PERSONALIZAR -->
    <section class="screen" data-screen="2">
      <div class="stepnum">Personalizar · passo 2 de 2 <small class="muted">(tudo opcional — já tem padrão)</small></div>

      <div class="blk">
        <h2>Nome do painel e horários</h2>
        <p class="why">O <b>nome</b> aparece no topo do painel (o que vier depois do ponto ganha o degradê). Os <b>horários</b> dizem quando ele roda sozinho.</p>
        <div class="grid">
          <label class="field"><span>Nome no topo do painel</span>
            <input type="text" id="brand" value="__BRAND__" placeholder="meu.vagas"></label>
          <label class="field"><span>Horários da coleta (HH:MM, vírgula)</span>
            <input type="text" id="run_at" value="__RUNAT__" placeholder="08:00,20:00"></label>
        </div>
        <div class="bprev">
          <div class="pvtop"><span class="pvbrand" id="pvbrand"></span><span class="pvsub">12 novas · hoje</span></div>
          <div class="pvtabs"><span class="pvtab on">Vagas</span><span class="pvtab">Freelas</span><span class="pvtab">Candidaturas</span><span class="pvtab">Notas</span></div>
          <div class="pvtag">prévia fiel do topo do seu painel</div>
        </div>
      </div>

      <div class="blk">
        <h2>Alertas no Telegram <small>(opcional)</small></h2>
        <p class="why">Recebe as vagas novas no celular. Sem isso, o painel funciona igual.</p>
        <label class="field"><span>TELEGRAM_BOT_TOKEN</span><input type="password" id="tg_tok" value="__TGTOK__" placeholder="token do @BotFather"></label>
        <label class="field" style="margin-top:8px"><span>TELEGRAM_CHAT_ID</span><input type="text" id="tg_chat" value="__TGCHAT__" placeholder="clique em Detectar"></label>
        <div class="btnrow">
          <a class="lk" href="https://t.me/BotFather" target="_blank" rel="noopener">Abrir @BotFather</a>
          <button type="button" class="lk" id="tgdetect">Detectar token + chat ID</button>
        </div>
        <div class="tag" id="tgtag"></div>
        <p class="why" style="margin-top:10px;border-color:var(--line)">1) no <b>@BotFather</b> mande <code>/newbot</code> — ele te dá um token, cole acima · 2) mande um "oi" pro seu bot · 3) clique <b>Detectar</b>: pego o chat ID sozinho.</p>
      </div>

      <div class="blk">
        <h2>Vagas para PcD</h2>
        <label class="toggle"><input type="checkbox" id="pcd"__PCD__> Incluir vagas afirmativas/exclusivas para PcD</label>
        <p class="why" style="margin-top:10px;border-color:var(--line)">Por padrão o garimpeiro <b>esconde</b> vagas reservadas a PcD (Pessoa com Deficiência). Se você <b>é PcD</b>, marque pra incluí-las.</p>
      </div>

      <div class="blk">
        <h2>Onde você vê o painel</h2>
        <div class="access">
          <div class="arow"><div class="k">No próprio PC<small>roda e abre sozinho</small></div>
            <span class="url">http://localhost:8765</span>
            <button type="button" class="cpy" data-cpy="http://localhost:8765">Copiar</button></div>
          <div class="arow"><div class="k">No celular (mesma Wi-Fi)<small>abra no navegador e "Adicionar à tela inicial" (PWA)</small></div>
            <span class="url">http://__LANIP__:8765</span>
            <button type="button" class="cpy" data-cpy="http://__LANIP__:8765">Copiar</button></div>
          <div class="arow"><div class="k">De qualquer lugar (fora de casa)<small>túnel seguro, sem abrir portas</small></div>
            <a class="lk" href="https://tailscale.com/" target="_blank" rel="noopener">Tailscale</a></div>
        </div>
        <p class="why" style="margin-top:14px;border-color:var(--line)"><b>Ver fora de casa, com segurança (sem abrir portas no roteador):</b><br>
          • <b>Tailscale</b> (recomendado): rede privada criptografada entre seus aparelhos; instala no PC e no celular, login com a mesma conta, painel acessível só pra você. Grátis pra uso pessoal.<br>
          • <b>Cloudflare Tunnel</b>: endereço <code>https</code> protegido, sem expor seu IP. Passo a passo no <code>README</code>.</p>
        <div class="sec"><span>🔒</span><div><b>Por que NÃO abrir porta no roteador:</b> deixaria o painel exposto na internet pública. Tailscale/Cloudflare mantêm ele privado, só pra você.</div></div>
      </div>

      <div class="blk">
        <h2>Fontes e repositório</h2>
        <label class="toggle"><input type="checkbox" id="logadas"__LOGADAS__> Ativar fontes LOGADAS (Vagas.com/Catho/Workana/99freelas + Jobbol)</label>
        <p class="why" style="margin-top:10px;border-color:var(--line)">Públicas (Gupy, Indeed/LinkedIn/Google, Trampos) já vêm ligadas, sem login. As logadas exigem Chrome + login manual e quebram mais fácil.</p>
        <div class="sec"><span>🔒</span><div><b>Fontes logadas:</b> usam seu login real num navegador na <b>sua</b> máquina (<code>login_nodriver.py</code>). A senha não é enviada a lugar nenhum.</div></div>
        <label class="toggle"><input type="checkbox" id="headless"__HEADLESS__> Rodar escondido (sem janelas roubando o foco)</label>
        <p class="why" style="margin-top:10px;border-color:var(--line)">As fontes públicas <b>nunca</b> abrem janela. As logadas abrem um Chrome (já fora da tela). Com isto ligado, ele roda <b>headless</b> (invisível) — mais discreto, mas alguns sites podem detectar. Deixe desligado se as logadas pararem de funcionar.</p>
        <label class="field" style="margin-top:14px"><span>Repositório p/ "Reportar problema" (usuario/repo)</span>
          <input type="text" id="github_repo" value="__GITHUB__"></label>
        <p class="why" style="margin-top:8px;border-color:var(--line)">Já aponta pro projeto oficial. Trocou pro seu fork? Edite aqui (ou depois no <code>config.yaml</code>).</p>
      </div>
      <div class="err" id="err"></div>
    </section>

    <div class="nav">
      <button class="secondary" id="left">Salvar agora</button>
      <button class="primary" id="right">Personalizar →</button>
    </div>
  </div>

  <div class="card done" id="done" style="display:none">
    <h1 style="font-size:2rem">Pronto<b>.</b></h1>
    <h2 style="text-align:center">Configuração salva</h2>
    <ul id="donelist"></ul>
    <p><small class="muted">Pode fechar esta aba — o servidor já encerrou.</small></p>
  </div>
</div>
<script>
  const TOKEN="__TOKEN__";
  const $=id=>document.getElementById(id);
  const TOTAL=2; let cur=1;
  const sb=$("steps"); for(let i=0;i<TOTAL;i++){sb.appendChild(document.createElement("i"));}
  function paint(){
    document.querySelectorAll(".screen").forEach(s=>s.classList.toggle("on",+s.dataset.screen===cur));
    [...sb.children].forEach((e,i)=>{e.classList.toggle("on",i<cur);e.classList.toggle("cur",i===cur-1);});
    $("left").textContent=cur===1?"Salvar agora":"← Voltar";
    $("right").textContent=cur===1?"Personalizar →":"Salvar configuração";
    window.scrollTo(0,0);
  }
  $("left").onclick=()=>{ if(cur===1) save(); else { cur=1; paint(); } };
  $("right").onclick=()=>{ if(cur===1){ cur=2; paint(); } else save(); };

  // seletor de IA -> mostra só a caixa do provedor escolhido
  function paintAI(){const v=$("ai_provider").value;
    document.querySelectorAll(".aibox").forEach(b=>b.style.display=b.dataset.ai===v?"block":"none");}
  $("ai_provider").addEventListener("change",paintAI);paintAI();

  // país -> estados
  $("country").onchange=async function(){
    try{
      const r=await fetch("/states?country="+encodeURIComponent($("country").value));
      const j=await r.json();const sel=$("state");sel.innerHTML="";
      (j.states||[]).forEach(s=>{const o=document.createElement("option");o.value=s.code;o.textContent=s.name+" ("+s.code+")";sel.appendChild(o);});
      const o=document.createElement("option");o.value="__OUTRO__";o.textContent="Outro / não listado…";sel.appendChild(o);
      sel.onchange();
    }catch(e){}
  };
  async function carregarCidades(){
    const uf=$("state").value;const dl=$("cidlist");
    if($("country").value!=="BR"||uf==="__OUTRO__"){dl.innerHTML="";return;}
    try{
      const r=await fetch("/cities?uf="+encodeURIComponent(uf));const j=await r.json();
      dl.innerHTML=(j.cities||[]).map(c=>'<option value="'+esc(c)+'">').join("");
    }catch(e){dl.innerHTML="";}
  }
  $("state").onchange=function(){
    $("otherwrap").style.display=$("state").value==="__OUTRO__"?"block":"none";
    carregarCidades();
  };
  $("state").onchange();

  // preview fiel do nome
  function esc(s){const d=document.createElement("div");d.textContent=s;return d.innerHTML;}
  function renderBrand(){
    const v=($("brand").value||"meu.vagas");const i=v.indexOf(".");
    let a=v,b="";if(i>=0){a=v.slice(0,i);b=v.slice(i);}
    $("pvbrand").innerHTML=esc(a)+(b?'<span class="pvbrand2">'+esc(b)+'</span>':"");
  }
  $("brand").addEventListener("input",renderBrand);renderBrand();

  document.querySelectorAll(".cpy").forEach(b=>b.onclick=()=>{
    navigator.clipboard.writeText(b.dataset.cpy).then(()=>{const t=b.textContent;b.textContent="Copiado!";setTimeout(()=>b.textContent=t,1200);});
  });

  $("tgdetect").onclick=async function(){
    const tok=$("tg_tok").value.trim();const tag=$("tgtag");
    if(!tok){tag.className="tag bad";tag.textContent="Cole o token do bot primeiro.";return;}
    tag.className="tag";tag.textContent="Consultando o Telegram...";
    try{
      const r=await fetch("/tg_check",{method:"POST",headers:{"Content-Type":"application/json","X-Setup-Token":TOKEN},body:JSON.stringify({token:tok})});
      const j=await r.json();
      if(!j.ok){tag.className="tag bad";tag.textContent="✗ "+(j.erro||"falhou");return;}
      let msg="✓ Bot @"+j.bot+" válido.";
      if(j.chat_id){$("tg_chat").value=j.chat_id;msg+=" Chat ID preenchido.";}
      else{msg+=" Mande um 'oi' pro bot e clique Detectar de novo.";}
      tag.className="tag ok";tag.textContent=msg;
    }catch(e){tag.className="tag bad";tag.textContent="✗ "+e.message;}
  };

  async function save(){
    $("err").textContent="";
    const areas=[...document.querySelectorAll('input[name=area]:checked')].map(c=>c.value);
    const dados={areas:areas,extra:$("extra").value,country:$("country").value,
      state_code:$("state").value,state_other:$("state_other").value,cidade:$("cidade").value,
      remoto:$("remoto").checked,pcd:$("pcd").checked,run_at:$("run_at").value,brand:$("brand").value,
      ai_provider:$("ai_provider").value,ai_model:$("ai_model").value,ollama_host:$("ollama_host").value,
      gemini:$("gemini").value,openai_key:$("openai_key").value,anthropic_key:$("anthropic_key").value,
      tg_tok:$("tg_tok").value,tg_chat:$("tg_chat").value,
      github_repo:$("github_repo").value,logadas:$("logadas").checked,headless:$("headless").checked};
    $("right").disabled=true;$("left").disabled=true;
    try{
      const r=await fetch("/save",{method:"POST",headers:{"Content-Type":"application/json","X-Setup-Token":TOKEN},body:JSON.stringify(dados)});
      const j=await r.json();
      if(!j.ok)throw new Error(j.erro||"falhou");
      const li=[];
      li.push("<li>"+j.termos+" termos · estados: "+(j.estados&&j.estados.length?j.estados.join(", "):"—")+"</li>");
      li.push("<li>IA: "+j.ai+(j.tem_ia?"":" (sem chave → nota neutra por enquanto)")+"</li>");
      li.push("<li>Sites: "+j.sites.join(", ")+"</li>");
      li.push("<li><b>Melhore a nota:</b> rode <code>python garimpeiro.py perfil</code> e conte sobre você</li>");
      if(j.logadas)li.push("<li>Fontes logadas ON: rode <code>python login_nodriver.py</code></li>");
      li.push("<li>Depois: <code>python garimpeiro.py once</code> (testar) e <code>schedule</code> (rodar + abrir painel)</li>");
      $("donelist").innerHTML=li.join("");
      $("card").style.display="none";$("steps").style.display="none";$("done").style.display="block";window.scrollTo(0,0);
    }catch(e){
      $("err").textContent="Erro ao salvar: "+e.message;
      $("right").disabled=false;$("left").disabled=false;
    }
  }
  paint();
</script>
</body></html>"""
