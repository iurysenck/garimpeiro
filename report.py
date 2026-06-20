"""Saída: painel HTML (abas, cards, filtros, arquivar, aplicados, notas) + Telegram.

Design: dark editorial, Syne + Space Grotesk, accent #ff3366 → #6366f1 (personalizável).
Ícones via Lucide (igual ao portfólio). Arquivar/Aplicados/Notas cross-device
(Web App do .gs) com localStorage de fallback. Swipe lateral troca de aba.
"""
from __future__ import annotations

import datetime
import hashlib
import html
import json
import os

from sources import Job

FOLLOWUP_DIAS = 7  # candidatura parada há mais que isso (sem resposta) = cutucar

import requests

_TG_API = "https://api.telegram.org/bot{token}/sendMessage"
_TG_LIMIT = 3800

# chips de área: (slug, ícone lucide, rótulo)
AREA_CHIPS = [
    ("design", "palette", "Design"),
    ("social", "megaphone", "Social"),
    ("foto", "camera", "Foto"),
    ("video", "clapperboard", "Vídeo"),
    ("web", "code", "Web"),
]


def _ic(name: str) -> str:
    return f'<i data-lucide="{name}"></i>'


def _brand_html(brand: str) -> str:
    """Marca: tudo antes do 1º '.' normal, o resto em gradiente (negrito)."""
    b = html.escape(brand or "Vagas")
    if "." in b:
        a, resto = b.split(".", 1)
        return f"{a}<b>.{resto}</b>"
    return f"<b>{b}</b>"


def _fmt_data(iso: str) -> str:
    p = (iso or "").split("-")
    return f"{p[2]}/{p[1]}/{p[0]}" if len(p) == 3 and len(p[0]) == 4 else (iso or "")


def _badge_color(score: int) -> str:
    if score >= 9:
        return "#22c55e"
    if score >= 7:
        return "#84cc16"
    if score >= 6:
        return "#eab308"
    return "#6b7280"


def _status_cor(status: str) -> str:
    s = status.upper()
    if "REJEIT" in s:
        return "#ef4444"
    if "AVAN" in s or "AÇÃO" in s or "ACAO" in s:
        return "#22c55e"
    return "#eab308"


def _area(job: Job) -> str:
    t = f"{job.title} {job.description}".lower()
    if any(k in t for k in ("social media", "mídias", "midias", "community")):
        return "social"
    if "fotógraf" in t or "fotograf" in t:
        return "foto"
    if any(
        k in t
        for k in ("vídeo", "video", "filmmaker", "videomaker", "cinegraf",
                  "motion", "audiovisual", "rtv", "filme")
    ):
        return "video"
    if any(k in t for k in ("web", "front", "landing", "ui/", "ux")):
        return "web"
    if any(k in t for k in ("finalista", "finaliz", "impress")):
        return "finalista"
    if any(
        k in t
        for k in ("design", "diretor de arte", "branding", "identidade",
                  "comunicação visual", "arte")
    ):
        return "design"
    return "outros"


def _vaga_card(job: Job, is_new: bool, is_applied: bool, kind: str = "vaga") -> str:
    e = html.escape
    cor = _badge_color(job.score)
    loc = (job.location or "").lower()
    rj = "1" if "rio de janeiro" in loc or "/rj" in loc else "0"
    busca = e(f"{job.title} {job.company} {job.resumo} {job.source}".lower())
    novo = '<span class="tag novo">novo</span>' if is_new else ""
    remoto = f' · {_ic("house")} remoto' if job.remote else ""
    dica = f'<p class="dica">{_ic("lightbulb")} {e(job.dica)}</p>' if job.dica else ""
    motivo = f'<p class="motivo">{e(job.motivo)}</p>' if job.motivo else ""
    resumo = f'<p class="resumo">{e(job.resumo)}</p>' if job.resumo else ""
    pitch_attr = f' data-pitch="{e(job.pitch)}"' if job.pitch else ""
    pitch_btn = (
        f'<button class="btn-sec pitchbtn" data-uid="{job.uid}">{_ic("clipboard-pen")} '
        f'<span class="plbl">Copiar pitch</span></button>'
        if job.pitch
        else ""
    )
    return f"""
      <article class="card" data-kind="{kind}" data-uid="{job.uid}" data-applied="{'1' if is_applied else '0'}"
        data-remote="{'1' if job.remote else '0'}" data-rj="{rj}" data-area="{_area(job)}"
        data-source="{e(job.source)}" data-text="{busca}"{pitch_attr}>
        <div class="card-head">
          <span class="badge" style="background:{cor}">{job.score}</span>
          <h3 class="title"><a href="{e(job.url)}" target="_blank" rel="noopener">{e(job.title) or '(sem título)'}</a></h3>
          <button class="fav" data-uid="{job.uid}" title="Favoritar" aria-label="Favoritar">{_ic("star")}</button>
          <button class="arch" data-uid="{job.uid}" title="Arquivar">{_ic("x")}</button>
        </div>
        <p class="meta">{_ic("building-2")} {e(job.company)} · {_ic("map-pin")} {e(job.location) or '—'}{remoto}</p>
        <div class="tags">{novo}</div>
        <details class="det"><summary>ver detalhes</summary>
          {resumo}{dica}{motivo}
          <p class="srcline">{e(job.source)} · {_fmt_data(job.posted)}</p>
        </details>
        <div class="card-actions">
          <button class="aplicar aplbtn" data-uid="{job.uid}">{_ic("check")} <span class="albl">Já apliquei</span></button>
          {pitch_btn}
        </div>
      </article>"""


def _cand_uid(c: dict) -> str:
    base = f"{c['empresa']}|{c['vaga']}|{c['data']}".lower()
    return "c" + hashlib.sha1(base.encode("utf-8")).hexdigest()[:15]


def _cand_idade_dias(data_str: str) -> int | None:
    """Idade em dias de uma candidatura (data DD/MM/YYYY). None se sem data válida."""
    p = (data_str or "").strip().split("/")
    if len(p) != 3:
        return None
    try:
        d = datetime.date(int(p[2]), int(p[1]), int(p[0]))
    except (ValueError, IndexError):
        return None
    return (datetime.date.today() - d).days


def _cand_terminal(status: str) -> bool:
    """Status que encerra o acompanhamento (não precisa de follow-up)."""
    s = (status or "").upper()
    return "REJEIT" in s or "AVAN" in s or "CONTRAT" in s


def _cand_precisa_followup(c: dict) -> bool:
    idade = _cand_idade_dias(c.get("data", ""))
    return idade is not None and idade >= FOLLOWUP_DIAS and not _cand_terminal(c.get("status", ""))


