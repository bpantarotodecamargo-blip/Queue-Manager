import { useState, useEffect } from "react";
import { Power, Activity, Terminal, Shield, Ticket, Key, FileText, Users, Clock, Server } from "lucide-react";
import { motion, AnimatePresence } from "framer-motion";

function formatUptime(seconds: number) {
  const days = Math.floor(seconds / (3600 * 24));
  const hrs = Math.floor((seconds % (3600 * 24)) / 3600);
  const mins = Math.floor((seconds % 3600) / 60);
  const secs = seconds % 60;

  const parts = [];
  if (days > 0) parts.push(`${days}d`);
  if (hrs > 0 || days > 0) parts.push(`${hrs.toString().padStart(2, "0")}h`);
  parts.push(`${mins.toString().padStart(2, "0")}m`);
  parts.push(`${secs.toString().padStart(2, "0")}s`);

  return parts.join(" : ");
}

export default function App() {
  const [isOnline, setIsOnline] = useState(true);
  const [uptime, setUptime] = useState(0);

  useEffect(() => {
    let interval: number | undefined;
    if (isOnline) {
      interval = window.setInterval(() => {
        setUptime((prev) => prev + 1);
      }, 1000);
    } else {
      setUptime(0);
    }
    return () => clearInterval(interval);
  }, [isOnline]);

  const togglePower = () => setIsOnline(!isOnline);

  const features = [
    { icon: <Shield className="w-5 h-5" />, name: "Sistema de Filas", status: "Ativo" },
    { icon: <Ticket className="w-5 h-5" />, name: "Tickets", status: "Ativo" },
    { icon: <Key className="w-5 h-5" />, name: "Sistema de Keys", status: "Operacional" },
    { icon: <FileText className="w-5 h-5" />, name: "Regras", status: "Carregado" },
    { icon: <Users className="w-5 h-5" />, name: "Convites", status: "Sincronizado" },
  ];

  return (
    <div className="min-h-screen bg-[#060608] text-white flex flex-col items-center justify-center p-4 relative overflow-hidden font-sans">
      
      {/* Background Elements */}
      <div className="fixed inset-0 pointer-events-none opacity-20">
        <div className="absolute top-[-20%] left-[-10%] w-[50%] h-[50%] rounded-full bg-primary blur-[120px]" />
        <div className="absolute bottom-[-20%] right-[-10%] w-[40%] h-[40%] rounded-full bg-primary blur-[100px]" />
      </div>
      
      <div className="absolute inset-0 pointer-events-none bg-[url('https://grainy-gradients.vercel.app/noise.svg')] opacity-[0.03] mix-blend-overlay"></div>

      <div className="w-full max-w-md mx-auto relative z-10 flex flex-col gap-8 pb-12">
        
        {/* Header */}
        <header className="flex flex-col items-center gap-2 pt-8">
          <motion.div 
            initial={{ opacity: 0, y: -20 }}
            animate={{ opacity: 1, y: 0 }}
            className="flex items-center justify-center gap-3 px-4 py-1.5 rounded-full border border-white/10 bg-white/5 backdrop-blur-md"
          >
            <div className={`w-2 h-2 rounded-full ${isOnline ? 'bg-primary animate-pulse shadow-[0_0_10px_var(--color-primary)]' : 'bg-destructive'}`} />
            <span className="text-xs font-bold tracking-widest uppercase text-white/70">
              {isOnline ? 'SISTEMA OPERACIONAL' : 'SISTEMA DESLIGADO'}
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

        {/* Hero Power Button */}
        <div className="flex justify-center py-8">
          <motion.button
            data-testid="button-power"
            onClick={togglePower}
            whileHover={{ scale: 1.05 }}
            whileTap={{ scale: 0.95 }}
            className="relative group"
          >
            <div className={`absolute inset-0 rounded-full blur-xl transition-all duration-500 ${isOnline ? 'bg-primary/40 group-hover:bg-primary/60' : 'bg-destructive/20 group-hover:bg-destructive/40'}`} />
            <div className={`w-40 h-40 md:w-48 md:h-48 rounded-full flex flex-col items-center justify-center gap-3 border-[3px] transition-all duration-500 relative z-10 bg-[#0a0a0c] shadow-2xl
              ${isOnline ? 'border-primary/50 text-primary shadow-[inset_0_0_40px_rgba(34,197,94,0.15)]' : 'border-destructive/30 text-destructive/80 shadow-[inset_0_0_40px_rgba(239,68,68,0.1)]'}`}
            >
              <Power className={`w-16 h-16 md:w-20 md:h-20 transition-all duration-500 ${isOnline ? 'drop-shadow-[0_0_15px_rgba(34,197,94,0.5)]' : ''}`} strokeWidth={1.5} />
              <span className="font-bold tracking-widest text-sm uppercase">
                {isOnline ? 'Desligar' : 'Ligar Bot'}
              </span>
            </div>
          </motion.button>
        </div>

        {/* Stats Grid */}
        <div className="grid grid-cols-2 gap-4">
          <div className="bg-white/5 border border-white/10 rounded-xl p-4 backdrop-blur-sm flex flex-col gap-1">
            <div className="flex items-center gap-2 text-white/50 mb-1">
              <Clock className="w-4 h-4" />
              <span className="text-xs uppercase font-bold tracking-wider">Uptime</span>
            </div>
            <div className={`font-mono text-xl font-bold tracking-tight ${isOnline ? 'text-primary' : 'text-white/30'}`}>
              {isOnline ? formatUptime(uptime) : '00:00:00'}
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
            <div className="text-xl font-bold tracking-tight text-white">2</div>
          </div>

          <div className="bg-white/5 border border-white/10 rounded-xl p-4 backdrop-blur-sm flex flex-col gap-1">
            <div className="flex items-center gap-2 text-white/50 mb-1">
              <Terminal className="w-4 h-4" />
              <span className="text-xs uppercase font-bold tracking-wider">Comandos</span>
            </div>
            <div className="text-xl font-bold tracking-tight text-white">20</div>
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
