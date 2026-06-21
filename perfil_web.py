#!/usr/bin/env python3
"""Editor guiado de perfil — `python garimpeiro.py perfil`.

Abre uma página local (127.0.0.1) com perguntas simples sobre você e o trabalho
que procura, e gera o `perfil.md`. É esse texto que a IA usa pra dar a nota das
vagas — quanto mais específico, melhor o ranqueamento. Feito depois do setup,
sem pressa. Mesma postura de segurança do instalador (só local, token no POST).
"""
from __future__ import annotations

import http.server
import json
import secrets
import socketserver
import threading
import time
import webbrowser

import garimpeiro as g  # PERFIL

_TOKEN = ""

_CAMPOS = [
    ("nome", "Seu nome", "ex: Maria Silva", False),
    ("titulo", "Profissão / cargo-alvo", "ex: Designer gráfico pleno", False),
    ("sobre", "Sobre você (1 parágrafo)", "quem você é, seu estilo, o que te diferencia...", True),
    ("experiencia", "Experiência (resumo)", "anos, áreas, empresas/clientes marcantes...", True),
    ("habilidades", "Habilidades / ferramentas", "ex: branding, Figma, After Effects, social media...", True),
    ("busca", "O que você procura agora", "tipo de vaga, regime (CLT/PJ/freela), remoto, faixa salarial...", True),
    ("destaques", "Conquistas / destaques", "prêmios, projetos de impacto, números...", True),
    ("links", "Links (portfólio, LinkedIn, site)", "um por linha", True),
]


def _esc(s: str) -> str:
    return (
        str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
    )


def _compose(d: dict) -> str:
    nome = (d.get("nome") or "").strip() or "Candidato"
    titulo = (d.get("titulo") or "").strip()
    blocos = [f"# Perfil — {nome}"]
    if titulo:
        blocos.append(f"**{titulo}**")
    secoes = [
        ("Sobre", "sobre"),
        ("Experiência", "experiencia"),
        ("Habilidades", "habilidades"),
        ("O que busco", "busca"),
        ("Destaques", "destaques"),
        ("Links", "links"),
    ]
    for rotulo, chave in secoes:
        val = (d.get(chave) or "").strip()
        if val:
            blocos.append(f"## {rotulo}\n{val}")
    return "\n\n".join(blocos) + "\n"


def _salvar(d: dict) -> dict:
    texto = _compose(d)
    g.PERFIL.write_text(texto, encoding="utf-8")
    return {"ok": True, "chars": len(texto), "path": str(g.PERFIL)}


def _prefill_raw() -> str:
    if g.PERFIL.exists():
        try:
            return g.PERFIL.read_text(encoding="utf-8")
        except Exception:  # noqa: BLE001
            return ""
    return ""


def _campos_html() -> str:
    out = []
    for cid, label, ph, multi in _CAMPOS:
        if multi:
            out.append(
                f'<label class="field"><span>{_esc(label)}</span>'
                f'<textarea id="{cid}" rows="3" placeholder="{_esc(ph)}"></textarea></label>'
            )
        else:
            out.append(
                f'<label class="field"><span>{_esc(label)}</span>'
                f'<input type="text" id="{cid}" placeholder="{_esc(ph)}"></label>'
            )
    return "\n".join(out)


def build_page(token: str) -> str:
    ids = ",".join(c[0] for c in _CAMPOS)
    return (
        _PAGE.replace("__TOKEN__", token)
        .replace("__CAMPOS__", _campos_html())
        .replace("__IDS__", ids)
        .replace("__RAW__", _esc(_prefill_raw()))
    )


def _make_handler(httpd_ref: dict):
    class Handler(http.server.BaseHTTPRequestHandler):
        def _host_ok(self) -> bool:
            return (self.headers.get("Host") or "").split(":")[0] in ("localhost", "127.0.0.1", "")

        def do_GET(self):  # noqa: N802
            if not self._host_ok() or self.path.split("?")[0] not in ("/", "/index.html"):
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
            if (
                self.path != "/save"
                or not self._host_ok()
                or self.headers.get("X-Setup-Token") != _TOKEN
            ):
                self.send_error(403)
                return
            try:
                n = int(self.headers.get("Content-Length", "0"))
                d = json.loads(self.rfile.read(n).decode("utf-8") or "{}")
                self._json(_salvar(d), 200)
            except Exception as exc:  # noqa: BLE001
                self._json({"ok": False, "erro": str(exc)}, 400)
                return
            httpd = httpd_ref.get("srv")
            if httpd:
                threading.Thread(
                    target=lambda: (time.sleep(1.0), httpd.shutdown()), daemon=True
                ).start()

        def _json(self, obj: dict, code: int) -> None:
            body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_args):
            return

    return Handler


def run(port: int = 8800) -> int:
    global _TOKEN
    _TOKEN = secrets.token_urlsafe(18)
    httpd_ref: dict = {}
    socketserver.TCPServer.allow_reuse_address = True
    httpd = None
    for p in range(port, port + 20):
        try:
            httpd = socketserver.TCPServer(("127.0.0.1", p), _make_handler(httpd_ref))
            port = p
            break
        except OSError:
            continue
    if httpd is None:
        print("Nao achei porta livre. Edite perfil.md manualmente.")
        return 1
    httpd_ref["srv"] = httpd
    url = f"http://127.0.0.1:{port}/"
    print(f"Editor de perfil:  {url}  (so local; ao salvar, fecha sozinho)")
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
    print("perfil.md salvo. Rode: python garimpeiro.py once")
    return 0


