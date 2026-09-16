import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { toast } from "sonner";
import { Zap, LogOut, Bike, Package, Settings, Plus, Trash2, MapPin, Send, Copy, Check, MessageCircle, Download, RefreshCw } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogTrigger, DialogFooter } from "@/components/ui/dialog";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Badge } from "@/components/ui/badge";
import { useAuth } from "@/context/AuthContext";

const STATUS_LABELS = {
  pending: { label: "Pendente", color: "bg-amber-500/20 text-amber-300 border-amber-500/30" },
  preparing: { label: "Em preparo", color: "bg-blue-500/20 text-blue-300 border-blue-500/30" },
  dispatched: { label: "Saiu p/ entrega", color: "bg-indigo-500/20 text-indigo-300 border-indigo-500/30" },
  delivered: { label: "Entregue", color: "bg-emerald-500/20 text-emerald-300 border-emerald-500/30" },
  canceled: { label: "Cancelado", color: "bg-rose-500/20 text-rose-300 border-rose-500/30" },
};

export default function StoreDashboard() {
  const { user, api, logout } = useAuth();
  const nav = useNavigate();
  const [motoboys, setMotoboys] = useState([]);
  const [orders, setOrders] = useState([]);
  const [store, setStore] = useState(null);
  const [tab, setTab] = useState("orders");
  const [openM, setOpenM] = useState(false);
  const [openO, setOpenO] = useState(false);
  const [openD, setOpenD] = useState(null); // dispatch dialog with order
  const [copied, setCopied] = useState(null);
  const [mForm, setMForm] = useState({ name: "", whatsapp: "", vehicle: "Moto", plate: "" });
  const [oForm, setOForm] = useState({ customer_name: "", customer_whatsapp: "", address: "", items: "", total: 0, payment_method: "PIX", notes: "" });
  const [ladToken, setLadToken] = useState("");
  const [dispatchMotoboy, setDispatchMotoboy] = useState("");
  const [openImport, setOpenImport] = useState(false);
  const [ladUuid, setLadUuid] = useState("");
  const [refreshing, setRefreshing] = useState(false);

  const loadAll = async () => {
    const [m, o, s] = await Promise.all([api.get("/motoboys"), api.get("/orders"), api.get("/store/me")]);
    setMotoboys(m.data); setOrders(o.data); setStore(s.data); setLadToken(s.data.lad_api_token || "");
  };
  useEffect(() => { loadAll(); const t = setInterval(loadAll, 15000); return () => clearInterval(t); }, []);

  const createMotoboy = async () => {
    try { await api.post("/motoboys", mForm); toast.success("Motoboy cadastrado"); setOpenM(false); setMForm({ name: "", whatsapp: "", vehicle: "Moto", plate: "" }); loadAll(); }
    catch (e) { toast.error(e.response?.data?.detail || "Erro"); }
  };
  const delMotoboy = async (id) => { await api.delete(`/motoboys/${id}`); toast.success("Removido"); loadAll(); };
  const createOrder = async () => {
    try { await api.post("/orders", { ...oForm, total: Number(oForm.total) }); toast.success("Pedido criado"); setOpenO(false);
      setOForm({ customer_name: "", customer_whatsapp: "", address: "", items: "", total: 0, payment_method: "PIX", notes: "" }); loadAll(); }
    catch (e) { toast.error(e.response?.data?.detail || "Erro"); }
  };
  const dispatchOrder = async () => {
    if (!dispatchMotoboy) { toast.error("Escolha um motoboy"); return; }
    try {
      const { data } = await api.post(`/orders/${openD.id}/dispatch`, { motoboy_id: dispatchMotoboy });
      const motoboy = motoboys.find(x => x.id === dispatchMotoboy);
      const publicUrl = window.location.origin;
      const customerLink = `${publicUrl}/track/${data.tracking_token}`;
      const motoboyLink = `${publicUrl}/motoboy/${data.motoboy_share_token}`;
      // WhatsApp to motoboy
      const msgMoto = `🚀 Novo pedido!\nCliente: ${data.customer_name}\nEndereço: ${data.address}\nTotal: R$ ${Number(data.total).toFixed(2)}\n\n📍 Compartilhe sua localização: ${motoboyLink}`;
      const msgClient = `🛵 Seu pedido saiu para entrega!\nAcompanhe em tempo real: ${customerLink}`;
      window.open(`https://wa.me/${sanitizeWhatsapp(motoboy.whatsapp)}?text=${encodeURIComponent(msgMoto)}`, "_blank");
      setTimeout(() => window.open(`https://wa.me/${sanitizeWhatsapp(data.customer_whatsapp)}?text=${encodeURIComponent(msgClient)}`, "_blank"), 500);
      toast.success("Pedido despachado — WhatsApp aberto");
      setOpenD(null); setDispatchMotoboy(""); loadAll();
    } catch (e) { toast.error(e.response?.data?.detail || "Erro"); }
  };
  const changeStatus = async (id, status) => { await api.patch(`/orders/${id}/status`, { status }); toast.success("Status atualizado"); loadAll(); };
  const saveLad = async () => { await api.put("/store/lad", { api_token: ladToken, api_base: "https://api2.laddelivery.com.br" }); toast.success("Token LAD salvo"); loadAll(); };
  const importLad = async () => {
    if (!ladUuid.trim()) { toast.error("Informe o UUID do pedido LAD"); return; }
    try {
      const { data } = await api.post("/store/lad/import", { uuid: ladUuid.trim() });
      toast.success(data.imported ? "Pedido importado da LAD" : "Pedido atualizado");
      setOpenImport(false); setLadUuid(""); loadAll();
    } catch (e) { toast.error(e.response?.data?.detail || "Falha ao importar"); }
  };
  const refreshLad = async () => {
    setRefreshing(true);
    try {
      const { data } = await api.post("/store/lad/refresh");
      toast.success(`${data.updated}/${data.total} pedidos sincronizados`);
      loadAll();
    } catch (e) { toast.error(e.response?.data?.detail || "Falha"); }
    finally { setRefreshing(false); }
  };
  const testLad = async () => {
    try { const { data } = await api.get("/store/lad/loja"); toast.success(`Conectado: ${data.data?.nome || "OK"}`); }
    catch (e) { toast.error(e.response?.data?.detail || "Falha"); }
  };
  const copyLink = (link, id) => { navigator.clipboard.writeText(link); setCopied(id); setTimeout(() => setCopied(null), 1500); };
  const sendClientWhatsapp = (order) => {
    const link = `${window.location.origin}/track/${order.tracking_token}`;
    const msg = `🛵 Acompanhe seu pedido em tempo real: ${link}`;
    window.open(`https://wa.me/${sanitizeWhatsapp(order.customer_whatsapp)}?text=${encodeURIComponent(msg)}`, "_blank");
  };

  return (
    <div className="min-h-screen bg-[#0B0F17] text-slate-100">
      <header className="glass sticky top-0 z-40 border-b border-slate-800 px-6 py-4">
        <div className="max-w-7xl mx-auto flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="w-9 h-9 rounded-xl bg-indigo-500 grid place-items-center"><Zap className="w-5 h-5" /></div>
            <div>
              <div className="font-display font-bold text-lg">{store?.name || "Minha Loja"}</div>
              <div className="text-xs text-slate-500">{user?.email}</div>
            </div>
          </div>
          <Button data-testid="store-logout-btn" onClick={() => { logout(); nav("/"); }} variant="ghost" className="text-slate-400 hover:text-white">
            <LogOut className="w-4 h-4 mr-2" /> Sair
          </Button>
        </div>
      </header>

      <main className="max-w-7xl mx-auto px-6 py-8">
        <Tabs value={tab} onValueChange={setTab}>
          <TabsList className="bg-slate-900 border border-slate-800">
            <TabsTrigger data-testid="tab-orders" value="orders"><Package className="w-4 h-4 mr-2" /> Pedidos</TabsTrigger>
            <TabsTrigger data-testid="tab-motoboys" value="motoboys"><Bike className="w-4 h-4 mr-2" /> Motoboys</TabsTrigger>
            <TabsTrigger data-testid="tab-settings" value="settings"><Settings className="w-4 h-4 mr-2" /> Integração LAD</TabsTrigger>
          </TabsList>

          <TabsContent value="orders" className="mt-6">
            <div className="flex items-center justify-between mb-4 flex-wrap gap-2">
              <h2 className="font-display font-bold text-2xl">Pedidos</h2>
              <div className="flex items-center gap-2 flex-wrap">
                {store?.lad_api_token && (
                  <>
                    <Button data-testid="lad-refresh-btn" onClick={refreshLad} disabled={refreshing} variant="outline" className="border-slate-700">
                      <RefreshCw className={`w-4 h-4 mr-2 ${refreshing ? "animate-spin" : ""}`} /> Sincronizar LAD
                    </Button>
                    <Dialog open={openImport} onOpenChange={setOpenImport}>
                      <DialogTrigger asChild>
                        <Button data-testid="lad-import-btn" variant="outline" className="border-emerald-700 text-emerald-300 hover:bg-emerald-950">
                          <Download className="w-4 h-4 mr-2" /> Importar da LAD
                        </Button>
                      </DialogTrigger>
                      <DialogContent className="bg-slate-950 border-slate-800 text-slate-100">
                        <DialogHeader><DialogTitle className="font-display">Importar pedido LAD</DialogTitle></DialogHeader>
                        <div>
                          <Label>UUID do pedido LAD</Label>
                          <Input data-testid="lad-uuid-input" value={ladUuid} onChange={e => setLadUuid(e.target.value)}
                            placeholder="b3f6a8f0-1234-4c56-9abc-def012345678"
                            className="bg-slate-900 border-slate-800 mt-1 font-mono" />
                          <p className="text-xs text-slate-500 mt-2">Puxaremos os dados do pedido diretamente da API LAD e criaremos um rastreio interno.</p>
                        </div>
                        <DialogFooter><Button data-testid="lad-import-confirm-btn" onClick={importLad} className="bg-indigo-500 hover:bg-indigo-600">Importar</Button></DialogFooter>
                      </DialogContent>
                    </Dialog>
                  </>
                )}
                <Dialog open={openO} onOpenChange={setOpenO}>
                <DialogTrigger asChild>
                  <Button data-testid="create-order-btn" className="bg-indigo-500 hover:bg-indigo-600"><Plus className="w-4 h-4 mr-2" /> Novo pedido</Button>
                </DialogTrigger>
                <DialogContent className="bg-slate-950 border-slate-800 text-slate-100 max-w-lg">
                  <DialogHeader><DialogTitle className="font-display">Novo pedido</DialogTitle></DialogHeader>
                  <div className="grid grid-cols-2 gap-3">
                    <div className="col-span-2"><Label>Cliente</Label><Input data-testid="order-customer-name" value={oForm.customer_name} onChange={e => setOForm({...oForm, customer_name: e.target.value})} className="bg-slate-900 border-slate-800 mt-1" /></div>
                    <div><Label>WhatsApp</Label><Input data-testid="order-customer-whatsapp" value={oForm.customer_whatsapp} onChange={e => setOForm({...oForm, customer_whatsapp: e.target.value})} placeholder="55119..." className="bg-slate-900 border-slate-800 mt-1" /></div>
                    <div><Label>Total (R$)</Label><Input data-testid="order-total" type="number" step="0.01" value={oForm.total} onChange={e => setOForm({...oForm, total: e.target.value})} className="bg-slate-900 border-slate-800 mt-1" /></div>
                    <div className="col-span-2"><Label>Endereço</Label><Input data-testid="order-address" value={oForm.address} onChange={e => setOForm({...oForm, address: e.target.value})} className="bg-slate-900 border-slate-800 mt-1" /></div>
                    <div className="col-span-2"><Label>Itens</Label><Textarea data-testid="order-items" value={oForm.items} onChange={e => setOForm({...oForm, items: e.target.value})} className="bg-slate-900 border-slate-800 mt-1" placeholder="1x X-Salada, 1x Coca 2L" /></div>
                    <div><Label>Pagamento</Label>
                      <Select value={oForm.payment_method} onValueChange={v => setOForm({...oForm, payment_method: v})}>
                        <SelectTrigger data-testid="order-payment" className="bg-slate-900 border-slate-800 mt-1"><SelectValue /></SelectTrigger>
                        <SelectContent className="bg-slate-900 border-slate-800 text-slate-100">
                          <SelectItem value="PIX">PIX</SelectItem><SelectItem value="DINHEIRO">Dinheiro</SelectItem>
                          <SelectItem value="CREDITO">Crédito</SelectItem><SelectItem value="DEBITO">Débito</SelectItem>
                        </SelectContent>
                      </Select>
                    </div>
                    <div><Label>Observações</Label><Input data-testid="order-notes" value={oForm.notes} onChange={e => setOForm({...oForm, notes: e.target.value})} className="bg-slate-900 border-slate-800 mt-1" /></div>
                  </div>
                  <DialogFooter><Button data-testid="order-save-btn" onClick={createOrder} className="bg-indigo-500 hover:bg-indigo-600">Criar pedido</Button></DialogFooter>
                </DialogContent>
              </Dialog>
              </div>
            </div>

            <div className="grid gap-3">
              {orders.map(o => {
                const st = STATUS_LABELS[o.status] || STATUS_LABELS.pending;
                const trackUrl = `${window.location.origin}/track/${o.tracking_token}`;
                return (
                  <Card key={o.id} data-testid={`order-card-${o.id}`} className="card-dark border-slate-800 p-5">
                    <div className="flex items-start justify-between gap-4 flex-wrap">
                      <div>
                        <div className="flex items-center gap-2 mb-1">
                          <span className="font-display font-bold text-lg">{o.customer_name}</span>
                          <Badge className={st.color}>{st.label}</Badge>
                        </div>
                        <div className="text-sm text-slate-400">{o.address}</div>
                        <div className="text-xs text-slate-500 mt-1">{o.items}</div>
                        {o.lad_uuid && <div className="text-xs text-emerald-400 mt-1 font-mono">LAD · {o.lad_uuid.slice(0, 8)}…</div>}
                        {o.motoboy && <div className="text-xs text-indigo-300 mt-1">🛵 {o.motoboy.name}</div>}
                      </div>
                      <div className="text-right">
                        <div className="text-2xl font-display font-bold">R$ {Number(o.total).toFixed(2)}</div>
                        <div className="text-xs text-slate-500">{o.payment_method}</div>
                      </div>
                    </div>
                    <div className="mt-4 flex flex-wrap gap-2">
                      {o.status !== "dispatched" && o.status !== "delivered" && (
                        <Button data-testid={`dispatch-btn-${o.id}`} size="sm" onClick={() => setOpenD(o)} className="bg-indigo-500 hover:bg-indigo-600">
                          <Send className="w-3 h-3 mr-2" /> Despachar
                        </Button>
                      )}
                      {o.status === "dispatched" && (
                        <>
                          <Button data-testid={`copy-track-${o.id}`} size="sm" variant="outline" onClick={() => copyLink(trackUrl, o.id)} className="border-slate-700">
                            {copied === o.id ? <Check className="w-3 h-3 mr-2 text-emerald-400" /> : <Copy className="w-3 h-3 mr-2" />}
                            Link cliente
                          </Button>
                          <Button data-testid={`whatsapp-client-${o.id}`} size="sm" variant="outline" onClick={() => sendClientWhatsapp(o)} className="border-emerald-700 text-emerald-300 hover:bg-emerald-950">
                            <MessageCircle className="w-3 h-3 mr-2" /> Reenviar WhatsApp
                          </Button>
                          <Button data-testid={`delivered-btn-${o.id}`} size="sm" variant="outline" onClick={() => changeStatus(o.id, "delivered")} className="border-slate-700">
                            Marcar entregue
                          </Button>
                        </>
                      )}
                      {o.status === "pending" && (
                        <Button size="sm" variant="ghost" onClick={() => changeStatus(o.id, "preparing")} className="text-slate-400">Em preparo</Button>
                      )}
                    </div>
                  </Card>
                );
              })}
              {orders.length === 0 && <div className="text-center text-slate-500 py-16">Nenhum pedido ainda.</div>}
            </div>
          </TabsContent>

          <TabsContent value="motoboys" className="mt-6">
            <div className="flex items-center justify-between mb-4">
              <h2 className="font-display font-bold text-2xl">Motoboys</h2>
              <Dialog open={openM} onOpenChange={setOpenM}>
                <DialogTrigger asChild>
                  <Button data-testid="create-motoboy-btn" className="bg-indigo-500 hover:bg-indigo-600"><Plus className="w-4 h-4 mr-2" /> Cadastrar</Button>
                </DialogTrigger>
                <DialogContent className="bg-slate-950 border-slate-800 text-slate-100">
                  <DialogHeader><DialogTitle className="font-display">Cadastrar motoboy</DialogTitle></DialogHeader>
                  <div className="space-y-3">
                    <div><Label>Nome</Label><Input data-testid="motoboy-name" value={mForm.name} onChange={e => setMForm({...mForm, name: e.target.value})} className="bg-slate-900 border-slate-800 mt-1" /></div>
                    <div><Label>WhatsApp (com DDD)</Label><Input data-testid="motoboy-whatsapp" value={mForm.whatsapp} onChange={e => setMForm({...mForm, whatsapp: e.target.value})} placeholder="11999998888" className="bg-slate-900 border-slate-800 mt-1" /></div>
                    <div className="grid grid-cols-2 gap-3">
                      <div><Label>Veículo</Label><Input data-testid="motoboy-vehicle" value={mForm.vehicle} onChange={e => setMForm({...mForm, vehicle: e.target.value})} className="bg-slate-900 border-slate-800 mt-1" /></div>
                      <div><Label>Placa</Label><Input data-testid="motoboy-plate" value={mForm.plate} onChange={e => setMForm({...mForm, plate: e.target.value})} className="bg-slate-900 border-slate-800 mt-1" /></div>
                    </div>
                  </div>
                  <DialogFooter><Button data-testid="motoboy-save-btn" onClick={createMotoboy} className="bg-indigo-500 hover:bg-indigo-600">Salvar</Button></DialogFooter>
                </DialogContent>
              </Dialog>
            </div>
            <div className="grid md:grid-cols-2 gap-3">
              {motoboys.map(m => (
                <Card key={m.id} data-testid={`motoboy-card-${m.id}`} className="card-dark border-slate-800 p-5 flex items-center justify-between">
                  <div className="flex items-center gap-3">
                    <div className="w-11 h-11 rounded-full bg-indigo-500/20 border border-indigo-500/30 grid place-items-center">
                      <Bike className="w-5 h-5 text-indigo-400" />
                    </div>
                    <div>
                      <div className="font-display font-bold">{m.name}</div>
                      <div className="text-xs text-slate-500">{m.whatsapp} · {m.vehicle} {m.plate && `· ${m.plate}`}</div>
                    </div>
                  </div>
                  <Button data-testid={`del-motoboy-${m.id}`} onClick={() => delMotoboy(m.id)} variant="ghost" size="icon" className="text-rose-400 hover:bg-rose-950">
                    <Trash2 className="w-4 h-4" />
                  </Button>
                </Card>
              ))}
              {motoboys.length === 0 && <div className="col-span-full text-center text-slate-500 py-12">Nenhum motoboy cadastrado.</div>}
            </div>
          </TabsContent>

          <TabsContent value="settings" className="mt-6">
            <Card className="card-dark border-slate-800 p-6 max-w-2xl">
              <h2 className="font-display font-bold text-2xl mb-2">Integração LAD Delivery</h2>
              <p className="text-slate-400 text-sm mb-4">Cole o token de API fornecido pela LAD Sistemas para sincronizar sua loja.</p>
              <Label>Bearer Token</Label>
              <Input data-testid="lad-token-input" value={ladToken} onChange={e => setLadToken(e.target.value)} type="password"
                className="bg-slate-900 border-slate-800 mt-1 mb-4 font-mono" placeholder="SEU_TOKEN" />
              <div className="flex gap-3">
                <Button data-testid="lad-save-btn" onClick={saveLad} className="bg-indigo-500 hover:bg-indigo-600">Salvar</Button>
                <Button data-testid="lad-test-btn" onClick={testLad} variant="outline" className="border-slate-700">Testar conexão</Button>
              </div>
              <div className="mt-6 pt-6 border-t border-slate-800 text-xs text-slate-500">
                Base URL: <span className="text-slate-300 font-mono">https://api2.laddelivery.com.br</span>
              </div>
            </Card>
          </TabsContent>
        </Tabs>
      </main>

      <Dialog open={!!openD} onOpenChange={() => setOpenD(null)}>
        <DialogContent className="bg-slate-950 border-slate-800 text-slate-100">
          <DialogHeader><DialogTitle className="font-display">Despachar pedido</DialogTitle></DialogHeader>
          <div className="space-y-4">
            <p className="text-sm text-slate-400">Ao despachar, abriremos o WhatsApp para o motoboy (com link de compartilhar localização) e para o cliente (link de rastreio).</p>
            <div>
              <Label>Motoboy</Label>
              <Select value={dispatchMotoboy} onValueChange={setDispatchMotoboy}>
                <SelectTrigger data-testid="dispatch-motoboy-select" className="bg-slate-900 border-slate-800 mt-1"><SelectValue placeholder="Selecione…" /></SelectTrigger>
                <SelectContent className="bg-slate-900 border-slate-800 text-slate-100">
                  {motoboys.map(m => <SelectItem key={m.id} value={m.id}>{m.name} · {m.whatsapp}</SelectItem>)}
                </SelectContent>
              </Select>
            </div>
          </div>
          <DialogFooter>
            <Button data-testid="confirm-dispatch-btn" onClick={dispatchOrder} className="bg-indigo-500 hover:bg-indigo-600"><Send className="w-4 h-4 mr-2" />Disparar rastreio</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}

function sanitizeWhatsapp(s) {
  if (!s) return "";
  const d = s.replace(/\D/g, "");
  return d.startsWith("55") ? d : `55${d}`;
}
