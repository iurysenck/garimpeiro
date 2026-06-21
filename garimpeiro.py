#!/usr/bin/env python3
"""Garimpeiro de Vagas — CLI.

Comandos:
  python garimpeiro.py setup        # assistente no terminal (funciona via SSH/sem tela)
  python garimpeiro.py setup --web  # mesmo assistente, porém visual no navegador (local)
  python garimpeiro.py once       # roda uma coleta agora
  python garimpeiro.py serve      # serve o painel em http://localhost:8765
  python garimpeiro.py schedule   # roda nos horários do config + serve o painel
  python garimpeiro.py shortcut   # cria atalho na Área de Trabalho (+ dica p/ celular)

Sem dependências de hospedagem: por padrão tudo roda local. Fontes públicas
(Gupy/JobSpy/Trampos) não exigem login. As logadas e o painel remoto são opt-in.
"""
from __future__ import annotations

import datetime
import functools
import http.server
import socketserver
import sys
import threading
import time
from pathlib import Path

BASE = Path(__file__).resolve().parent
CONFIG = BASE / "config.yaml"
ENVFILE = BASE / ".env"
PERFIL = BASE / "perfil.md"


# ---------------------------------------------------------------- helpers de UI
def ask(msg: str, default: str = "") -> str:
    suf = f" [{default}]" if default else ""
    r = input(f"{msg}{suf}: ").strip()
    return r or default


def ask_yes(msg: str, default: bool = True) -> bool:
    d = "S/n" if default else "s/N"
    r = input(f"{msg} ({d}): ").strip().lower()
    if not r:
        return default
    return r in ("s", "sim", "y", "yes")


def titulo(t: str) -> None:
    print("\n" + "=" * 60 + f"\n  {t}\n" + "=" * 60)


# ----------------------------------------------------------------- wizard setup
def cmd_setup() -> None:
    import presets

    titulo("Garimpeiro de Vagas — Assistente de configuração")
    print("Responda as perguntas. Enter aceita o padrão entre colchetes.\n")

    # 1) Áreas
    print("Áreas disponíveis (escolha 1+ separadas por vírgula):")
    chaves = list(presets.PRESETS.keys())
    for i, k in enumerate(chaves, 1):
        print(f"  {i:2}. {k:18} {presets.PRESETS[k]['label']}")
    escolha = ask("\nNúmeros das áreas (ex: 1,3,4)", "1")
    idxs = [s.strip() for s in escolha.split(",") if s.strip()]
    nomes = []
    for s in idxs:
        if s.isdigit() and 1 <= int(s) <= len(chaves):
            nomes.append(chaves[int(s) - 1])
        elif s in presets.PRESETS:
            nomes.append(s)
    if not nomes:
        nomes = ["design"]
    bloco = presets.montar(nomes)
    extra = ask("Termos extras (vírgula, opcional)", "")
    if extra:
        for t in [x.strip() for x in extra.split(",") if x.strip()]:
            if t not in bloco["search_terms"]:
                bloco["search_terms"].append(t)
    print(f"  -> {len(bloco['search_terms'])} termos definidos.")

    # 2) Localização
    titulo("Localização")
    cidade = ask("Cidade-base (filtro/busca)", "Rio de Janeiro")
    estado = ask("Estado aceito (nome como aparece nas vagas)", cidade)
    remoto = ask_yes("Incluir vagas remotas?", True)
    brand = ask("Nome/marca no topo do painel (use '.' p/ destaque, ex: meu.vagas)", "Vagas")

    # 3) Chaves
    titulo("Chaves (vão para o .env, nunca commitado)")
    print("Gemini (IA de ranqueamento) — grátis em https://aistudio.google.com/apikey")
    gem = ask("GEMINI_API_KEY (Enter p/ pular = score neutro)", "")
    print("\nTelegram (alertas) — opcional. @BotFather pega o token, @userinfobot o chat id.")
    tg_tok = ask("TELEGRAM_BOT_TOKEN (Enter p/ pular)", "")
    tg_chat = ask("TELEGRAM_CHAT_ID (Enter p/ pular)", "") if tg_tok else ""

    # 4) Fontes
    titulo("Fontes")
    print("Públicas (sem login, sem navegador): Gupy, Indeed/LinkedIn/Google, Trampos.")
    usar_logadas = ask_yes(
        "Ativar fontes LOGADAS (Vagas.com/Catho/Workana/99freelas + Jobbol)?\n"
        "  Exigem Chrome + login manual (login_nodriver.py) e são mais frágeis", False
    )

    # 5) Modo de uso
    titulo("Como você quer rodar?")
    print("  1. Local — roda e serve o painel em http://localhost:8765 (mais simples)")
    print("  2. Local + acesso remoto — igual, + guia p/ Tailscale/Cloudflare (celular)")
    print("  3. Painel na nuvem — Cloudflare Pages/Vercel (avançado, ver README)")
    modo = ask("Modo (1/2/3)", "1")

    # ---- escreve .env
    ENVFILE.write_text(
        f"GEMINI_API_KEY={gem}\nTELEGRAM_BOT_TOKEN={tg_tok}\nTELEGRAM_CHAT_ID={tg_chat}\n",
        encoding="utf-8",
    )
    # ---- perfil
    if not PERFIL.exists():
        exemplo = BASE / "perfil.example.md"
        if exemplo.exists():
            PERFIL.write_text(exemplo.read_text(encoding="utf-8"), encoding="utf-8")

    # ---- config.yaml
    escrever_config(bloco, cidade, estado, remoto, usar_logadas, bool(tg_tok), brand)

    sites = ["Gupy", "Indeed", "LinkedIn", "Google (JobSpy)", "Trampos.co"]
    if usar_logadas:
        sites += ["Vagas.com", "Catho", "Workana", "99freelas", "Jobbol"]

    titulo("Pronto!")
    print(f"- config.yaml e .env escritos em {BASE}")
    print(f"- Sites monitorados: {', '.join(sites)}")
    print(f"- EDITE seu currículo em: {PERFIL}  (é o que a IA usa pra pontuar)")
    if usar_logadas:
        print("- Fontes logadas ON: rode 'python login_nodriver.py' e logue nos sites.")
    print("\nAgora:")
    print("  python garimpeiro.py once       # testar uma coleta")
    print("  python garimpeiro.py serve      # abrir o painel local")
    print("  python garimpeiro.py schedule   # rodar nos horários + painel")
    if modo == "2":
        print("\nAcesso remoto (celular): veja a seção Tailscale no README.md.")
    elif modo == "3":
        print("\nPainel na nuvem: veja a seção Cloudflare Pages no README.md.")


