import { useEffect, useRef, useState } from "react";
import { useParams } from "react-router-dom";
import { MapContainer, TileLayer, Marker, useMap } from "react-leaflet";
import L from "leaflet";
import { MapPin, Play, Square, Navigation, Package } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import axios from "axios";
import { toast } from "sonner";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;

const bikeIcon = new L.DivIcon({
  className: "custom-marker",
  html: `<div style="background:#6366F1;width:40px;height:40px;border-radius:50% 50% 50% 0;transform:rotate(-45deg);border:3px solid #fff;box-shadow:0 4px 12px rgba(0,0,0,0.4);display:grid;place-items:center;">
    <div style="transform:rotate(45deg);color:white;font-size:18px;">🛵</div>
  </div>`,
  iconSize: [40, 40], iconAnchor: [20, 40],
});

function Recenter({ pos }) {
  const map = useMap();
  useEffect(() => { if (pos) map.setView(pos, map.getZoom() || 15); }, [pos, map]);
  return null;
}

export default function MotoboyShare() {
  const { token } = useParams();
  const [data, setData] = useState(null);
  const [err, setErr] = useState(null);
  const [sharing, setSharing] = useState(false);
  const [pos, setPos] = useState(null);
  const [count, setCount] = useState(0);
  const watchId = useRef(null);

  useEffect(() => {
    axios.get(`${API}/motoboy-track/${token}`).then(r => setData(r.data))
      .catch(e => setErr(e.response?.data?.detail || "Sessão inválida"));
  }, [token]);

  const startShare = () => {
    if (!navigator.geolocation) { toast.error("Geolocalização não suportada"); return; }
    setSharing(true);
    watchId.current = navigator.geolocation.watchPosition(
      async (p) => {
        const { latitude, longitude, accuracy, speed, heading } = p.coords;
        setPos([latitude, longitude]);
        try {
          await axios.post(`${API}/motoboy-track/${token}/location`, { lat: latitude, lng: longitude, accuracy, speed, heading });
          setCount(c => c + 1);
        } catch { /* ignore transient */ }
      },
      (e) => { toast.error("Não foi possível obter localização: " + e.message); setSharing(false); },
      { enableHighAccuracy: true, maximumAge: 5000, timeout: 15000 }
    );
    toast.success("Compartilhando localização");
  };
  const stopShare = () => {
    if (watchId.current !== null) navigator.geolocation.clearWatch(watchId.current);
    watchId.current = null; setSharing(false);
    toast.info("Compartilhamento pausado");
  };
  useEffect(() => () => { if (watchId.current !== null) navigator.geolocation.clearWatch(watchId.current); }, []);

  if (err) return <div className="min-h-screen bg-[#0B0F17] grid place-items-center text-slate-400 px-6 text-center">{err}</div>;
  if (!data) return <div className="min-h-screen bg-[#0B0F17] grid place-items-center text-slate-400">Carregando…</div>;

  const trackLink = `${window.location.origin}/track/${data.order.tracking_token}`;

  return (
    <div className="min-h-screen bg-[#0B0F17] text-slate-100">
      <header className="glass border-b border-slate-800 px-4 py-4">
        <div className="max-w-3xl mx-auto flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-xl bg-indigo-500/20 border border-indigo-500/30 grid place-items-center"><Navigation className="w-5 h-5 text-indigo-400" /></div>
            <div>
              <div className="font-display font-bold">Motoboy · {data.motoboy?.name}</div>
              <div className="text-xs text-slate-500">{data.store?.name}</div>
            </div>
          </div>
          <div className={`text-xs px-3 py-1 rounded-full border ${sharing ? "bg-emerald-500/20 text-emerald-300 border-emerald-500/30" : "bg-slate-800 text-slate-400 border-slate-700"}`}>
            {sharing ? "AO VIVO" : "PAUSADO"}
          </div>
        </div>
      </header>

      <main className="max-w-3xl mx-auto px-4 py-6 space-y-4">
        <Card className="card-dark border-slate-800 p-5" data-testid="motoboy-order-info">
          <div className="flex items-start gap-3 mb-3">
            <Package className="w-5 h-5 text-indigo-400 mt-1" />
            <div className="flex-1">
              <div className="font-display font-bold text-lg">{data.order.customer_name}</div>
              <div className="text-sm text-slate-300">{data.order.address}</div>
              {data.order.notes && <div className="text-xs text-slate-500 mt-1">Obs: {data.order.notes}</div>}
            </div>
          </div>
          <div className="grid grid-cols-2 gap-3 pt-3 border-t border-slate-800">
            <div><div className="text-xs text-slate-500">Total</div><div className="font-display font-bold text-xl">R$ {Number(data.order.total).toFixed(2)}</div></div>
            <div><div className="text-xs text-slate-500">Status</div><div className="text-sm text-indigo-300 uppercase">{data.order.status}</div></div>
          </div>
        </Card>

        <Card className="card-dark border-slate-800 overflow-hidden">
          <div className="p-4 border-b border-slate-800 flex items-center gap-2">
            <MapPin className="w-4 h-4 text-indigo-400" />
            <span className="font-display font-bold">Sua localização</span>
            {sharing && <span className="text-xs text-emerald-400 ml-auto">{count} pings enviados</span>}
          </div>
          <div className="h-[320px]">
            {pos ? (
              <MapContainer center={pos} zoom={15} style={{height: "100%", width: "100%"}}>
                <TileLayer attribution='&copy; OpenStreetMap' url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png" />
                <Marker position={pos} icon={bikeIcon} />
                <Recenter pos={pos} />
              </MapContainer>
            ) : (
              <div className="h-full grid place-items-center text-slate-500 text-sm px-6 text-center">
                Toque em "Iniciar" e permita o acesso à localização quando o navegador pedir.
              </div>
            )}
          </div>
        </Card>

        <div className="flex gap-3">
          {!sharing ? (
            <Button data-testid="start-share-btn" onClick={startShare} className="flex-1 bg-indigo-500 hover:bg-indigo-600 h-12 text-base"><Play className="w-4 h-4 mr-2" />Iniciar compartilhamento</Button>
          ) : (
            <Button data-testid="stop-share-btn" onClick={stopShare} variant="outline" className="flex-1 border-rose-700 text-rose-300 hover:bg-rose-950 h-12 text-base"><Square className="w-4 h-4 mr-2" />Parar</Button>
          )}
        </div>

        <div className="text-xs text-slate-500 text-center pt-2">
          Link do cliente: <a href={trackLink} target="_blank" rel="noreferrer" className="text-indigo-400 hover:underline">abrir</a>
        </div>
      </main>
    </div>
  );
}
