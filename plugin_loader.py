"""Carregador de plugins — estenda o garimpeiro sem tocar no core.

Coloque um arquivo .py em plugins/ com um dict META e uma função:

  META = {"name": "Minha Fonte", "type": "source", "enabled": True}
  def fetch(cfg, log) -> list[Job]:        # type "source": adiciona vagas
      ...

  # ou um painel/seção no app:
  META = {"name": "Meu Widget", "type": "panel", "enabled": True}
  def panel_html(cfg) -> str:              # type "panel": injeta HTML auto-contido
      return "<section class='group'>...</section>"

Arquivos começando com "_" são ignorados. Um plugin que dá erro é só pulado (WARN),
nunca derruba a rodada. Veja plugins/exemplo_fonte.py.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path


def load_plugins(base, log=None):
    """Devolve (sources, panels):
    sources = [(meta, fetch_callable), ...]
    panels  = [(meta, panel_html_callable), ...]
    """
    pdir = Path(base) / "plugins"
    sources: list[tuple[dict, callable]] = []
    panels: list[tuple[dict, callable]] = []
    if not pdir.exists():
        return sources, panels
    for f in sorted(pdir.glob("*.py")):
        if f.name.startswith("_"):
            continue
        try:
            spec = importlib.util.spec_from_file_location(f"plugin_{f.stem}", f)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)  # type: ignore[union-attr]
            meta = getattr(mod, "META", {}) or {}
            if not meta.get("enabled", True):
                continue
            tipo = meta.get("type")
            if tipo == "source" and hasattr(mod, "fetch"):
                sources.append((meta, mod.fetch))
            elif tipo == "panel" and hasattr(mod, "panel_html"):
                panels.append((meta, mod.panel_html))
        except Exception as exc:  # noqa: BLE001
            if log:
                log(f"  [Plugin] falha em {f.name}: {exc}", level="WARN")
    return sources, panels
