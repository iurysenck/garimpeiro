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
    "arquitetura": {
        "label": "Arquitetura / Interiores / Urbanismo",
        "search_terms": [
            "arquiteto", "arquitetura", "design de interiores", "urbanismo",
            "projetista", "revit", "autocad", "paisagismo",
        ],
        "trampos_categories": ["design", "criacao"],
        "jobbol_cargos": ["arquiteto", "projetista"],
    },
    "moda": {
        "label": "Moda / Estilismo / Têxtil",
        "search_terms": [
            "estilista", "designer de moda", "modelagem", "produção de moda",
            "consultor de moda", "têxtil", "vitrinismo",
        ],
        "trampos_categories": ["design", "criacao"],
        "jobbol_cargos": ["estilista", "designer-de-moda"],
    },
    "musica-audio": {
        "label": "Música / Produção de áudio / Sound design",
        "search_terms": [
            "produtor musical", "editor de áudio", "sound design", "mixagem",
            "engenheiro de som", "técnico de áudio", "podcast",
        ],
        "trampos_categories": ["producao", "rtv"],
        "jobbol_cargos": ["editor-de-audio", "produtor-musical"],
    },
    "games": {
        "label": "Games / Game design / Pixel art",
        "search_terms": [
            "game designer", "desenvolvedor de jogos", "unity", "unreal",
            "level designer", "pixel art", "narrative designer",
        ],
        "trampos_categories": ["design", "ti"],
        "jobbol_cargos": ["game-designer", "desenvolvedor-de-jogos"],
    },
    "engenharia": {
        "label": "Engenharia (civil / produção / mecânica)",
        "search_terms": [
            "engenheiro", "engenharia civil", "engenharia de produção",
            "engenheiro mecânico", "engenheiro eletricista", "planejamento",
        ],
        "trampos_categories": ["ti"],
        "jobbol_cargos": ["engenheiro", "engenheiro-civil"],
    },
    "financeiro": {
        "label": "Financeiro / Contábil / Controladoria",
        "search_terms": [
            "analista financeiro", "contador", "controladoria", "contas a pagar",
            "contas a receber", "tesouraria", "fiscal",
        ],
        "trampos_categories": ["negocios"],
        "jobbol_cargos": ["analista-financeiro", "contador"],
    },
    "rh": {
        "label": "RH / Recrutamento / Departamento pessoal",
        "search_terms": [
            "recursos humanos", "recrutamento e seleção", "analista de rh",
            "departamento pessoal", "business partner", "tech recruiter",
        ],
        "trampos_categories": ["negocios"],
        "jobbol_cargos": ["analista-de-rh", "recrutador"],
    },
    "juridico": {
        "label": "Jurídico / Advocacia / Paralegal",
        "search_terms": [
            "advogado", "assistente jurídico", "paralegal", "analista jurídico",
            "estágio em direito", "contratos",
        ],
        "trampos_categories": ["negocios"],
        "jobbol_cargos": ["advogado", "assistente-juridico"],
    },
    "saude": {
        "label": "Saúde / Enfermagem / Cuidados",
        "search_terms": [
            "enfermeiro", "técnico de enfermagem", "cuidador", "fisioterapeuta",
            "nutricionista", "psicólogo", "recepcionista de clínica",
        ],
        "trampos_categories": ["negocios"],
        "jobbol_cargos": ["enfermeiro", "tecnico-de-enfermagem"],
    },
    "educacao": {
        "label": "Educação / Professor / Tutoria",
        "search_terms": [
            "professor", "tutor", "instrutor", "coordenador pedagógico",
            "monitor", "designer instrucional", "ead",
        ],
        "trampos_categories": ["criacao"],
        "jobbol_cargos": ["professor", "instrutor"],
    },
    "logistica": {
        "label": "Logística / Estoque / Operações",
        "search_terms": [
            "logística", "estoquista", "almoxarife", "supply chain",
            "expedição", "operador de logística", "analista de operações",
        ],
        "trampos_categories": ["negocios"],
        "jobbol_cargos": ["logistica", "estoquista"],
    },
    "traducao": {
        "label": "Tradução / Idiomas / Revisão",
        "search_terms": [
            "tradutor", "revisor de texto", "legendagem", "intérprete",
            "localização", "transcrição",
        ],
        "trampos_categories": ["criacao", "marketing"],
        "jobbol_cargos": ["tradutor", "revisor"],
    },
    "eventos": {
        "label": "Produção de eventos / Cenografia",
        "search_terms": [
            "produtor de eventos", "cenógrafo", "assistente de produção",
            "coordenador de eventos", "montagem de eventos", "produção cultural",
        ],
        "trampos_categories": ["producao", "rtv"],
        "jobbol_cargos": ["produtor-de-eventos", "cenografo"],
    },
    "secretariado": {
        "label": "Secretariado / Assistente executivo",
        "search_terms": [
            "secretária", "assistente executivo", "assistente pessoal",
            "recepcionista", "auxiliar de escritório", "office manager",
        ],
        "trampos_categories": ["negocios"],
        "jobbol_cargos": ["secretaria", "assistente-executivo"],
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
