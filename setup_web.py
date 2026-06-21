#!/usr/bin/env python3
"""Instalador web local do Garimpeiro — interface no navegador, cross-platform.

`python garimpeiro.py setup --web` sobe um servidor HTTP em 127.0.0.1 (apenas
local), abre o navegador numa página guiada e grava `config.yaml` + `.env`.
O assistente de terminal (`setup` sem `--web`) continua como fallback universal
para servidores sem tela (Oracle/RPi/Docker/CI), mantendo tudo cross-platform.

Segurança por design:
  - Liga somente em 127.0.0.1 (nunca exposto na rede).
  - Exige um token anti-CSRF (gerado a cada execução) no cabeçalho do POST;
    como o token só existe dentro da página servida, sites externos não
    conseguem forjar o POST.
  - Valida o cabeçalho Host (só localhost/127.0.0.1).
  - A única chamada externa possível é o "Detectar Telegram" — opcional, sob
    clique, usando o token do próprio usuário p/ achar o chat_id. Nada mais sai.
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
import urllib.parse
import urllib.request
import webbrowser

import garimpeiro as g  # BASE, CONFIG, ENVFILE, PERFIL, escrever_config
import presets

# Repo oficial p/ "Reportar problema". O usuário pode trocar pelo fork dele no
# instalador (campo editável) ou depois no config.yaml (chave github_repo).
DEFAULT_REPO = "iuryart/garimpeiro"

# token anti-CSRF da sessão (preenchido em run())
_TOKEN = ""


# --------------------------------------------------------------- util de rede
def _lan_ip() -> str:
    """IP do PC na rede local (p/ abrir o painel no celular). Sem tráfego real."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))  # só resolve a rota; UDP não envia pacote
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:  # noqa: BLE001
        return "127.0.0.1"


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


