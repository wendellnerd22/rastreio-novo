"""Admin (revendedor): stats, lojas, planos."""
import secrets
import uuid

from fastapi import APIRouter, Depends, HTTPException

from lib.auth import User, admin_user, hash_senha
from lib.db import db
from lib.tracker import PLAN_QUOTAS, utcnow
from models.tracker import AdminCreateStoreIn, PlanIn, StoreToggleIn

router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(admin_user)])


@router.get("/stats")
async def admin_stats():
    return {
        "stores": await db.stores.count_documents({}),
        "users": await db.users.count_documents({}),
        "motoboys": await db.motoboys.count_documents({}),
        "orders": await db.orders.count_documents({}),
    }


@router.get("/stores")
async def admin_stores():
    stores = await db.stores.find({}, {"_id": 0, "webhook_token": 0}).to_list(500)
    for s in stores:
        s["motoboys_count"] = await db.motoboys.count_documents({"store_id": s["id"]})
        s["orders_count"] = await db.orders.count_documents({"store_id": s["id"]})
        s.setdefault("plano", "free")
        s["lad_token"] = bool(s.get("lad_token"))
    return stores


@router.post("/stores")
async def admin_create_store(body: AdminCreateStoreIn):
    if await db.users.find_one({"email": body.email_dono.lower()}):
        raise HTTPException(400, "Email já cadastrado")
    if body.plano not in PLAN_QUOTAS:
        raise HTTPException(400, "Plano inválido")
    sid = str(uuid.uuid4())
    owner = User(email=body.email_dono.lower(), nome=body.nome_dono, role="lojista",
                 store_id=sid, senha_hash=hash_senha(body.senha_dono))
    await db.users.insert_one(owner.model_dump())
    await db.stores.insert_one({
        "id": sid, "nome": body.nome_loja, "owner_id": owner.id, "telefone": body.telefone,
        "lad_token": "", "lad_demo": False, "webhook_token": secrets.token_urlsafe(16),
        "plano": body.plano, "ativa": True, "created_at": utcnow(),
    })
    return {"id": sid, "plano": body.plano}


@router.patch("/stores/{sid}")
async def admin_toggle_store(sid: str, body: StoreToggleIn):
    r = await db.stores.update_one({"id": sid}, {"$set": {"ativa": body.ativa}})
    if r.matched_count == 0:
        raise HTTPException(404, "Loja não encontrada")
    return {"ok": True, "ativa": body.ativa}


@router.put("/stores/{sid}/plan")
async def admin_update_plan(sid: str, body: PlanIn):
    if body.plano not in PLAN_QUOTAS:
        raise HTTPException(400, "Plano inválido")
    r = await db.stores.update_one({"id": sid}, {"$set": {"plano": body.plano}})
    if r.matched_count == 0:
        raise HTTPException(404, "Loja não encontrada")
    return {"ok": True, "plano": body.plano}


@router.delete("/stores/{sid}")
async def admin_delete_store(sid: str):
    if not await db.stores.find_one({"id": sid}):
        raise HTTPException(404, "Loja não encontrada")
    order_ids = [o["id"] for o in await db.orders.find({"store_id": sid}, {"_id": 0, "id": 1}).to_list(10000)]
    await db.users.delete_many({"store_id": sid, "role": {"$ne": "admin"}})
    await db.motoboys.delete_many({"store_id": sid})
    await db.notes.delete_many({"store_id": sid})
    if order_ids:
        await db.locations.delete_many({"order_id": {"$in": order_ids}})
        await db.push_subs.delete_many({"order_id": {"$in": order_ids}})
    await db.orders.delete_many({"store_id": sid})
    await db.stores.delete_one({"id": sid})
    return {"ok": True}


@router.get("/plans")
async def admin_plans():
    return PLAN_QUOTAS