def _yaml_list(items: list[str]) -> str:
    return "\n".join(f'  - "{i}"' for i in items)


def escrever_config(
    bloco, cidade, estado, remoto, logadas, tem_tg, brand="Vagas",
    github_repo="", run_at="08:00,20:00", estados=None,
) -> None:
    # estados aceitos: lista (nome + sigla) ou, no fallback do CLI, só o texto.
    lista_estados = [s for s in (estados or [estado]) if str(s).strip()]
    if not lista_estados:
        lista_estados = [estado]
    on = "true" if logadas else "false"
    cfg = f"""# Gerado por: python garimpeiro.py setup  (edite à vontade)

# Marca exibida no topo do painel (parte após o "." ganha o gradiente).
brand: "{brand}"

search_terms:
{_yaml_list(bloco['search_terms'])}

location: "{cidade}"
location_full: "{cidade}, Brazil"
include_remote: {"true" if remoto else "false"}
accepted_states:
{_yaml_list(lista_estados)}

min_score: 6
exclude_pcd: true
exclude_title_keywords:
  - "estágio"
  - "estagiário"
  - "aprendiz"

max_per_term: 15
hours_old: 96

gemini_model: "gemini-3.1-flash-lite"
gemini_batch_size: 8

# Públicas = sem login. Logadas = exigem login_nodriver.py + Chrome.
sources:
  gupy: true
  jobspy: true
  trampos: true
  vagas_logado: {on}
  catho_logado: {on}
  workana_logado: {on}
  freelas99_logado: {on}
  jobbol: {on}

trampos_categories:
{_yaml_list(bloco['trampos_categories'] or ['design'])}
trampos_max_pages: 3

jobbol_cargos:
{_yaml_list(bloco['jobbol_cargos'] or ['designer-grafico'])}
jobbol_max_pages: 2

workana_categories:
  - "design-multimedia"
workana_max_pages: 3
freelas99_max_pages: 3
vagas_logado_max_pages: 4

jobspy_sites:
  - "indeed"
  - "linkedin"
  - "google"

# Sync/painel remoto (opcional — só p/ modo nuvem). Vazio = painel local.
tracker_csv_url: ""
applied_csv_url: ""
webapp_url: ""
sync_token: ""
painel_url: ""

# Repo GitHub (usuario/repo) p/ "Reportar problema" no painel/Telegram. Vazio = sem link.
github_repo: "{github_repo}"

# Horários do 'schedule' (HH:MM, vírgula). Padrão 2x/dia.
run_at: "{run_at}"

output:
  html: true
  html_path: "public/index.html"
  telegram: {"true" if tem_tg else "false"}
  telegram_top_n: 10
"""
    CONFIG.write_text(cfg, encoding="utf-8")


# ------------------------------------------------------------------- once/serve
def cmd_once() -> int:
    if not CONFIG.exists():
        print("Sem config.yaml. Rode primeiro: python garimpeiro.py setup")
        return 1
    import main
    return main.main()


def _serve_dir() -> Path:
    import yaml
    try:
        cfg = yaml.safe_load(CONFIG.read_text(encoding="utf-8")) or {}
        rel = cfg.get("output", {}).get("html_path", "public/index.html")
    except Exception:
        rel = "public/index.html"
    d = (BASE / rel).parent
    d.mkdir(parents=True, exist_ok=True)
    return d


