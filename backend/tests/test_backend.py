"""Backend E2E tests for ZapPedidos + LAD Tracker (cookie session, PT-BR fields)."""
import os
import time
import uuid
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
if not BASE_URL:
    # fallback to frontend env
    with open("/app/frontend/.env") as f:
        for line in f:
            if line.startswith("REACT_APP_BACKEND_URL="):
                BASE_URL = line.split("=", 1)[1].strip().rstrip("/")
API = f"{BASE_URL}/api"

ADMIN_EMAIL = "admin@zappedidos.com"
ADMIN_PASSWORD = "admin123"


def _uniq(prefix="t"):
    return f"TEST_{prefix}_{uuid.uuid4().hex[:8]}"


# ================= AUTH =================
class TestAuth:
    def test_admin_login_sets_cookie(self):
        s = requests.Session()
        r = s.post(f"{API}/auth/login", json={"email": ADMIN_EMAIL, "senha": ADMIN_PASSWORD})
        assert r.status_code == 200, r.text
        assert r.json()["user"]["role"] == "admin"
        assert "zp_session" in s.cookies.get_dict()

    def test_me_via_cookie(self):
        s = requests.Session()
        s.post(f"{API}/auth/login", json={"email": ADMIN_EMAIL, "senha": ADMIN_PASSWORD})
        r = s.get(f"{API}/auth/me")
        assert r.status_code == 200
        assert r.json()["email"] == ADMIN_EMAIL

    def test_logout_clears_cookie(self):
        s = requests.Session()
        s.post(f"{API}/auth/login", json={"email": ADMIN_EMAIL, "senha": ADMIN_PASSWORD})
        r = s.post(f"{API}/auth/logout")
        assert r.status_code == 200
        # after logout, /me should be 401 (use fresh session that has no cookie)
        s2 = requests.Session()
        r2 = s2.get(f"{API}/auth/me")
        assert r2.status_code == 401

    def test_register_lojista(self):
        s = requests.Session()
        email = f"{_uniq('reg')}@teste.com"
        r = s.post(f"{API}/auth/register", json={
            "nome": "Dono Teste", "email": email, "senha": "senha123",
            "nome_loja": _uniq("Loja"), "telefone": "11999998888",
        })
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["user"]["role"] == "lojista"
        assert data["user"]["store_id"]
        assert "zp_session" in s.cookies.get_dict()

    def test_brute_force_lockout(self):
        # use a unique unknown email so we don't lock a real user
        email = f"{_uniq('bad')}@teste.com"
        s = requests.Session()
        codes = []
        for _ in range(6):
            r = s.post(f"{API}/auth/login", json={"email": email, "senha": "wrongpw"})
            codes.append(r.status_code)
        # first 5 should be 401, 6th 429 (or the 5th once threshold hit)
        assert 429 in codes, f"Expected lockout 429, got {codes}"


# ================= ADMIN =================
@pytest.fixture(scope="module")
def admin_session():
    s = requests.Session()
    r = s.post(f"{API}/auth/login", json={"email": ADMIN_EMAIL, "senha": ADMIN_PASSWORD})
    assert r.status_code == 200
    return s


@pytest.fixture(scope="module")
def lojista_a():
    s = requests.Session()
    email = f"{_uniq('lojA')}@teste.com"
    r = s.post(f"{API}/auth/register", json={
        "nome": "Loja A", "email": email, "senha": "senha123",
        "nome_loja": _uniq("LojaA"), "telefone": "1111",
    })
    assert r.status_code == 200
    return s, r.json()["user"]


@pytest.fixture(scope="module")
def lojista_b():
    s = requests.Session()
    email = f"{_uniq('lojB')}@teste.com"
    r = s.post(f"{API}/auth/register", json={
        "nome": "Loja B", "email": email, "senha": "senha123",
        "nome_loja": _uniq("LojaB"), "telefone": "2222",
    })
    assert r.status_code == 200
    return s, r.json()["user"]