def _prefill() -> dict:
    cfg = _read_cfg()
    env = _read_env()
    src = cfg.get("sources", {}) if isinstance(cfg.get("sources"), dict) else {}
    estados = cfg.get("accepted_states") or [""]
    return {
        "cidade": cfg.get("location", "Rio de Janeiro"),
        "estado": estados[0] if estados else "Rio de Janeiro",
        "remoto": bool(cfg.get("include_remote", True)),
        "brand": cfg.get("brand", "Vagas"),
        "logadas": bool(src.get("vagas_logado") or src.get("catho_logado") or src.get("jobbol")),
        "github_repo": cfg.get("github_repo") or DEFAULT_REPO,
        "run_at": cfg.get("run_at", "08:00,20:00"),
        "gemini": env.get("GEMINI_API_KEY", ""),
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

    cidade = (dados.get("cidade") or "Rio de Janeiro").strip()
    estado = (dados.get("estado") or cidade).strip()
    remoto = bool(dados.get("remoto", True))
    brand = (dados.get("brand") or "Vagas").strip()
    logadas = bool(dados.get("logadas", False))
    github_repo = (dados.get("github_repo") or "").strip().strip("/")
    run_at = (dados.get("run_at") or "08:00,20:00").strip()

    gem = (dados.get("gemini") or "").strip()
    tg_tok = (dados.get("tg_tok") or "").strip()
    tg_chat = (dados.get("tg_chat") or "").strip() if tg_tok else ""

    g.ENVFILE.write_text(
        f"GEMINI_API_KEY={gem}\nTELEGRAM_BOT_TOKEN={tg_tok}\nTELEGRAM_CHAT_ID={tg_chat}\n",
        encoding="utf-8",
    )
    if not g.PERFIL.exists():
        exemplo = g.BASE / "perfil.example.md"
        if exemplo.exists():
            g.PERFIL.write_text(exemplo.read_text(encoding="utf-8"), encoding="utf-8")

    g.escrever_config(
        bloco, cidade, estado, remoto, logadas, bool(tg_tok), brand,
        github_repo=github_repo, run_at=run_at,
    )

    sites = ["Gupy", "Indeed", "LinkedIn", "Google (JobSpy)", "Trampos.co"]
    if logadas:
        sites += ["Vagas.com", "Catho", "Workana", "99freelas", "Jobbol"]
    return {
        "ok": True,
        "sites": sites,
        "termos": len(bloco["search_terms"]),
        "logadas": logadas,
    }


# ----------------------------------------------- helper opcional do Telegram
def _tg_check(token: str) -> dict:
    """Valida o token do bot e tenta achar o chat_id da última mensagem recebida.

    Chamada externa ÚNICA do instalador, sob clique do usuário, com o token do
    próprio bot dele. O token é codificado na URL p/ evitar injeção no path.
    """
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
    linhas = []
    for nome, p in presets.PRESETS.items():
        chk = " checked" if nome in selecionadas else ""
        linhas.append(
            f'<label class="opt"><input type="checkbox" name="area" value="{_esc(nome)}"{chk}>'
            f'<span class="optk">{_esc(nome)}</span><span class="optl">{_esc(p["label"])}</span></label>'
        )
    return "\n".join(linhas)


def build_page(token: str) -> str:
    pf = _prefill()
    return (
        _PAGE.replace("__TOKEN__", token)
        .replace("__AREAS__", _areas_html({"design"}))
        .replace("__CIDADE__", _esc(pf["cidade"]))
        .replace("__ESTADO__", _esc(pf["estado"]))
        .replace("__BRAND__", _esc(pf["brand"]))
        .replace("__GITHUB__", _esc(pf["github_repo"]))
        .replace("__RUNAT__", _esc(pf["run_at"]))
        .replace("__GEMINI__", _esc(pf["gemini"]))
        .replace("__TGTOK__", _esc(pf["tg_tok"]))
        .replace("__TGCHAT__", _esc(pf["tg_chat"]))
        .replace("__LANIP__", _esc(_lan_ip()))
        .replace("__REMOTO__", " checked" if pf["remoto"] else "")
        .replace("__LOGADAS__", " checked" if pf["logadas"] else "")
    )


# --------------------------------------------------------------------- servidor
def _make_handler(httpd_ref: dict):
    class Handler(http.server.BaseHTTPRequestHandler):
        def _host_ok(self) -> bool:
            host = (self.headers.get("Host") or "").split(":")[0]
            return host in ("localhost", "127.0.0.1", "")

        def _body(self) -> dict:
            n = int(self.headers.get("Content-Length", "0"))
            return json.loads(self.rfile.read(n).decode("utf-8") or "{}")

        def do_GET(self):  # noqa: N802
            if not self._host_ok():
                self.send_error(403)
                return
            if self.path.split("?")[0] not in ("/", "/index.html"):
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
                dados = self._body()
                if self.path == "/tg_check":
                    self._json(_tg_check(dados.get("token", "")), 200)
                    return
                if self.path == "/save":
                    res = _salvar(dados)
                    self._json(res, 200)
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
            body = json.dumps(obj).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_args):  # silencia logs (evita vazar querystrings/segredos)
            return

    return Handler