def _funil_candidaturas(cands: list[dict]) -> str:
    """Resumo em pílulas: total, em análise, avançaram, rejeitadas, a cutucar."""
    total = len(cands)
    avancou = sum(1 for c in cands if "AVAN" in c["status"].upper() or "CONTRAT" in c["status"].upper())
    rejeit = sum(1 for c in cands if "REJEIT" in c["status"].upper())
    analise = total - avancou - rejeit
    cutucar = sum(1 for c in cands if _cand_precisa_followup(c))
    pills = [
        (_ic("layers"), "Total", total, "var(--muted)"),
        (_ic("hourglass"), "Em análise", analise, "#eab308"),
        (_ic("trending-up"), "Avançaram", avancou, "#22c55e"),
        (_ic("x-circle"), "Rejeitadas", rejeit, "#ef4444"),
    ]
    if cutucar:
        pills.append((_ic("bell-ring"), "Cutucar", cutucar, "var(--accent)"))
    cells = "".join(
        f'<div class="fcell"><span class="fnum" style="color:{cor}">{n}</span>'
        f'<span class="flbl">{ic} {lbl}</span></div>'
        for ic, lbl, n, cor in pills
    )
    return f'<div class="funil">{cells}</div>'


def _cand_card(c: dict) -> str:
    e = html.escape
    cor = _status_cor(c["status"])
    idade = _cand_idade_dias(c.get("data", ""))
    followup = (
        f'<span class="tag follow">{_ic("bell-ring")} cutucar · {idade}d</span>'
        if _cand_precisa_followup(c)
        else ""
    )
    acao = (
        f'<p class="acao">{_ic("alert-triangle")} {e(c["acao"])}</p>'
        if c["acao"] and c["acao"] not in ("-", "null")
        else ""
    )
    resumo = f'<p class="resumo">{e(c["resumo"])}</p>' if c["resumo"] else ""
    botoes = []
    link_acao = (c.get("link_acao") or "").strip()
    if link_acao and link_acao.lower() not in ("-", "null"):
        botoes.append(
            f'<a class="aplicar" href="{e(link_acao)}" target="_blank" rel="noopener">{_ic("external-link")} Concluir</a>'
        )
    email = (c.get("email") or "").strip()
    if email and email.lower() not in ("-", "null"):
        botoes.append(
            f'<a class="btn-sec" href="{e(email)}" target="_blank" rel="noopener">{_ic("mail")} Email</a>'
        )
    acoes = f'<div class="card-actions">{"".join(botoes)}</div>' if botoes else ""
    detalhe = (
        f'<details class="det"><summary>ver detalhes</summary>{resumo}</details>'
        if c["resumo"]
        else ""
    )
    return f"""
      <article class="card cand" data-kind="cand" data-uid="{_cand_uid(c)}">
        <div class="card-head">
          <span class="pill" style="background:{cor}">{e(c['status']) or '—'}</span>
          <h3 class="title">{e(c['vaga']) or '—'}</h3>
          <button class="arch" data-uid="{_cand_uid(c)}" title="Arquivar">{_ic("x")}</button>
        </div>
        <p class="meta">{_ic("building-2")} {e(c['empresa'])} · {e(c['data']) or '—'}</p>
        <div class="tags">{followup}</div>
        {acao}{detalhe}{acoes}
      </article>"""


def _painel_candidaturas(cands: list[dict]) -> str:
    if not cands:
        return '<div class="vazio">Sem candidaturas ainda.</div>'
    # cutucar primeiro, depois por idade (mais antigas no topo)
    ordenadas = sorted(
        cands,
        key=lambda c: (
            not _cand_precisa_followup(c),
            -(_cand_idade_dias(c.get("data", "")) or 0),
        ),
    )
    funil = _funil_candidaturas(cands)
    cards = "".join(_cand_card(c) for c in ordenadas)
    return f'{funil}<div class="grid">{cards}</div>'


def _grupos(jobs, new_uids, applied_uids, kind="vaga") -> str:
    tiers = [
        (f'{_ic("star")} Destaques', [j for j in jobs if j.score >= 9]),
        ("Boas", [j for j in jobs if 7 <= j.score <= 8]),
        ("Ok", [j for j in jobs if j.score == 6]),
    ]
    out = []
    for titulo, lst in tiers:
        if not lst:
            continue
        cards = "".join(
            _vaga_card(j, j.uid in new_uids, j.uid in applied_uids, kind) for j in lst
        )
        out.append(
            f'<section class="group"><h2 class="grp">{titulo} '
            f'<span class="count">{len(lst)}</span></h2>'
            f'<div class="grid">{cards}</div></section>'
        )
    return "".join(out)


