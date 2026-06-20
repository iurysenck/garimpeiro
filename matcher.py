"""Pontuação semântica das vagas com Gemini (tier grátis).

Envia o perfil + um lote de vagas e recebe score 0-10, resumo e motivo.
Em lote para economizar quota. Se a IA falhar, cai para score neutro.
"""
from __future__ import annotations

import json
import os
import re
import time

from sources import Job

_FENCE_RE = re.compile(r"^```(?:json)?|```$", re.MULTILINE)
_RETRY_RE = re.compile(r"retry.{0,12}?(\d+(?:\.\d+)?)s", re.IGNORECASE)
# Tier grátis = 15 req/min. ~4.2s entre chamadas mantém abaixo do limite.
_THROTTLE_S = 4.5
_MAX_WAIT_S = 65.0

_PROMPT = """Você avalia vagas para o candidato abaixo. Seja criterioso e honesto.

=== PERFIL DO CANDIDATO ===
{perfil}

=== VAGAS (avalie cada uma) ===
{vagas}

Para CADA vaga, devolva:
- "i": índice da vaga (inteiro, igual ao informado)
- "score": 0 a 10 — quão compatível com o perfil (10 = encaixe perfeito; <6 = fraco)
- "resumo": 1 a 2 frases em PT-BR resumindo a vaga (o que faz, requisitos-chave)
- "motivo": 1 frase em PT-BR explicando o score (por que combina ou não)
- "dica": 1 frase em PT-BR — o que o candidato deve destacar na candidatura/portfólio
  para essa vaga específica (ex: "destaque seus projetos de branding e a passagem pela Globo")
- "pitch": SÓ se score >= 6. Mensagem de candidatura pronta para colar, em PT-BR, 1ª pessoa,
  3 a 4 frases, tom profissional e direto. Apresente o candidato, conecte a experiência dele
  ao que a vaga pede e feche com disponibilidade. Sem saudação genérica tipo "Prezados".
  Se score < 6, deixe "" (string vazia).

Responda APENAS um array JSON válido, sem texto extra. Exemplo:
[{{"i":0,"score":8,"resumo":"...","motivo":"...","dica":"...","pitch":"..."}}]
"""


def _chunks(seq: list, n: int):
    for i in range(0, len(seq), n):
        yield seq[i : i + n]


def _format_vagas(batch: list[Job]) -> str:
    linhas = []
    for i, job in enumerate(batch):
        desc = job.description[:600]
        linhas.append(
            f"[{i}] Título: {job.title}\n"
            f"    Empresa: {job.company} | Local: {job.location} | "
            f"Remoto: {'sim' if job.remote else 'não'} | Fonte: {job.source}\n"
            f"    Descrição: {desc}"
        )
    return "\n\n".join(linhas)


def _parse(text: str) -> list[dict]:
    text = _FENCE_RE.sub("", text).strip()
    start, end = text.find("["), text.rfind("]")
    if start == -1 or end == -1:
        return []
    try:
        return json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return []


def _generate(client, model: str, prompt: str, log) -> list[dict]:
    """Chama o Gemini com 1 retry em caso de rate-limit (429)."""
    for tentativa in (1, 2):
        try:
            resp = client.models.generate_content(model=model, contents=prompt)
            return _parse(resp.text or "")
        except Exception as exc:  # noqa: BLE001
            msg = str(exc)
            rate_limited = "429" in msg or "RESOURCE_EXHAUSTED" in msg
            if rate_limited and tentativa == 1:
                m = _RETRY_RE.search(msg)
                espera = min(float(m.group(1)) + 1 if m else 40.0, _MAX_WAIT_S)
                log(f"  [Matcher] rate-limit; aguardando {espera:.0f}s e tentando de novo")
                time.sleep(espera)
                continue
            log(f"  [Matcher] erro Gemini: {msg[:160]}")
            return []
    return []


def score_jobs(jobs: list[Job], perfil: str, model: str, batch_size: int, log) -> None:
    """Atribui score/resumo/motivo a cada Job (mutação in-place)."""
    if not jobs:
        return
    api_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not api_key:
        log("  [Matcher] GEMINI_API_KEY ausente — usando score neutro (6)")
        for job in jobs:
            job.score, job.resumo = 6, job.description[:160]
            job.motivo = "Sem IA: score neutro. Configure GEMINI_API_KEY."
        return

    try:
        from google import genai
    except ImportError:
        log("  [Matcher] google-genai não instalado — score neutro")
        for job in jobs:
            job.score, job.resumo = 6, job.description[:160]
        return

    client = genai.Client(api_key=api_key)
    for bi, batch in enumerate(_chunks(jobs, batch_size)):
        if bi:
            time.sleep(_THROTTLE_S)  # respeita 15 req/min do tier grátis
        prompt = _PROMPT.format(perfil=perfil, vagas=_format_vagas(batch))
        results = _generate(client, model, prompt, log)

        by_index = {int(r["i"]): r for r in results if "i" in r}
        for i, job in enumerate(batch):
            r = by_index.get(i)
            if r:
                job.score = int(r.get("score", 0))
                job.resumo = str(r.get("resumo", "")).strip()
                job.motivo = str(r.get("motivo", "")).strip()
                job.dica = str(r.get("dica", "")).strip()
                job.pitch = str(r.get("pitch", "")).strip()
            else:
                job.score = 5
                job.resumo = job.description[:160]
                job.motivo = "IA não retornou avaliação desta vaga."
        log(f"  [Matcher] lote avaliado: {len(batch)} vagas")
