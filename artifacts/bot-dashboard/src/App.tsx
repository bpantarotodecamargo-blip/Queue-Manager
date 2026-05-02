import { useState, useEffect, useCallback } from "react";
import { Power, Activity, Terminal, Shield, Ticket, Key, FileText, Users, Clock, Server } from "lucide-react";
import { motion } from "framer-motion";

interface BotStatus {
  online: boolean;
  uptime_seconds: number;
  guilds: number;
  commands: number;
  filas_ativas: boolean;
}

function formatUptime(seconds: number) {
  const days = Math.floor(seconds / (3600 * 24));
  const hrs = Math.floor((seconds % (3600 * 24)) / 3600);
  const mins = Math.floor((seconds % 3600) / 60);
  const secs = seconds % 60;

  const parts: string[] = [];
  if (days > 0) parts.push(`${days}d`);
  if (hrs > 0 || days > 0) parts.push(`${hrs.toString().padStart(2, "0")}h`);
  parts.push(`${mins.toString().padStart(2, "0")}m`);
  parts.push(`${secs.toString().padStart(2, "0")}s`);

  return parts.join(" : ");
}

const BASE = import.meta.env.BASE_URL?.replace(/\/$/, "") ?? "";

export default function App() {
  const [status, setStatus] = useState<BotStatus>({
    online: false,
    uptime_seconds: 0,
    guilds: 0,
    commands: 0,
    filas_ativas: true,
  });
  const [toggling, setToggling] = useState(false);
  const [displayUptime, setDisplayUptime] = useState(0);

  const fetchStatus = useCallback(async () => {
    try {
      const res = await fetch(`${BASE}/api/bot-status`);
      if (res.ok) {
        const data: BotStatus = await res.json();
        setStatus(data);
        setDisplayUptime(data.uptime_seconds);
      }
    } catch {
      setStatus((prev) => ({ ...prev, online: false }));
    }
  }, []);

  useEffect(() => {
    fetchStatus();
    const poll = setInterval(fetchStatus, 5000);
    return () => clearInterval(poll);
  }, [fetchStatus]);

  useEffect(() => {
    if (!status.online) return;
    const tick = setInterval(() => setDisplayUptime((p) => p + 1), 1000);
    return () => clearInterval(tick);
  }, [status.online]);

  const toggleFilas = async () => {
    if (toggling) return;
    setToggling(true);
    try {
      const res = await fetch(`${BASE}/api/bot-toggle`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({}),
      });
      if (res.ok) {
        const data = await res.json();
        setStatus((prev) => ({ ...prev, filas_ativas: data.filas_ativas }));
      }
    } catch {
    } finally {
      setToggling(false);
      setTimeout(fetchStatus, 500);
    }
  };

  const isOnline = status.online;
  const filasOn = status.filas_ativas;

  const features = [
    { icon: <Shield className="w-5 h-5" />, name: "Sistema de Filas", status: filasOn ? "Ativo" : "Pausado" },
    { icon: <Ticket className="w-5 h-5" />, name: "Tickets", status: "Ativo" },
    { icon: <Key className="w-5 h-5" />, name: "Sistema de Keys", status: "Operacional" },
    { icon: <FileText className="w-5 h-5" />, name: "Regras", status: "Carregado" },
    { icon: <Users className="w-5 h-5" />, name: "Convites", status: "Sincronizado" },
  ];

  return (
    <div className="min-h-screen bg-[#060608] text-white flex flex-col items-center justify-center p-4 relative overflow-hidden font-sans">
      <div className="fixed inset-0 pointer-events-none opacity-20">
        <div className="absolute top-[-20%] left-[-10%] w-[50%] h-[50%] rounded-full bg-primary blur-[120px]" />
        <div className="absolute bottom-[-20%] right-[-10%] w-[40%] h-[40%] rounded-full bg-primary blur-[100px]" />
      </div>

      <div className="absolute inset-0 pointer-events-none bg-[url('https://grainy-gradients.vercel.app/noise.svg')] opacity-[0.03] mix-blend-overlay"></div>

      <div className="w-full max-w-md mx-auto relative z-10 flex flex-col gap-8 pb-12">

        <header className="flex flex-col items-center gap-2 pt-8">
          <motion.div
            initial={{ opacity: 0, y: -20 }}
            animate={{ opacity: 1, y: 0 }}
            className="flex items-center justify-center gap-3 px-4 py-1.5 rounded-full border border-white/10 bg-white/5 backdrop-blur-md"
          >
            <div className={`w-2 h-2 rounded-full ${isOnline ? 'bg-primary animate-pulse shadow-[0_0_10px_var(--color-primary)]' : 'bg-destructive'}`} />
            <span className="text-xs font-bold tracking-widest uppercase text-white/70">
              {isOnline ? 'SISTEMA OPERACIONAL' : 'SISTEMA OFFLINE'}
            </span>
          </motion.div>
          <motion.h1
            initial={{ opacity: 0, scale: 0.9 }}
            animate={{ opacity: 1, scale: 1 }}
            className="text-5xl md:text-6xl font-bold tracking-tighter mt-4 uppercase text-transparent bg-clip-text bg-gradient-to-br from-white to-white/50"
          >
            BOT FILAS
          </motion.h1>
        </header>

        {/* Hero Power Button — toggles filas on/off */}
        <div className="flex flex-col items-center gap-3 py-6">
          <motion.button
            data-testid="button-power"
            onClick={toggleFilas}
            disabled={toggling || !isOnline}
            whileHover={{ scale: isOnline ? 1.05 : 1 }}
            whileTap={{ scale: isOnline ? 0.95 : 1 }}
            className="relative group disabled:cursor-not-allowed"
          >
            <div className={`absolute inset-0 rounded-full blur-xl transition-all duration-500 ${filasOn && isOnline ? 'bg-primary/40 group-hover:bg-primary/60' : 'bg-destructive/20 group-hover:bg-destructive/40'}`} />
            <div className={`w-40 h-40 md:w-48 md:h-48 rounded-full flex flex-col items-center justify-center gap-3 border-[3px] transition-all duration-500 relative z-10 bg-[#0a0a0c] shadow-2xl
              ${filasOn && isOnline ? 'border-primary/50 text-primary shadow-[inset_0_0_40px_rgba(34,197,94,0.15)]' : 'border-destructive/30 text-destructive/80 shadow-[inset_0_0_40px_rgba(239,68,68,0.1)]'}`}
            >
              <Power className={`w-16 h-16 md:w-20 md:h-20 transition-all duration-500 ${filasOn && isOnline ? 'drop-shadow-[0_0_15px_rgba(34,197,94,0.5)]' : ''}`} strokeWidth={1.5} />
              <span className="font-bold tracking-widest text-sm uppercase">
                {toggling ? '...' : filasOn ? 'Filas ON' : 'Filas OFF'}
              </span>
            </div>
          </motion.button>
          <p className="text-xs text-white/30 text-center">
            {isOnline ? 'Clique para ligar/desligar as filas' : 'Bot offline — aguardando conexão'}
          </p>
        </div>

        {/* Stats Grid */}
        <div className="grid grid-cols-2 gap-4">
          <div className="bg-white/5 border border-white/10 rounded-xl p-4 backdrop-blur-sm flex flex-col gap-1">
            <div className="flex items-center gap-2 text-white/50 mb-1">
              <Clock className="w-4 h-4" />
              <span className="text-xs uppercase font-bold tracking-wider">Uptime</span>
            </div>
            <div className={`font-mono text-xl font-bold tracking-tight ${isOnline ? 'text-primary' : 'text-white/30'}`}>
              {isOnline ? formatUptime(displayUptime) : '--:--:--'}
            </div>
          </div>

          <div className="bg-white/5 border border-white/10 rounded-xl p-4 backdrop-blur-sm flex flex-col gap-1">
            <div className="flex items-center gap-2 text-white/50 mb-1">
              <Activity className="w-4 h-4" />
              <span className="text-xs uppercase font-bold tracking-wider">Status</span>
            </div>
            <div className={`text-xl font-bold tracking-tight ${isOnline ? 'text-primary' : 'text-destructive'}`}>
              {isOnline ? 'ONLINE' : 'OFFLINE'}
            </div>
          </div>

          <div className="bg-white/5 border border-white/10 rounded-xl p-4 backdrop-blur-sm flex flex-col gap-1">
            <div className="flex items-center gap-2 text-white/50 mb-1">
              <Server className="w-4 h-4" />
              <span className="text-xs uppercase font-bold tracking-wider">Servidores</span>
            </div>
            <div className="text-xl font-bold tracking-tight text-white">{status.guilds}</div>
          </div>

          <div className="bg-white/5 border border-white/10 rounded-xl p-4 backdrop-blur-sm flex flex-col gap-1">
            <div className="flex items-center gap-2 text-white/50 mb-1">
              <Terminal className="w-4 h-4" />
              <span className="text-xs uppercase font-bold tracking-wider">Comandos</span>
            </div>
            <div className="text-xl font-bold tracking-tight text-white">{status.commands}</div>
          </div>
        </div>

        {/* Features List */}
        <div className="bg-white/5 border border-white/10 rounded-2xl p-5 backdrop-blur-sm mt-2">
          <h3 className="text-xs uppercase font-bold tracking-widest text-white/50 mb-4 border-b border-white/10 pb-3 flex items-center gap-2">
            <Shield className="w-4 h-4" />
            Módulos do Sistema
          </h3>
          <div className="flex flex-col gap-4">
            {features.map((feature, i) => (
              <div key={i} className="flex items-center justify-between">
                <div className="flex items-center gap-3 text-white/80">
                  <div className={`p-2 rounded-lg bg-white/5 border ${isOnline ? 'border-primary/20 text-primary' : 'border-white/10 text-white/40'}`}>
                    {feature.icon}
                  </div>
                  <span className="font-medium">{feature.name}</span>
                </div>
                <div className="flex items-center gap-2">
                  <span className="text-xs font-bold tracking-wider text-white/40 uppercase hidden sm:block">
                    {isOnline ? feature.status : 'Desconectado'}
                  </span>
                  <div className={`w-1.5 h-1.5 rounded-full ${isOnline ? 'bg-primary shadow-[0_0_5px_var(--color-primary)]' : 'bg-white/20'}`} />
                </div>
              </div>
            ))}
          </div>
        </div>

      </div>
    </div>
  );
}
