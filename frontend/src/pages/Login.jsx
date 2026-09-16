import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { toast } from "sonner";
import { Zap } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useAuth } from "@/context/AuthContext";

export default function Login() {
  const { login } = useAuth();
  const nav = useNavigate();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);

  const submit = async (e) => {
    e.preventDefault();
    setLoading(true);
    try {
      const u = await login(email, password);  // senha field mapped in AuthContext.login
      toast.success("Bem-vindo!");
      nav(u.role === "admin" ? "/admin" : "/dashboard");
    } catch (err) {
      toast.error(err.response?.data?.detail || "Falha ao entrar");
    } finally { setLoading(false); }
  };

  return (
    <div className="min-h-screen bg-[#0B0F17] grid place-items-center px-6 gradient-mesh">
      <div className="w-full max-w-md">
        <Link to="/" className="flex items-center gap-2 justify-center mb-8">
          <div className="w-9 h-9 rounded-xl bg-indigo-500 grid place-items-center"><Zap className="w-5 h-5" /></div>
          <span className="font-display font-bold text-xl text-white">ZapPedidos</span>
        </Link>
        <div className="card-dark p-8">
          <h1 className="font-display font-bold text-3xl text-white mb-2">Entrar</h1>
          <p className="text-slate-400 text-sm mb-6">Acesse seu painel de gestão.</p>
          <form onSubmit={submit} className="space-y-4">
            <div>
              <Label className="text-slate-300">Email</Label>
              <Input data-testid="login-email-input" type="email" required value={email} onChange={e => setEmail(e.target.value)}
                className="mt-1 bg-slate-900 border-slate-800 text-white" placeholder="voce@loja.com" />
            </div>
            <div>
              <Label className="text-slate-300">Senha</Label>
              <Input data-testid="login-password-input" type="password" required value={password} onChange={e => setPassword(e.target.value)}
                className="mt-1 bg-slate-900 border-slate-800 text-white" placeholder="••••••••" />
            </div>
            <Button data-testid="login-submit-btn" disabled={loading} type="submit" className="w-full bg-indigo-500 hover:bg-indigo-600 h-11">
              {loading ? "Entrando…" : "Entrar"}
            </Button>
          </form>
          <div className="mt-6 text-center text-sm text-slate-500">
            Não tem conta? <Link to="/register" className="text-indigo-400 hover:text-indigo-300">Criar agora</Link>
          </div>
          <div className="mt-6 border-t border-slate-800 pt-4 text-xs text-slate-500 text-center">
            Admin demo: <span className="text-slate-300">admin@zappedidos.com</span> / <span className="text-slate-300">admin123</span>
          </div>
        </div>
      </div>
    </div>
  );
}
