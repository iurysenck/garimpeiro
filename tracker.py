"""Tracking de candidaturas — lê o Google Sheet alimentado pelo email-notf.gs.

O .gs grava linhas: [Data, Empresa, Vaga, Status, Resumo, Ação].
Aqui lemos o CSV público da planilha (sem auth) e devolvemos as candidaturas
para a página HTML montar a seção "Minhas Candidaturas".

Como publicar a planilha (uma vez): no Sheets → Compartilhar → "Qualquer pessoa
com o link: leitor". A URL CSV fica:
  https://docs.google.com/spreadsheets/d/<ID>/gviz/tq?tqx=out:csv
"""
from __future__ import annotations

import csv
import io

import requests

# Ordem de prioridade dos status (mais urgente primeiro)
_PRIORIDADE = {"AÇÃO": 0, "ACAO": 0, "AVANCOU": 1, "AVANÇOU": 1, "AGUARDANDO": 2, "REJEITADO": 3}


def buscar_candidaturas(csv_url: str, log) -> list[dict]:
    """Baixa e parseia o CSV da planilha. Lista vazia em qualquer falha."""
    if not csv_url:
        return []
    try:
        resp = requests.get(csv_url, timeout=30)
        resp.raise_for_status()
        resp.encoding = "utf-8"
        linhas = list(csv.reader(io.StringIO(resp.text)))
    except Exception as exc:  # noqa: BLE001
        log(f"  [Tracker] falha ao ler planilha: {exc}")
        return []

    if not linhas:
        return []

    # Detecta cabeçalho (se a 1ª linha parece título e não dados)
    inicio = 1 if "empresa" in " ".join(linhas[0]).lower() else 0
    candidaturas: list[dict] = []
    for row in linhas[inicio:]:
        if not any(c.strip() for c in row):
            continue
        row = (row + [""] * 8)[:8]
        candidaturas.append(
            {
                "data": row[0].strip(),
                "empresa": row[1].strip(),
                "vaga": row[2].strip(),
                "status": row[3].strip(),
                "resumo": row[4].strip(),
                "acao": row[5].strip(),
                "email": row[6].strip(),
                "link_acao": row[7].strip(),
            }
        )

    candidaturas.sort(key=lambda c: _PRIORIDADE.get(c["status"].upper(), 9))
    log(f"  [Tracker] {len(candidaturas)} candidaturas na planilha")
    return candidaturas


def buscar_aplicadas(csv_url: str, log) -> set[str]:
    """Lê a aba 'Aplicadas' (CSV público): coluna uid = vagas marcadas como aplicadas."""
    if not csv_url:
        return set()
    try:
        resp = requests.get(csv_url, timeout=30)
        resp.raise_for_status()
        resp.encoding = "utf-8"
        linhas = list(csv.reader(io.StringIO(resp.text)))
    except Exception as exc:  # noqa: BLE001
        log(f"  [Tracker] falha ao ler aplicadas: {exc}")
        return set()
    uids: set[str] = set()
    for row in linhas:
        if not row:
            continue
        uid = row[0].strip()
        if uid and uid.lower() != "uid":  # ignora cabeçalho
            uids.add(uid)
    log(f"  [Tracker] {len(uids)} vagas marcadas como aplicadas")
    return uids
