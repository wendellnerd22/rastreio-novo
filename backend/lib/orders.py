"""Liberação do pedido na LAD após o pagamento ser confirmado."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Optional

from lib import payments
from lib.db import db
from lib.lad import LadClient, LadError
from models.schemas import OrderRecord, PaymentIntent, Store


async def load_intent(intent_id: str) -> Optional[PaymentIntent]:
    doc = await db.payment_intents.find_one({"id": intent_id})
    if not doc:
        return None
    doc.pop("_id", None)
    return PaymentIntent(**doc)


async def save_intent(intent: PaymentIntent) -> None:
    await db.payment_intents.update_one({"id": intent.id}, {"$set": intent.model_dump()},
                                        upsert=True)


async def load_store(store_id: str) -> Optional[Store]:
    doc = await db.stores.find_one({"id": store_id})
    if not doc:
        return None
    doc.pop("_id", None)
    return Store(**doc)


async def liberar_pedido(intent: PaymentIntent) -> PaymentIntent:
    """Cria o pedido na LAD para uma intenção aprovada (idempotente pelo id da intenção)."""
    if intent.status != payments.APROVADO or intent.lad_order_uuid:
        return intent
    store = await load_store(intent.store_id)
    if store is None:
        intent.lad_erro = "Loja não encontrada"
        await save_intent(intent)
        return intent

    payload: Dict[str, Any] = dict(intent.pedido_payload)
    payload["idempotencyKey"] = intent.id  # retry nunca duplica pedido
    lad = LadClient(token=store.token, demo=store.demo or not store.token)
    try:
        pedido = await lad.criar_pedido(payload)
    except LadError as exc:
        intent.lad_erro = f"[{exc.status}] {exc.descricao}"
        await save_intent(intent)
        return intent

    intent.lad_order_uuid = pedido.get("uuid")
    intent.lad_erro = None
    await save_intent(intent)

    status = pedido.get("status") or {}
    cliente = pedido.get("cliente") or {}
    record = OrderRecord(
        id=str(pedido.get("uuid")), store_id=intent.store_id, session_id=intent.session_id,
        cliente_nome=cliente.get("nome") or intent.cliente_nome,
        cliente_telefone=cliente.get("telefone") or intent.cliente_telefone,
        tipo=pedido.get("tipo", "DELIVERY"),
        status_codigo=status.get("codigo", "E"),
        status_descricao=status.get("descricao", "Pendente"),
        valor_total=float(pedido.get("valorTotal") or intent.valor),
        data_pedido=str(pedido.get("dataPedido") or ""),
        demo=store.demo or not store.token,
        payload=pedido,
    )
    await db.orders.update_one({"id": record.id}, {"$set": record.model_dump()}, upsert=True)
    return intent


async def aprovar(intent: PaymentIntent) -> PaymentIntent:
    intent.status = payments.APROVADO
    intent.approved_at = datetime.now(timezone.utc)
    await save_intent(intent)
    return await liberar_pedido(intent)


async def sincronizar(intent: PaymentIntent) -> PaymentIntent:
    """Polling de reserva: consulta o provedor e libera o pedido se estiver aprovado."""
    if intent.status == payments.APROVADO:
        return await liberar_pedido(intent)
    if intent.provider == "simulado":
        return intent
    try:
        status = await payments.consultar_status(intent.provider, intent.provider_payment_id)
    except payments.PaymentError:
        return intent
    if status and status != intent.status:
        intent.status = status
        await save_intent(intent)
        if status == payments.APROVADO:
            intent.approved_at = datetime.now(timezone.utc)
            await save_intent(intent)
            return await liberar_pedido(intent)
    return intent
