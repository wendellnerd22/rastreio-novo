"""Tracking público (cliente e motoboy), alertas, notas e Web Push."""
import uuid
from datetime import datetime, timezone
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException

from lib.auth import User
from lib.db import db
from lib.tracker import PUSH_RADIUS_KM, VAPID_PUBLIC_KEY, haversine_km, require_store, send_push, utcnow
from models.tracker import LocationIn, NoteIn, PushSubscribeIn

router = APIRouter(tags=["tracking"])


def _as_dt(v) -> datetime:
    d = v if isinstance(v, datetime) else datetime.fromisoformat(v)
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


# ---------- cliente ----------
@router.get("/track/{token}")
async def public_track(token: str):
    o = await db.orders.find_one({"tracking_token": token},
                                 {"_id": 0, "cliente_whatsapp": 0, "motoboy_share_token": 0, "store_id": 1,
                                  "id": 1, "cliente_nome": 1, "endereco": 1, "itens": 1, "total": 1,
                                  "forma_pagamento": 1, "observacao": 1, "status": 1, "motoboy_id": 1,
                                  "created_at": 1, "dispatched_at": 1, "delivered_at": 1, "tracking_token": 1,
                                  "dest_lat": 1, "dest_lng": 1, "last_location": 1, "lad_uuid": 1})
    if not o:
        raise HTTPException(404, "Rastreamento não encontrado")
    s = await db.stores.find_one({"id": o["store_id"]}, {"_id": 0, "nome": 1, "telefone": 1})
    m = None
    if o.get("motoboy_id"):
        mo = await db.motoboys.find_one({"id": o["motoboy_id"]}, {"_id": 0})
        if mo:
            m = {"nome": mo["nome"], "veiculo": mo.get("veiculo"), "placa": mo.get("placa")}
    return {"order": o, "store": s, "motoboy": m}


@router.get("/track/{token}/location")
async def get_last_location(token: str):
    o = await db.orders.find_one({"tracking_token": token},
                                 {"_id": 0, "last_location": 1, "status": 1, "dest_lat": 1, "dest_lng": 1})
    if not o:
        raise HTTPException(404, "Não encontrado")
    eta_min = None
    if o.get("last_location") and o.get("dest_lat") is not None and o.get("dest_lng") is not None:
        km = haversine_km((o["last_location"]["lat"], o["last_location"]["lng"]), (o["dest_lat"], o["dest_lng"]))
        eta_min = max(1, int(round(km / 25 * 60)))
    return {**o, "eta_minutes": eta_min}


@router.get("/track/{token}/route")
async def get_route(token: str):
    o = await db.orders.find_one({"tracking_token": token}, {"_id": 0, "id": 1, "dest_lat": 1, "dest_lng": 1})
    if not o:
        raise HTTPException(404, "Não encontrado")
    points = await db.locations.find({"order_id": o["id"]}, {"_id": 0, "lat": 1, "lng": 1, "at": 1}).sort("at", 1).to_list(500)
    return {"points": points, "destination": {"lat": o.get("dest_lat"), "lng": o.get("dest_lng")}}


@router.post("/track/{token}/note")
async def customer_note(token: str, body: NoteIn):
    o = await db.orders.find_one({"tracking_token": token})
    if not o:
        raise HTTPException(404, "Rastreamento não encontrado")
    recent = await db.notes.count_documents({"order_id": o["id"]})
    if recent >= 20:
        raise HTTPException(429, "Limite de recados para este pedido atingido")
    s = await db.stores.find_one({"id": o["store_id"]}, {"_id": 0, "telefone": 1, "nome": 1})
    await db.notes.insert_one({
        "id": str(uuid.uuid4()), "order_id": o["id"], "store_id": o["store_id"],
        "mensagem": body.mensagem, "cliente_nome": o["cliente_nome"], "at": utcnow(), "lida": False,
    })
    phone = "".join(ch for ch in (s.get("telefone") or "") if ch.isdigit())
    if phone and not phone.startswith("55"):
        phone = "55" + phone
    text = f"📝 Nota de {o['cliente_nome']} (pedido #{o['id'][:8]}):\n{body.mensagem}"
    wa = f"https://wa.me/{phone}?text={quote(text)}" if phone else None
    return {"ok": True, "wa_url": wa, "store": s.get("nome")}


# ---------- push ----------
@router.get("/push/vapid-public")
async def vapid_public():
    return {"key": VAPID_PUBLIC_KEY}


