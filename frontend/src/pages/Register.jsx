import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { toast } from "sonner";
import { Zap } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useAuth } from "@/context/AuthContext";

export default function Register() {
  const { register } = useAuth();
  const nav = useNavigate();
  const [f, setF] = useState({ name: "", email: "", password: "", store_name: "", phone: "" });
  const [loading, setLoading] = useState(false);
  const upd = (k) => (e) => setF({ ...f, [k]: e.target.value });

  const submit = async (e) => {
    e.preventDefault();
    setLoading(true);
    try {
      await register(f);
      toast.success("Conta criada!");
      nav("/dashboard");
    } catch (err) {
      toast.error(err.response?.data?.detail || "Falha ao criar conta");
    } finally { setLoading(false); }
  };

  return (
    <div className="min-h-screen bg-[#0B0F17] grid place-items-center px-6 py-10 gradient-mesh">
      <div className="w-full max-w-md">
        <Link to="/" className="flex items-center gap-2 justify-center mb-8">
          <div className="w-9 h-9 rounded-xl bg-indigo-500 grid place-items-center"><Zap className="w-5 h-5" /></div>
          <span className="font-display font-bold text-xl text-white">ZapPedidos</span>
        </Link>
        <div className="card-dark p-8">
          <h1 className="font-display font-bold text-3xl text-white mb-2">Cadastre sua loja</h1>
          <p className="text-slate-400 text-sm mb-6">Comece a rastrear pedidos em minutos.</p>
          <form onSubmit={submit} className="space-y-4">
            <div><Label className="text-slate-300">Nome do responsável</Label>
              <Input data-testid="register-name-input" required value={f.name} onChange={upd("name")} className="mt-1 bg-slate-900 border-slate-800 text-white" /></div>
            <div><Label className="text-slate-300">Nome da loja</Label>
              <Input data-testid="register-store-input" required value={f.store_name} onChange={upd("store_name")} className="mt-1 bg-slate-900 border-slate-800 text-white" /></div>
            <div><Label className="text-slate-300">Email</Label>
              <Input data-testid="register-email-input" type="email" required value={f.email} onChange={upd("email")} className="mt-1 bg-slate-900 border-slate-800 text-white" /></div>
            <div><Label className="text-slate-300">Telefone / WhatsApp</Label>
              <Input data-testid="register-phone-input" value={f.phone} onChange={upd("phone")} placeholder="(11) 99999-9999" className="mt-1 bg-slate-900 border-slate-800 text-white" /></div>
            <div><Label className="text-slate-300">Senha</Label>
              <Input data-testid="register-password-input" type="password" required minLength={6} value={f.password} onChange={upd("password")} className="mt-1 bg-slate-900 border-slate-800 text-white" /></div>
            <Button data-testid="register-submit-btn" disabled={loading} type="submit" className="w-full bg-indigo-500 hover:bg-indigo-600 h-11">
              {loading ? "Criando…" : "Criar conta"}
            </Button>
          </form>
          <div className="mt-6 text-center text-sm text-slate-500">
            Já tem conta? <Link to="/login" className="text-indigo-400 hover:text-indigo-300">Entrar</Link>
          </div>
        </div>
      </div>
    </div>
  );
}
