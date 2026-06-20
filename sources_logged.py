"""Fonte logada: Vagas.com recomendadas (nodriver pega token fresco + API JSON).

nodriver abre a sessão (.nddata) off-screen, captura o Bearer da chamada interna
recomendacao_ia, e então o requests pagina a API — JSON limpo, sem raspar DOM.
Sessão expira: rode login_nodriver.py de novo quando o token não vier.
"""
from __future__ import annotations

import asyncio
from pathlib import Path

import nodriver as uc
import requests
from nodriver import cdp

from sources import Job

PROFILE = Path(__file__).resolve().parent / ".nddata"
RECO_PAGE = "https://www.vagas.com.br/meu-perfil/vagas-recomendadas"
API = "https://api-candidato.vagas.com.br/v2/vagas/recomendacao_ia/pt-BR?page={page}&per_page=24"
_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/124.0 Safari/537.36"


async def _capturar_token() -> tuple[str, str]:
    browser = await uc.start(
        user_data_dir=str(PROFILE),
        headless=False,
        browser_args=["--window-position=-2400,-2400", "--window-size=1200,860"],
    )
    auth: dict = {}

    def on_req(ev):
        try:
            if "recomendacao_ia" in ev.request.url:
                h = ev.request.headers
                a = h.get("Authorization") or h.get("authorization")
                if a:
                    auth["t"] = a
                    auth["ua"] = h.get("User-Agent") or h.get("user-agent") or _UA
        except Exception:
            pass

    tab = await browser.get("about:blank")
    tab.add_handler(cdp.network.RequestWillBeSent, on_req)
    await tab.send(cdp.network.enable())
    await tab.get(RECO_PAGE)
    for _ in range(15):
        await asyncio.sleep(1)
        if auth.get("t"):
            break
    try:
        browser.stop()
    except Exception:
        pass
    return auth.get("t", ""), auth.get("ua", _UA)


import re

WORKANA_PAGE = "https://www.workana.com/jobs?language=pt"
WORKANA_API = "https://www.workana.com/jobs?language=pt&category={cat}&page={page}"


async def _workana_projetos(cats: list[str], max_pages: int) -> list[dict]:
    browser = await uc.start(
        user_data_dir=str(PROFILE),
        headless=False,
        browser_args=["--window-position=-2400,-2400", "--window-size=1200,860"],
    )
    tab = await browser.get(WORKANA_PAGE)
    await asyncio.sleep(5)
    out: list[dict] = []
    for cat in cats:
        for page in range(1, max_pages + 1):
            url = WORKANA_API.format(cat=cat, page=page)
            js = (
                "(async()=>{try{const r=await fetch(%r,{credentials:'include',"
                "headers:{'Accept':'application/json','X-Requested-With':'XMLHttpRequest'}});"
                "return await r.text();}catch(e){return 'ERR '+e;}})()" % url
            )
            try:
                import json
                txt = await tab.evaluate(js, await_promise=True)
                res = json.loads(txt).get("results", {}).get("results", [])
            except Exception:
                break
            if not res:
                break
            for p in res:
                out.append({"slug": p.get("slug", ""), "title_html": p.get("title", ""),
                            "cat": cat})
    try:
        browser.stop()
    except Exception:
        pass
    return out


def fetch_workana_logged(cats: list[str], max_pages: int, log) -> list[Job]:
    """Projetos freelance da Workana (logado). Lista vazia se sem sessão."""
    if not PROFILE.exists():
        log("  [Workana] sem sessão (.nddata) — rode login_nodriver.py")
        return []
    try:
        raw = uc.loop().run_until_complete(_workana_projetos(cats, max_pages))
    except Exception as exc:  # noqa: BLE001
        log(f"  [Workana] falha: {exc}")
        return []
    jobs: list[Job] = []
    for p in raw:
        th = p.get("title_html", "")
        m = re.search(r'title="([^"]+)"', th)
        titulo = (m.group(1) if m else re.sub(r"<[^>]+>", "", th)).strip()
        slug = p.get("slug", "")
        if not titulo or not slug:
            continue
        jobs.append(
            Job(
                source="Workana",
                title=titulo,
                company="Cliente Workana",
                url=f"https://www.workana.com/job/{slug}",
                location="Remoto",
                remote=True,
                description=f"Freela · {p.get('cat', '')}",
                posted="",
                freela=True,
            )
        )
    log(f"  [Workana] {len(jobs)} projetos freela")
    return jobs