@router.post("/track/{token}/push-subscribe")
async def push_subscribe(token: str, body: PushSubscribeIn):
    o = await db.orders.find_one({"tracking_token": token}, {"_id": 0, "id": 1})
    if not o:
        raise HTTPException(404, "Rastreamento não encontrado")
    await db.push_subs.update_one(
        {"order_id": o["id"], "endpoint": body.endpoint},
        {"$set": {"order_id": o["id"], "endpoint": body.endpoint, "keys": body.keys, "at": utcnow()}},
        upsert=True,
    )
    return {"ok": True}


# ---------- motoboy ----------
@router.get("/motoboy-track/{token}")
async def motoboy_track_info(token: str):
    o = await db.orders.find_one({"motoboy_share_token": token}, {"_id": 0})
    if not o:
        raise HTTPException(404, "Sessão não encontrada")
    s = await db.stores.find_one({"id": o["store_id"]}, {"_id": 0, "nome": 1})
    m = None
    if o.get("motoboy_id"):
        m = await db.motoboys.find_one({"id": o["motoboy_id"]}, {"_id": 0, "nome": 1, "telefone": 1})
    return {
        "order": {"id": o["id"], "cliente_nome": o["cliente_nome"], "endereco": o["endereco"],
                  "total": o["total"], "status": o["status"], "observacao": o.get("observacao"),
                  "tracking_token": o["tracking_token"]},
        "store": s, "motoboy": m,
    }


@router.post("/motoboy-track/{token}/location")
async def post_location(token: str, body: LocationIn):
    o = await db.orders.find_one({"motoboy_share_token": token})
    if not o:
        raise HTTPException(404, "Sessão inválida")
    if o["status"] in ("delivered", "canceled"):
        raise HTTPException(400, "Pedido finalizado")
    loc = {**body.model_dump(), "at": utcnow()}
    await db.orders.update_one({"id": o["id"]}, {"$set": {"last_location": loc}})
    await db.locations.insert_one({"order_id": o["id"], **loc})
    if o.get("dest_lat") is not None and o.get("dest_lng") is not None and not o.get("push_arrival_sent"):
        if haversine_km((body.lat, body.lng), (o["dest_lat"], o["dest_lng"])) <= PUSH_RADIUS_KM:
            subs = await db.push_subs.find({"order_id": o["id"]}, {"_id": 0}).to_list(20)
            store = await db.stores.find_one({"id": o["store_id"]}, {"_id": 0, "nome": 1})
            sent = sum(1 for s in subs if send_push(
                s, "🛵 Está chegando!",
                f"O entregador da {store.get('nome', 'loja')} está a menos de 500m. Prepare-se!",
                f"/track/{o['tracking_token']}"))
            if sent:
                await db.orders.update_one({"id": o["id"]}, {"$set": {"push_arrival_sent": utcnow()}})
    return {"ok": True}


# ---------- alertas da loja ----------
@router.get("/alerts")
async def live_alerts(user: User = Depends(require_store), stale_min: int = 5):
    now = utcnow()
    orders = await db.orders.find({"store_id": user.store_id, "status": "dispatched"},
                                  {"_id": 0, "id": 1, "cliente_nome": 1, "motoboy_id": 1,
                                   "last_location": 1, "dispatched_at": 1, "dest_lat": 1, "dest_lng": 1}).to_list(200)
    alerts = []
    for o in orders:
        loc = o.get("last_location")
        if not loc:
            if o.get("dispatched_at"):
                delta = (now - _as_dt(o["dispatched_at"])).total_seconds() / 60
                if delta > stale_min:
                    alerts.append({"order_id": o["id"], "cliente_nome": o["cliente_nome"], "type": "no_location",
                                   "minutes": int(delta), "message": f"Sem localização há {int(delta)} min desde o despacho"})
            continue
        delta = (now - _as_dt(loc["at"])).total_seconds() / 60
        if delta > stale_min:
            alerts.append({"order_id": o["id"], "cliente_nome": o["cliente_nome"], "type": "stale_location",
                           "minutes": int(delta), "message": f"Motoboy parou de enviar localização há {int(delta)} min"})
            continue
        if o.get("dest_lat") is not None and o.get("dest_lng") is not None:
            recent = await db.locations.find({"order_id": o["id"]}, {"_id": 0, "lat": 1, "lng": 1}).sort("at", -1).to_list(3)
            if len(recent) == 3:
                dests = (o["dest_lat"], o["dest_lng"])
                d0, d1, d2 = (haversine_km((p["lat"], p["lng"]), dests) for p in (recent[2], recent[1], recent[0]))
                if d2 > d1 > d0 and (d2 - d0) > 0.3:
                    alerts.append({"order_id": o["id"], "cliente_nome": o["cliente_nome"], "type": "off_route",
                                   "distance_km": round(d2, 2),
                                   "message": f"Se afastando do destino ({round((d2 - d0) * 1000)}m nos últimos pings)"})
    return {"alerts": alerts, "count": len(alerts)}