_CSS = """
  :root{--bg:#050505;--text:#fff;--muted:#8a8a90;--accent:#ff3366;--accent2:#6366f1;
    --line:rgba(255,255,255,.08);--card:rgba(255,255,255,.025);--grad:linear-gradient(135deg,#ff3366,#6366f1)}
  *{box-sizing:border-box;margin:0;padding:0}
  body{background:var(--bg);color:var(--text);
    font-family:'Space Grotesk',-apple-system,Segoe UI,Roboto,sans-serif;line-height:1.55;
    -webkit-font-smoothing:antialiased;overflow-x:hidden}
  body.swiping{user-select:none;-webkit-user-select:none;cursor:grabbing}
  svg.lucide{width:1.05em;height:1.05em;vertical-align:-.18em;stroke-width:2;flex:0 0 auto}
  .glow{position:fixed;top:-30%;right:-20%;width:600px;height:600px;border-radius:50%;
    background:var(--accent);filter:blur(160px);opacity:.10;pointer-events:none;z-index:0}
  .glow2{position:fixed;bottom:-30%;left:-20%;width:600px;height:600px;border-radius:50%;
    background:var(--accent2);filter:blur(160px);opacity:.10;pointer-events:none;z-index:0}
  .topbar{position:sticky;top:0;z-index:10;background:rgba(5,5,5,.86);backdrop-filter:blur(14px);
    border-bottom:1px solid var(--line);padding:14px 16px 0}
  .bar1,.tabs{transition:max-height .32s ease,opacity .25s ease,margin .3s ease;overflow:hidden}
  .bar1{display:flex;align-items:baseline;justify-content:space-between;gap:12px;max-width:1180px;
    margin:0 auto;max-height:48px;opacity:1}
  .brand{font-family:'Syne',sans-serif;font-weight:800;font-size:1.25rem;letter-spacing:-.02em}
  .brand b{background:var(--grad);-webkit-background-clip:text;background-clip:text;-webkit-text-fill-color:transparent}
  .sub{color:var(--muted);font-size:.8rem}
  .tabs{display:flex;gap:4px;align-items:center;max-width:1180px;margin:12px auto 0;max-height:48px;
    opacity:1;overflow-x:auto}
  .tabs::-webkit-scrollbar{height:0}
  .tab{background:transparent;border:none;border-bottom:2px solid transparent;color:var(--muted);
    font-family:'Syne',sans-serif;font-weight:700;font-size:.92rem;padding:8px 9px;cursor:pointer;
    transition:color .2s;white-space:nowrap;display:inline-flex;align-items:center;gap:5px}
  .tab:hover{color:#fff}
  .tab.on{color:#fff;border-bottom-color:var(--accent)}
  .tab .n{font-family:'Space Grotesk';font-weight:500;font-size:.66rem;color:var(--muted);
    background:var(--card);border:1px solid var(--line);padding:1px 7px;border-radius:20px}
  .iconbtn{background:transparent;border:1px solid var(--line);color:var(--muted);font-family:inherit;
    font-size:.78rem;font-weight:600;padding:6px 10px;border-radius:100px;cursor:pointer;white-space:nowrap;
    display:inline-flex;align-items:center;gap:5px}
  .iconbtn.on{border-color:var(--accent);color:#fff}
  #densbtn{margin-left:auto}
  .filters{max-width:1180px;margin:0 auto;padding:12px 0;display:flex;flex-direction:column;gap:10px}
  .frow{display:flex;align-items:center;gap:8px}
  .searchbtn{flex:0 0 auto;width:42px;height:42px;background:var(--card);border:1px solid var(--line);
    color:var(--muted);border-radius:100px;cursor:pointer;transition:all .2s;display:grid;place-items:center}
  .searchbtn:hover{border-color:var(--accent);color:#fff}
  .frow.searching .chiprow,.frow.searching .searchbtn{display:none}
  #q{flex:1;min-width:0;background:var(--card);border:1px solid var(--line);border-radius:12px;color:#fff;
    font-family:inherit;font-size:.95rem;padding:12px 14px;outline:none}
  #q:focus{border-color:var(--accent)}
  #q::placeholder{color:var(--muted)}
  .chiprow{display:flex;gap:8px;overflow-x:auto;padding-bottom:2px;-webkit-overflow-scrolling:touch}
  .chiprow::-webkit-scrollbar{height:0}
  .chip{flex:0 0 auto;background:var(--card);border:1px solid var(--line);color:var(--muted);
    font-family:inherit;font-size:.8rem;font-weight:600;padding:8px 13px;border-radius:100px;cursor:pointer;
    white-space:nowrap;transition:all .2s;display:inline-flex;align-items:center;gap:5px}
  .chip:hover{border-color:rgba(255,255,255,.25);color:#fff}
  .chip.on{background:var(--grad);border-color:transparent;color:#fff}
  .topbar.compact .bar1,.topbar.compact .tabs{max-height:0;opacity:0;margin-top:0;pointer-events:none}
  main{position:relative;z-index:1;max-width:1180px;margin:0 auto;padding:18px 16px 64px;touch-action:pan-y}
  .grp{font-family:'Syne',sans-serif;font-weight:700;font-size:1.1rem;letter-spacing:-.01em;
    margin:24px 2px 12px;display:flex;align-items:center;gap:8px;color:#e8e8ec}
  .count{font-family:'Space Grotesk';font-weight:500;font-size:.76rem;color:var(--muted);
    border:1px solid var(--line);padding:2px 11px;border-radius:20px}
  .grid{display:grid;grid-template-columns:1fr;gap:14px}
  @media(min-width:640px){.grid{grid-template-columns:repeat(2,1fr)}}
  @media(min-width:1024px){.grid{grid-template-columns:repeat(3,1fr)}}
  .panel.hidden{display:none}
  .card{background:var(--card);border:1px solid var(--line);border-radius:18px;padding:16px 18px;
    display:flex;flex-direction:column;gap:8px;transition:border-color .3s,transform .3s,opacity .3s}
  .card:hover{border-color:rgba(255,51,102,.4);transform:translateY(-2px)}
  .card.feita{opacity:.5}
  .card-head{display:flex;align-items:center;gap:11px}
  .badge{font-family:'Syne',sans-serif;font-weight:800;font-size:1rem;min-width:40px;height:40px;
    display:grid;place-items:center;border-radius:12px;color:#050505;flex:0 0 auto}
  .title{flex:1;min-width:0;font-family:'Syne',sans-serif;font-weight:700;font-size:1rem;line-height:1.2}
  .title a{color:#fff;text-decoration:none}
  .title a:hover{color:var(--accent)}
  .arch{flex:0 0 auto;background:transparent;border:none;color:var(--muted);cursor:pointer;padding:6px;
    border-radius:8px;transition:all .2s;display:grid;place-items:center}
  .arch:hover{color:var(--accent);background:rgba(255,255,255,.04)}
  .arch svg.lucide{width:18px;height:18px}
  .tags{display:flex;flex-wrap:wrap;gap:6px}
  .tags:empty{display:none}
  .tag{font-size:.62rem;font-weight:700;text-transform:uppercase;letter-spacing:.05em;padding:3px 8px;border-radius:6px}
  .novo{background:var(--accent);color:#fff}
  .meta{font-size:.82rem;color:var(--muted);display:flex;align-items:center;gap:4px;flex-wrap:wrap}
  .meta svg.lucide{width:13px;height:13px;opacity:.8}
  .resumo{font-size:.88rem;color:#d4d4d8;margin-top:4px}
  .dica{font-size:.83rem;color:#ffd24d;margin-top:6px}
  .dica svg.lucide{width:14px;height:14px}
  .motivo{font-size:.8rem;color:var(--muted);font-style:italic;margin-top:6px}
  .srcline{font-size:.72rem;color:var(--muted);margin-top:8px}
  .det{font-size:.8rem}
  .det summary{color:var(--accent);cursor:pointer;font-weight:600;list-style:none;font-size:.76rem}
  .det summary::-webkit-details-marker{display:none}
  .det summary::after{content:' ▾'}
  .det[open] summary::after{content:' ▴'}
  body.rich .det>summary{display:none}
  .pill{display:inline-flex;align-items:center;padding:5px 12px;border-radius:20px;color:#050505;font-weight:700;
    font-size:.66rem;text-transform:uppercase;letter-spacing:.04em;flex:0 0 auto}
  .acao{font-size:.82rem;color:#fca5a5;font-weight:600;display:flex;align-items:center;gap:5px}
  .aplicar{align-self:flex-start;background:var(--grad);color:#fff;font-weight:700;font-size:.82rem;
    text-decoration:none;padding:10px 16px;border-radius:100px;min-height:42px;display:inline-flex;
    align-items:center;gap:6px;cursor:pointer;border:none;font-family:inherit;transition:filter .2s,transform .2s}
  .aplicar:hover{filter:brightness(1.1);transform:scale(1.03)}
  .aplicar svg.lucide{width:16px;height:16px}
  .card.feita .aplbtn{background:#22c55e22;color:#22c55e}
  .btn-sec{background:var(--card);border:1px solid var(--line);color:#fff;font-weight:600;font-size:.8rem;
    text-decoration:none;padding:9px 14px;border-radius:100px;min-height:42px;display:inline-flex;
    align-items:center;gap:6px;cursor:pointer;font-family:inherit;transition:border-color .2s}
  .btn-sec:hover{border-color:var(--accent)}
  .btn-sec svg.lucide{width:15px;height:15px}
  .card-actions{display:flex;flex-wrap:wrap;gap:8px;margin-top:4px}
  .fav{flex:0 0 auto;background:transparent;border:none;color:var(--muted);cursor:pointer;padding:6px;
    border-radius:8px;transition:all .2s;display:grid;place-items:center}
  .fav:hover{color:#fbbf24;background:rgba(255,255,255,.04)}
  .fav svg.lucide{width:18px;height:18px}
  .card.favon .fav{color:#fbbf24}
  .card.favon .fav svg.lucide{fill:#fbbf24}
  .pitchbtn.copied{border-color:#22c55e;color:#22c55e}
  .follow{background:var(--accent);color:#fff;display:inline-flex;align-items:center;gap:4px}
  .follow svg.lucide{width:12px;height:12px}
  .funil{display:flex;gap:10px;overflow-x:auto;padding:2px 2px 18px;-webkit-overflow-scrolling:touch}
  .funil::-webkit-scrollbar{height:0}
  .fcell{flex:0 0 auto;background:var(--card);border:1px solid var(--line);border-radius:14px;
    padding:12px 16px;min-width:96px;display:flex;flex-direction:column;gap:5px;align-items:flex-start}
  .fnum{font-family:'Syne',sans-serif;font-weight:800;font-size:1.5rem;line-height:1}
  .flbl{font-size:.72rem;color:var(--muted);display:flex;align-items:center;gap:4px;white-space:nowrap}
  .flbl svg.lucide{width:12px;height:12px}
  #more{display:block;margin:28px auto 0;background:var(--card);border:1px solid var(--line);color:#fff;
    font-family:inherit;font-weight:600;font-size:.9rem;padding:12px 28px;border-radius:100px;cursor:pointer}
  #more:hover{border-color:var(--accent)}
  #empty{display:none;text-align:center;color:var(--muted);padding:50px 20px;border:1px dashed var(--line);border-radius:18px}
  .vazio{text-align:center;color:var(--muted);padding:50px 20px;border:1px dashed var(--line);border-radius:18px}
  .notaform{display:flex;flex-direction:column;gap:10px;margin-bottom:22px}
  .notaform input,.notaform textarea{background:var(--card);border:1px solid var(--line);border-radius:12px;
    color:#fff;font-family:inherit;font-size:.95rem;padding:12px 14px;outline:none;width:100%}
  .notaform input:focus,.notaform textarea:focus{border-color:var(--accent)}
  .notaform textarea{min-height:120px;resize:vertical}
  .notabody{white-space:pre-wrap;font-family:inherit;font-size:.86rem;color:#d4d4d8;background:rgba(0,0,0,.25);
    border:1px solid var(--line);border-radius:10px;padding:12px;margin:4px 0}
  .nota .title{font-size:1rem}
  @keyframes paneInR{from{opacity:0;transform:translateX(26px)}to{opacity:1;transform:translateX(0)}}
  @keyframes paneInL{from{opacity:0;transform:translateX(-26px)}to{opacity:1;transform:translateX(0)}}
  .livetoast{position:fixed;left:50%;bottom:22px;transform:translateX(-50%) translateY(160%);
    background:var(--grad);color:#fff;border:none;font-family:inherit;font-weight:700;font-size:.9rem;
    padding:13px 22px;border-radius:100px;cursor:pointer;z-index:50;box-shadow:0 8px 30px rgba(0,0,0,.45);
    display:inline-flex;align-items:center;gap:8px;transition:transform .35s cubic-bezier(.16,1,.3,1)}
  .livetoast.on{transform:translateX(-50%) translateY(0)}
  .livetoast svg.lucide{width:16px;height:16px}
  .themepanel{position:fixed;right:14px;top:62px;z-index:60;width:240px;display:none;
    background:rgba(12,12,15,.97);border:1px solid var(--line);border-radius:16px;padding:14px;
    box-shadow:0 14px 44px rgba(0,0,0,.55)}
  .themepanel.on{display:block;animation:paneInR .2s ease}
  .themepanel h4{font-family:'Syne',sans-serif;font-size:.82rem;margin-bottom:10px;color:#fff}
  .swatches{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:12px}
  .sw{width:30px;height:30px;border-radius:9px;cursor:pointer;border:2px solid transparent;transition:transform .15s}
  .sw:hover{transform:scale(1.1)} .sw.on{border-color:#fff}
  .trow{display:flex;align-items:center;justify-content:space-between;gap:8px;margin:9px 0;
    font-size:.82rem;color:var(--muted)}
  .trow input[type=color]{width:36px;height:28px;border:1px solid var(--line);border-radius:6px;
    background:none;cursor:pointer;padding:0}
  .tbtn{width:100%;margin-top:8px;background:var(--card);border:1px solid var(--line);color:#fff;
    border-radius:10px;padding:9px;cursor:pointer;font-family:inherit;font-size:.8rem}
  .tbtn:hover{border-color:var(--accent)}
  body.lighttheme .title a,body.lighttheme .grp,body.lighttheme .nota .title{color:#15151a}
  body.lighttheme .resumo,body.lighttheme .notabody{color:#33333a}
  body.lighttheme .notabody{background:rgba(0,0,0,.04)}
  body.lighttheme .topbar{background:rgba(246,246,248,.88)}
  body.lighttheme .glow,body.lighttheme .glow2{opacity:.06}
"""