def _start_server(port: int = 8765) -> None:
    diretorio = str(_serve_dir())
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=diretorio)
    socketserver.TCPServer.allow_reuse_address = True
    httpd = socketserver.TCPServer(("0.0.0.0", port), handler)
    print(f"Painel em  http://localhost:{port}   (Ctrl+C p/ parar)")
    httpd.serve_forever()


def cmd_serve() -> int:
    _start_server()
    return 0


# -------------------------------------------------------------------- schedule
def cmd_schedule() -> int:
    if not CONFIG.exists():
        print("Sem config.yaml. Rode primeiro: python garimpeiro.py setup")
        return 1
    import yaml
    cfg = yaml.safe_load(CONFIG.read_text(encoding="utf-8")) or {}
    horarios = [h.strip() for h in str(cfg.get("run_at", "08:00,20:00")).split(",") if h.strip()]
    print(f"Agendado para: {', '.join(horarios)}  (deixe rodando)")

    # serve o painel numa thread
    threading.Thread(target=_start_server, daemon=True).start()

    import main
    ja_rodou = ""  # 'YYYY-MM-DD HH:MM' do último disparo p/ não repetir no mesmo minuto
    # roda uma vez ao iniciar pra já ter painel populado
    try:
        main.main()
    except Exception as exc:  # noqa: BLE001
        print(f"erro na coleta inicial: {exc}")
    while True:
        agora = datetime.datetime.now().strftime("%H:%M")
        marca = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
        if agora in horarios and marca != ja_rodou:
            ja_rodou = marca
            print(f"[{marca}] disparando coleta agendada...")
            try:
                main.main()
            except Exception as exc:  # noqa: BLE001
                print(f"erro na coleta: {exc}")
        time.sleep(20)


def cmd_shortcut(port: int = 8765) -> int:
    """Cria um atalho na Área de Trabalho que inicia o app + abre o painel.
    No celular: o atalho é o PWA — abra o painel no navegador e 'Adicionar à tela inicial'."""
    import os

    desktop = Path(os.path.expanduser("~")) / "Desktop"
    if not desktop.exists():
        desktop = Path(os.path.expanduser("~")) / "Área de Trabalho"
    desktop.mkdir(parents=True, exist_ok=True)
    py = sys.executable
    url = f"http://localhost:{port}"

    if sys.platform.startswith("win"):
        alvo = desktop / "Garimpeiro de Vagas.bat"
        alvo.write_text(
            f'@echo off\r\ncd /d "{BASE}"\r\nstart "" {url}\r\n"{py}" garimpeiro.py schedule\r\n',
            encoding="utf-8",
        )
    elif sys.platform == "darwin":
        alvo = desktop / "Garimpeiro de Vagas.command"
        alvo.write_text(
            f'#!/bin/bash\ncd "{BASE}"\nopen {url}\n"{py}" garimpeiro.py schedule\n',
            encoding="utf-8",
        )
        os.chmod(alvo, 0o755)
    else:
        alvo = desktop / "garimpeiro-vagas.desktop"
        alvo.write_text(
            "[Desktop Entry]\nType=Application\nName=Garimpeiro de Vagas\n"
            f'Exec=bash -c \'cd "{BASE}" && (xdg-open {url} &) && "{py}" garimpeiro.py schedule\'\n'
            "Terminal=true\n",
            encoding="utf-8",
        )
        os.chmod(alvo, 0o755)

    print(f"Atalho criado: {alvo}")
    print(f"Ao abrir, ele inicia a coleta agendada e abre o painel em {url}.")
    print("\nNo CELULAR (atalho na tela inicial / PWA):")
    print(f"  1. Abra o painel no navegador do celular (mesmo Wi-Fi: http://<ip-do-pc>:{port}")
    print("     ou seu domínio, se usar modo nuvem).")
    print("  2. iPhone: botão Compartilhar -> 'Adicionar à Tela de Início'.")
    print("     Android: menu do navegador -> 'Instalar app' / 'Adicionar à tela inicial'.")
    return 0


def main_cli() -> int:
    cmd = sys.argv[1] if len(sys.argv) > 1 else "help"
    if cmd == "setup":
        if "--web" in sys.argv[2:]:
            try:
                import setup_web
            except Exception as exc:  # noqa: BLE001
                print(f"Nao consegui carregar o instalador web ({exc}). Usando o terminal.")
                cmd_setup()
                return 0
            return setup_web.run()
        cmd_setup()
        return 0
    if cmd == "once":
        return cmd_once()
    if cmd == "serve":
        return cmd_serve()
    if cmd == "schedule":
        return cmd_schedule()
    if cmd == "shortcut":
        return cmd_shortcut()
    print(__doc__)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main_cli())
    except KeyboardInterrupt:
        print("\nParado.")
