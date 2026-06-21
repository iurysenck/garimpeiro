#!/usr/bin/env python3
"""Países e estados/províncias para o instalador.

Brasil vem embutido (funciona offline, sem dependência). Outros países usam
`pycountry` (ISO 3166-1 países + 3166-2 subdivisões) quando instalado — é a
forma gratuita e offline de listar "tudo selecionando o país". Sem pycountry,
o seletor mostra só Brasil + "Outro" (campo livre).

Datasets gratuitos para internacionalizar mais a fundo:
  - pycountry (pip): países + estados/províncias (ISO). Já usado aqui.
  - dr5hn/countries-states-cities-database (GitHub, JSON): inclui cidades.
  - IBGE (Brasil): municípios via API/CSV pública.
"""
from __future__ import annotations

# (sigla, nome oficial com acento) — 26 estados + DF
BR_STATES: list[tuple[str, str]] = [
    ("AC", "Acre"), ("AL", "Alagoas"), ("AP", "Amapá"), ("AM", "Amazonas"),
    ("BA", "Bahia"), ("CE", "Ceará"), ("DF", "Distrito Federal"),
    ("ES", "Espírito Santo"), ("GO", "Goiás"), ("MA", "Maranhão"),
    ("MT", "Mato Grosso"), ("MS", "Mato Grosso do Sul"), ("MG", "Minas Gerais"),
    ("PA", "Pará"), ("PB", "Paraíba"), ("PR", "Paraná"), ("PE", "Pernambuco"),
    ("PI", "Piauí"), ("RJ", "Rio de Janeiro"), ("RN", "Rio Grande do Norte"),
    ("RS", "Rio Grande do Sul"), ("RO", "Rondônia"), ("RR", "Roraima"),
    ("SC", "Santa Catarina"), ("SP", "São Paulo"), ("SE", "Sergipe"),
    ("TO", "Tocantins"),
]


def countries() -> list[dict]:
    """Lista de países [{code, name}] — Brasil primeiro, resto via pycountry."""
    base = [{"code": "BR", "name": "Brasil"}]
    try:
        import pycountry

        resto = sorted(
            ({"code": c.alpha_2, "name": c.name} for c in pycountry.countries),
            key=lambda c: c["name"],
        )
        return base + [c for c in resto if c["code"] != "BR"]
    except Exception:  # noqa: BLE001
        return base


def states(country_code: str = "BR") -> list[dict]:
    """Estados/províncias [{code, name}] do país. Brasil embutido; resto pycountry."""
    cc = (country_code or "BR").upper()
    if cc == "BR":
        return [{"code": s, "name": n} for s, n in BR_STATES]
    try:
        import pycountry

        subs = pycountry.subdivisions.get(country_code=cc) or []
        out = [{"code": s.code.split("-")[-1], "name": s.name} for s in subs]
        return sorted(out, key=lambda s: s["name"])
    except Exception:  # noqa: BLE001
        return []


def cities(uf: str) -> list[str]:
    """Municípios de um estado BR (sigla de 2 letras) via API pública do IBGE.

    Chamada read-only, opcional (só preenche um datalist no instalador). Falha
    silenciosa → cidade vira campo livre. Outros países não têm lista de cidades aqui.
    """
    uf = (uf or "").strip().upper()
    if len(uf) != 2:
        return []
    try:
        import json
        import urllib.request

        url = f"https://servicodados.ibge.gov.br/api/v1/localidades/estados/{uf}/municipios"
        with urllib.request.urlopen(url, timeout=8) as r:
            data = json.load(r)
        return sorted(m["nome"] for m in data if m.get("nome"))
    except Exception:  # noqa: BLE001
        return []


def state_variants(country_code: str, code: str) -> list[str]:
    """Variantes p/ casar a vaga: [nome oficial, sigla]. Ex.: ('BR','RJ') ->
    ['Rio de Janeiro', 'RJ']. O matcher normaliza acento/caixa depois."""
    code = (code or "").strip()
    for s in states(country_code):
        if s["code"].upper() == code.upper():
            return [s["name"], s["code"]]
    return [code] if code else []