_JS = """
  const all=[...document.querySelectorAll('.card[data-uid]')];
  const vagaCards=all.filter(c=>c.dataset.kind==='vaga');
  const freelaCards=all.filter(c=>c.dataset.kind==='freela');
  const candCards=all.filter(c=>c.dataset.kind==='cand');
  const chips=[...document.querySelectorAll('.chip')];
  const q=document.getElementById('q');
  const more=document.getElementById('more');
  const empty=document.getElementById('empty');
  const tabs=[...document.querySelectorAll('.tab')];
  const filterbar=document.getElementById('filterbar');
  const arqBtn=document.getElementById('arqtog');
  const aplBtn=document.getElementById('apltog');
  const favBtn=document.getElementById('favtog');
  const densBtn=document.getElementById('densbtn');
  const panes={vagas:document.getElementById('tab-vagas'),freelas:document.getElementById('tab-freelas'),cand:document.getElementById('tab-cand'),notas:document.getElementById('tab-notas')};
  const TABS=['vagas','freelas','cand','notas'];
  const AREAS=['design','social','foto','video','web'];
  let filtro='all', limite=18, modo='normal', cur='vagas';
  const WEBAPP=window.WEBAPP_URL||'';
  const TOKEN=window.SYNC_TOKEN||'';
  const TQ=TOKEN?('&token='+encodeURIComponent(TOKEN)):'';
  function loadSet(k){try{return new Set(JSON.parse(localStorage.getItem(k)||'[]'));}catch(e){return new Set();}}
  let arch=loadSet('garimpo_arq');
  let apl=loadSet('garimpo_apl');
  let fav=loadSet('garimpo_fav');
  [...vagaCards,...freelaCards].forEach(c=>{if(c.dataset.applied==='1')apl.add(c.dataset.uid);});
  function save(k,s){localStorage.setItem(k,JSON.stringify([...s]));}
  function push(action,uid,op){if(!WEBAPP)return;fetch(WEBAPP,{method:'POST',mode:'no-cors',
    headers:{'Content-Type':'text/plain'},body:JSON.stringify({action:action,uid:uid,op:op,token:TOKEN})}).catch(()=>{});}
  function jsonp(action,cb){if(!WEBAPP)return;const n='__cb'+Math.floor(Math.random()*1e6);window[n]=cb;
    const s=document.createElement('script');s.src=WEBAPP+(WEBAPP.indexOf('?')>-1?'&':'?')+'action='+action+'&callback='+n+TQ+'&t='+Date.now();
    document.body.appendChild(s);}
  function okVaga(c){
    if(filtro==='remoto'&&c.dataset.remote!=='1')return false;
    if(filtro==='rj'&&c.dataset.rj!=='1')return false;
    if(AREAS.includes(filtro)&&c.dataset.area!==filtro)return false;
    const t=q.value.trim().toLowerCase();
    if(t&&!c.dataset.text.includes(t))return false;
    return true;
  }
  function baseVis(uid){
    const a=arch.has(uid),p=apl.has(uid);
    if(modo==='arq')return a;
    if(modo==='apl')return p;
    if(modo==='fav')return fav.has(uid)&&!a;
    return !a&&!p;
  }
  function refresh(){
    let shown=0,total=0;
    for(const c of vagaCards){
      const uid=c.dataset.uid, ap=apl.has(uid);
      c.classList.toggle('feita',ap);
      c.classList.toggle('favon',fav.has(uid));
      const lbl=c.querySelector('.albl');if(lbl)lbl.textContent=ap?'Aplicada':'Já apliquei';
      let vis=baseVis(uid);
      if(vis&&!okVaga(c))vis=false;
      if(vis){total++;if(shown<limite){c.style.display='';shown++;}else c.style.display='none';}
      else c.style.display='none';
    }
    document.querySelectorAll('#tab-vagas .group').forEach(g=>{
      const v=[...g.querySelectorAll('.card')].some(c=>c.style.display!=='none');g.style.display=v?'':'none';});
    more.style.display=total>shown?'block':'none';
    empty.style.display=total===0?'block':'none';
    for(const c of freelaCards){
      const uid=c.dataset.uid, ap=apl.has(uid);
      c.classList.toggle('feita',ap);
      c.classList.toggle('favon',fav.has(uid));
      const lbl=c.querySelector('.albl');if(lbl)lbl.textContent=ap?'Aplicada':'Já apliquei';
      c.style.display=baseVis(uid)?'':'none';
    }
    document.querySelectorAll('#tab-freelas .group').forEach(g=>{
      const v=[...g.querySelectorAll('.card')].some(c=>c.style.display!=='none');g.style.display=v?'':'none';});
    for(const c of candCards){c.style.display=baseVis(c.dataset.uid)?'':'none';}
    if(arqBtn){const n=arqBtn.querySelector('.n');if(n)n.textContent=arch.size;}
    if(aplBtn){const n=aplBtn.querySelector('.n');if(n)n.textContent=apl.size;}
    if(favBtn){const n=favBtn.querySelector('.n');if(n)n.textContent=fav.size;}
  }
  document.addEventListener('click',ev=>{
    const ar=ev.target.closest('.arch');
    if(ar){ev.preventDefault();const u=ar.dataset.uid;const op=arch.has(u)?'del':'add';
      if(arch.has(u))arch.delete(u);else arch.add(u);save('garimpo_arq',arch);refresh();push('arq',u,op);return;}
    const ap=ev.target.closest('.aplbtn');
    if(ap){ev.preventDefault();const u=ap.dataset.uid;const op=apl.has(u)?'del':'add';
      if(apl.has(u))apl.delete(u);else apl.add(u);save('garimpo_apl',apl);refresh();push('apl',u,op);return;}
    const fv=ev.target.closest('.fav');
    if(fv){ev.preventDefault();const u=fv.dataset.uid;const op=fav.has(u)?'del':'add';
      if(fav.has(u))fav.delete(u);else fav.add(u);save('garimpo_fav',fav);refresh();push('fav',u,op);return;}
    const pb=ev.target.closest('.pitchbtn');
    if(pb){ev.preventDefault();const card=pb.closest('.card');const txt=card?card.dataset.pitch:'';
      if(txt){navigator.clipboard.writeText(txt).then(()=>{pb.classList.add('copied');
        const l=pb.querySelector('.plbl');const o=l?l.textContent:'';if(l)l.textContent='Copiado!';
        setTimeout(()=>{pb.classList.remove('copied');if(l)l.textContent=o||'Copiar pitch';},1600);});}return;}
  });
  if(arqBtn)arqBtn.onclick=()=>{modo=modo==='arq'?'normal':'arq';
    arqBtn.classList.toggle('on',modo==='arq');if(aplBtn)aplBtn.classList.remove('on');
    if(favBtn)favBtn.classList.remove('on');limite=18;refresh();};
  if(aplBtn)aplBtn.onclick=()=>{modo=modo==='apl'?'normal':'apl';
    aplBtn.classList.toggle('on',modo==='apl');if(arqBtn)arqBtn.classList.remove('on');
    if(favBtn)favBtn.classList.remove('on');limite=18;refresh();};
  if(favBtn)favBtn.onclick=()=>{modo=modo==='fav'?'normal':'fav';
    favBtn.classList.toggle('on',modo==='fav');if(arqBtn)arqBtn.classList.remove('on');
    if(aplBtn)aplBtn.classList.remove('on');limite=18;refresh();};
  chips.forEach(ch=>ch.onclick=()=>{filtro=ch.dataset.f;limite=18;
    chips.forEach(x=>x.classList.toggle('on',x===ch));refresh();});
  q.oninput=()=>{limite=18;refresh();};
  const searchbtn=document.getElementById('searchbtn');
  const frow=document.getElementById('frow');
  searchbtn.onclick=()=>{frow.classList.add('searching');q.hidden=false;q.focus();};
  q.onblur=()=>{if(!q.value.trim()){frow.classList.remove('searching');q.hidden=true;}};
  const topbar=document.querySelector('.topbar');
  window.addEventListener('scroll',()=>{topbar.classList.toggle('compact',window.scrollY>70);},{passive:true});
  more.onclick=()=>{limite+=18;refresh();};
  let rich=localStorage.getItem('garimpo_dens')==='rich';
  function applyDens(){document.body.classList.toggle('rich',rich);
    document.querySelectorAll('.det').forEach(d=>{d.open=rich;});
    if(densBtn){densBtn.classList.toggle('on',rich);
      densBtn.querySelector('.dlbl').textContent=rich?'Menos info':'Mais info';}}
  if(densBtn)densBtn.onclick=()=>{rich=!rich;localStorage.setItem('garimpo_dens',rich?'rich':'lean');applyDens();};
  function setTab(name,dir){cur=name;
    tabs.forEach(t=>t.classList.toggle('on',t.dataset.tab===name));
    for(const k in panes){if(panes[k])panes[k].classList.toggle('hidden',k!==name);}
    filterbar.style.display=name==='vagas'?'':'none';
    const p=panes[name];if(p){const a=dir<0?'paneInL':'paneInR';p.style.animation='none';void p.offsetWidth;p.style.animation=a+' .28s ease';}}
  tabs.forEach(t=>t.onclick=()=>setTab(t.dataset.tab,0));
  let sx=0,sy=0,sw=false,moved=false;
  document.addEventListener('pointerdown',e=>{
    if(e.target.closest('.card,button,a,input,textarea,select,.chiprow,details,summary')){sw=false;return;}
    sx=e.clientX;sy=e.clientY;sw=true;moved=false;});
  document.addEventListener('pointermove',e=>{
    if(!sw)return;const dx=e.clientX-sx,dy=e.clientY-sy;
    if(!moved&&Math.abs(dx)>10&&Math.abs(dx)>Math.abs(dy)){moved=true;document.body.classList.add('swiping');}
    if(moved)e.preventDefault();});
  document.addEventListener('pointerup',e=>{
    document.body.classList.remove('swiping');if(!sw)return;sw=false;
    const dx=e.clientX-sx,dy=e.clientY-sy;
    if(Math.abs(dx)>70&&Math.abs(dx)>Math.abs(dy)*1.4){const d=dx<0?1:-1;let i=TABS.indexOf(cur)+d;
      if(i<0)i=TABS.length-1;if(i>=TABS.length)i=0;setTab(TABS[i],d);window.scrollTo(0,0);}});
  const NKEY='garimpo_notas';
  function esc(s){const d=document.createElement('div');d.textContent=s||'';return d.innerHTML;}
  function getNotas(){try{return JSON.parse(localStorage.getItem(NKEY)||'[]');}catch(e){return[];}}
  function saveNotas(l){localStorage.setItem(NKEY,JSON.stringify(l));}
  function pushNota(op,n){if(!WEBAPP)return;fetch(WEBAPP,{method:'POST',mode:'no-cors',
    headers:{'Content-Type':'text/plain'},body:JSON.stringify(Object.assign({action:'nota',op:op,token:TOKEN},n))}).catch(()=>{});}
  let verTrash=false;
  const notrash=document.getElementById('notrash');
  function renderNotas(){
    const l=getNotas();const box=document.getElementById('notaslist');if(!box)return;
    const lixo=l.filter(n=>n.trashed), ativos=l.filter(n=>!n.trashed);
    if(notrash){const n=notrash.querySelector('.n');if(n)n.textContent=lixo.length;}
    const show=verTrash?lixo:ativos;
    if(!show.length){box.innerHTML='<div class="vazio">'+(verTrash?'Lixeira vazia.':'Nenhuma nota ainda. Salve apresentações, descrições e respostas que você reusa.')+'</div>';if(window.lucide)lucide.createIcons();return;}
    box.innerHTML=show.map(function(n){
      const head='<div class="card-head"><h3 class="title">'+(esc(n.titulo)||'(sem título)')+'</h3></div>';
      const body='<pre class="notabody">'+esc(n.corpo)+'</pre>';
      const acts=verTrash
        ?'<div class="card-actions"><button class="btn-sec nrestore" data-id="'+n.id+'"><i data-lucide=\\"rotate-ccw\\"></i> Restaurar</button><button class="btn-sec npurge" data-id="'+n.id+'"><i data-lucide=\\"trash-2\\"></i> Excluir definitivo</button></div>'
        :'<div class="card-actions"><button class="btn-sec ncopy" data-id="'+n.id+'"><i data-lucide=\\"copy\\"></i> Copiar</button><button class="btn-sec ndel" data-id="'+n.id+'"><i data-lucide=\\"trash-2\\"></i> Excluir</button></div>';
      return '<article class="card nota">'+head+body+acts+'</article>';
    }).join('');
    if(window.lucide)lucide.createIcons();
  }
  if(notrash)notrash.onclick=function(){verTrash=!verTrash;notrash.classList.toggle('on',verTrash);renderNotas();};
  const nadd=document.getElementById('nadd');
  if(nadd)nadd.onclick=()=>{const t=document.getElementById('ntit'),c=document.getElementById('ncorpo');
    if(!c.value.trim())return;const note={id:'n'+Date.now(),titulo:t.value.trim(),corpo:c.value,trashed:false};
    const l=getNotas();l.unshift(note);saveNotas(l);t.value='';c.value='';renderNotas();pushNota('add',note);};
  document.addEventListener('click',ev=>{
    const cp=ev.target.closest('.ncopy');
    if(cp){const n=getNotas().find(x=>x.id===cp.dataset.id);
      if(n){navigator.clipboard.writeText(n.corpo).then(()=>{cp.innerHTML='<i data-lucide=\\"check\\"></i> Copiado!';
        if(window.lucide)lucide.createIcons();setTimeout(()=>{cp.innerHTML='<i data-lucide=\\"copy\\"></i> Copiar';if(window.lucide)lucide.createIcons();},1500);});}return;}
    const dl=ev.target.closest('.ndel');
    if(dl){const l=getNotas();const n=l.find(x=>x.id===dl.dataset.id);if(n){n.trashed=true;saveNotas(l);renderNotas();pushNota('trash',{id:dl.dataset.id});}return;}
    const rs=ev.target.closest('.nrestore');
    if(rs){const l=getNotas();const n=l.find(x=>x.id===rs.dataset.id);if(n){n.trashed=false;saveNotas(l);renderNotas();pushNota('restore',{id:rs.dataset.id});}return;}
    const pg=ev.target.closest('.npurge');
    if(pg){saveNotas(getNotas().filter(x=>x.id!==pg.dataset.id));renderNotas();pushNota('purge',{id:pg.dataset.id});}});
  applyDens();setTab('vagas',0);renderNotas();
  if(window.lucide)lucide.createIcons();
  jsonp('getarq',function(l){try{(l||[]).forEach(u=>arch.add(u));save('garimpo_arq',arch);refresh();}catch(e){}});
  jsonp('getapl',function(l){try{(l||[]).forEach(u=>apl.add(u));save('garimpo_apl',apl);refresh();}catch(e){}});
  jsonp('getfav',function(l){try{(l||[]).forEach(u=>fav.add(u));save('garimpo_fav',fav);refresh();}catch(e){}});
  jsonp('getnotas',function(l){try{if(Array.isArray(l)){saveNotas(l);renderNotas();}}catch(e){}});

  // ---- atualização ao vivo (sem rescrape; reflete a última publicação) ----
  const BUILD=window.BUILD||'';
  function mostraToast(){
    let t=document.getElementById('liveToast');
    if(!t){t=document.createElement('button');t.id='liveToast';t.className='livetoast';
      t.innerHTML='<i data-lucide="refresh-cw"></i> Vagas novas — atualizar';
      t.onclick=function(){location.reload();};document.body.appendChild(t);
      if(window.lucide)lucide.createIcons();}
    t.classList.add('on');
  }
  async function checaVersao(){
    try{const r=await fetch('version.json?t='+Date.now(),{cache:'no-store'});
      if(!r.ok)return;const v=await r.json();
      if(v&&v.build&&BUILD&&v.build!==BUILD)mostraToast();}catch(e){}
  }
  function resync(){
    jsonp('getarq',function(l){try{(l||[]).forEach(u=>arch.add(u));save('garimpo_arq',arch);refresh();}catch(e){}});
    jsonp('getapl',function(l){try{(l||[]).forEach(u=>apl.add(u));save('garimpo_apl',apl);refresh();}catch(e){}});
    jsonp('getfav',function(l){try{(l||[]).forEach(u=>fav.add(u));save('garimpo_fav',fav);refresh();}catch(e){}});
  }
  setInterval(function(){if(!document.hidden)checaVersao();},90000);
  setInterval(function(){if(!document.hidden)resync();},45000);
  document.addEventListener('visibilitychange',function(){if(!document.hidden){checaVersao();resync();}});

  // ---- personalização de cores ----
  const TPRE=[['#ff3366','#6366f1'],['#22c55e','#06b6d4'],['#f59e0b','#ef4444'],['#8b5cf6','#ec4899'],['#0ea5e9','#14b8a6'],['#eab308','#f97316']];
  function applyTheme(t){
    const r=document.documentElement.style;
    r.setProperty('--accent',t.a1);r.setProperty('--accent2',t.a2);
    r.setProperty('--grad','linear-gradient(135deg,'+t.a1+','+t.a2+')');
    if(t.light){r.setProperty('--bg','#f6f6f8');r.setProperty('--text','#15151a');r.setProperty('--muted','#5a5a66');
      r.setProperty('--card','rgba(0,0,0,.03)');r.setProperty('--line','rgba(0,0,0,.10)');document.body.classList.add('lighttheme');}
    else{['--bg','--text','--muted','--card','--line'].forEach(v=>r.removeProperty(v));document.body.classList.remove('lighttheme');}
  }
  function getTheme(){try{return JSON.parse(localStorage.getItem('garimpo_theme'))||{a1:'#ff3366',a2:'#6366f1',light:false};}catch(e){return {a1:'#ff3366',a2:'#6366f1',light:false};}}
  function saveTheme(t){localStorage.setItem('garimpo_theme',JSON.stringify(t));}
  let theme=getTheme();applyTheme(theme);
  const tpanel=document.getElementById('themepanel'),themebtn=document.getElementById('themebtn');
  const c1=document.getElementById('c1'),c2=document.getElementById('c2'),lightchk=document.getElementById('lightchk');
  if(c1){c1.value=theme.a1;c2.value=theme.a2;lightchk.checked=!!theme.light;}
  if(themebtn)themebtn.onclick=function(e){e.stopPropagation();tpanel.classList.toggle('on');};
  document.addEventListener('click',function(e){if(tpanel&&tpanel.classList.contains('on')&&!tpanel.contains(e.target)&&themebtn&&!themebtn.contains(e.target))tpanel.classList.remove('on');});
  const swbox=document.getElementById('swatches');
  if(swbox)TPRE.forEach(function(p){var d=document.createElement('div');d.className='sw';
    d.style.background='linear-gradient(135deg,'+p[0]+','+p[1]+')';
    d.onclick=function(){theme.a1=p[0];theme.a2=p[1];if(c1){c1.value=p[0];c2.value=p[1];}saveTheme(theme);applyTheme(theme);};swbox.appendChild(d);});
  if(c1){c1.oninput=function(){theme.a1=c1.value;saveTheme(theme);applyTheme(theme);};
    c2.oninput=function(){theme.a2=c2.value;saveTheme(theme);applyTheme(theme);};
    lightchk.onchange=function(){theme.light=lightchk.checked;saveTheme(theme);applyTheme(theme);};}
  const treset=document.getElementById('treset');
  if(treset)treset.onclick=function(){theme={a1:'#ff3366',a2:'#6366f1',light:false};saveTheme(theme);applyTheme(theme);if(c1){c1.value=theme.a1;c2.value=theme.a2;lightchk.checked=false;}};

  refresh();
"""


