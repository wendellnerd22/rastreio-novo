import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { Toaster } from "@/components/ui/sonner";
import { AuthProvider, useAuth } from "@/context/AuthContext";
import Landing from "@/pages/Landing";
import Login from "@/pages/Login";
import Register from "@/pages/Register";
import AdminDashboard from "@/pages/AdminDashboard";
import StoreDashboard from "@/pages/StoreDashboard";
import CustomerTrack from "@/pages/CustomerTrack";
import MotoboyShare from "@/pages/MotoboyShare";
import "@/App.css";
import "leaflet/dist/leaflet.css";

function Protected({ role, children }) {
  const { user, loading } = useAuth();
  if (loading) return <div className="min-h-screen grid place-items-center text-slate-400">Carregando…</div>;
  if (!user) return <Navigate to="/login" replace />;
  // "role" prop expects legacy "store"; new backend uses "lojista"
  const roles = role === "store" ? ["lojista"] : role ? [role] : null;
  if (roles && !roles.includes(user.role)) return <Navigate to={user.role === "admin" ? "/admin" : "/dashboard"} replace />;
  return children;
}

function App() {
  return (
    <AuthProvider>
      <BrowserRouter>
        <Routes>
          <Route path="/" element={<Landing />} />
          <Route path="/login" element={<Login />} />
          <Route path="/register" element={<Register />} />
          <Route path="/admin" element={<Protected role="admin"><AdminDashboard /></Protected>} />
          <Route path="/dashboard" element={<Protected role="store"><StoreDashboard /></Protected>} />
          <Route path="/track/:token" element={<CustomerTrack />} />
          <Route path="/motoboy/:token" element={<MotoboyShare />} />
        </Routes>
        <Toaster position="top-right" richColors />
      </BrowserRouter>
    </AuthProvider>
  );
}

export default App;
