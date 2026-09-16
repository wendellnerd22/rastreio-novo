"""Cobrança PIX e link de checkout (cartão) via Mercado Pago.

Sem `MERCADOPAGO_ACCESS_TOKEN` no .env o provedor roda em modo SIMULADO: gera um
código PIX fictício e um link interno de checkout, com um botão de aprovação manual.
Assim o fluxo completo (cobrar → confirmar → criar pedido na LAD) é testável antes de
o revendedor ter conta no Mercado Pago.
"""
from __future__ import annotations

import hashlib
import hmac
import os
import uuid
from typing import Any, Dict, Optional, Tuple

import httpx

from lib.net_retry import RetriesExhausted, with_retry

MP_BASE = "https://api.mercadopago.com"
TIMEOUT = 20.0

# status normalizados do app
PENDENTE = "pendente"
APROVADO = "aprovado"
REJEITADO = "rejeitado"
EXPIRADO = "expirado"

_MP_MAP = {
    "approved": APROVADO,
    "authorized": APROVADO,
    "pending": PENDENTE,
    "in_process": PENDENTE,
    "in_mediation": PENDENTE,
    "rejected": REJEITADO,
    "cancelled": REJEITADO,
    "refunded": REJEITADO,
    "charged_back": REJEITADO,
}


def access_token() -> str:
    return os.environ.get("MERCADOPAGO_ACCESS_TOKEN", "").strip()


def simulado() -> bool:
    return not access_token()


def app_url() -> str:
    return os.environ.get("APP_URL", "").rstrip("/")


def _headers(idempotency_key: Optional[str] = None) -> Dict[str, str]:
    headers = {"Authorization": f"Bearer {access_token()}", "Content-Type": "application/json"}
    if idempotency_key:
        headers["X-Idempotency-Key"] = idempotency_key
    return headers


class PaymentError(Exception):
    pass


async def _mp(method: str, path: str, **kwargs: Any) -> Dict[str, Any]:
    async with httpx.AsyncClient(base_url=MP_BASE, timeout=TIMEOUT) as http:
        try:
            resp = await with_retry(lambda: http.request(method, path, **kwargs),
                                    nome="Mercado Pago")
        except RetriesExhausted as exc:
            raise PaymentError(f"Mercado Pago indisponível (rede instável): {exc}") from exc
        except httpx.HTTPError as exc:
            raise PaymentError(f"Falha de rede ao contatar o Mercado Pago: {exc}") from exc
    if resp.status_code >= 400:
        raise PaymentError(f"Mercado Pago respondeu {resp.status_code}: {resp.text[:300]}")
    return resp.json()


async def criar_cobranca_pix(intent_id: str, valor: float, descricao: str,
                             email: str) -> Dict[str, Any]:
    """Devolve {provider, provider_payment_id, status, pix_copia_e_cola, pix_qr_base64}."""
    if simulado():
        codigo = f"00020126SIMULADO-{intent_id.replace('-', '')[:20]}5204000053039865802BR"
        return {
            "provider": "simulado",
            "provider_payment_id": f"sim-{intent_id}",
            "status": PENDENTE,
            "pix_copia_e_cola": codigo,
            "pix_qr_base64": "",
            "checkout_url": "",
        }
    payload = {
        "transaction_amount": round(float(valor), 2),
        "description": descricao[:255],
        "payment_method_id": "pix",
        "external_reference": intent_id,
        "payer": {"email": email or "cliente@zappedidos.com"},
    }
    if app_url():
        payload["notification_url"] = f"{app_url()}/api/webhooks/mercadopago"
    data = await _mp("POST", "/v1/payments", headers=_headers(f"pix-{intent_id}"), json=payload)
    tx = (data.get("point_of_interaction") or {}).get("transaction_data") or {}
    return {
        "provider": "mercadopago",
        "provider_payment_id": str(data.get("id")),
        "status": _MP_MAP.get(str(data.get("status")), PENDENTE),
        "pix_copia_e_cola": tx.get("qr_code") or "",
        "pix_qr_base64": tx.get("qr_code_base64") or "",
        "checkout_url": tx.get("ticket_url") or "",
    }


async def criar_checkout_cartao(intent_id: str, valor: float, titulo: str,
                                email: str) -> Dict[str, Any]:
    """Link hospedado do Mercado Pago (crédito/débito) — não tocamos em dados de cartão."""
    if simulado():
        return {
            "provider": "simulado",
            "provider_payment_id": f"sim-{intent_id}",
            "status": PENDENTE,
            "pix_copia_e_cola": "",
            "pix_qr_base64": "",
            "checkout_url": f"{app_url()}/pagamento/{intent_id}" if app_url() else f"/pagamento/{intent_id}",
        }
    base = app_url()
    payload: Dict[str, Any] = {
        "items": [{
            "id": intent_id, "title": titulo[:255], "quantity": 1,
            "currency_id": "BRL", "unit_price": round(float(valor), 2),
        }],
        "external_reference": intent_id,
        "payer": {"email": email or "cliente@zappedidos.com"},
    }
    if base:
        payload["notification_url"] = f"{base}/api/webhooks/mercadopago"
        payload["back_urls"] = {
            "success": f"{base}/pagamento/{intent_id}",
            "pending": f"{base}/pagamento/{intent_id}",
            "failure": f"{base}/pagamento/{intent_id}",
        }
    data = await _mp("POST", "/checkout/preferences", headers=_headers(str(uuid.uuid4())),
                     json=payload)
    return {
        "provider": "mercadopago",
        "provider_payment_id": str(data.get("id")),
        "status": PENDENTE,
        "pix_copia_e_cola": "",
        "pix_qr_base64": "",
        "checkout_url": data.get("init_point") or data.get("sandbox_init_point") or "",
    }


async def consultar_status(provider: str, provider_payment_id: str) -> str:
    """Polling: fonte de verdade é sempre o provedor, nunca o retorno do browser."""
    if provider == "simulado" or simulado():
        return ""  # o modo simulado só muda de status pelo endpoint de aprovação manual
    data = await _mp("GET", f"/v1/payments/{provider_payment_id}", headers=_headers())
    return _MP_MAP.get(str(data.get("status")), PENDENTE)


async def buscar_pagamento(provider_payment_id: str) -> Tuple[str, str]:
    """Devolve (status normalizado, external_reference) — usado pelo webhook."""
    data = await _mp("GET", f"/v1/payments/{provider_payment_id}", headers=_headers())
    return (_MP_MAP.get(str(data.get("status")), PENDENTE),
            str(data.get("external_reference") or ""))


def assinatura_valida(x_signature: Optional[str], x_request_id: Optional[str],
                      data_id: Optional[str]) -> bool:
    secret = os.environ.get("MERCADOPAGO_WEBHOOK_SECRET", "").strip()
    if not secret:
        return True  # sem segredo configurado não há o que validar (sandbox)
    if not x_signature:
        return False
    partes = dict(p.split("=", 1) for p in x_signature.split(",") if "=" in p)
    ts, recebido = partes.get("ts"), partes.get("v1")
    if not ts or not recebido:
        return False
    manifesto = []
    if data_id:
        manifesto.append(f"id:{data_id.lower()}")
    if x_request_id:
        manifesto.append(f"request-id:{x_request_id}")
    manifesto.append(f"ts:{ts}")
    esperado = hmac.new(secret.encode(), (";".join(manifesto) + ";").encode(),
                        hashlib.sha256).hexdigest()
    return hmac.compare_digest(esperado, recebido)