def gerar_html(
    jobs: list[Job],
    path: str,
    gerado_em: str,
    new_uids: set[str] | None = None,
    candidaturas: list[dict] | None = None,
    applied_uids: set[str] | None = None,
    bot_username: str = "",
    webapp_url: str = "",
    sync_token: str = "",
    brand: str = "Vagas",
) -> None:
    """Escreve o painel HTML (abas, ícones Lucide, arquivar/aplicados/notas)."""
    new_uids = new_uids or set()
    candidaturas = candidaturas or []
    applied_uids = applied_uids or set()
    jobs = sorted(jobs, key=lambda j: j.score, reverse=True)
    vagas = [j for j in jobs if not j.freela]
    freelas = [j for j in jobs if j.freela]
    grupos = _grupos(vagas, new_uids, applied_uids, "vaga")
    grupos_freela = _grupos(freelas, new_uids, applied_uids, "freela") or (
        '<div class="vazio">Nenhum freela garimpado ainda (Trampos). Volte mais tarde.</div>'
    )
    chips = (
        '<button class="chip on" data-f="all">Todas</button>'
        f'<button class="chip" data-f="remoto">{_ic("house")} Remoto</button>'
        f'<button class="chip" data-f="rj">{_ic("map-pin")} RJ</button>'
        + "".join(
            f'<button class="chip" data-f="{slug}">{_ic(ico)} {rot}</button>'
            for slug, ico, rot in AREA_CHIPS
        )
    )
    doc = f"""<!doctype html>
<html lang="pt-br"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>Vagas · {html.escape(brand)}</title>
<link rel="manifest" href="manifest.webmanifest">
<meta name="theme-color" content="#050505">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<meta name="apple-mobile-web-app-title" content="Vagas">
<link rel="icon" type="image/svg+xml" href="icon.svg">
<link rel="icon" type="image/png" href="icon.png">
<link rel="apple-touch-icon" href="icon.png">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@400;500;600;700&family=Syne:wght@600;700;800&display=swap" rel="stylesheet">
<script src="https://unpkg.com/lucide@latest"></script>
<style>{_CSS}</style>
<script>(function(){{try{{var t=JSON.parse(localStorage.getItem('garimpo_theme'));if(!t)return;
var r=document.documentElement.style;r.setProperty('--accent',t.a1);r.setProperty('--accent2',t.a2);
r.setProperty('--grad','linear-gradient(135deg,'+t.a1+','+t.a2+')');
if(t.light){{r.setProperty('--bg','#f6f6f8');r.setProperty('--text','#15151a');r.setProperty('--muted','#5a5a66');
r.setProperty('--card','rgba(0,0,0,.03)');r.setProperty('--line','rgba(0,0,0,.10)');
document.documentElement.classList.add('prelight');}}}}catch(e){{}}}})();</script>
</head>
<body>
  <div class="glow"></div><div class="glow2"></div>
  <header class="topbar">
    <div class="bar1">
      <div class="brand">{_brand_html(brand)}</div>
      <div class="sub">{len(new_uids)} novas · {gerado_em}</div>
    </div>
    <nav class="tabs">
      <button class="tab on" data-tab="vagas">{_ic("search")} Vagas <span class="n">{len(vagas)}</span></button>
      <button class="tab" data-tab="freelas">{_ic("zap")} Freelas <span class="n">{len(freelas)}</span></button>
      <button class="tab" data-tab="cand">{_ic("bookmark")} Candidaturas <span class="n">{len(candidaturas)}</span></button>
      <button class="tab" data-tab="notas">{_ic("notebook-pen")} Notas</button>
      <button id="densbtn" class="iconbtn">{_ic("layout-list")} <span class="dlbl">Mais info</span></button>
      <button id="themebtn" class="iconbtn" title="Cores">{_ic("palette")}</button>
      <button id="favtog" class="iconbtn">{_ic("star")} <span class="n">0</span></button>
      <button id="apltog" class="iconbtn">{_ic("circle-check")} <span class="n">0</span></button>
      <button id="arqtog" class="iconbtn">{_ic("archive")} <span class="n">0</span></button>
    </nav>
    <div class="filters" id="filterbar">
      <div class="frow" id="frow">
        <button id="searchbtn" class="searchbtn" aria-label="Buscar">{_ic("search")}</button>
        <input id="q" type="search" placeholder="Buscar por cargo, empresa..." hidden>
        <div class="chiprow">{chips}</div>
      </div>
    </div>
  </header>
  <div class="themepanel" id="themepanel">
    <h4>{_ic("palette")} Cores do painel</h4>
    <div class="swatches" id="swatches"></div>
    <div class="trow"><span>Cor 1</span><input type="color" id="c1" value="#ff3366"></div>
    <div class="trow"><span>Cor 2</span><input type="color" id="c2" value="#6366f1"></div>
    <div class="trow"><span>Tema claro</span><input type="checkbox" id="lightchk"></div>
    <button class="tbtn" id="treset">Restaurar padrão</button>
  </div>
  <main>
    <section id="tab-vagas" class="panel">
      {grupos}
      <div id="empty">Nenhuma vaga aqui. Tenta limpar a busca ou os filtros.</div>
      <button id="more">Carregar mais</button>
    </section>
    <section id="tab-freelas" class="panel hidden">
      {grupos_freela}
    </section>
    <section id="tab-cand" class="panel hidden">
      {_painel_candidaturas(candidaturas)}
    </section>
    <section id="tab-notas" class="panel hidden">
      <div class="notaform">
        <input id="ntit" placeholder="Título (ex: Carta de apresentação)">
        <textarea id="ncorpo" placeholder="Cole/escreva apresentação, descrição, respostas que você reusa..."></textarea>
        <button id="nadd" class="aplicar">{_ic("save")} Salvar nota</button>
      </div>
      <div class="notabar"><button id="notrash" class="iconbtn">{_ic("trash-2")} Lixeira <span class="n">0</span></button></div>
      <div id="notaslist" class="grid"></div>
    </section>
  </main>
  <script>window.WEBAPP_URL={json.dumps(webapp_url)};window.SYNC_TOKEN={json.dumps(sync_token)};window.BUILD={json.dumps(gerado_em)};</script>
  <script>{_JS}</script>
</body></html>"""
    with open(path, "w", encoding="utf-8") as f:
        f.write(doc)