_PAGE = """<!doctype html>
<html lang="pt-br"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Garimpeiro · Perfil</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@400;500;600;700&family=Syne:wght@700;800&display=swap" rel="stylesheet">
<style>
  :root{--bg:#080809;--text:#f1f1f4;--muted:#9a9aa6;--line:rgba(255,255,255,.10);--a2:#7c83ff;
    --grad:linear-gradient(180deg,#5b62e6,#4b51c9)}
  *{box-sizing:border-box;scrollbar-width:thin;scrollbar-color:rgba(124,131,255,.5) transparent}
  *::-webkit-scrollbar{width:10px}
  *::-webkit-scrollbar-thumb{background:rgba(124,131,255,.35);border-radius:8px;border:2px solid transparent;background-clip:content-box}
  body{margin:0;background:var(--bg);color:var(--text);font-family:'Space Grotesk',system-ui,sans-serif;line-height:1.5;padding:26px 16px 60px}
  .glow{position:fixed;width:460px;height:460px;border-radius:50%;filter:blur(90px);opacity:.1;z-index:-1;
    background:radial-gradient(circle,#4f46e5,transparent 70%);top:-160px;left:-120px;pointer-events:none}
  .wrap{max-width:660px;margin:0 auto}
  h1{font-family:'Syne',sans-serif;font-size:2rem;margin:0 0 4px;letter-spacing:-.02em}
  h1 b{background:var(--grad);-webkit-background-clip:text;background-clip:text;-webkit-text-fill-color:transparent}
  .lead{color:var(--muted);font-size:.9rem;margin:0 0 20px}
  .card{border-radius:18px;padding:20px 22px;border:1px solid var(--line);
    background:radial-gradient(135% 90% at 22% 0%,rgba(255,255,255,.10),rgba(255,255,255,.025) 56%);
    box-shadow:0 8px 30px rgba(0,0,0,.30),inset 0 1px 0 rgba(255,255,255,.20)}
  label.field{display:block;font-size:.78rem;color:var(--muted);margin-bottom:14px}
  .field span{display:block;margin-bottom:5px}
  input[type=text],textarea{width:100%;background:rgba(0,0,0,.25);border:1px solid var(--line);border-radius:10px;
    color:var(--text);font:inherit;font-size:.9rem;padding:10px 12px;outline:none;transition:border-color .2s;resize:vertical}
  input:focus,textarea:focus{border-color:var(--a2)}
  .save{margin-top:6px;width:100%;border:0;border-radius:12px;cursor:pointer;font-family:'Syne',sans-serif;
    font-weight:700;font-size:1rem;color:#fff;padding:14px;background:var(--grad);box-shadow:0 10px 26px rgba(99,102,241,.32)}
  .save:hover{filter:brightness(1.08)} .save:disabled{opacity:.6}
  details{margin:14px 0}
  details summary{cursor:pointer;color:var(--muted);font-size:.82rem}
  details pre{white-space:pre-wrap;background:rgba(0,0,0,.3);border:1px solid var(--line);border-radius:10px;padding:12px;font-size:.78rem;color:#cbd5cf;max-height:260px;overflow:auto}
  .err{color:#ff6b75;font-size:.82rem;margin-top:8px;text-align:center;min-height:1em}
  .done{text-align:center;display:none} .done.on{display:block}
  code{background:rgba(255,255,255,.08);padding:1px 6px;border-radius:6px;font-size:.84em}
</style></head>
<body>
<div class="glow"></div>
<div class="wrap">
  <h1>Seu perfil<b>.</b></h1>
  <p class="lead">É esse texto que a IA usa pra dar a nota das vagas. Quanto mais específico, melhor o ranqueamento. Tudo fica só no seu <code>perfil.md</code> local.</p>
  <div class="card" id="form">
    __CAMPOS__
    <details><summary>Já tenho um perfil.md — ver o texto atual</summary>
      <pre>__RAW__</pre>
      <small style="color:var(--muted)">Salvar abaixo substitui pelo conteúdo dos campos acima.</small>
    </details>
    <button class="save" id="save">Salvar perfil</button>
    <div class="err" id="err"></div>
  </div>
  <div class="card done" id="done">
    <h1 style="font-size:1.6rem">Perfil salvo<b>.</b></h1>
    <p class="lead" style="text-align:center">Agora rode <code>python garimpeiro.py once</code> pra ver o ranqueamento. Pode fechar esta aba.</p>
  </div>
</div>
<script>
  const TOKEN="__TOKEN__";const IDS="__IDS__".split(",");
  document.getElementById("save").onclick=async function(){
    const b=this;b.disabled=true;b.textContent="Salvando...";document.getElementById("err").textContent="";
    const d={};IDS.forEach(id=>{const el=document.getElementById(id);if(el)d[id]=el.value;});
    try{
      const r=await fetch("/save",{method:"POST",headers:{"Content-Type":"application/json","X-Setup-Token":TOKEN},body:JSON.stringify(d)});
      const j=await r.json();if(!j.ok)throw new Error(j.erro||"falhou");
      document.getElementById("form").style.display="none";document.getElementById("done").classList.add("on");window.scrollTo(0,0);
    }catch(e){document.getElementById("err").textContent="Erro: "+e.message;b.disabled=false;b.textContent="Salvar perfil";}
  };
</script>
</body></html>"""
