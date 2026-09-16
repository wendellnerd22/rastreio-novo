"""Loja: config LAD, webhook URL, importação/sync LAD e webhook público."""
import secrets
import uuid
from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException

from lib.auth import User
from lib.db import db
from lib.lad import LadClient, LadError
from lib.tracker import geocode, get_store, require_store, store_lad_ready, utcnow
from models.tracker import LadConfigIn, LadImportIn

router = APIRouter(prefix="/store", tags=["store"])
webhook_router = APIRouter(prefix="/webhook", tags=["webhook"])


@router.get("/me")
async def get_my_store(user: User = Depends(require_store)):
    return await get_store(user.store_id)


@router.put("/lad")
async def update_lad_config(body: LadConfigIn, user: User = Depends(require_store)):
    await db.stores.update_one({"id": user.store_id},
                               {"$set": {"lad_token": body.token, "lad_demo": bool(body.demo)}})
    return {"ok": True}


@router.get("/lad/loja")
async def lad_loja(user: User = Depends(require_store)):
    s = await get_store(user.store_id)
    if not store_lad_ready(s):
        raise HTTPException(400, "Configure o token LAD (ou ative demo) primeiro")
    try:
        return {"data": await LadClient(s.get("lad_token", ""), demo=bool(s.get("lad_demo"))).loja()}
    except LadError as e:
        raise HTTPException(e.status or 502, e.descricao)


@router.get("/webhook-url")
async def get_webhook_url(user: User = Depends(require_store)):
    s = await db.stores.find_one({"id": user.store_id}, {"_id": 0, "webhook_token": 1})
    if not s.get("webhook_token"):
        tok = secrets.token_urlsafe(16)
        await db.stores.update_one({"id": user.store_id}, {"$set": {"webhook_token": tok}})
        return {"token": tok}
    return {"token": s["webhook_token"]}


@router.post("/webhook-url/rotate")
async def rotate_webhook_url(user: User = Depends(require_store)):
    tok = secrets.token_urlsafe(16)
    await db.stores.update_one({"id": user.store_id}, {"$set": {"webhook_token": tok}})
    return {"token": tok}


# ---------- LAD import ----------
STATUS_MAP = {"E": "pending", "A": "preparing", "V": "preparing", "X": "dispatched",
              "D": "delivered", "P": "pending", "C": "canceled", "R": "canceled"}


def lad_to_internal(lad: Dict[str, Any]) -> Dict[str, Any]:
    itens_txt = ", ".join(f"{i.get('quantidade', 1)}x {i.get('nome', '')}" for i in lad.get("itens", []))
    addr = lad.get("enderecoEntrega") or {}
    endereco = ", ".join(p for p in [addr.get("endereco"), addr.get("numero"), addr.get("bairro"), addr.get("cidade")] if p) \
        or "Retirada na loja"
    cliente = lad.get("cliente") or {}
    status_code = (lad.get("status") or {}).get("codigo", "E")
    return {
        "cliente_nome": cliente.get("nome") or "Cliente LAD",
        "cliente_whatsapp": (cliente.get("telefone") or "").replace(" ", ""),
        "endereco": endereco,
        "itens": itens_txt or "Pedido LAD",
        "total": float(lad.get("valorTotal") or 0),
        "forma_pagamento": (lad.get("pagamento") or {}).get("forma", "—"),
        "observacao": lad.get("observacao"),
        "status": STATUS_MAP.get(status_code, "pending"),
        "lad_uuid": lad.get("uuid"),
    }


async def import_lad_uuid(store: Dict[str, Any], lad_uuid: str) -> Dict[str, Any]:
    lad_client = LadClient(store.get("lad_token", ""), demo=bool(store.get("lad_demo")))
    try:
        lad = await lad_client.pedido(lad_uuid)
    except LadError as e:
        raise HTTPException(e.status or 502, e.descricao)
    internal = lad_to_internal(lad)
    existing = await db.orders.find_one({"store_id": store["id"], "lad_uuid": lad.get("uuid")})
    if existing:
        await db.orders.update_one({"id": existing["id"]}, {"$set": internal})
        doc = await db.orders.find_one({"id": existing["id"]}, {"_id": 0})
        return {"imported": False, "updated": True, "order": doc}
    dest = await geocode(internal["endereco"])
    doc = {
        "id": str(uuid.uuid4()), "store_id": store["id"], **internal, "motoboy_id": None,
        "tracking_token": secrets.token_urlsafe(12), "motoboy_share_token": secrets.token_urlsafe(12),
        "dest_lat": dest[0] if dest else None, "dest_lng": dest[1] if dest else None,
        "created_at": utcnow(), "dispatched_at": None, "delivered_at": None, "last_location": None,
    }
    await db.orders.insert_one(doc)
    doc.pop("_id", None)
    return {"imported": True, "updated": False, "order": doc}


@router.post("/lad/import")
async def lad_import_order(body: LadImportIn, user: User = Depends(require_store)):
    s = await get_store(user.store_id)
    if not store_lad_ready(s):
        raise HTTPException(400, "Configure o token LAD primeiro")
    return await import_lad_uuid(s, body.uuid)


@router.post("/lad/refresh")
async def lad_refresh_all(user: User = Depends(require_store)):
    s = await get_store(user.store_id)
    if not store_lad_ready(s):
        raise HTTPException(400, "Configure o token LAD primeiro")
    lad_client = LadClient(s.get("lad_token", ""), demo=bool(s.get("lad_demo")))
    active = await db.orders.find({"store_id": user.store_id, "lad_uuid": {"$ne": None},
                                   "status": {"$nin": ["delivered", "canceled"]}},
                                  {"_id": 0, "id": 1, "lad_uuid": 1}).to_list(50)
    updated = 0
    for o in active:
        try:
            lad = await lad_client.pedido(o["lad_uuid"])
            await db.orders.update_one({"id": o["id"]}, {"$set": {"status": lad_to_internal(lad)["status"]}})
            updated += 1
        except Exception:
            continue
    return {"updated": updated, "total": len(active)}


@webhook_router.post("/lad/{webhook_token}")
async def lad_webhook(webhook_token: str, payload: Dict[str, Any]):
    s = await db.stores.find_one({"webhook_token": webhook_token}, {"_id": 0})
    if not s:
        raise HTTPException(404, "Webhook não encontrado")
    if s.get("ativa") is False:
        raise HTTPException(403, "Loja desativada")
    if not store_lad_ready(s):
        raise HTTPException(400, "Loja sem token LAD")
    lad_uuid = payload.get("uuid") or payload.get("pedido_uuid") or (payload.get("data") or {}).get("uuid")
    if not lad_uuid:
        raise HTTPException(400, "Payload sem uuid")
    return {"ok": True, **await import_lad_uuid(s, str(lad_uuid))}
