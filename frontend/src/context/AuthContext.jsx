import { createContext, useContext, useEffect, useState } from "react";
import axios from "axios";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;
const AuthCtx = createContext(null);

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(true);
  const [token, setToken] = useState(() => localStorage.getItem("zp_token"));

  useEffect(() => {
    if (!token) { setLoading(false); return; }
    axios.get(`${API}/auth/me`, { headers: { Authorization: `Bearer ${token}` } })
      .then(r => setUser(r.data))
      .catch(() => { localStorage.removeItem("zp_token"); setToken(null); })
      .finally(() => setLoading(false));
  }, [token]);

  const login = async (email, password) => {
    const { data } = await axios.post(`${API}/auth/login`, { email, password });
    localStorage.setItem("zp_token", data.token);
    setToken(data.token); setUser(data.user);
    return data.user;
  };
  const register = async (payload) => {
    const { data } = await axios.post(`${API}/auth/register`, payload);
    localStorage.setItem("zp_token", data.token);
    setToken(data.token); setUser(data.user);
    return data.user;
  };
  const logout = () => { localStorage.removeItem("zp_token"); setToken(null); setUser(null); };

  const api = axios.create({ baseURL: API, headers: token ? { Authorization: `Bearer ${token}` } : {} });

  return <AuthCtx.Provider value={{ user, loading, token, login, register, logout, api, API }}>{children}</AuthCtx.Provider>;
}

export const useAuth = () => useContext(AuthCtx);
export { API };
