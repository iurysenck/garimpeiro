#!/usr/bin/env python3
"""Instalador web local do Garimpeiro — interface no navegador, cross-platform.

`python garimpeiro.py setup --web` sobe um servidor HTTP em 127.0.0.1 (apenas
local), abre o navegador numa página estilizada e grava `config.yaml` + `.env`.
O assistente de terminal (`setup` sem `--web`) continua como fallback universal
para servidores sem tela (Oracle/RPi/Docker/CI), mantendo tudo cross-platform.

Segurança por design:
  - Liga somente em 127.0.0.1 (nunca exposto na rede).
  - Exige um token anti-CSRF (gerado a cada execução) no cabeçalho do POST;
    como o token só existe dentro da página servida, sites externos não
    conseguem forjar o POST (não conseguem ler o token nem mandar o header).
  - Valida o cabeçalho Host (só localhost/127.0.0.1).
  - Nenhuma chamada externa; escreve apenas arquivos locais do projeto.
  - Segredos (chaves) nunca são logados no terminal.
"""
from __future__ import annotations

import http.server
import json
import secrets
import socketserver
import threading
import time
import webbrowser
from pathlib import Path

import garimpeiro as g  # BASE, CONFIG, ENVFILE, PERFIL, escrever_config
import presets

# token anti-CSRF da sessão (preenchido em run())
_TOKEN = ""


# ----------------------------------------------------------- leitura p/ prefill
def _read_env() -> dict[str, str]:
    """Lê o .env atual (se existir) para pré-preencher o formulário."""
    out: dict[str, str] = {}
    if g.ENVFILE.exists():
        for line in g.ENVFILE.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                k, _, v = line.partition("=")
                out[k.strip()] = v.strip()
    return out


def _read_cfg() -> dict:
    """Lê o config.yaml atual (se existir) para pré-preencher o formulário."""
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
        "github_repo": cfg.get("github_repo", ""),
        "run_at": cfg.get("run_at", "08:00,20:00"),
        "gemini": env.get("GEMINI_API_KEY", ""),
        "tg_tok": env.get("TELEGRAM_BOT_TOKEN", ""),
        "tg_chat": env.get("TELEGRAM_CHAT_ID", ""),
    }


