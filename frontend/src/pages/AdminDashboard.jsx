import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { toast } from "sonner";
import { Store, Users, Bike, Package, LogOut, Zap, ToggleLeft, ToggleRight, Plus, Trash2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Badge } from "@/components/ui/badge";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogTrigger, DialogFooter } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { useAuth } from "@/context/AuthContext";

const PLAN_COLOR = {
  free: "bg-slate-700 text-slate-300",
  basic: "bg-indigo-500/20 text-indigo-300 border-indigo-500/30",
  pro: "bg-amber-500/20 text-amber-300 border-amber-500/30",
};

export default function AdminDashboard() {
  const { user, api, logout } = useAuth();
  const nav = useNavigate();
  const [stats, setStats] = useState({});
  const [stores, setStores] = useState([]);
  const [openNew, setOpenNew] = useState(false);
  const [form, setForm] = useState({ store_name: "", owner_name: "", owner_email: "", owner_password: "", phone: "", plan: "free" });

  const load = async () => {
    try {
      const [s, st] = await Promise.all([api.get("/admin/stats"), api.get("/admin/stores")]);
      setStats(s.data); setStores(st.data);
    } catch (e) {
      if (e.response?.status === 401) { logout(); nav("/login"); }
      else toast.error(e.response?.data?.detail || "Falha ao carregar");
    }
  };
  useEffect(() => { load(); }, []);

  const toggle = async (sid, ativa) => {
    try { await api.patch(`/admin/stores/${sid}`, { ativa: !ativa }); toast.success("Status atualizado"); load(); }
    catch { toast.error("Falha"); }
  };
  const changePlan = async (sid, plano) => {
    try { await api.put(`/admin/stores/${sid}/plan`, { plano }); toast.success(`Plano ${plano}`); load(); }
    catch (e) { toast.error(e.response?.data?.detail || "Erro"); }
  };
  const createStore = async () => {
    try {
      const payload = { nome_loja: form.store_name, nome_dono: form.owner_name,
        email_dono: form.owner_email, senha_dono: form.owner_password,
        telefone: form.phone, plano: form.plan };
      await api.post("/admin/stores", payload);
      toast.success("Loja criada");
      setOpenNew(false);
      setForm({ store_name: "", owner_name: "", owner_email: "", owner_password: "", phone: "", plan: "free" });
      load();
    } catch (e) { toast.error(e.response?.data?.detail || "Erro"); }
  };
  const delStore = async (sid) => {
    if (!window.confirm("Excluir a loja e todos os dados?")) return;
    try { await api.delete(`/admin/stores/${sid}`); toast.success("Removida"); load(); }
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
              <div className="text-xs text-slate-500">Revendedor · {user?.nome}</div>
            </div>
          </div>
          <Button data-testid="admin-logout-btn" onClick={async () => { await logout(); nav("/"); }} variant="ghost" className="text-slate-400 hover:text-white">
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
            <div className="flex items-center gap-3">
              <h2 className="font-display font-bold text-xl">Lojas conectadas</h2>
              <Badge variant="outline" className="border-indigo-500/30 text-indigo-300">{stores.length} total</Badge>
            </div>
            <Dialog open={openNew} onOpenChange={setOpenNew}>
              <DialogTrigger asChild>
                <Button data-testid="admin-new-store-btn" className="bg-indigo-500 hover:bg-indigo-600"><Plus className="w-4 h-4 mr-2" />Nova loja</Button>
              </DialogTrigger>
              <DialogContent className="bg-slate-950 border-slate-800 text-slate-100 max-w-lg">
                <DialogHeader><DialogTitle className="font-display">Criar loja + usuário</DialogTitle></DialogHeader>
                <div className="grid grid-cols-2 gap-3">
                  <div className="col-span-2"><Label>Nome da loja</Label><Input data-testid="new-store-name" value={form.store_name} onChange={e => setForm({...form, store_name: e.target.value})} className="bg-slate-900 border-slate-800 mt-1" /></div>
                  <div><Label>Responsável</Label><Input data-testid="new-store-owner" value={form.owner_name} onChange={e => setForm({...form, owner_name: e.target.value})} className="bg-slate-900 border-slate-800 mt-1" /></div>
                  <div><Label>Telefone</Label><Input value={form.phone} onChange={e => setForm({...form, phone: e.target.value})} className="bg-slate-900 border-slate-800 mt-1" /></div>
                  <div><Label>Email login</Label><Input data-testid="new-store-email" type="email" value={form.owner_email} onChange={e => setForm({...form, owner_email: e.target.value})} className="bg-slate-900 border-slate-800 mt-1" /></div>
                  <div><Label>Senha inicial</Label><Input data-testid="new-store-password" type="text" value={form.owner_password} onChange={e => setForm({...form, owner_password: e.target.value})} className="bg-slate-900 border-slate-800 mt-1" /></div>
                  <div className="col-span-2"><Label>Plano</Label>
                    <Select value={form.plan} onValueChange={v => setForm({...form, plan: v})}>
                      <SelectTrigger data-testid="new-store-plan" className="bg-slate-900 border-slate-800 mt-1"><SelectValue /></SelectTrigger>
                      <SelectContent className="bg-slate-900 border-slate-800 text-slate-100">
                        <SelectItem value="free">Free — 2 motoboys, 50 pedidos/mês</SelectItem>
                        <SelectItem value="basic">Basic — 5 motoboys, 500 pedidos/mês</SelectItem>
                        <SelectItem value="pro">Pro — ilimitado</SelectItem>
                      </SelectContent>
                    </Select>
                  </div>
                </div>
                <DialogFooter><Button data-testid="new-store-save-btn" onClick={createStore} className="bg-indigo-500 hover:bg-indigo-600">Criar</Button></DialogFooter>
              </DialogContent>
            </Dialog>
          </div>
          <Table>
            <TableHeader>
              <TableRow className="border-slate-800 hover:bg-transparent">
                <TableHead className="text-slate-400">Loja</TableHead>
                <TableHead className="text-slate-400">Plano</TableHead>
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
                  <TableCell className="font-medium">{s.nome}<div className="text-xs text-slate-500">{s.telefone || "sem telefone"}</div></TableCell>
                  <TableCell>
                    <Select value={s.plano || "free"} onValueChange={v => changePlan(s.id, v)}>
                      <SelectTrigger data-testid={`plan-${s.id}`} className="w-28 bg-slate-900 border-slate-800 h-8 text-xs"><SelectValue /></SelectTrigger>
                      <SelectContent className="bg-slate-900 border-slate-800 text-slate-100">
                        <SelectItem value="free">Free</SelectItem><SelectItem value="basic">Basic</SelectItem><SelectItem value="pro">Pro</SelectItem>
                      </SelectContent>
                    </Select>
                  </TableCell>
                  <TableCell>{s.motoboys_count}</TableCell>
                  <TableCell>{s.orders_count}</TableCell>
                  <TableCell>{s.lad_token ? <Badge className="bg-emerald-500/20 text-emerald-400 border-emerald-500/30">Conectada</Badge> : <span className="text-slate-500 text-sm">—</span>}</TableCell>
                  <TableCell>
                    {s.ativa ? <Badge className="bg-indigo-500/20 text-indigo-300 border-indigo-500/30">Ativa</Badge>
                              : <Badge className="bg-slate-700 text-slate-300">Inativa</Badge>}
                  </TableCell>
                  <TableCell className="text-right">
                    <Button data-testid={`admin-toggle-${s.id}`} onClick={() => toggle(s.id, s.ativa)} variant="ghost" size="sm" className="text-slate-400 hover:text-white">
                      {s.ativa ? <ToggleRight className="w-5 h-5 text-indigo-400" /> : <ToggleLeft className="w-5 h-5" />}
                    </Button>
                    <Button data-testid={`admin-del-${s.id}`} onClick={() => delStore(s.id)} variant="ghost" size="sm" className="text-rose-400 hover:bg-rose-950">
                      <Trash2 className="w-4 h-4" />
                    </Button>
                  </TableCell>
                </TableRow>
              ))}
              {stores.length === 0 && (
                <TableRow className="border-slate-800"><TableCell colSpan={7} className="text-center text-slate-500 py-10">Nenhuma loja cadastrada ainda.</TableCell></TableRow>
              )}
            </TableBody>
          </Table>
        </Card>
      </main>
    </div>
  );
}
