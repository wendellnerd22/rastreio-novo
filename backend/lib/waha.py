"""Cliente para o WAHA (WhatsApp HTTP API, devlikeapro/waha) — self-hosted.

Uma única instância do WAHA atende todas as lojas: cada loja usa uma *session*
própria dentro do WAHA (nome da sessão = id da loja), e o webhook dessa sessão
aponta para POST /api/webhooks/waha/{store_id} deste backend.

Sem WAHA_BASE_URL/WAHA_API_KEY configurados, send_text() só loga (não derruba o
webhook) — assim dá pra testar o recebimento sem uma instância WAHA no ar ainda.
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import os
import random
from typing import Any, Dict, Optional

import httpx

from lib.net_retry import RetriesExhausted, with_retry

TIMEOUT = 20.0

# Anti-banimento: intervalo mínimo entre mensagens da mesma sessão (loja), com jitter
# aleatório — evita rajadas de envio "perfeitas demais" que o WhatsApp associa a bot.
INTERVALO_MIN_SEGUNDOS = 1.5
INTERVALO_JITTER_SEGUNDOS = 2.5
_ultimo_envio_por_sessao: Dict[str, float] = {}
_lock_throttle = asyncio.Lock()


async def _aguardar_throttle(session: str) -> None:
    async with _lock_throttle:
        agora = asyncio.get_event_loop().time()
        ultimo = _ultimo_envio_por_sessao.get(session)
        espera_extra = random.uniform(0, INTERVALO_JITTER_SEGUNDOS)
        if ultimo is not None:
            decorrido = agora - ultimo
            faltando = INTERVALO_MIN_SEGUNDOS - decorrido
            if faltando > 0:
                espera_extra += faltando
        _ultimo_envio_por_sessao[session] = agora + espera_extra
    if espera_extra > 0:
        await asyncio.sleep(espera_extra)


def base_url() -> str:
    return os.environ.get("WAHA_BASE_URL", "").rstrip("/")


def api_key() -> str:
    return os.environ.get("WAHA_API_KEY", "").strip()


def webhook_hmac_key() -> str:
    return os.environ.get("WAHA_WEBHOOK_HMAC_KEY", "").strip()


class WahaError(Exception):
    pass


def assinatura_valida(raw_body: bytes, x_webhook_hmac: Optional[str],
                      algoritmo: Optional[str]) -> bool:
    """Confere X-Webhook-Hmac (documentado como sha512 por padrão no WAHA).
    Sem WAHA_WEBHOOK_HMAC_KEY configurado, não há o que validar (uso local/dev)."""
    secret = webhook_hmac_key()
    if not secret:
        return True
    if not x_webhook_hmac:
        return False
    algo = (algoritmo or "sha512").lower()
    digestmod = hashlib.sha512 if algo == "sha512" else hashlib.sha256
    esperado = hmac.new(secret.encode(), raw_body, digestmod).hexdigest()
    return hmac.compare_digest(esperado, x_webhook_hmac.lower())


async def send_text(session: str, chat_id: str, text: str) -> None:
    """Envia uma mensagem de texto de volta pelo WAHA. Silencioso (não levanta)
    se o WAHA não estiver configurado — útil em ambiente de testes."""
    url = base_url()
    if not url:
        return
    await _aguardar_throttle(session)  # anti-banimento: espaça os envios da mesma loja
    payload: Dict[str, Any] = {"session": session, "chatId": chat_id, "text": text}
    headers = {"Content-Type": "application/json"}
    if api_key():
        headers["X-Api-Key"] = api_key()
    async with httpx.AsyncClient(base_url=url, timeout=TIMEOUT) as http:
        try:
            resp = await with_retry(
                lambda: http.post("/api/sendText", json=payload, headers=headers),
                nome="WAHA",
            )
        except RetriesExhausted as exc:
            raise WahaError(f"WAHA indisponível (rede instável): {exc}") from exc
        except httpx.HTTPError as exc:
            raise WahaError(f"Falha de rede ao contatar o WAHA: {exc}") from exc
    if resp.status_code >= 400:
        raise WahaError(f"WAHA respondeu {resp.status_code}: {resp.text[:300]}")
