import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { MapContainer, TileLayer, Marker, Popup, useMap } from "react-leaflet";
import L from "leaflet";
import { MapPin, Bike, Store, Package, Clock, CheckCircle2 } from "lucide-react";
import axios from "axios";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;

// Custom marker icons
const bikeIcon = new L.DivIcon({
  className: "custom-marker",
  html: `<div style="background:#6366F1;width:44px;height:44px;border-radius:50% 50% 50% 0;transform:rotate(-45deg);border:3px solid #fff;box-shadow:0 4px 12px rgba(0,0,0,0.4);display:grid;place-items:center;">
    <div style="transform:rotate(45deg);color:white;font-size:20px;">🛵</div>
  </div>`,
  iconSize: [44, 44], iconAnchor: [22, 44],
});
const storeIcon = new L.DivIcon({
  className: "custom-marker",
  html: `<div style="background:#10B981;width:44px;height:44px;border-radius:50% 50% 50% 0;transform:rotate(-45deg);border:3px solid #fff;box-shadow:0 4px 12px rgba(0,0,0,0.4);display:grid;place-items:center;">
    <div style="transform:rotate(45deg);color:white;font-size:18px;">🏪</div>
  </div>`,
  iconSize: [44, 44], iconAnchor: [22, 44],
});

function FitBounds({ points }) {
  const map = useMap();
  useEffect(() => {
    if (points.length === 0) return;
    if (points.length === 1) { map.setView(points[0], 15); return; }
    map.fitBounds(points, { padding: [40, 40] });
  }, [points, map]);
  return null;
}

const STATUS_STEPS = [
  { key: "pending", label: "Pedido recebido", icon: Package },
  { key: "preparing", label: "Em preparo", icon: Clock },
  { key: "dispatched", label: "Saiu para entrega", icon: Bike },
  { key: "delivered", label: "Entregue", icon: CheckCircle2 },
];

export default function CustomerTrack() {
  const { token } = useParams();
  const [data, setData] = useState(null);
  const [loc, setLoc] = useState(null);
  const [err, setErr] = useState(null);

  useEffect(() => {
    let alive = true;
    const load = async () => {
      try {
        const [d, l] = await Promise.all([
          axios.get(`${API}/track/${token}`),
          axios.get(`${API}/track/${token}/location`).catch(() => ({ data: {} })),
        ]);
        if (!alive) return;
        setData(d.data); setLoc(l.data.last_location);
      } catch (e) { if (alive) setErr(e.response?.data?.detail || "Rastreamento indisponível"); }
    };
    load();
    const t = setInterval(load, 8000);
    return () => { alive = false; clearInterval(t); };
  }, [token]);

  if (err) return <div className="min-h-screen bg-[#0B0F17] grid place-items-center text-slate-400 px-6 text-center">{err}</div>;
  if (!data) return <div className="min-h-screen bg-[#0B0F17] grid place-items-center text-slate-400">Carregando rastreio…</div>;

  const order = data.order;
  const activeIdx = STATUS_STEPS.findIndex(s => s.key === order.status);
  const points = [];
  if (loc) points.push([loc.lat, loc.lng]);

  return (
    <div className="min-h-screen bg-[#0B0F17] text-slate-100">
      <header className="glass border-b border-slate-800 px-6 py-4">
        <div className="max-w-4xl mx-auto flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-xl bg-emerald-500/20 border border-emerald-500/30 grid place-items-center"><Store className="w-5 h-5 text-emerald-400" /></div>
            <div>
              <div className="font-display font-bold">{data.store?.name}</div>
              <div className="text-xs text-slate-500">Pedido de {order.customer_name}</div>
            </div>
          </div>
          <div className="text-right">
            <div className="text-2xl font-display font-bold">R$ {Number(order.total).toFixed(2)}</div>
            <div className="text-xs text-slate-500">{order.payment_method}</div>
          </div>
        </div>
      </header>

      <main className="max-w-4xl mx-auto px-6 py-6 space-y-6">
        <div className="card-dark p-6" data-testid="track-status-timeline">
          <h2 className="font-display font-bold text-xl mb-5">Status do pedido</h2>
          <div className="grid grid-cols-4 gap-2">
            {STATUS_STEPS.map((s, i) => {
              const done = i <= activeIdx;
              const current = i === activeIdx;
              return (
                <div key={s.key} className="text-center">
                  <div className={`w-11 h-11 mx-auto rounded-full grid place-items-center border-2 ${done ? "bg-indigo-500 border-indigo-400" : "bg-slate-900 border-slate-800"} ${current ? "pulse-dot" : ""}`}>
                    <s.icon className={`w-5 h-5 ${done ? "text-white" : "text-slate-600"}`} />
                  </div>
                  <div className={`text-xs mt-2 ${done ? "text-slate-200" : "text-slate-600"}`}>{s.label}</div>
                </div>
              );
            })}
          </div>
        </div>

        {order.status === "dispatched" && (
          <div className="card-dark overflow-hidden" data-testid="track-map">
            <div className="p-4 border-b border-slate-800 flex items-center justify-between">
              <div className="flex items-center gap-2">
                <MapPin className="w-4 h-4 text-indigo-400" />
                <span className="font-display font-bold">Localização em tempo real</span>
              </div>
              {loc && <div className="text-xs text-emerald-400 flex items-center gap-1"><span className="w-2 h-2 rounded-full bg-emerald-400 pulse-dot" /> Ao vivo</div>}
            </div>
            <div className="h-[420px]">
              {loc ? (
                <MapContainer center={[loc.lat, loc.lng]} zoom={15} style={{height: "100%", width: "100%"}} className="rounded-b-2xl">
                  <TileLayer attribution='&copy; OpenStreetMap' url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png" />
                  <Marker position={[loc.lat, loc.lng]} icon={bikeIcon}><Popup>{data.motoboy?.name || "Motoboy"}</Popup></Marker>
                  <FitBounds points={points} />
                </MapContainer>
              ) : (
                <div className="h-full grid place-items-center text-slate-500 text-sm">Aguardando localização do motoboy…</div>
              )}
            </div>
          </div>
        )}

        <div className="grid md:grid-cols-2 gap-4">
          <div className="card-dark p-5">
            <div className="text-xs text-slate-500 uppercase tracking-wider mb-3">Endereço de entrega</div>
            <div className="text-slate-200">{order.address}</div>
          </div>
          <div className="card-dark p-5">
            <div className="text-xs text-slate-500 uppercase tracking-wider mb-3">Motoboy</div>
            {data.motoboy ? (
              <div>
                <div className="font-display font-bold">{data.motoboy.name}</div>
                <div className="text-xs text-slate-500">{data.motoboy.vehicle} {data.motoboy.plate && `· ${data.motoboy.plate}`}</div>
              </div>
            ) : <div className="text-slate-500 text-sm">Aguardando despacho…</div>}
          </div>
        </div>

        <div className="card-dark p-5">
          <div className="text-xs text-slate-500 uppercase tracking-wider mb-3">Itens</div>
          <div className="text-slate-300 text-sm whitespace-pre-line">{order.items}</div>
          {order.notes && <div className="mt-3 pt-3 border-t border-slate-800 text-xs text-slate-500">Obs: {order.notes}</div>}
        </div>
      </main>
    </div>
  );
}