class TestAdmin:
    def test_stats_forbidden_for_lojista(self, lojista_a):
        s, _ = lojista_a
        r = s.get(f"{API}/admin/stats")
        assert r.status_code == 403

    def test_stats_ok_for_admin(self, admin_session):
        r = admin_session.get(f"{API}/admin/stats")
        assert r.status_code == 200
        d = r.json()
        for k in ("stores", "users", "motoboys", "orders"):
            assert k in d

    def test_admin_create_store_with_plano(self, admin_session):
        payload = {
            "nome_loja": _uniq("AdmStore"),
            "nome_dono": "Owner",
            "email_dono": f"{_uniq('admstore')}@teste.com",
            "senha_dono": "senha123",
            "telefone": "3333",
            "plano": "basic",
        }
        r = admin_session.post(f"{API}/admin/stores", json=payload)
        assert r.status_code == 200, r.text
        sid = r.json()["id"]
        assert r.json()["plano"] == "basic"

        # update plan
        r2 = admin_session.put(f"{API}/admin/stores/{sid}/plan", json={"plano": "pro"})
        assert r2.status_code == 200
        assert r2.json()["plano"] == "pro"

        # verify via list
        r3 = admin_session.get(f"{API}/admin/stores")
        assert r3.status_code == 200
        found = [x for x in r3.json() if x["id"] == sid]
        assert found and found[0]["plano"] == "pro"

        # toggle ativa
        r4 = admin_session.patch(f"{API}/admin/stores/{sid}", json={"ativa": False})
        assert r4.status_code == 200
        r5 = admin_session.get(f"{API}/admin/stores")
        found = [x for x in r5.json() if x["id"] == sid]
        assert found[0]["ativa"] is False


# ================= MOTOBOYS / PLAN QUOTA =================
class TestMotoboys:
    def test_free_plan_motoboy_quota(self, lojista_a):
        s, u = lojista_a
        # register creates plano=free by default -> quota max 2
        created = 0
        for i in range(2):
            r = s.post(f"{API}/motoboys", json={
                "nome": _uniq(f"mb{i}"), "telefone": f"9999{i}", "veiculo": "Moto", "placa": "ABC1D23",
            })
            assert r.status_code == 200, r.text
            created += 1
        # 3rd should fail
        r3 = s.post(f"{API}/motoboys", json={
            "nome": _uniq("mb3"), "telefone": "9999X", "veiculo": "Moto"
        })
        assert r3.status_code == 400
        assert "Limite" in r3.json().get("detail", "") or "plano" in r3.json().get("detail", "").lower()

    def test_tenant_isolation(self, lojista_a, lojista_b):
        sa, _ = lojista_a
        sb, _ = lojista_b
        ra = sa.get(f"{API}/motoboys").json()
        rb = sb.get(f"{API}/motoboys").json()
        ids_a = {m["id"] for m in ra}
        ids_b = {m["id"] for m in rb}
        assert ids_a.isdisjoint(ids_b), "Lojista B saw Lojista A motoboys"


# ================= ORDERS + TRACKING + NOTES =================
@pytest.fixture(scope="module")
def order_setup(lojista_a):
    s, u = lojista_a
    # motoboys already created (2). fetch one
    motoboys = s.get(f"{API}/motoboys").json()
    assert motoboys, "no motoboys in fixture"
    mb = motoboys[0]
    # create order
    r = s.post(f"{API}/orders", json={
        "cliente_nome": "Fulano Teste",
        "cliente_whatsapp": "11987654321",
        "endereco": "Av Paulista, 1000, Sao Paulo",
        "itens": "1x Pizza",
        "total": 50.0,
        "forma_pagamento": "PIX",
        "observacao": "sem cebola",
    })
    assert r.status_code == 200, r.text
    order = r.json()
    return s, order, mb