def obter_username_bot(log) -> str:
    """Descobre o @username do bot (getMe) para montar deep-links na página."""
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        return ""
    try:
        resp = requests.get(f"https://api.telegram.org/bot{token}/getMe", timeout=20)
        resp.raise_for_status()
        return resp.json().get("result", {}).get("username", "") or ""
    except Exception as exc:  # noqa: BLE001
        log(f"  [Telegram] getMe falhou: {exc}")
        return ""


def _score_emoji(score: int) -> str:
    if score >= 7:
        return "🟢"
    if score >= 6:
        return "🟡"
    return "⚪"


def enviar_followup(
    cands: list[dict], log, dias: int = FOLLOWUP_DIAS, painel_url: str = ""
) -> None:
    """Alerta no Telegram das candidaturas paradas (sem resposta há >= `dias`)."""
    pendentes = [c for c in cands if _cand_precisa_followup(c)]
    if not pendentes:
        return
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat_id:
        log("  [Follow-up] sem token/chat — pulando", level="WARN")
        return
    e = html.escape
    pendentes.sort(key=lambda c: -(_cand_idade_dias(c.get("data", "")) or 0))
    head = (
        f"🔔 <b>{len(pendentes)} candidatura(s) para cutucar</b> "
        f"(sem resposta há {dias}+ dias)\n"
    )
    if painel_url:
        head += f'📋 <a href="{e(painel_url)}">Abrir painel</a>\n'
    head += "➖➖➖➖➖➖➖➖➖➖\n"
    blocos = [head]
    for c in pendentes[:15]:
        idade = _cand_idade_dias(c.get("data", "")) or 0
        link = (c.get("link_acao") or c.get("email") or "").strip()
        alvo = (
            f'\n🔗 <a href="{e(link)}">retomar</a>'
            if link and link.lower() not in ("-", "null")
            else ""
        )
        blocos.append(
            f"\n⏳ <b>{idade}d</b> · {e(c.get('vaga') or '—')}\n"
            f"🏢 {e(c.get('empresa') or '—')} · {e(c.get('status') or '—')}{alvo}\n"
        )
    msg, partes = "", []
    for b in blocos:
        if len(msg) + len(b) > _TG_LIMIT:
            partes.append(msg)
            msg = ""
        msg += b
    if msg:
        partes.append(msg)
    url = _TG_API.format(token=token)
    for parte in partes:
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
            log(f"  [Follow-up] falha ao enviar: {exc}", level="WARN")
            return
    log(f"  [Follow-up] {len(pendentes)} candidatura(s) sinalizada(s)")


