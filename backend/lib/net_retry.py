"""Retry com backoff exponencial para chamadas HTTP externas.

Cobre quebras de link transitórias: timeout, DNS falhou, conexão recusada
(WAHA reiniciando, por exemplo), ou a API respondeu 502/503/504. Erros de
negócio (400, 401, 404...) NÃO são reter tentados — só o que é claramente
uma falha de conexão passageira.
"""
from __future__ import annotations

import asyncio
import random
from typing import Awaitable, Callable, TypeVar

import httpx

T = TypeVar("T")

RETRYABLE_STATUS = {502, 503, 504}


class RetriesExhausted(Exception):
    """Todas as tentativas falharam — a última exceção fica em __cause__."""


async def with_retry(
    fazer_chamada: Callable[[], Awaitable[httpx.Response]],
    *,
    tentativas: int = 3,
    espera_base: float = 0.5,
    nome: str = "chamada externa",
) -> httpx.Response:
    """Executa fazer_chamada() com retry. fazer_chamada deve devolver a Response
    (não levantar em 4xx/5xx) para que possamos decidir aqui o que é retentável."""
    ultimo_erro: Exception | None = None
    for tentativa in range(1, tentativas + 1):
        try:
            resp = await fazer_chamada()
        except (httpx.TransportError, httpx.TimeoutException) as exc:
            ultimo_erro = exc
        else:
            if resp.status_code not in RETRYABLE_STATUS:
                return resp
            ultimo_erro = RuntimeError(f"{nome} respondeu {resp.status_code}")

        if tentativa < tentativas:
            espera = espera_base * (2 ** (tentativa - 1)) + random.uniform(0, 0.25)
            await asyncio.sleep(espera)

    raise RetriesExhausted(f"{nome}: sem resposta após {tentativas} tentativas") from ultimo_erro