NF_PROJECTS = "https://www.99freelas.com.br/projects"
NF_PAGE = "https://www.99freelas.com.br/projects?page={page}"
# Só cards reais: meta contém "Propostas:". Notificações e /project/new ficam de fora.
_NF_JS = r"""(() => {
  const out=[];
  const vistos=new Set();
  document.querySelectorAll('a[href^="/project/"]').forEach(a=>{
    const h=(a.getAttribute('href')||'').split('?')[0];
    const titulo=(a.innerText||'').trim();
    if(!titulo || h==='/project/new' || vistos.has(h)) return;
    let box=a;
    for(let i=0;i<6 && box.parentElement;i++){
      box=box.parentElement;
      if((box.innerText||'').length>120) break;
    }
    const full=(box.innerText||'').replace(/\s+/g,' ').trim();
    if(!/Propostas:/.test(full)) return;   // descarta notificações
    vistos.add(h);
    // meta = tudo depois do título
    let meta=full.startsWith(titulo) ? full.slice(titulo.length).trim() : full;
    const partes=meta.split('|').map(s=>s.trim());
    const cat=partes[0]||'';
    const pub=(partes.find(p=>/^Publicado:/.test(p))||'').replace('Publicado:','').trim();
    out.push({h, titulo, categoria:cat, publicado:pub, meta:meta.slice(0,200)});
  });
  return JSON.stringify(out);
})()"""


async def _nf_projetos(max_pages: int) -> list[dict]:
    browser = await uc.start(
        user_data_dir=str(PROFILE),
        headless=False,
        browser_args=["--window-position=-2400,-2400", "--window-size=1200,860"],
    )
    out: list[dict] = []
    import json
    tab = await browser.get(NF_PROJECTS)
    await asyncio.sleep(7)
    for page in range(1, max_pages + 1):
        if page > 1:
            await tab.get(NF_PAGE.format(page=page))
            await asyncio.sleep(5)
        try:
            raw = await tab.evaluate(_NF_JS)
            cards = json.loads(raw)
        except Exception:
            break
        if not cards:
            break
        out += cards
    try:
        browser.stop()
    except Exception:
        pass
    return out


def fetch_99freelas_logged(max_pages: int, log) -> list[Job]:
    """Projetos freela do 99freelas (logado, raspa DOM). Vazio se sem sessão."""
    if not PROFILE.exists():
        log("  [99freelas] sem sessão (.nddata) — rode login_nodriver.py")
        return []
    try:
        raw = uc.loop().run_until_complete(_nf_projetos(max_pages))
    except Exception as exc:  # noqa: BLE001
        log(f"  [99freelas] falha: {exc}")
        return []
    jobs: list[Job] = []
    vistos: set[str] = set()
    for p in raw:
        h = p.get("h", "")
        titulo = p.get("titulo", "").strip()
        if not h or not titulo or h in vistos:
            continue
        vistos.add(h)
        cat = p.get("categoria", "")
        jobs.append(
            Job(
                source="99freelas",
                title=titulo,
                company="Cliente 99freelas",
                url=f"https://www.99freelas.com.br{h}",
                location="Remoto",
                remote=True,
                description=f"Freela · {cat}. {p.get('meta', '')}".strip(),
                posted=p.get("publicado", ""),
                freela=True,
            )
        )
    log(f"  [99freelas] {len(jobs)} projetos freela")
    return jobs


CATHO_AREA = "https://www.catho.com.br/area-candidato/"
CATHO_APPLIES = "https://seguro.catho.com.br/area-candidato/api/applies-data/"


async def _catho_applies_text() -> str:
    browser = await uc.start(
        user_data_dir=str(PROFILE),
        headless=False,
        browser_args=["--window-position=-2400,-2400", "--window-size=1200,860"],
    )
    tab = await browser.get(CATHO_AREA)
    await asyncio.sleep(5)
    await tab.get(CATHO_APPLIES)
    await asyncio.sleep(3)
    try:
        txt = await tab.evaluate("document.body.innerText")
    except Exception:
        txt = ""
    try:
        browser.stop()
    except Exception:
        pass
    return txt or ""


