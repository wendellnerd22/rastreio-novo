import { createContext, useContext, useEffect, useState } from "react";
import axios from "axios";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;

// axios instance com cookie httpOnly (zp_session) sempre enviado
const api = axios.create({ baseURL: API, withCredentials: true });

const AuthCtx = createContext(null);

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(true);

  const refresh = async () => {
    try {
      const { data } = await api.get("/auth/me");
      setUser(data);
    } catch { setUser(null); }
    finally { setLoading(false); }
  };

  useEffect(() => { refresh(); }, []);

  const login = async (email, senha) => {
    const { data } = await api.post("/auth/login", { email, senha });
    setUser(data.user);
    return data.user;
  };
  // register recebe {name, email, password, store_name, phone} do form antigo,
  // mas o backend novo espera {nome, email, senha, nome_loja, telefone}
  const _mapRegister = (p) => ({
    nome: p.name || p.nome, email: p.email, senha: p.password || p.senha,
    nome_loja: p.store_name || p.nome_loja, telefone: p.phone || p.telefone,
  });
  const register = async (payload) => {
    const { data } = await api.post("/auth/register", _mapRegister(payload));
    setUser(data.user);
    return data.user;
  };
  const logout = async () => {
    try { await api.post("/auth/logout"); } catch {}
    setUser(null);
  };

  return <AuthCtx.Provider value={{ user, loading, login, register, logout, api, API }}>{children}</AuthCtx.Provider>;
}

export const useAuth = () => useContext(AuthCtx);
export { API, api };