# ----------------------------------------------------------------- gravação
def _salvar(dados: dict) -> dict:
    """Valida o payload do formulário e grava .env + config.yaml + perfil.md."""
    # áreas -> presets válidos
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

    # .env
    g.ENVFILE.write_text(
        f"GEMINI_API_KEY={gem}\nTELEGRAM_BOT_TOKEN={tg_tok}\nTELEGRAM_CHAT_ID={tg_chat}\n",
        encoding="utf-8",
    )
    # perfil.md a partir do exemplo, se ainda não existe
    if not g.PERFIL.exists():
        exemplo = g.BASE / "perfil.example.md"
        if exemplo.exists():
            g.PERFIL.write_text(exemplo.read_text(encoding="utf-8"), encoding="utf-8")

    # config.yaml (mesma função do wizard CLI)
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
        "config": str(g.CONFIG),
        "perfil": str(g.PERFIL),
        "logadas": logadas,
    }


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
    sel = {"design"}  # áreas começam só com design (config não guarda os nomes dos presets)
    rem = " checked" if pf["remoto"] else ""
    log = " checked" if pf["logadas"] else ""
    return (
        _PAGE.replace("__TOKEN__", token)
        .replace("__AREAS__", _areas_html(sel))
        .replace("__CIDADE__", _esc(pf["cidade"]))
        .replace("__ESTADO__", _esc(pf["estado"]))
        .replace("__BRAND__", _esc(pf["brand"]))
        .replace("__GITHUB__", _esc(pf["github_repo"]))
        .replace("__RUNAT__", _esc(pf["run_at"]))
        .replace("__GEMINI__", _esc(pf["gemini"]))
        .replace("__TGTOK__", _esc(pf["tg_tok"]))
        .replace("__TGCHAT__", _esc(pf["tg_chat"]))
        .replace("__REMOTO__", rem)
        .replace("__LOGADAS__", log)
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
            if self.path != "/save" or not self._host_ok():
                self.send_error(404)
                return
            if self.headers.get("X-Setup-Token") != _TOKEN:
                self.send_error(403, "token invalido")
                return
            try:
                n = int(self.headers.get("Content-Length", "0"))
                dados = json.loads(self.rfile.read(n).decode("utf-8") or "{}")
                res = _salvar(dados)
            except Exception as exc:  # noqa: BLE001
                self._json({"ok": False, "erro": str(exc)}, 400)
                return
            self._json(res, 200)
            # encerra o servidor logo após salvar (a página já mostrou o sucesso)
            httpd = httpd_ref.get("srv")
            if httpd:
                threading.Thread(
                    target=lambda: (time.sleep(1.0), httpd.shutdown()), daemon=True
                ).start()

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
    for p in range(port, port + 20):  # acha uma porta livre
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
    --card:rgba(255,255,255,.04);--a1:#ff3366;--a2:#6366f1;--grad:linear-gradient(135deg,#ff3366,#6366f1)}
  *{box-sizing:border-box}
  body{margin:0;background:var(--bg);color:var(--text);font-family:'Space Grotesk',system-ui,sans-serif;
    line-height:1.5;padding:32px 16px 80px}
  .glow{position:fixed;width:560px;height:560px;border-radius:50%;filter:blur(120px);opacity:.16;z-index:-1;
    background:var(--grad);top:-160px;left:-120px;pointer-events:none}
  .glow2{position:fixed;width:480px;height:480px;border-radius:50%;filter:blur(120px);opacity:.12;z-index:-1;
    background:radial-gradient(circle,#6366f1,transparent 70%);bottom:-160px;right:-120px;pointer-events:none}
  .wrap{max-width:760px;margin:0 auto}
  h1{font-family:'Syne',sans-serif;font-size:clamp(1.8rem,1rem + 3vw,2.6rem);margin:0 0 4px;letter-spacing:-.02em}
  h1 b{background:var(--grad);-webkit-background-clip:text;background-clip:text;-webkit-text-fill-color:transparent}
  .lead{color:var(--muted);margin:0 0 26px;font-size:.95rem}
  .lead code{background:rgba(255,255,255,.08);padding:1px 6px;border-radius:6px;color:var(--text)}
  .card{position:relative;border-radius:18px;padding:20px 22px;margin-bottom:16px;
    background:radial-gradient(135% 90% at 22% 0%,rgba(255,255,255,.11),rgba(255,255,255,.028) 56%);
    border:1px solid var(--line);backdrop-filter:blur(9px) saturate(1.8);-webkit-backdrop-filter:blur(9px) saturate(1.8);
    box-shadow:0 8px 30px rgba(0,0,0,.30),inset 0 1px 0 rgba(255,255,255,.22)}
  .card h2{font-family:'Syne',sans-serif;font-size:1.05rem;margin:0 0 4px}
  .card h2 small{font-weight:400;font-size:.72rem}
  .card .hint{color:var(--muted);font-size:.8rem;margin:0 0 14px}
  .grid{display:grid;grid-template-columns:1fr 1fr;gap:12px}
  @media(max-width:560px){.grid{grid-template-columns:1fr}}
  label.field{display:block;font-size:.78rem;color:var(--muted);margin-bottom:2px}
  .field span{display:block;margin-bottom:5px}
  input[type=text],input[type=password]{width:100%;background:rgba(0,0,0,.25);border:1px solid var(--line);
    border-radius:10px;color:var(--text);font:inherit;font-size:.9rem;padding:10px 12px;outline:none;transition:border-color .2s}
  input[type=text]:focus,input[type=password]:focus{border-color:var(--a2)}
  .areas{display:grid;grid-template-columns:1fr 1fr;gap:8px}
  @media(max-width:560px){.areas{grid-template-columns:1fr}}
  .opt{display:flex;align-items:baseline;gap:8px;background:rgba(0,0,0,.2);border:1px solid var(--line);
    border-radius:11px;padding:9px 11px;cursor:pointer;transition:border-color .2s,background .2s}
  .opt:hover{border-color:var(--a2)}
  .opt input{margin:0;accent-color:var(--a1)}
  .optk{font-weight:600;font-size:.82rem}
  .optl{color:var(--muted);font-size:.72rem;flex:1}
  .toggle{display:flex;align-items:center;gap:10px;font-size:.85rem;color:var(--text);cursor:pointer;margin-top:4px}
  .toggle input{width:18px;height:18px;accent-color:var(--a1)}
  .save{position:sticky;bottom:16px;width:100%;border:0;border-radius:14px;cursor:pointer;
    font-family:'Syne',sans-serif;font-weight:700;font-size:1rem;color:#fff;padding:15px;background:var(--grad);
    box-shadow:0 12px 30px rgba(99,102,241,.35);transition:transform .15s,filter .2s}
  .save:hover{transform:translateY(-2px);filter:brightness(1.08)}
  .save:disabled{opacity:.6;cursor:default;transform:none}
  .done{display:none}
  .done.on{display:block;animation:pop .3s ease}
  @keyframes pop{from{opacity:0;transform:scale(.96)}to{opacity:1;transform:none}}
  .done h2{font-family:'Syne',sans-serif;font-size:1.4rem;margin:8px 0 6px;text-align:center}
  .done ul{text-align:left;max-width:460px;margin:14px auto;color:var(--muted);font-size:.85rem;line-height:1.8}
  .done code{background:rgba(255,255,255,.08);padding:2px 7px;border-radius:6px;font-size:.82rem;color:var(--text)}
  .err{color:#ff6b75;font-size:.82rem;margin-top:8px;min-height:1em;text-align:center}
  small.muted{color:var(--muted)}
</style></head>
<body>
<div class="glow"></div><div class="glow2"></div>
<div class="wrap">
  <div id="form">
    <h1>Garimpeiro<b>.</b> setup</h1>
    <p class="lead">Preencha e clique em salvar. Grava <code>config.yaml</code> e <code>.env</code> localmente — nada sai do seu computador.</p>

    <div class="card">
      <h2>1 · O que você procura</h2>
      <p class="hint">Marque uma ou mais áreas. Elas viram os termos de busca.</p>
      <div class="areas">__AREAS__</div>
      <div style="margin-top:12px">
        <label class="field"><span>Termos extras (vírgula, opcional)</span>
          <input type="text" id="extra" placeholder="ex: brand designer, editor de vídeo"></label>
      </div>
    </div>

    <div class="card">
      <h2>2 · Onde e como aparece</h2>
      <div class="grid">
        <label class="field"><span>Cidade-base</span><input type="text" id="cidade" value="__CIDADE__"></label>
        <label class="field"><span>Estado aceito (como aparece na vaga)</span><input type="text" id="estado" value="__ESTADO__"></label>
        <label class="field"><span>Nome no topo do painel (use "." p/ destaque)</span><input type="text" id="brand" value="__BRAND__"></label>
        <label class="field"><span>Horários do schedule (HH:MM, vírgula)</span><input type="text" id="run_at" value="__RUNAT__"></label>
      </div>
      <label class="toggle" style="margin-top:12px"><input type="checkbox" id="remoto"__REMOTO__> Incluir vagas remotas</label>
    </div>

    <div class="card">
      <h2>3 · Chaves <small class="muted">(opcionais — vão só p/ o .env, nunca commitado)</small></h2>
      <p class="hint">Gemini ranqueia as vagas (grátis em aistudio.google.com/apikey). Telegram manda alertas.</p>
      <div class="grid">
        <label class="field"><span>GEMINI_API_KEY</span><input type="password" id="gemini" value="__GEMINI__" placeholder="Enter p/ pular = score neutro"></label>
        <label class="field"><span>GitHub repo p/ "Reportar problema" (usuario/repo)</span><input type="text" id="github_repo" value="__GITHUB__" placeholder="opcional"></label>
        <label class="field"><span>TELEGRAM_BOT_TOKEN</span><input type="password" id="tg_tok" value="__TGTOK__" placeholder="opcional"></label>
        <label class="field"><span>TELEGRAM_CHAT_ID</span><input type="password" id="tg_chat" value="__TGCHAT__" placeholder="opcional"></label>
      </div>
    </div>

    <div class="card">
      <h2>4 · Fontes</h2>
      <p class="hint">Públicas (Gupy, Indeed/LinkedIn/Google, Trampos) já vêm ligadas — sem login, sem navegador.</p>
      <label class="toggle"><input type="checkbox" id="logadas"__LOGADAS__> Ativar fontes LOGADAS (Vagas.com/Catho/Workana/99freelas + Jobbol)</label>
      <p class="hint" style="margin-top:8px">Exigem Chrome + login manual (<code>login_nodriver.py</code>) e são mais frágeis. Deixe desligado se não tiver certeza.</p>
    </div>

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
      li.push("<li>Agora: <code>python garimpeiro.py once</code> (testar) e <code>schedule</code> (rodar nos horários)</li>");
      $("donelist").innerHTML=li.join("");
      $("form").style.display="none";$("done").classList.add("on");
    }catch(e){
      $("err").textContent="Erro ao salvar: "+e.message;
      $("save").disabled=false;$("save").textContent="Salvar configuração";
    }
  };
</script>
</body></html>"""