def fetch_catho_applies(log) -> list[dict]:
    """Candidaturas reais do Catho (logado) — para a aba Candidaturas."""
    if not PROFILE.exists():
        log("  [Catho] sem sessão (.nddata) — rode login_nodriver.py")
        return []
    import json
    try:
        txt = uc.loop().run_until_complete(_catho_applies_text())
        data = json.loads(txt).get("data", {})
    except Exception as exc:  # noqa: BLE001
        log(f"  [Catho] falha: {exc}")
        return []
    ads = data.get("job_ads", []) if isinstance(data, dict) else []
    out = []
    for a in ads:
        out.append(
            {
                "data": "",
                "empresa": a.get("company_name") or "",
                "vaga": a.get("title") or "",
                "status": a.get("resume_hiring_process_status") or "—",
                "resumo": "Candidatura no Catho",
                "acao": "",
                "email": "",
                "link_acao": a.get("link") or "",
            }
        )
    log(f"  [Catho] {len(out)} candidaturas")
    return out


def fetch_vagas_logged(max_pages: int, log) -> list[Job]:
    """Vagas.com recomendadas (logado). Lista vazia se sem sessão/token."""
    if not PROFILE.exists():
        log("  [Vagas.com] sem sessão (.nddata) — rode login_nodriver.py")
        return []
    try:
        token, ua = uc.loop().run_until_complete(_capturar_token())
    except Exception as exc:  # noqa: BLE001
        log(f"  [Vagas.com] nodriver falhou: {exc}")
        return []
    if not token:
        log("  [Vagas.com] token não capturado — sessão expirou? rode login_nodriver.py")
        return []

    sess = requests.Session()
    sess.headers.update({"Authorization": token, "User-Agent": ua, "Accept": "application/json"})
    jobs: list[Job] = []
    for page in range(1, max_pages + 1):
        try:
            r = sess.get(API.format(page=page), timeout=30)
            r.raise_for_status()
            arr = r.json().get("candidato_versus_vaga", [])
        except Exception as exc:  # noqa: BLE001
            log(f"  [Vagas.com] página {page}: {exc}")
            break
        if not arr:
            break
        for o in arr:
            if o.get("pcd"):  # vaga reservada a PcD
                continue
            loc = (o.get("location") or "").replace(" - BR", "").strip()
            company = o.get("company_name") or ("Confidencial" if o.get("confidential") else "")
            jobs.append(
                Job(
                    source="Vagas.com",
                    title=(o.get("vacancy_title") or "").strip(),
                    company=(company or "").strip(),
                    url=o.get("url") or "",
                    location=loc,
                    remote="remoto" in loc.lower() or "home office" in loc.lower(),
                    description=f"{o.get('level', '')}. {o.get('positions_number', '')} vaga(s)".strip(),
                    posted="",
                )
            )
        log(f"  [Vagas.com] página {page}: {len(arr)} vagas")
    return jobs


# ===== Jobbol (agregador BR; Cloudflare bloqueia requests, nodriver passa) =====
# Sem login. As vagas listam em /cargos/<slug> como .card-vaga; cada card traz o
# jobkey (= /vaga/<id>) e o texto com data/título/local/empresa.
JOBBOL_CARGO = "https://www.jobbol.com.br/cargos/{slug}"
_JOBBOL_JS = r"""(() => {
  const out=[]; const vistos=new Set();
  document.querySelectorAll('a[href*="jobkey="]').forEach(a=>{
    const m=(a.getAttribute('href')||'').match(/jobkey=(\d+)/); if(!m)return;
    const id=m[1]; if(vistos.has(id))return; vistos.add(id);
    let box=a;
    for(let i=0;i<8&&box.parentElement;i++){box=box.parentElement;
      if((box.className||'').indexOf('card-vaga')>-1||(box.innerText||'').length>70)break;}
    out.push({id, txt:(box.innerText||'').replace(/\s+/g,' ').trim().slice(0,300)});
  });
  return JSON.stringify(out);
})()"""

