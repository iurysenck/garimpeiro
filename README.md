# 🪙 Garimpeiro de Vagas

Bot que garimpa vagas em várias fontes brasileiras, **ranqueia por IA** (Gemini, grátis),
deduplica e mostra num **painel** + alerta no **Telegram**. Você escolhe **quais áreas**
garimpar e **como rodar**. **Não se candidata a nada** — só lê, ranqueia e organiza.

Fontes: Gupy, Indeed/LinkedIn/Google (JobSpy), Trampos.co (públicas, sem login) e,
opcionais, Vagas.com / Catho / Workana / 99freelas / Jobbol (logadas).

---

## Instalação rápida (3 passos)

```bash
git clone <este-repo> garimpeiro && cd garimpeiro
python -m venv .venv && . .venv/bin/activate    # Windows: .venv\Scripts\activate
pip install -r requirements.txt

python garimpeiro.py setup     # assistente: escolhe áreas, fontes, modo, chaves
```

O assistente pergunta:
- **Quais áreas** garimpar (design, social, audiovisual, dev, marketing, dados… — escolha 1+)
- Cidade + se inclui remoto
- Chave do **Gemini** (grátis) e, opcional, **Telegram**
- **Fontes**: públicas (padrão) ou ativar as logadas
- **Como rodar** (3 modos abaixo)

Depois, edite seu currículo em `perfil.md` (é o que a IA usa pra pontuar) e rode:

```bash
python garimpeiro.py once       # uma coleta de teste
python garimpeiro.py serve      # abre o painel em http://localhost:8765
python garimpeiro.py schedule   # roda nos horários do config + serve o painel
```

---

## Os 3 modos (você escolhe no setup)

### 1. Local (mais simples, recomendado)
Tudo na sua máquina. `python garimpeiro.py schedule` roda nos horários e serve o
painel em `http://localhost:8765`. **Sem hospedagem, sem login externo, sem custo.**
Privado por padrão (só acessível na sua máquina).

### 2. Local + acesso remoto (ver no celular)
Igual ao modo 1, + **Tailscale** pra acessar de qualquer lugar com segurança:
1. Instale o [Tailscale](https://tailscale.com/) no PC e no celular (login grátis).
2. Deixe `python garimpeiro.py schedule` rodando.
3. No celular, acesse `http://<nome-do-pc>:8765` pela rede do Tailscale.

Privado pra você, sem domínio, sem configurar login. (Alternativa: `tailscale serve`
pra HTTPS.)

### 3. Painel na nuvem (avançado)
Publica o painel num host estático (Cloudflare Pages / Vercel) **com login** na frente.
Recomendado: **Cloudflare Pages + Access** (grátis). Resumo:
- Suba a pasta `public/` (após um `once`) via Wrangler: `npx wrangler pages deploy public`.
- Coloque o site atrás do **Cloudflare Access** (Zero Trust → Access → Application →
  só o seu e-mail). Isso bloqueia o acesso **antes** de renderizar — ninguém vê sem login.
- Sync entre dispositivos (arquivar/aplicado/favorito/notas) é **opcional** via Google
  Apps Script (veja `docs/` se incluído). No modo local não precisa.

> ⚠️ Não use host estático público **sem** auth (Access/senha) — qualquer um com o link
> veria suas vagas/notas.

---

## Fontes logadas (opcional)
Vagas.com, Catho, Workana, 99freelas e Jobbol exigem **Chrome** + login manual:

```bash
python login_nodriver.py     # abre o Chrome; logue nos sites; feche
```

São mais frágeis (anti-bot, sessão expira). Por isso vêm **desligadas** por padrão.
Quando uma vier 0 várias vezes, é sinal de sessão expirada — rode o login de novo.

---

## Segurança
- Segredos só no `.env` (gitignored). `config.yaml` e `perfil.md` também são gitignored.
- Modo local = privado por construção. Modo nuvem = **sempre** atrás de login (Access).
- Sessões logadas ficam locais (`.nddata/`), nunca saem da máquina.
- Sem auto-candidatura (decisão de produto).

## Como funciona (resumo técnico)
`garimpeiro.py` (CLI) → `main.py` (orquestra) → `sources*.py` (coleta) →
`store.py` (dedup 3 camadas, SQLite) → `matcher.py` (Gemini: score/resumo/pitch) →
`report.py` (painel HTML + Telegram). Detalhes em `DOCS.md` se incluído.

## Licença
MIT — veja `LICENSE`.
