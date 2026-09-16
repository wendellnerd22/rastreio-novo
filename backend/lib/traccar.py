"""Cliente para o Traccar (traccar/traccar) — servidor GPS self-hosted.

Um dispositivo no Traccar = um motoboy. O app gratuito "Traccar Client"
(Android/iOS) instalado no celular dele reporta a posição usando o
uniqueId do dispositivo — não precisamos desenvolver nenhum app.

Fluxo usado aqui: garante que o dispositivo do motoboy existe, depois
cria um "compartilhamento" (usuário temporário + token) escopado só
àquele dispositivo, com expiração — esse é o link que vai pro cliente.
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Optional

import httpx

from lib.net_retry import RetriesExhausted, with_retry

TIMEOUT = 20.0


class TraccarError(Exception):
    pass


def base_url() -> str:
    return os.environ.get("TRACCAR_BASE_URL", "").rstrip("/")


def _auth() -> httpx.BasicAuth:
    email = os.environ.get("TRACCAR_ADMIN_EMAIL", "").strip()
    senha = os.environ.get("TRACCAR_ADMIN_PASSWORD", "").strip()
    return httpx.BasicAuth(email, senha)


async def _api(method: str, path: str, **kwargs) -> httpx.Response:
    url = base_url()
    if not url:
        raise TraccarError("TRACCAR_BASE_URL não configurado no .env")
    async with httpx.AsyncClient(base_url=url, auth=_auth(), timeout=TIMEOUT) as http:
        try:
            resp = await with_retry(lambda: http.request(method, path, **kwargs),
                                    nome="Traccar")
        except RetriesExhausted as exc:
            raise TraccarError(f"Traccar indisponível (rede instável): {exc}") from exc
        except httpx.HTTPError as exc:
            raise TraccarError(f"Falha de rede ao contatar o Traccar: {exc}") from exc
    if resp.status_code >= 400:
        raise TraccarError(f"Traccar respondeu {resp.status_code}: {resp.text[:300]}")
    return resp


async def garantir_dispositivo(motoboy_id: str, nome: str) -> dict:
    """Cria o dispositivo se ainda não existir (uniqueId = motoboy_id, estável
    entre rotas). Devolve o objeto do dispositivo."""
    resp = await _api("GET", "/api/devices", params={"uniqueId": motoboy_id})
    existentes = resp.json()
    if existentes:
        return existentes[0]
    resp = await _api("POST", "/api/devices", json={"name": nome, "uniqueId": motoboy_id})
    return resp.json()


async def criar_link_rastreamento(device_id: int, horas_validade: float = 4) -> str:
    """Cria um usuário temporário com acesso só a esse dispositivo, gera um
    token e devolve a URL pública que o cliente pode abrir sem login."""
    expiracao = datetime.now(timezone.utc) + timedelta(hours=horas_validade)
    resp = await _api("POST", "/api/users", json={
        "name": f"tracking-{device_id}",
        "email": f"tracking-{device_id}-{int(expiracao.timestamp())}@zappedidos.local",
        "password": os.urandom(12).hex(),
        "temporary": True,
        "expirationTime": expiracao.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "deviceLimit": 1,
    })
    temp_user = resp.json()
    await _api("POST", "/api/permissions", json={
        "userId": temp_user["id"], "deviceId": device_id,
    })
    resp = await _api("POST", "/api/session/token",
                      params={"userId": temp_user["id"]},
                      data={"expiration": expiracao.strftime("%Y-%m-%dT%H:%M:%SZ")})
    token = resp.text.strip().strip('"')
    return f"{base_url()}/?token={token}"
