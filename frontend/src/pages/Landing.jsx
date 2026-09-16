import { Link } from "react-router-dom";
import { MapPin, Zap, Bike, Store, Shield, MessageCircle } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useAuth } from "@/context/AuthContext";

export default function Landing() {
  const { user } = useAuth();
  return (
    <div className="min-h-screen bg-[#0B0F17] text-slate-100 relative overflow-hidden">
      <div className="absolute inset-0 gradient-mesh" />
      <nav className="relative z-10 flex items-center justify-between px-8 py-6 max-w-7xl mx-auto">
        <div className="flex items-center gap-2">
          <div className="w-9 h-9 rounded-xl bg-indigo-500 grid place-items-center">
            <Zap className="w-5 h-5 text-white" />
          </div>
          <span className="font-display font-bold text-xl">ZapPedidos</span>
          <span className="text-xs text-slate-500 ml-2 hidden sm:inline">· LAD Tracker</span>
        </div>
        <div className="flex items-center gap-3">
          {user ? (
            <Link to={user.role === "admin" ? "/admin" : "/dashboard"} data-testid="nav-dashboard-link">
              <Button data-testid="nav-dashboard-btn" className="bg-indigo-500 hover:bg-indigo-600">Painel</Button>
            </Link>
          ) : (
            <>
              <Link to="/login"><Button data-testid="nav-login-btn" variant="ghost" className="text-slate-300 hover:text-white">Entrar</Button></Link>
              <Link to="/register"><Button data-testid="nav-register-btn" className="bg-indigo-500 hover:bg-indigo-600">Criar conta</Button></Link>
            </>
          )}
        </div>
      </nav>

      <section className="relative z-10 max-w-7xl mx-auto px-8 pt-16 pb-24">
        <div className="grid lg:grid-cols-2 gap-16 items-center">
          <div>
            <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-indigo-500/10 border border-indigo-500/30 text-xs text-indigo-300 mb-6">
              <span className="w-2 h-2 rounded-full bg-indigo-400 pulse-dot" />
              Rastreamento em tempo real
            </div>
            <h1 className="font-display font-black text-5xl sm:text-6xl lg:text-7xl leading-[1.02]">
              Do WhatsApp<br/>
              à porta do<br/>
              <span className="text-indigo-400">cliente.</span>
            </h1>
            <p className="text-slate-400 text-lg mt-6 max-w-lg">
              Painel completo para revendedores e lojas: cadastre motoboys, dispare rastreio ao vivo pelo
              WhatsApp e integre-se à API LAD Delivery em minutos.
            </p>
            <div className="flex flex-wrap gap-3 mt-8">
              <Link to="/register">
                <Button data-testid="hero-cta-btn" size="lg" className="bg-indigo-500 hover:bg-indigo-600 text-base px-6 h-12">
                  Começar agora
                </Button>
              </Link>
              <Link to="/login">
                <Button data-testid="hero-login-btn" size="lg" variant="outline" className="border-slate-700 hover:bg-slate-800 text-base px-6 h-12">
                  Já sou cliente
                </Button>
              </Link>
            </div>
            <div className="mt-10 flex items-center gap-6 text-sm text-slate-500">
              <div className="flex items-center gap-2"><Shield className="w-4 h-4" /> Multi-tenant</div>
              <div className="flex items-center gap-2"><MessageCircle className="w-4 h-4" /> WhatsApp nativo</div>
              <div className="flex items-center gap-2"><MapPin className="w-4 h-4" /> Live tracking</div>
            </div>
          </div>

          <div className="relative">
            <div className="card-dark p-6 relative overflow-hidden">
              <div className="flex items-center justify-between mb-4">
                <div className="text-xs text-slate-500 uppercase tracking-wider">Pedido #1042</div>
                <div className="text-xs px-2 py-1 rounded-full bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">
                  Em rota
                </div>
              </div>
              <div className="h-64 rounded-xl bg-slate-900 border border-slate-800 grid place-items-center relative overflow-hidden">
                <div className="absolute inset-0 opacity-30" style={{background: "radial-gradient(circle at 60% 40%, #6366F1 0%, transparent 40%)"}} />
                <MapPin className="w-16 h-16 text-indigo-400 pulse-dot" />
              </div>
              <div className="mt-4 space-y-3">
                <div className="flex items-center gap-3">
                  <div className="w-8 h-8 rounded-full bg-indigo-500/20 grid place-items-center"><Bike className="w-4 h-4 text-indigo-400" /></div>
                  <div>
                    <div className="text-sm font-medium">Carlos Silva</div>
                    <div className="text-xs text-slate-500">Honda CG 160 · A 4 min</div>
                  </div>
                </div>
                <div className="flex items-center gap-3">
                  <div className="w-8 h-8 rounded-full bg-emerald-500/20 grid place-items-center"><Store className="w-4 h-4 text-emerald-400" /></div>
                  <div>
                    <div className="text-sm font-medium">Du Cheff Burguer</div>
                    <div className="text-xs text-slate-500">Rua Natal, 123 · Centro</div>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </section>

      <section className="relative z-10 max-w-7xl mx-auto px-8 pb-24">
        <div className="grid md:grid-cols-3 gap-6">
          {[
            { icon: Store, title: "Admin geral", desc: "Gerencie todas as lojas do revendedor em um painel único." },
            { icon: Bike, title: "Motoboys por loja", desc: "Cadastro rápido, WhatsApp, veículo e placa." },
            { icon: MapPin, title: "Rastreio ao vivo", desc: "Link único para cliente e motoboy — sem apps." },
          ].map((f, i) => (
            <div key={i} className="card-dark p-6">
              <div className="w-11 h-11 rounded-xl bg-indigo-500/10 border border-indigo-500/30 grid place-items-center mb-4">
                <f.icon className="w-5 h-5 text-indigo-400" />
              </div>
              <h3 className="font-display font-bold text-xl mb-2">{f.title}</h3>
              <p className="text-slate-400 text-sm">{f.desc}</p>
            </div>
          ))}
        </div>
      </section>
    </div>
  );
}
