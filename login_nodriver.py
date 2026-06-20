"""Login único (undetected) nos sites com nodriver — perfil dedicado .nddata.

Abre um Chrome real SEM flags de automação (o Google/anti-bot não bloqueia).
Faça login em cada aba e FECHE a janela — os cookies ficam salvos em .nddata/.
Depois o garimpeiro reusa esse perfil (off-screen/background) para raspar logado.

Rode:  .venv\\Scripts\\python.exe login_nodriver.py
NUNCA comite .nddata/ (contém sua sessão).
"""
from __future__ import annotations

import asyncio
from pathlib import Path

import nodriver as uc

PROFILE = Path(__file__).resolve().parent / ".nddata"
SITES = [
    "https://www.workana.com/login",
    "https://www.99freelas.com.br/login",
    "https://www.vagas.com.br/login",
    "https://www.catho.com.br/",
]


async def main() -> None:
    browser = await uc.start(user_data_dir=str(PROFILE), headless=False)
    await browser.get(SITES[0])
    for url in SITES[1:]:
        await browser.get(url, new_tab=True)
    print(">>> Faça login em cada aba. FECHE a janela quando terminar. <<<", flush=True)
    while True:
        try:
            await asyncio.sleep(2)
            if not browser.tabs:
                break
        except Exception:
            break
    try:
        browser.stop()
    except Exception:
        pass
    print("Sessão salva em .nddata/")


if __name__ == "__main__":
    uc.loop().run_until_complete(main())
