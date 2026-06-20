"""TEMPLATE de plugin de FONTE de vagas.

O nome começa com "_" => o loader IGNORA este arquivo. Para usar:
  1. Copie para plugins/minha_fonte.py (sem o "_").
  2. Ajuste META["name"] e a função fetch().
  3. Retorne uma lista de Job (de sources.py).

A coleta roda esta fonte junto com as nativas; dedup/IA/painel vêm de graça.
Erros são capturados (a rodada não quebra) e podem virar issue no GitHub.
"""
from sources import Job

META = {"name": "Minha Fonte", "type": "source", "enabled": True}


def fetch(cfg, log) -> list[Job]:
    """cfg = dict do config.yaml; log(msg, level=...) para registrar.
    Retorne list[Job]. Exemplo (troque pela sua coleta real):"""
    # import requests
    # r = requests.get("https://api.exemplo.com/vagas", timeout=30); dados = r.json()
    dados = []  # <- sua coleta aqui
    vagas: list[Job] = []
    for d in dados:
        vagas.append(
            Job(
                source=META["name"],
                title=d.get("titulo", ""),
                company=d.get("empresa", ""),
                url=d.get("link", ""),
                location=d.get("local", ""),
                remote=bool(d.get("remoto")),
                description=d.get("descricao", ""),
                posted=d.get("data", ""),   # ISO yyyy-mm-dd se tiver
                freela=bool(d.get("freela")),
            )
        )
    log(f"  [{META['name']}] {len(vagas)} vagas")
    return vagas
