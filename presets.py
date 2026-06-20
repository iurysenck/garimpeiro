"""Presets de área — o usuário escolhe quais quer garimpar.

Cada preset mapeia para: termos de busca (Gupy/JobSpy), categorias do Trampos.co
e cargos do Jobbol. O wizard (garimpeiro.py setup) junta os presets escolhidos e
escreve no config.yaml. Dá pra misturar vários e/ou adicionar termos manuais.

Cobertura ampla de propósito: criativo, tech, marketing, conteúdo, negócios, etc.
Adicione/edite presets à vontade — é só dado, sem lógica.
"""
from __future__ import annotations

PRESETS: dict[str, dict] = {
    "design": {
        "label": "Design gráfico / Diretor de arte / Identidade visual",
        "search_terms": [
            "designer gráfico", "designer", "diretor de arte", "arte finalista",
            "identidade visual", "comunicação visual", "designer de produto",
            "design de embalagem", "branding",
        ],
        "trampos_categories": ["design", "criacao"],
        "jobbol_cargos": ["designer-grafico", "designer", "diretor-de-arte"],
    },
    "ux-ui": {
        "label": "UX/UI / Product Design",
        "search_terms": [
            "ux designer", "ui designer", "product designer", "ux/ui",
            "ux writer", "design de produto", "designer de interface",
        ],
        "trampos_categories": ["design", "produto"],
        "jobbol_cargos": ["ux-designer", "ui-designer", "product-designer"],
    },
    "social": {
        "label": "Social Media / Community / Mídias sociais",
        "search_terms": [
            "social media", "mídias sociais", "community manager",
            "analista de redes sociais", "gestor de mídias sociais",
        ],
        "trampos_categories": ["social-media", "midia"],
        "jobbol_cargos": ["social-media", "midias-sociais"],
    },
    "audiovisual": {
        "label": "Fotografia / Vídeo / Filmmaker / Edição",
        "search_terms": [
            "fotógrafo", "filmmaker", "videomaker", "editor de vídeo",
            "edição de vídeo", "edição de fotos", "tratamento de imagem",
            "produtor audiovisual", "cinegrafista", "assistente de fotografia",
            "DIT", "data wrangler",
        ],
        "trampos_categories": ["producao", "rtv", "criacao"],
        "jobbol_cargos": ["fotografo", "editor-de-video", "videomaker"],
    },
    "motion": {
        "label": "Motion / Animação / Ilustração / 3D",
        "search_terms": [
            "motion designer", "animador", "motion graphics", "ilustrador",
            "designer 3d", "artista 3d", "vfx",
        ],
        "trampos_categories": ["design", "criacao"],
        "jobbol_cargos": ["motion-designer", "ilustrador", "animador"],
    },
    "web": {
        "label": "Web Designer / Front-end / No-code",
        "search_terms": [
            "web designer", "desenvolvedor front-end", "front end",
            "desenvolvedor web", "wordpress", "webflow", "landing page",
        ],
        "trampos_categories": ["design", "ti"],
        "jobbol_cargos": ["web-designer", "desenvolvedor-front-end"],
    },
    "dev": {
        "label": "Programação / Desenvolvimento (geral)",
        "search_terms": [
            "desenvolvedor", "programador", "engenheiro de software",
            "back-end", "full stack", "python", "javascript",
        ],
        "trampos_categories": ["ti"],
        "jobbol_cargos": ["desenvolvedor", "programador"],
    },
    "marketing": {
        "label": "Marketing / Tráfego / Growth",
        "search_terms": [
            "marketing", "analista de marketing", "tráfego pago",
            "growth", "marketing digital", "performance",
        ],
        "trampos_categories": ["marketing", "midia"],
        "jobbol_cargos": ["marketing", "analista-de-marketing"],
    },
    "conteudo": {
        "label": "Redação / Conteúdo / Copy",
        "search_terms": [
            "redator", "copywriter", "redação", "produtor de conteúdo",
            "content", "revisor", "jornalista",
        ],
        "trampos_categories": ["criacao", "marketing"],
        "jobbol_cargos": ["redator", "copywriter"],
    },
    "produto-projetos": {
        "label": "Produto / Projetos / Gestão",
        "search_terms": [
            "product manager", "gerente de produto", "gerente de projetos",
            "product owner", "scrum master",
        ],
        "trampos_categories": ["produto", "negocios"],
        "jobbol_cargos": ["product-manager", "gerente-de-projetos"],
    },
    "dados": {
        "label": "Dados / Analytics / BI",
        "search_terms": [
            "analista de dados", "cientista de dados", "bi",
            "data analyst", "engenheiro de dados", "power bi",
        ],
        "trampos_categories": ["ti"],
        "jobbol_cargos": ["analista-de-dados"],
    },
    "admin": {
        "label": "Administrativo / Atendimento / Vendas",
        "search_terms": [
            "assistente administrativo", "atendimento", "vendas",
            "comercial", "recepcionista", "auxiliar administrativo",
        ],
        "trampos_categories": ["negocios"],
        "jobbol_cargos": ["assistente-administrativo", "vendas", "atendimento"],
    },
}


def montar(escolhidos: list[str]) -> dict:
    """Junta os presets escolhidos num bloco de config (sem duplicar)."""
    termos: list[str] = []
    trampos: list[str] = []
    cargos: list[str] = []
    for nome in escolhidos:
        p = PRESETS.get(nome)
        if not p:
            continue
        for t in p["search_terms"]:
            if t not in termos:
                termos.append(t)
        for c in p["trampos_categories"]:
            if c not in trampos:
                trampos.append(c)
        for c in p["jobbol_cargos"]:
            if c not in cargos:
                cargos.append(c)
    return {
        "search_terms": termos,
        "trampos_categories": trampos,
        "jobbol_cargos": cargos,
    }
