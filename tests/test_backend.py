import requests, uuid, sys

BASE = "https://order-tracker-768.preview.emergentagent.com/api"
results = {"passed": [], "failed": []}

def check(name, cond, evidence=""):
    if cond:
        results["passed"].append(name)
        print(f"PASS: {name}")
    else:
        results["failed"].append({"area": name, "evidence": evidence})
        print(f"FAIL: {name} | {evidence}")

# 1. Admin login
r = requests.post(f"{BASE}/auth/login", json={"email":"admin@zappedidos.com","password":"admin123"})
check("admin login", r.status_code==200 and r.json()["user"]["role"]=="admin", f"{r.status_code} {r.text[:200]}")
admin_token = r.json().get("token") if r.status_code==200 else None

# 2. Register store A
emailA = f"a_{uuid.uuid4().hex[:8]}@t.com"
r = requests.post(f"{BASE}/auth/register", json={"name":"A","email":emailA,"password":"x1","store_name":"StoreA","phone":"11"})
check("register store A", r.status_code==200 and r.json()["user"]["role"]=="store" and r.json()["user"]["store_id"], f"{r.status_code} {r.text[:200]}")
tokA = r.json()["token"]
storeA_id = r.json()["user"]["store_id"]

# 3. Register store B
emailB = f"b_{uuid.uuid4().hex[:8]}@t.com"
r = requests.post(f"{BASE}/auth/register", json={"name":"B","email":emailB,"password":"x1","store_name":"StoreB"})
tokB = r.json()["token"]
check("register store B", r.status_code==200, r.text[:200])

# 4. auth/me
r = requests.get(f"{BASE}/auth/me", headers={"Authorization":f"Bearer {tokA}"})
check("GET auth/me", r.status_code==200 and r.json().get("email")==emailA, f"{r.status_code} {r.text[:200]}")

# 5. admin/stats requires admin (403 for store)
r = requests.get(f"{BASE}/admin/stats", headers={"Authorization":f"Bearer {tokA}"})
check("admin/stats 403 for store", r.status_code==403, f"{r.status_code}")
r = requests.get(f"{BASE}/admin/stats", headers={"Authorization":f"Bearer {admin_token}"})
check("admin/stats 200 for admin", r.status_code==200 and "stores" in r.json(), f"{r.status_code} {r.text[:200]}")

# 6. admin/stores with counts
r = requests.get(f"{BASE}/admin/stores", headers={"Authorization":f"Bearer {admin_token}"})
ok = r.status_code==200 and isinstance(r.json(), list) and all("motoboys_count" in s and "orders_count" in s for s in r.json())
check("admin/stores has counts", ok, f"{r.status_code} sample={r.json()[:1] if r.status_code==200 else r.text[:200]}")

# 7. Create motoboy in A
r = requests.post(f"{BASE}/motoboys", json={"name":"Moto1","whatsapp":"11999","vehicle":"Moto","plate":"ABC1"}, headers={"Authorization":f"Bearer {tokA}"})
check("create motoboy A", r.status_code==200 and r.json()["store_id"]==storeA_id, f"{r.status_code} {r.text[:200]}")
motoA_id = r.json()["id"]

# 8. Create motoboy in B
r = requests.post(f"{BASE}/motoboys", json={"name":"MotoB","whatsapp":"22"}, headers={"Authorization":f"Bearer {tokB}"})
motoB_id = r.json()["id"]

# 9. List motoboys tenant isolation
rA = requests.get(f"{BASE}/motoboys", headers={"Authorization":f"Bearer {tokA}"}).json()
rB = requests.get(f"{BASE}/motoboys", headers={"Authorization":f"Bearer {tokB}"}).json()
check("tenant iso motoboys", all(m["id"]!=motoB_id for m in rA) and all(m["id"]!=motoA_id for m in rB), f"A={[m['id'] for m in rA]} B={[m['id'] for m in rB]}")

# 10. Create order in A
r = requests.post(f"{BASE}/orders", json={"customer_name":"Cli","customer_whatsapp":"11888","address":"Rua X","items":"1x Pizza","total":50.0}, headers={"Authorization":f"Bearer {tokA}"})
ok = r.status_code==200 and r.json()["status"]=="pending" and r.json()["tracking_token"] and r.json()["motoboy_share_token"]
check("create order A", ok, f"{r.status_code} {r.text[:200]}")
order = r.json()
track_tok = order["tracking_token"]
share_tok = order["motoboy_share_token"]
order_id = order["id"]

# 11. Tenant iso orders - B cannot fetch A's order
r = requests.get(f"{BASE}/orders/{order_id}", headers={"Authorization":f"Bearer {tokB}"})
check("tenant iso order fetch", r.status_code==404, f"{r.status_code}")

# 12. Dispatch order
r = requests.post(f"{BASE}/orders/{order_id}/dispatch", json={"motoboy_id":motoA_id}, headers={"Authorization":f"Bearer {tokA}"})
check("dispatch order", r.status_code==200 and r.json()["status"]=="dispatched" and r.json()["motoboy_id"]==motoA_id, f"{r.status_code} {r.text[:200]}")

# 13. Public tracking without customer_whatsapp
r = requests.get(f"{BASE}/track/{track_tok}")
data = r.json() if r.status_code==200 else {}
ok = r.status_code==200 and "customer_whatsapp" not in data.get("order",{}) and data.get("store") and data.get("motoboy")
check("public track no auth, no whatsapp", ok, f"{r.status_code} keys={list(data.get('order',{}).keys()) if data else 'none'}")

# 14. Post motoboy location
r = requests.post(f"{BASE}/motoboy-track/{share_tok}/location", json={"lat":-23.5,"lng":-46.6,"accuracy":10})
check("post motoboy location", r.status_code==200 and r.json().get("ok"), f"{r.status_code} {r.text[:200]}")

# 15. GET last location
r = requests.get(f"{BASE}/track/{track_tok}/location")
ok = r.status_code==200 and r.json().get("last_location") and r.json()["last_location"]["lat"]==-23.5
check("get last location", ok, f"{r.status_code} {r.text[:200]}")

# 16. PUT /store/lad
r = requests.put(f"{BASE}/store/lad", json={"api_token":"tok_test_123","api_base":"https://api2.laddelivery.com.br"}, headers={"Authorization":f"Bearer {tokA}"})
check("PUT store/lad", r.status_code==200 and r.json().get("ok"), f"{r.status_code} {r.text[:200]}")
r = requests.get(f"{BASE}/store/me", headers={"Authorization":f"Bearer {tokA}"})
check("store/me shows lad token", r.status_code==200 and r.json().get("lad_api_token")=="tok_test_123", f"{r.status_code} {r.text[:200]}")

print(f"\n=== {len(results['passed'])} passed, {len(results['failed'])} failed ===")
if results["failed"]:
    for f in results["failed"]:
        print(f)
    sys.exit(1)
