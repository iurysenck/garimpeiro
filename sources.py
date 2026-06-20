"""Fontes de vagas: Gupy (API oculta) + JobSpy (Indeed/LinkedIn/Google).

Cada fetcher devolve uma lista de objetos Job normalizados.
"""
from __future__ import annotations

import hashlib
import re
import time
import unicodedata
from dataclasses import dataclass

import requests

GUPY_API = "https://employability-portal.gupy.io/api/v1/jobs"
_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)
_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")

# Palavras-ruído removidas antes de comparar vagas (não distinguem a vaga em si).
_NOISE = {
    "vaga", "vagas", "efetivo", "pj", "clt", "home", "office", "homeoffice", "remoto",
    "remota", "hibrido", "hibrida", "presencial", "junior", "jr", "pleno", "pl",
    "senior", "sr", "estagio", "estagiario", "trainee", "temporario", "freelancer",
    "freela", "freelance", "afirmativa", "pcd", "exclusiva", "exclusivo", "banco",
    "talentos", "urgente", "contrata", "contratacao", "oportunidade", "the", "of",
    "i", "ii", "iii", "iv", "de", "da", "do", "das", "dos", "e", "para", "com", "em",
    "a", "o", "as", "os", "no", "na",
}
# Empresas genéricas: quando uma das vagas não diz a empresa real, comparar só o cargo.
_GENERIC_CO = {
    "", "confidencial", "empresa", "cliente", "contratante", "grupo", "agencia",
    "consultoria", "rh", "recrutamento", "cliente workana", "cliente 99freelas",
}


def _strip_accents(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))


def normalizar(s: str) -> str:
    """minúsculo, sem acento, só alfanumérico, espaços colapsados."""
    s = _strip_accents((s or "").lower())
    s = re.sub(r"[^a-z0-9 ]", " ", s)
    return _WS_RE.sub(" ", s).strip()


def sig_tokens(s: str) -> frozenset:
    """Conjunto de tokens significativos (sem ruído) para comparar similaridade."""
    return frozenset(t for t in normalizar(s).split() if t not in _NOISE and len(t) > 1)


def empresa_generica(c: str) -> bool:
    return normalizar(c) in _GENERIC_CO


def jaccard(a: frozenset, b: frozenset) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


@dataclass
class Job:
    """Vaga normalizada de qualquer fonte."""

    source: str
    title: str
    company: str
    url: str
    location: str = ""
    remote: bool = False
    description: str = ""
    posted: str = ""  # ISO yyyy-mm-dd
    freela: bool = False
    # preenchidos pelo matcher
    score: int = 0
    resumo: str = ""
    motivo: str = ""
    dica: str = ""
    pitch: str = ""  # mensagem de candidatura pronta (gerada pela IA)

    @property
    def uid(self) -> str:
        base = (self.url or f"{self.source}|{self.title}|{self.company}").strip().lower()
        return hashlib.sha1(base.encode("utf-8")).hexdigest()

    @property
    def dkey(self) -> str:
        """Chave de dedup semântica: tokens normalizados de título+empresa (sem
        acento, sem ruído, ordenados) — pega a mesma vaga em fontes diferentes."""
        t = " ".join(sorted(sig_tokens(self.title)))
        c = " ".join(sorted(sig_tokens(self.company)))
        return hashlib.sha1(f"{t}|{c}".encode("utf-8")).hexdigest()

    @property
    def tsig(self) -> frozenset:
        """Assinatura de tokens do título (para comparação fuzzy)."""
        return sig_tokens(self.title)

    @property
    def csig(self) -> frozenset:
        """Assinatura de tokens da empresa (vazia = empresa genérica/omitida)."""
        return frozenset() if empresa_generica(self.company) else sig_tokens(self.company)


def _clean(text: str, limit: int = 1500) -> str:
    """Remove HTML e normaliza espaços, cortando em `limit` chars."""
    if not text:
        return ""
    text = _TAG_RE.sub(" ", text)
    text = _WS_RE.sub(" ", text).strip()
    return text[:limit]


def fetch_gupy(terms: list[str], max_per_term: int, log) -> list[Job]:
    """Consulta a API pública do portal Gupy para cada termo."""
    jobs: list[Job] = []
    sess = requests.Session()
    sess.headers.update({"User-Agent": _UA, "Accept": "application/json"})
    for term in terms:
        try:
            resp = sess.get(
                GUPY_API,
                params={"jobName": term, "limit": max_per_term, "offset": 0},
                timeout=30,
            )
            resp.raise_for_status()
            data = resp.json().get("data", [])
        except Exception as exc:  # noqa: BLE001
            log(f"  [Gupy] falha '{term}': {exc}")
            continue
        for j in data:
            jobs.append(
                Job(
                    source="Gupy",
                    title=(j.get("name") or "").strip(),
                    company=(j.get("careerPageName") or "").strip(),
                    url=j.get("jobUrl") or "",
                    location=f"{j.get('city') or ''}/{j.get('state') or ''}".strip("/"),
                    remote=bool(j.get("isRemoteWork")),
                    description=_clean(j.get("description", "")),
                    posted=(j.get("publishedDate") or "")[:10],
                )
            )
        log(f"  [Gupy] '{term}': {len(data)} vagas")
        time.sleep(0.5)  # gentil com a API
    return jobs


