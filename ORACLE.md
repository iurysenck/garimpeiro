# Rodar 24/7 de graça na Oracle Cloud (VM ARM) — guia seguro

Tutorial pra hospedar o garimpeiro numa **VM ARM grátis pra sempre** da Oracle Cloud.
Sem dados pessoais aqui — é genérico, e o foco é **segurança**.

> **Atualização (jun/2026):** o limite Always Free do ARM (Ampere A1) passou a ser
> **2 OCPU + 12 GB RAM** (antes 4/24) + 200 GB de disco. Ainda sobra MUITO pro projeto —
> inclusive fontes logadas (Chromium cabe em 12 GB).

---

## 1. O que muda no paradigma

| Antes (seu PC) | Com a VM Oracle |
|----------------|-----------------|
| PC/Windows ligado 24/7 | VM Linux sempre ligada, **independente do seu PC** |
| Agendador do Windows | `systemd` (serviço Linux que reinicia sozinho) |
| Painel só na sua máquina | Painel acessível com segurança de qualquer lugar |
| Conta de luz do seu PC | **Grátis** (dentro do Always Free) |

Roda **tudo**: fontes públicas **e** logadas (a VM tem Chromium). Você loga uma vez
(via túnel SSH) e a sessão fica salva na VM.

---

## 2. Criar a VM ARM (passo a passo, jul/2026)

### 2.1 Região de origem (escolha com cuidado — não dá pra mudar depois)
Ao criar a conta, a **home region** é fixa. Regiões com mais capacidade ARM costumam ser
**US East (Ashburn)**, **US West (Phoenix)** e **Frankfurt**. Se a sua der "Out of
capacity" sempre, é o motivo nº 1 de dor de cabeça (passo 2.4).

### 2.2 Criar a instância
1. Console Oracle Cloud → menu ☰ → **Compute → Instances → Create instance**.
2. **Name:** `garimpeiro`.
3. **Image and shape → Edit:**
   - Image: **Ubuntu 22.04/24.04** (ou Oracle Linux) — versão **aarch64/ARM**.
   - Shape: **Ampere** → **VM.Standard.A1.Flex** → **2 OCPU / 12 GB** (o teto free atual).
4. **Networking:** deixe criar uma **VCN** nova + sub-rede pública. Marque
   **Assign a public IPv4 address**.
5. **Add SSH keys:** escolha **Generate a key pair for me** e **baixe a chave privada**
   (guarde bem!) ou cole a sua pública. **Nunca** use senha.
6. **Boot volume:** padrão (até 200 GB free no total).
7. **Create**.

### 2.3 Conectar
```bash
chmod 600 sua-chave.key
ssh -i sua-chave.key ubuntu@SEU_IP_PUBLICO   # Oracle Linux: opc@IP
```

### 2.4 Se der "Out of capacity"
Comum no free. Opções:
- **Tente de novo** a cada poucos minutos (capacidade abre quando outros liberam).
- **Mude a Availability Domain** (AD-1/2/3) no formulário.
- **Upgrade pra Pay As You Go**: NÃO cobra nada se você ficar dentro do Always Free, e
  dá acesso a um pool maior → resolve quase sempre.
- Scripts que ficam tentando sozinhos existem (ex.: `hitrov/oci-arm-host-capacity`).

---

## 3. Segurança da VM (faça ANTES de instalar o app)

A VM tem IP público — trate como exposta.

```bash
sudo apt update && sudo apt -y upgrade
sudo apt -y install ufw fail2ban git python3-venv

# Firewall: só SSH. NÃO abra a porta do painel (8765) pro mundo.
sudo ufw default deny incoming
sudo ufw default allow outgoing
sudo ufw allow 22/tcp
sudo ufw enable
sudo systemctl enable --now fail2ban
```

No **Console Oracle** (Networking → VCN → Security List da sub-rede): deixe **só** a
Ingress Rule de SSH (22). **Não** adicione regra pra 8765 — o painel será acessado por
túnel (passo 5), nunca exposto.

Boas práticas:
- **SSH só por chave** (sem senha). Opcional: trocar a porta 22, criar usuário sem root.
- `sudo` com senha forte; mantenha o SO atualizado (`unattended-upgrades`).
- Segredos só no `.env` (já é assim).

---

## 4. Instalar o OSS na VM

```bash
git clone <URL-do-repo> garimpeiro && cd garimpeiro
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
python garimpeiro.py setup        # escolha áreas, fontes, modo 1 (local)
nano perfil.md                    # cole seu currículo
```

**Fontes logadas na VM (opcional):** precisa do Chromium + fazer login uma vez.
A VM é headless; logue via **túnel SSH + VNC** ou rode `login_nodriver.py` com um
display virtual (`xvfb`). Se for complexo, comece só com **fontes públicas** (funciona
liso) e ative logadas depois.

### Rodar 24/7 com systemd (reinicia sozinho)
```bash
sudo tee /etc/systemd/system/garimpeiro.service >/dev/null <<EOF
[Unit]
Description=Garimpeiro de Vagas
After=network-online.target

[Service]
User=$USER
WorkingDirectory=$HOME/garimpeiro
ExecStart=$HOME/garimpeiro/.venv/bin/python garimpeiro.py schedule
Restart=always

[Install]
WantedBy=multi-user.target
EOF
sudo systemctl daemon-reload
sudo systemctl enable --now garimpeiro
journalctl -u garimpeiro -f        # ver os logs ao vivo
```

---

## 5. Acessar o painel COM SEGURANÇA (sem expor a porta)

A VM serve o painel em `localhost:8765` **dentro dela**. Nunca abra essa porta no
firewall. Três formas seguras de ver de fora:

**A) Túnel SSH (mais simples, zero config extra)** — no seu PC:
```bash
ssh -i sua-chave.key -L 8765:localhost:8765 ubuntu@SEU_IP
# agora abra http://localhost:8765 no SEU navegador
```

**B) Tailscale (melhor pra celular)** — instale na VM e no celular:
```bash
curl -fsSL https://tailscale.com/install.sh | sh && sudo tailscale up
```
Acesse `http://<nome-da-vm>:8765` pela rede privada do Tailscale (só seus aparelhos).

**C) Cloudflare Tunnel + Access** — se quiser um domínio com login Google na frente
(igual o painel na nuvem). Mais passos; veja a seção Cloudflare do README.

> Resumo de segurança: **porta 8765 fechada no firewall**; acesso só por SSH/Tailscale/
> Cloudflare. Assim o painel (com suas vagas/notas) nunca fica público.

---

## 6. Custos e pegadinhas
- **Grátis** dentro do Always Free (2 OCPU/12 GB/200 GB). Telegram/Gemini têm tiers free.
- A Oracle pode **recuperar instâncias Always Free ociosas** — manter o `schedule`
  rodando (CPU/uso periódico) ajuda a não ser marcada como idle.
- Faça **backup** do `config.yaml`/`perfil.md` (eles ficam só na VM).

---

Pronto: com a VM da Oracle, o garimpeiro roda sozinho, de graça, independente do seu
Windows — e o painel só você acessa.