def run(port: int = 8799) -> int:
    """Sobe o instalador web em 127.0.0.1 e abre o navegador. Bloqueia até salvar."""
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
    print("Instalador encerrado. Proximo: python garimpeiro.py once")
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
  :root{--bg:#050505;--text:#f4f4f5;--muted:#a1a1aa;--line:rgba(255,255,255,.12);
    --a1:#ff3366;--a2:#6366f1;--grad:linear-gradient(135deg,#ff3366,#6366f1)}
  *{box-sizing:border-box}
  body{margin:0;background:var(--bg);color:var(--text);font-family:'Space Grotesk',system-ui,sans-serif;
    line-height:1.5;padding:28px 16px 90px}
  .glow{position:fixed;width:560px;height:560px;border-radius:50%;filter:blur(120px);opacity:.16;z-index:-1;
    background:var(--grad);top:-160px;left:-120px;pointer-events:none}
  .glow2{position:fixed;width:480px;height:480px;border-radius:50%;filter:blur(120px);opacity:.12;z-index:-1;
    background:radial-gradient(circle,#6366f1,transparent 70%);bottom:-160px;right:-120px;pointer-events:none}
  .wrap{max-width:740px;margin:0 auto}
  .top{display:flex;justify-content:space-between;align-items:flex-start;gap:12px;margin-bottom:4px}
  h1{font-family:'Syne',sans-serif;font-size:clamp(1.7rem,1rem + 3vw,2.5rem);margin:0;letter-spacing:-.02em}
  h1 b{background:var(--grad);-webkit-background-clip:text;background-clip:text;-webkit-text-fill-color:transparent}
  .lead{color:var(--muted);margin:2px 0 18px;font-size:.92rem}
  .lead code{background:rgba(255,255,255,.08);padding:1px 6px;border-radius:6px;color:var(--text)}
  /* toggle discreto do guia */
  .guidetog{display:inline-flex;align-items:center;gap:7px;cursor:pointer;white-space:nowrap;
    font-size:.78rem;color:var(--muted);border:1px solid var(--line);border-radius:999px;padding:6px 11px;
    background:rgba(255,255,255,.03);transition:border-color .2s,color .2s}
  .guidetog:hover{border-color:var(--a2);color:var(--text)}
  .guidetog input{width:15px;height:15px;accent-color:var(--a1);margin:0}
  .help{display:none;border-left:2px solid var(--a2);background:rgba(99,102,241,.07);
    border-radius:0 10px 10px 0;padding:9px 12px;margin:8px 0 2px;font-size:.8rem;color:var(--muted);line-height:1.6}
  body.guide .help{display:block;animation:fade .25s ease}
  @keyframes fade{from{opacity:0}to{opacity:1}}
  .help b{color:var(--text)}
  .help ol{margin:6px 0 0;padding-left:18px} .help li{margin:3px 0}
  .card{position:relative;border-radius:18px;padding:18px 20px;margin-bottom:14px;
    background:radial-gradient(135% 90% at 22% 0%,rgba(255,255,255,.11),rgba(255,255,255,.028) 56%);
    border:1px solid var(--line);backdrop-filter:blur(9px) saturate(1.8);-webkit-backdrop-filter:blur(9px) saturate(1.8);
    box-shadow:0 8px 30px rgba(0,0,0,.30),inset 0 1px 0 rgba(255,255,255,.22)}
  .card h2{font-family:'Syne',sans-serif;font-size:1.02rem;margin:0 0 3px}
  .card h2 small{font-weight:400;font-size:.72rem;color:var(--muted)}
  .card .hint{color:var(--muted);font-size:.8rem;margin:0 0 12px}
  .grid{display:grid;grid-template-columns:1fr 1fr;gap:12px}
  @media(max-width:560px){.grid{grid-template-columns:1fr}}
  label.field{display:block;font-size:.78rem;color:var(--muted);margin-bottom:2px}
  .field span{display:block;margin-bottom:5px}
  input[type=text],input[type=password]{width:100%;background:rgba(0,0,0,.25);border:1px solid var(--line);
    border-radius:10px;color:var(--text);font:inherit;font-size:.9rem;padding:10px 12px;outline:none;transition:border-color .2s}
  input:focus{border-color:var(--a2)}
  .areas{display:grid;grid-template-columns:1fr 1fr;gap:8px}
  @media(max-width:560px){.areas{grid-template-columns:1fr}}
  .opt{display:flex;align-items:baseline;gap:8px;background:rgba(0,0,0,.2);border:1px solid var(--line);
    border-radius:11px;padding:8px 11px;cursor:pointer;transition:border-color .2s,background .2s}
  .opt:hover{border-color:var(--a2)}
  .opt input{margin:0;accent-color:var(--a1)}
  .optk{font-weight:600;font-size:.8rem}
  .optl{color:var(--muted);font-size:.7rem;flex:1}
  .toggle{display:flex;align-items:center;gap:10px;font-size:.85rem;color:var(--text);cursor:pointer;margin-top:6px}
  .toggle input{width:18px;height:18px;accent-color:var(--a1)}
  .btnrow{display:flex;flex-wrap:wrap;gap:8px;margin-top:8px}
  .lk{display:inline-flex;align-items:center;gap:6px;text-decoration:none;font-size:.78rem;color:var(--text);
    border:1px solid var(--line);border-radius:9px;padding:7px 12px;background:rgba(255,255,255,.04);transition:border-color .2s}
  .lk:hover{border-color:var(--a2)}
  .lk.brand{border-color:transparent;background:var(--grad);font-weight:600}
  .tag{font-size:.74rem;color:var(--muted);margin-top:6px;min-height:1em}
  .tag.ok{color:#34d399} .tag.bad{color:#ff6b75}
  details{margin-bottom:14px;border:1px solid var(--line);border-radius:14px;background:rgba(255,255,255,.02)}
  details>summary{cursor:pointer;padding:13px 18px;font-family:'Syne',sans-serif;font-size:.95rem;list-style:none}
  details>summary::-webkit-details-marker{display:none}
  details>summary::before{content:"＋ ";color:var(--a2)}
  details[open]>summary::before{content:"－ "}
  details .inner{padding:0 18px 16px}
  .access{display:flex;flex-direction:column;gap:10px}
  .arow{display:flex;align-items:center;justify-content:space-between;gap:10px;flex-wrap:wrap;
    border-top:1px solid rgba(255,255,255,.06);padding-top:10px}
  .arow:first-child{border-top:0;padding-top:0}
  .arow .k{font-size:.82rem;font-weight:600}
  .arow .k small{display:block;color:var(--muted);font-weight:400;font-size:.72rem}
  .url{font-family:ui-monospace,Menlo,monospace;font-size:.82rem;background:rgba(0,0,0,.3);
    border:1px solid var(--line);border-radius:8px;padding:6px 10px;color:var(--text)}
  .cpy{cursor:pointer;border:1px solid var(--line);background:rgba(255,255,255,.04);color:var(--text);
    border-radius:8px;padding:6px 10px;font:inherit;font-size:.76rem}
  .cpy:hover{border-color:var(--a2)}
  .save{position:sticky;bottom:14px;width:100%;border:0;border-radius:14px;cursor:pointer;
    font-family:'Syne',sans-serif;font-weight:700;font-size:1rem;color:#fff;padding:15px;background:var(--grad);
    box-shadow:0 12px 30px rgba(99,102,241,.35);transition:transform .15s,filter .2s}
  .save:hover{transform:translateY(-2px);filter:brightness(1.08)}
  .save:disabled{opacity:.6;cursor:default;transform:none}
  .done{display:none}
  .done.on{display:block;animation:pop .3s ease}
  @keyframes pop{from{opacity:0;transform:scale(.96)}to{opacity:1;transform:none}}
  .done h2{font-family:'Syne',sans-serif;font-size:1.4rem;margin:8px 0 6px;text-align:center}
  .done ul{text-align:left;max-width:470px;margin:14px auto;color:var(--muted);font-size:.85rem;line-height:1.8}
  .done code{background:rgba(255,255,255,.08);padding:2px 7px;border-radius:6px;font-size:.82rem;color:var(--text)}
  .err{color:#ff6b75;font-size:.82rem;margin-top:8px;min-height:1em;text-align:center}
  small.muted{color:var(--muted)}
</style></head>
<body>
<div class="glow"></div><div class="glow2"></div>
<div class="wrap">
  <div id="form">
    <div class="top">
      <h1>Garimpeiro<b>.</b> setup</h1>
      <label class="guidetog"><input type="checkbox" id="guide"> Mostrar explicações</label>
    </div>
    <p class="lead">Marque suas áreas e clique em salvar — o resto tem padrão pronto. Grava <code>config.yaml</code> e <code>.env</code> só no seu computador.</p>

    <div class="card">
      <h2>1 · O que você procura</h2>
      <p class="hint">Marque uma ou mais áreas.</p>
      <div class="help">Cada área vira uma lista de <b>termos de busca</b> nos sites. Pode marcar várias e ainda somar termos próprios no campo abaixo (ex.: um nicho específico seu).</div>
      <div class="areas">__AREAS__</div>
      <div style="margin-top:12px">
        <label class="field"><span>Termos extras (vírgula, opcional)</span>
          <input type="text" id="extra" placeholder="ex: brand designer, editor de vídeo"></label>
      </div>
    </div>

    <div class="card">
      <h2>2 · Localização e nome</h2>
      <div class="help">A <b>cidade</b> filtra vagas presenciais; <b>remotas</b> entram de qualquer lugar se marcado. O <b>nome</b> aparece no topo do painel — o que vier depois do ponto ganha o degradê (ex.: <code>meu.vagas</code>).</div>
      <div class="grid">
        <label class="field"><span>Cidade-base</span><input type="text" id="cidade" value="__CIDADE__"></label>
        <label class="field"><span>Nome no topo do painel</span><input type="text" id="brand" value="__BRAND__"></label>
      </div>
      <label class="toggle"><input type="checkbox" id="remoto"__REMOTO__> Incluir vagas remotas</label>
    </div>

    <div class="card">
      <h2>3 · Chaves <small>(opcionais — pode pular e preencher depois)</small></h2>
      <p class="hint">Vão só pro <code>.env</code>, que nunca é enviado a lugar nenhum.</p>

      <label class="field" style="margin-top:6px"><span>GEMINI_API_KEY — a IA que ranqueia as vagas</span>
        <input type="password" id="gemini" value="__GEMINI__" placeholder="cole aqui (vazio = todas com score neutro)"></label>
      <div class="btnrow">
        <a class="lk brand" href="https://aistudio.google.com/apikey" target="_blank" rel="noopener">Pegar chave Gemini (grátis)</a>
      </div>
      <div class="help"><b>Como pegar (1 min):</b><ol>
        <li>Abra o botão acima e entre com sua conta Google.</li>
        <li>Clique em <b>Create API key</b> → <b>Create in new project</b>.</li>
        <li>Copie a chave e cole no campo. Pronto. É de graça no nível gratuito.</li></ol></div>

      <label class="field" style="margin-top:14px"><span>TELEGRAM_BOT_TOKEN — alertas no seu celular</span>
        <input type="password" id="tg_tok" value="__TGTOK__" placeholder="cole o token do BotFather (opcional)"></label>
      <label class="field" style="margin-top:8px"><span>TELEGRAM_CHAT_ID</span>
        <input type="text" id="tg_chat" value="__TGCHAT__" placeholder="clique em Detectar p/ preencher sozinho"></label>
      <div class="btnrow">
        <a class="lk" href="https://t.me/BotFather" target="_blank" rel="noopener">Abrir @BotFather</a>
        <button type="button" class="lk" id="tgdetect">Detectar token + chat ID</button>
      </div>
      <div class="tag" id="tgtag"></div>
      <div class="help"><b>Bem mais fácil assim:</b><ol>
        <li>Abra o <b>@BotFather</b>, mande <code>/newbot</code> e siga (dá um nome). Ele devolve um <b>token</b> — cole no campo de cima.</li>
        <li>Abra a conversa do <b>seu</b> bot recém-criado e mande qualquer "oi".</li>
        <li>Volte aqui e clique <b>Detectar</b>: eu valido o token e pego o seu <b>chat ID</b> automaticamente.</li></ol>
        Sem Telegram? Deixe vazio — os alertas só não chegam, o painel funciona igual.</div>
    </div>

    <div class="card">
      <h2>4 · Onde você vê o painel</h2>
      <p class="hint">Prioridade: abrir no PC e no celular. Escolha conforme a necessidade — nada aqui precisa ser preenchido.</p>
      <div class="access">
        <div class="arow">
          <div class="k">No próprio PC<small>roda e abre sozinho</small></div>
          <span class="url">http://localhost:8765</span>
          <button type="button" class="cpy" data-cpy="http://localhost:8765">Copiar</button>
        </div>
        <div class="arow">
          <div class="k">No celular (mesma Wi-Fi)<small>abra no navegador do celular e "Adicionar à tela inicial"</small></div>
          <span class="url" id="lanurl">http://__LANIP__:8765</span>
          <button type="button" class="cpy" id="cpylan" data-cpy="http://__LANIP__:8765">Copiar</button>
        </div>
        <div class="arow">
          <div class="k">De qualquer lugar (fora de casa)<small>túnel seguro — sem abrir portas</small></div>
          <a class="lk" href="https://tailscale.com/" target="_blank" rel="noopener">Tailscale</a>
        </div>
      </div>
      <div class="help"><b>Detalhe de cada um:</b><ol>
        <li><b>PC:</b> <code>python garimpeiro.py schedule</code> já serve o painel e roda nos horários.</li>
        <li><b>Celular na mesma rede:</b> use o endereço com o IP do seu PC (já preenchido). Instale como app pelo "Adicionar à tela inicial" — vira um PWA.</li>
        <li><b>De qualquer lugar:</b> Tailscale (VPN pessoal, grátis) ou Cloudflare Tunnel dão um endereço fixo sem expor sua casa. Passo a passo no README.</li></ol></div>
    </div>

    <details>
      <summary>Opções avançadas</summary>
      <div class="inner">
        <div class="grid">
          <label class="field"><span>Estado aceito (como aparece na vaga)</span><input type="text" id="estado" value="__ESTADO__"></label>
          <label class="field"><span>Horários do schedule (HH:MM, vírgula)</span><input type="text" id="run_at" value="__RUNAT__"></label>
          <label class="field"><span>Repo p/ "Reportar problema" (usuario/repo)</span><input type="text" id="github_repo" value="__GITHUB__"></label>
        </div>
        <div class="help"><b>Repo de issues:</b> já vem apontando pro repositório oficial do Garimpeiro, p/ você mandar bugs/sugestões. Trocou pro seu fork? É só editar aqui (ou depois no <code>config.yaml</code>, chave <code>github_repo</code>).</div>
        <label class="toggle" style="margin-top:14px"><input type="checkbox" id="logadas"__LOGADAS__> Ativar fontes LOGADAS (Vagas.com/Catho/Workana/99freelas + Jobbol)</label>
        <div class="help">Públicas (Gupy, Indeed/LinkedIn/Google, Trampos) já vêm ligadas — sem login. As <b>logadas</b> exigem Chrome + login manual (<code>login_nodriver.py</code>) e quebram mais fácil. Deixe desligado se estiver começando.</div>
      </div>
    </details>

    <button class="save" id="save">Salvar configuração</button>
    <div class="err" id="err"></div>
  </div>

  <div class="done card" id="done">
    <h1 style="font-size:2rem;text-align:center">Pronto<b>.</b></h1>
    <h2>Configuração salva</h2>
    <ul id="donelist"></ul>
    <p style="text-align:center"><small class="muted">Pode fechar esta aba — o servidor já encerrou.</small></p>
  </div>
</div>
<script>
  const TOKEN="__TOKEN__";
  const $=id=>document.getElementById(id);
  $("guide").onchange=e=>document.body.classList.toggle("guide",e.target.checked);

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
      else{msg+=" Mande um 'oi' pro bot e clique Detectar de novo p/ pegar o chat ID.";}
      tag.className="tag ok";tag.textContent=msg;
    }catch(e){tag.className="tag bad";tag.textContent="✗ "+e.message;}
  };

  $("save").onclick=async function(){
    $("err").textContent="";
    const areas=[...document.querySelectorAll('input[name=area]:checked')].map(c=>c.value);
    const dados={areas:areas,extra:$("extra").value,cidade:$("cidade").value,estado:$("estado").value,
      brand:$("brand").value,run_at:$("run_at").value,remoto:$("remoto").checked,
      gemini:$("gemini").value,github_repo:$("github_repo").value,
      tg_tok:$("tg_tok").value,tg_chat:$("tg_chat").value,logadas:$("logadas").checked};
    $("save").disabled=true;$("save").textContent="Salvando...";
    try{
      const r=await fetch("/save",{method:"POST",headers:{"Content-Type":"application/json","X-Setup-Token":TOKEN},body:JSON.stringify(dados)});
      const j=await r.json();
      if(!j.ok)throw new Error(j.erro||"falhou");
      const li=[];
      li.push("<li>"+j.termos+" termos de busca definidos</li>");
      li.push("<li>Sites monitorados: "+j.sites.join(", ")+"</li>");
      li.push("<li>config.yaml e .env escritos no projeto</li>");
      li.push("<li>Edite seu currículo em <code>perfil.md</code> — é o que a IA usa p/ pontuar</li>");
      if(j.logadas)li.push("<li>Fontes logadas ON: rode <code>python login_nodriver.py</code> e logue nos sites</li>");
      li.push("<li>Agora: <code>python garimpeiro.py once</code> (testar) e <code>schedule</code> (rodar + abrir painel)</li>");
      $("donelist").innerHTML=li.join("");
      $("form").style.display="none";$("done").classList.add("on");window.scrollTo(0,0);
    }catch(e){
      $("err").textContent="Erro ao salvar: "+e.message;
      $("save").disabled=false;$("save").textContent="Salvar configuração";
    }
  };
</script>
</body></html>"""