def fetch_jobspy(
    terms: list[str],
    sites: list[str],
    location_full: str,
    hours_old: int,
    max_per_term: int,
    log,
    country: str = "Brazil",
) -> list[Job]:
    """Usa a lib JobSpy para Indeed/LinkedIn/Google de uma vez."""
    try:
        from jobspy import scrape_jobs
    except ImportError:
        log("  [JobSpy] lib não instalada — pulando (pip install python-jobspy)")
        return []

    jobs: list[Job] = []
    for term in terms:
        try:
            df = scrape_jobs(
                site_name=sites,
                search_term=term,
                google_search_term=f"{term} vaga {location_full}",
                location=location_full,
                results_wanted=max_per_term,
                hours_old=hours_old or None,
                country_indeed=country,
                verbose=0,
            )
        except Exception as exc:  # noqa: BLE001
            log(f"  [JobSpy] falha '{term}': {exc}")
            continue
        if df is None or df.empty:
            log(f"  [JobSpy] '{term}': 0 vagas")
            continue
        for _, row in df.iterrows():
            url = str(row.get("job_url") or row.get("job_url_direct") or "")
            if not url:
                continue
            jobs.append(
                Job(
                    source=str(row.get("site") or "JobSpy").capitalize(),
                    title=str(row.get("title") or "").strip(),
                    company=str(row.get("company") or "").strip(),
                    url=url,
                    location=str(row.get("location") or "").strip(),
                    remote=bool(row.get("is_remote")),
                    description=_clean(str(row.get("description") or "")),
                    posted=str(row.get("date_posted") or "")[:10],
                )
            )
        log(f"  [JobSpy] '{term}': {len(df)} vagas")
        time.sleep(1.0)
    return jobs


TRAMPOS_API = "https://www.trampos.co/api/v2/opportunities"


def fetch_trampos(categorias: list[str], max_pages: int, log) -> list[Job]:
    """API pública do Trampos.co (criativo BR) — sem login.

    categorias: slugs (design, social-media, criacao, producao, rtv, marketing, midia...).
    """
    jobs: list[Job] = []
    sess = requests.Session()
    sess.headers.update({"User-Agent": _UA, "Accept": "application/json"})
    base = [("ct[]", c) for c in categorias] + [("tp[]", "emprego"), ("tp[]", "freela")]
    for page in range(1, max_pages + 1):
        try:
            resp = sess.get(TRAMPOS_API, params=base + [("page", page)], timeout=30)
            resp.raise_for_status()
            ops = resp.json().get("opportunities", [])
        except Exception as exc:  # noqa: BLE001
            log(f"  [Trampos] falha página {page}: {exc}")
            break
        if not ops:
            break
        for o in ops:
            cidade = (o.get("city") or "").strip()
            estado = (o.get("state") or "").strip()
            remoto = bool(o.get("hybrid")) or cidade.lower().startswith("remot") or (
                "home" in cidade.lower()
            )
            salario = o.get("salary") or ""
            tipo = f"{o.get('type_slug', '')} {o.get('type_name', '')}".lower()
            jobs.append(
                Job(
                    source="Trampos",
                    title=(o.get("name") or "").strip(),
                    company=(o.get("custom_company_name") or "Empresa confidencial").strip(),
                    url=f"https://www.trampos.co/oportunidades/{o.get('id')}",
                    location=f"{cidade}/{estado}".strip("/"),
                    remote=remoto,
                    description=f"{o.get('category_name', '')}. {('Salário: ' + salario) if salario else ''}".strip(),
                    posted=(o.get("published_at") or "")[:10],
                    freela="freela" in tipo,
                )
            )
        log(f"  [Trampos] página {page}: {len(ops)} vagas")
        time.sleep(0.6)
    return jobs


def in_scope(job: Job, accepted_states: list[str], include_remote: bool) -> bool:
    """Filtra por escopo: estados aceitos + remoto."""
    loc = (job.location or "").lower()
    if include_remote and (job.remote or "remot" in loc or "home office" in loc):
        return True
    return any(state.lower() in loc for state in accepted_states)


# PCD no título = vaga reservada a PcD. Exclusividade na descrição idem.
_PCD_TITLE = re.compile(r"\b(pcd|pne)\b|defici[êe]nci", re.IGNORECASE)
_PCD_EXCL = re.compile(
    r"(exclusiv\w*|afirmativ\w*|reservad\w*|destinad\w*|somente|apenas)"
    r"[^.]{0,45}(pcd|pne|defici[êe]nci)"
    r"|(pcd|pne|defici[êe]nci)[^.]{0,45}(exclusiv\w*|reservad\w*|afirmativ\w*)",
    re.IGNORECASE,
)


def is_pcd_exclusive(job: Job) -> bool:
    """True se a vaga é reservada/exclusiva para PcD (candidato não elegível).

    Conservador: marca por PCD/deficiência no TÍTULO, ou exclusividade explícita
    na descrição. Não exclui vagas que apenas mencionam ser inclusivas.
    """
    if _PCD_TITLE.search(job.title or ""):
        return True
    return bool(_PCD_EXCL.search(job.description or ""))
