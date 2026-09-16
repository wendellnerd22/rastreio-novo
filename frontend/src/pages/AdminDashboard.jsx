import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { toast } from "sonner";
import { Store, Users, Bike, Package, LogOut, Zap, ToggleLeft, ToggleRight } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Badge } from "@/components/ui/badge";
import { useAuth } from "@/context/AuthContext";

export default function AdminDashboard() {
  const { user, api, logout } = useAuth();
  const nav = useNavigate();
  const [stats, setStats] = useState({});
  const [stores, setStores] = useState([]);

  const load = async () => {
    const [s, st] = await Promise.all([api.get("/admin/stats"), api.get("/admin/stores")]);
    setStats(s.data); setStores(st.data);
  };
  useEffect(() => { load(); }, []);

  const toggle = async (sid, active) => {
    try { await api.patch(`/admin/stores/${sid}`, { active: !active }); toast.success("Status atualizado"); load(); }
    catch { toast.error("Falha"); }
  };

  const cards = [
    { label: "Lojas", value: stats.stores || 0, icon: Store, color: "text-indigo-400" },
    { label: "Usuários", value: stats.users || 0, icon: Users, color: "text-emerald-400" },
    { label: "Motoboys", value: stats.motoboys || 0, icon: Bike, color: "text-amber-400" },
    { label: "Pedidos", value: stats.orders || 0, icon: Package, color: "text-rose-400" },
  ];

  return (
    <div className="min-h-screen bg-[#0B0F17] text-slate-100">
      <header className="glass sticky top-0 z-40 border-b border-slate-800 px-6 py-4">
        <div className="max-w-7xl mx-auto flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="w-9 h-9 rounded-xl bg-indigo-500 grid place-items-center"><Zap className="w-5 h-5" /></div>
            <div>
              <div className="font-display font-bold text-lg">Painel Admin</div>
              <div className="text-xs text-slate-500">Revendedor · {user?.name}</div>
            </div>
          </div>
          <Button data-testid="admin-logout-btn" onClick={() => { logout(); nav("/"); }} variant="ghost" className="text-slate-400 hover:text-white">
            <LogOut className="w-4 h-4 mr-2" /> Sair
          </Button>
        </div>
      </header>

      <main className="max-w-7xl mx-auto px-6 py-8">
        <h1 className="font-display font-bold text-3xl mb-6">Visão geral</h1>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-10">
          {cards.map((c, i) => (
            <Card key={i} data-testid={`admin-stat-${c.label.toLowerCase()}`} className="card-dark p-5 border-slate-800">
              <c.icon className={`w-6 h-6 ${c.color} mb-3`} />
              <div className="text-3xl font-display font-bold text-white">{c.value}</div>
              <div className="text-xs text-slate-500 uppercase tracking-wider mt-1">{c.label}</div>
            </Card>
          ))}
        </div>

        <Card className="card-dark border-slate-800 overflow-hidden">
          <div className="p-5 border-b border-slate-800 flex items-center justify-between">
            <h2 className="font-display font-bold text-xl">Lojas conectadas</h2>
            <Badge variant="outline" className="border-indigo-500/30 text-indigo-300">{stores.length} total</Badge>
          </div>
          <Table>
            <TableHeader>
              <TableRow className="border-slate-800 hover:bg-transparent">
                <TableHead className="text-slate-400">Loja</TableHead>
                <TableHead className="text-slate-400">Motoboys</TableHead>
                <TableHead className="text-slate-400">Pedidos</TableHead>
                <TableHead className="text-slate-400">LAD</TableHead>
                <TableHead className="text-slate-400">Status</TableHead>
                <TableHead className="text-slate-400 text-right">Ações</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {stores.map(s => (
                <TableRow key={s.id} className="border-slate-800 hover:bg-slate-900/50" data-testid={`admin-store-row-${s.id}`}>
                  <TableCell className="font-medium">{s.name}<div className="text-xs text-slate-500">{s.phone || "sem telefone"}</div></TableCell>
                  <TableCell>{s.motoboys_count}</TableCell>
                  <TableCell>{s.orders_count}</TableCell>
                  <TableCell>{s.lad_api_token ? <Badge className="bg-emerald-500/20 text-emerald-400 border-emerald-500/30">Conectada</Badge> : <span className="text-slate-500 text-sm">—</span>}</TableCell>
                  <TableCell>
                    {s.active ? <Badge className="bg-indigo-500/20 text-indigo-300 border-indigo-500/30">Ativa</Badge>
                              : <Badge className="bg-slate-700 text-slate-300">Inativa</Badge>}
                  </TableCell>
                  <TableCell className="text-right">
                    <Button data-testid={`admin-toggle-${s.id}`} onClick={() => toggle(s.id, s.active)} variant="ghost" size="sm" className="text-slate-400 hover:text-white">
                      {s.active ? <ToggleRight className="w-5 h-5 text-indigo-400" /> : <ToggleLeft className="w-5 h-5" />}
                    </Button>
                  </TableCell>
                </TableRow>
              ))}
              {stores.length === 0 && (
                <TableRow className="border-slate-800"><TableCell colSpan={6} className="text-center text-slate-500 py-10">Nenhuma loja cadastrada ainda.</TableCell></TableRow>
              )}
            </TableBody>
          </Table>
        </Card>
      </main>
    </div>
  );
}
