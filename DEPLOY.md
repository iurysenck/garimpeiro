# Deploy — rodar o Garimpeiro de graça, sem deixar o PC ligado

Não existe SaaS multi-usuário "de graça" de verdade (compute + cota de IA + dados
dos outros custam e dão responsabilidade). Mas dá pra cada pessoa rodar a **própria
instância** em camada gratuita, com a **própria chave** — a sensação de SaaS, custo
zero pra quem mantém o projeto. Abaixo, do mais fácil ao mais técnico.

> Em qualquer opção: o painel é HTML estático e as chaves ficam só no `.env`/secrets
> do seu serviço. Nada de credencial sua sobe pro repositório.

---

## 1) Grátis e automático — GitHub Actions + Cloudflare Pages (recomendado)

A coleta roda no **GitHub Actions** (cron grátis) e o painel é servido pelo
**Cloudflare Pages** (grátis). Não precisa de PC ligado.

1. **Fork** deste repositório pra sua conta.
2. No fork: **Settings → Secrets and variables → Actions → New repository secret**
   e adicione `GEMINI_API_KEY` (e, se quiser alertas, `TELEGRAM_BOT_TOKEN` e
   `TELEGRAM_CHAT_ID`). As fontes públicas não precisam de mais nada.
3. Edite o `config.yaml` (ou rode `python garimpeiro.py setup` localmente e suba o
   arquivo) com suas áreas/estado.
4. O workflow [`.github/workflows/garimpo.yml`](.github/workflows/garimpo.yml) já roda
   nos horários e gera o painel em `public/`.
5. **Painel:** crie um projeto no [Cloudflare Pages](https://pages.cloudflare.com/)
   apontando pra pasta `public/` do seu fork (build vazio, só assets). Grátis e com
   HTTPS. Quer acesso só pra você? Ative **Cloudflare Access** no projeto.

Custo: **R$ 0**. Limite do Actions free cobre tranquilo 2–3 coletas/dia.
Obs.: as **fontes logadas** (Vagas.com/Catho/etc.) não rodam bem em CI (precisam de
login com navegador) — no modo nuvem use só as públicas.

---

## 2) VM grátis pra sempre — Oracle Cloud Always Free

Uma máquina ARM que não expira, roda tudo (inclusive fontes logadas) e fica sua.
Passo a passo seguro em [ORACLE.md](ORACLE.md). Depois é só:

```bash
git clone <seu-fork> garimpeiro && cd garimpeiro
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
python garimpeiro.py setup        # ou setup --web pelo navegador
python garimpeiro.py schedule     # roda nos horários + serve o painel
```

Acesse de qualquer lugar com Tailscale/Cloudflare Tunnel (sem abrir portas).

---

## 3) Docker — qualquer VPS, NAS ou Raspberry Pi

Já existe um [Dockerfile](Dockerfile). Em qualquer host com Docker:

```bash
docker build -t garimpeiro .
docker run -d --env-file .env -v "$PWD/public:/app/public" --name garimpeiro garimpeiro
```

Sirva a pasta `public/` com qualquer servidor estático (ou Cloudflare Pages).

---

## 4) Render / Railway (camada gratuita, com ressalvas)

Dá pra rodar como **worker** (processo contínuo) usando o [`render.yaml`](render.yaml)
como blueprint no Render, ou um serviço equivalente no Railway. Atenção: as camadas
gratuitas têm **limites de horas/créditos** e podem hibernar — pra uso contínuo o
item 1 (Actions + Pages) ou o item 2 (Oracle) saem na frente. Configure as chaves
como variáveis de ambiente do serviço, nunca no repositório.

---

## Resumo

| Opção | Custo | PC ligado? | Fontes logadas | Esforço |
|---|---|---|---|---|
| GitHub Actions + Pages | grátis | não | não | baixo |
| Oracle Always Free | grátis | não | sim | médio |
| Docker (VPS/RPi) | varia | não | sim | médio |
| Render/Railway | grátis* | não | não | baixo |

\* com limites de horas/créditos.
