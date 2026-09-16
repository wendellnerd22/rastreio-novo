"""Motoboys e pedidos da loja (CRUD, despacho, status)."""
import secrets
import uuid
from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException

from lib.auth import User
from lib.db import db
from lib.tracker import ORDER_STATUSES, PLAN_QUOTAS, geocode, get_store, require_store, utcnow
from models.tracker import DispatchIn, MotoboyIn, OrderIn, StatusIn

router = APIRouter(tags=["loja"], dependencies=[Depends(require_store)])


# ---------- motoboys ----------
@router.get("/motoboys")
async def list_motoboys(user: User = Depends(require_store)):
    return await db.motoboys.find({"store_id": user.store_id}, {"_id": 0}).to_list(500)


@router.post("/motoboys")
async def create_motoboy(body: MotoboyIn, user: User = Depends(require_store)):
    store = await get_store(user.store_id)
    quota = PLAN_QUOTAS.get(store.get("plano", "free"), PLAN_QUOTAS["free"])
    if await db.motoboys.count_documents({"store_id": user.store_id}) >= quota["max_motoboys"]:
        raise HTTPException(400, f"Limite do plano {quota['label']} atingido ({quota['max_motoboys']} motoboys). Faça upgrade.")
    doc = {"id": str(uuid.uuid4()), "store_id": user.store_id, **body.model_dump(), "ativo": True, "created_at": utcnow()}
    await db.motoboys.insert_one(doc)
    doc.pop("_id", None)
    return doc


@router.put("/motoboys/{mid}")
async def update_motoboy(mid: str, body: MotoboyIn, user: User = Depends(require_store)):
    r = await db.motoboys.update_one({"id": mid, "store_id": user.store_id}, {"$set": body.model_dump()})
    if r.matched_count == 0:
        raise HTTPException(404, "Motoboy não encontrado")
    return {"ok": True}


@router.delete("/motoboys/{mid}")
async def delete_motoboy(mid: str, user: User = Depends(require_store)):
    await db.motoboys.delete_one({"id": mid, "store_id": user.store_id})
    return {"ok": True}


# ---------- pedidos ----------
@router.get("/orders")
async def list_orders(user: User = Depends(require_store)):
    orders = await db.orders.find({"store_id": user.store_id}, {"_id": 0}).sort("created_at", -1).to_list(500)
    for o in orders:
        if o.get("motoboy_id"):
            o["motoboy"] = await db.motoboys.find_one({"id": o["motoboy_id"]}, {"_id": 0, "nome": 1, "telefone": 1, "id": 1})
    return orders


@router.post("/orders")
async def create_order(body: OrderIn, user: User = Depends(require_store)):
    store = await get_store(user.store_id)
    quota = PLAN_QUOTAS.get(store.get("plano", "free"), PLAN_QUOTAS["free"])
    month_start = utcnow().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    if await db.orders.count_documents({"store_id": user.store_id, "created_at": {"$gte": month_start}}) >= quota["max_orders_month"]:
        raise HTTPException(400, f"Limite de pedidos do plano {quota['label']} atingido neste mês. Faça upgrade.")
    dest = await geocode(body.endereco)
    doc = {
        "id": str(uuid.uuid4()), "store_id": user.store_id, **body.model_dump(),
        "status": "pending", "motoboy_id": None,
        "tracking_token": secrets.token_urlsafe(12), "motoboy_share_token": secrets.token_urlsafe(12),
        "dest_lat": dest[0] if dest else None, "dest_lng": dest[1] if dest else None,
        "created_at": utcnow(), "dispatched_at": None, "delivered_at": None,
        "last_location": None, "lad_uuid": None,
    }
    await db.orders.insert_one(doc)
    doc.pop("_id", None)
    return doc


@router.post("/orders/{oid}/dispatch")
async def dispatch_order(oid: str, body: DispatchIn, user: User = Depends(require_store)):
    o = await db.orders.find_one({"id": oid, "store_id": user.store_id})
    if not o:
        raise HTTPException(404, "Pedido não encontrado")
    if o["status"] in ("delivered", "canceled"):
        raise HTTPException(400, "Pedido já finalizado")
    m = await db.motoboys.find_one({"id": body.motoboy_id, "store_id": user.store_id})
    if not m:
        raise HTTPException(400, "Motoboy inválido")
    await db.orders.update_one({"id": oid}, {"$set": {"motoboy_id": body.motoboy_id, "status": "dispatched",
                                                     "dispatched_at": utcnow()}})
    o2 = await db.orders.find_one({"id": oid}, {"_id": 0})
    o2["motoboy"] = {k: m.get(k) for k in ("id", "nome", "telefone")}
    return o2


@router.patch("/orders/{oid}/status")
async def update_status(oid: str, body: StatusIn, user: User = Depends(require_store)):
    if body.status not in ORDER_STATUSES:
        raise HTTPException(400, "Status inválido")
    upd: Dict[str, Any] = {"status": body.status}
    if body.status == "delivered":
        upd["delivered_at"] = utcnow()
    r = await db.orders.update_one({"id": oid, "store_id": user.store_id}, {"$set": upd})
    if r.matched_count == 0:
        raise HTTPException(404, "Pedido não encontrado")
    return {"ok": True}


@router.delete("/orders/{oid}")
async def delete_order(oid: str, user: User = Depends(require_store)):
    await db.orders.delete_one({"id": oid, "store_id": user.store_id})
    return {"ok": True}


# ---------- notas e alertas ----------
@router.get("/notes")
async def list_notes(user: User = Depends(require_store)):
    return await db.notes.find({"store_id": user.store_id}, {"_id": 0}).sort("at", -1).to_list(100)


@router.patch("/notes/{nid}/read")
async def mark_note_read(nid: str, user: User = Depends(require_store)):
    await db.notes.update_one({"id": nid, "store_id": user.store_id}, {"$set": {"lida": True}})
    return {"ok": True}