def enviar_telegram(
    jobs: list[Job], top_n: int, log, painel_url: str = "", total_painel: int = 0
) -> None:
    """Manda as top N vagas da rodada no Telegram (HTML parse mode)."""
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat_id:
        log("  [Telegram] TELEGRAM_BOT_TOKEN/CHAT_ID ausentes — pulando")
        return
    if not jobs:
        return

    top = sorted(jobs, key=lambda j: j.score, reverse=True)[:top_n]
    e = html.escape
    cabecalho = f"🎯 <b>{len(jobs)} vagas novas</b> · top {len(top)}\n"
    if painel_url:
        rotulo = (
            f"Ver painel completo ({total_painel} vagas)"
            if total_painel
            else "Ver painel completo"
        )
        cabecalho += f'📋 <a href="{e(painel_url)}">{rotulo}</a>\n'
    cabecalho += "➖➖➖➖➖➖➖➖➖➖\n"
    blocos = [cabecalho]
    for job in top:
        remoto = " 🏠" if job.remote else ""
        local = f" · 📍 {e(job.location)}" if job.location else ""
        dica = f"💡 <i>{e(job.dica[:160])}</i>\n" if job.dica else ""
        blocos.append(
            f"\n{_score_emoji(job.score)} <b>{job.score}/10</b> · "
            f'<a href="{e(job.url)}">{e(job.title)}</a>\n'
            f"🏢 {e(job.company)}{local}{remoto}\n"
            f"📝 {e(job.resumo[:180])}\n"
            f"{dica}"
        )

    msg, partes = "", []
    for bloco in blocos:
        if len(msg) + len(bloco) > _TG_LIMIT:
            partes.append(msg)
            msg = ""
        msg += bloco
    if msg:
        partes.append(msg)

    # Sem botões de callback: webhook Apps Script responde 302 e o Telegram entra
    # em loop de retry. Ações de "apliquei" agora são feitas no painel (sincronizado).
    url = _TG_API.format(token=token)
    for parte in partes:
        corpo = {
            "chat_id": chat_id,
            "text": parte,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }
        try:
            resp = requests.post(url, json=corpo, timeout=30)
            resp.raise_for_status()
        except Exception as exc:  # noqa: BLE001
            log(f"  [Telegram] falha ao enviar: {exc}")
            return
    log(f"  [Telegram] enviado: {len(top)} vagas em {len(partes)} mensagem(ns)")