_JB_DATE = re.compile(r"(\d{2})/(\d{2})/(\d{4})")
# "<título MAIÚSCULO> <Cidade Title-case> / UF" antes de "Oportunidade"
_JB_HEAD = re.compile(r"(.+?)\s*/\s*([A-Z]{2})\b")
_JB_EMP = re.compile(r"\bem\s+(.+?),\s*c[óo]d", re.I)
_JB_AREA = re.compile(r"na área de\s+(.+?)\s+em\s", re.I)


def _parse_jobbol(card: dict) -> dict | None:
    txt = card.get("txt", "")
    cid = card.get("id", "")
    if not txt or not cid:
        return None
    d = _JB_DATE.search(txt)
    posted = f"{d.group(3)}-{d.group(2)}-{d.group(1)}" if d else ""
    rest = txt[d.end():].strip() if d else txt
    head = rest.split("Oportunidade")[0].strip()  # "TÍTULO Cidade / UF"
    titulo, loc = head, ""
    m = _JB_HEAD.search(head)
    if m:
        left, uf = m.group(1).strip(), m.group(2)
        toks = left.split()
        # título = sequência inicial de tokens MAIÚSCULOS (cidade vem em Title-case)
        ti: list[str] = []
        while toks and (toks[0].isupper() or toks[0] in "-–"):
            ti.append(toks.pop(0))
        titulo = " ".join(ti).strip(" -–·") or left
        cidade = " ".join(toks).strip()
        loc = f"{cidade} / {uf}" if cidade else uf
    if titulo.isupper():
        titulo = titulo.title()
    emp = _JB_EMP.search(txt)
    company = emp.group(1).strip() if emp else "Confidencial"
    area = _JB_AREA.search(txt)
    desc = f"Área: {area.group(1).strip()}. " if area else ""
    return {
        "id": cid,
        "titulo": titulo,
        "company": company,
        "location": loc,
        "posted": posted,
        "desc": desc + txt[:200],
    }


async def _jobbol_cards(slugs: list[str], max_pages: int) -> list[dict]:
    import json
    browser = await uc.start(
        user_data_dir=str(PROFILE),
        headless=False,
        browser_args=["--window-position=-2400,-2400", "--window-size=1200,860"],
    )
    out: list[dict] = []
    seen: set[str] = set()  # dedup de id entre todos os cargos
    tab = await browser.get("about:blank")
    for slug in slugs:
        for page in range(1, max_pages + 1):
            url = JOBBOL_CARGO.format(slug=slug) + (f"?page={page}" if page > 1 else "")
            try:
                await tab.get(url)
                await asyncio.sleep(6 if page == 1 else 3)
                await tab.evaluate("window.scrollTo(0,document.body.scrollHeight)")
                await asyncio.sleep(2)
                cards = json.loads(await tab.evaluate(_JOBBOL_JS))
            except Exception:
                break
            novos = [c for c in cards if c.get("id") and c["id"] not in seen]
            if not novos:
                break
            for c in novos:
                seen.add(c["id"])
                out.append(c)
    try:
        browser.stop()
    except Exception:
        pass
    return out


def fetch_jobbol(slugs: list[str], max_pages: int, log) -> list[Job]:
    """Vagas do Jobbol por cargo (nodriver passa o Cloudflare, raspa o DOM)."""
    if not slugs:
        return []
    try:
        raw = uc.loop().run_until_complete(_jobbol_cards(slugs, max_pages))
    except Exception as exc:  # noqa: BLE001
        log(f"  [Jobbol] falha: {exc}")
        return []
    jobs: list[Job] = []
    for card in raw:
        p = _parse_jobbol(card)
        if not p or not p["titulo"]:
            continue
        t = f"{p['titulo']} {p['desc']}".lower()
        remoto = "remoto" in t or "home office" in t or "home-office" in t or "híbrid" in t
        jobs.append(
            Job(
                source="Jobbol",
                title=p["titulo"],
                company=p["company"],
                url=f"https://www.jobbol.com.br/vaga/{p['id']}",
                location=p["location"],
                remote=remoto,
                description=p["desc"],
                posted=p["posted"],
            )
        )
    log(f"  [Jobbol] {len(jobs)} vagas")
    return jobs