class TestOrdersAndTracking:
    def test_create_order(self, order_setup):
        s, order, mb = order_setup
        assert order["status"] == "pending"
        assert order["tracking_token"]
        assert order["cliente_nome"] == "Fulano Teste"

    def test_dispatch_order(self, order_setup):
        s, order, mb = order_setup
        r = s.post(f"{API}/orders/{order['id']}/dispatch", json={"motoboy_id": mb["id"]})
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["status"] == "dispatched"
        assert d["motoboy_id"] == mb["id"]

    def test_public_track_no_auth_and_no_whatsapp(self, order_setup):
        _, order, _ = order_setup
        r = requests.get(f"{API}/track/{order['tracking_token']}")
        assert r.status_code == 200
        d = r.json()
        assert "cliente_whatsapp" not in d["order"], "cliente_whatsapp leaked in public track"
        assert d["store"]["nome"]
        assert d["motoboy"]["nome"]

    def test_customer_note(self, order_setup):
        _, order, _ = order_setup
        r = requests.post(f"{API}/track/{order['tracking_token']}/note", json={"mensagem": "Cadê meu pedido?"})
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["ok"] is True
        assert d["wa_url"] and "wa.me" in d["wa_url"]

    def test_list_and_mark_notes(self, order_setup):
        s, order, _ = order_setup
        r = s.get(f"{API}/notes")
        assert r.status_code == 200
        notes = r.json()
        assert notes and any(n["order_id"] == order["id"] for n in notes)
        nid = notes[0]["id"]
        r2 = s.patch(f"{API}/notes/{nid}/read")
        assert r2.status_code == 200
        # verify
        r3 = s.get(f"{API}/notes").json()
        for n in r3:
            if n["id"] == nid:
                assert n["lida"] is True

    def test_alerts_endpoint(self, order_setup):
        s, _, _ = order_setup
        r = s.get(f"{API}/alerts", params={"stale_min": 0})
        assert r.status_code == 200
        d = r.json()
        assert "alerts" in d and "count" in d
        # order was just dispatched; with stale_min=0, expect at least one no_location
        assert d["count"] >= 1

    def test_tenant_isolation_orders(self, order_setup, lojista_b):
        _, order, _ = order_setup
        sb, _ = lojista_b
        r = sb.get(f"{API}/orders").json()
        assert all(o["id"] != order["id"] for o in r)


# ================= WEBHOOK LAD =================
class TestWebhook:
    def test_webhook_invalid_token(self):
        r = requests.post(f"{API}/webhook/lad/nonexistent-token", json={"uuid": "abc"})
        assert r.status_code == 404

    def test_webhook_valid_token_but_no_lad_config(self, lojista_a):
        s, _ = lojista_a
        # get webhook token
        r = s.get(f"{API}/store/webhook-url")
        assert r.status_code == 200
        tok = r.json()["token"]
        # store not configured -> 400
        r2 = requests.post(f"{API}/webhook/lad/{tok}", json={"uuid": "abc"})
        assert r2.status_code == 400


# ================= PUSH =================
class TestPush:
    def test_vapid_public(self):
        r = requests.get(f"{API}/push/vapid-public")
        assert r.status_code == 200
        assert r.json()["key"]

    def test_push_subscribe(self, order_setup):
        _, order, _ = order_setup
        payload = {
            "endpoint": f"https://push.example/{uuid.uuid4().hex}",
            "keys": {"p256dh": "aaa", "auth": "bbb"},
        }
        r = requests.post(f"{API}/track/{order['tracking_token']}/push-subscribe", json=payload)
        assert r.status_code == 200
        # upsert - repeat
        r2 = requests.post(f"{API}/track/{order['tracking_token']}/push-subscribe", json=payload)
        assert r2.status_code == 200

    def test_push_subscribe_invalid_token(self):
        r = requests.post(f"{API}/track/nonexistent-tok/push-subscribe", json={
            "endpoint": "x", "keys": {"p256dh": "a", "auth": "b"}
        })
        assert r.status_code == 404
