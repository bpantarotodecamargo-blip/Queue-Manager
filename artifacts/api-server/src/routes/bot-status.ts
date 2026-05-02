import { Router, type IRouter } from "express";

const router: IRouter = Router();

const BOT_PORT = parseInt(process.env.BOT_PORT ?? "8081", 10);
const BOT_BASE = `http://localhost:${BOT_PORT}`;

router.get("/bot-status", async (_req, res) => {
  try {
    const r = await fetch(`${BOT_BASE}/status`, { signal: AbortSignal.timeout(3000) });
    const data = await r.json();
    res.json(data);
  } catch {
    res.json({ online: false, uptime_seconds: 0, guilds: 0, commands: 0, filas_ativas: false });
  }
});

router.post("/bot-toggle", async (req, res) => {
  try {
    const body = req.body ?? {};
    const r = await fetch(`${BOT_BASE}/toggle-filas`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
      signal: AbortSignal.timeout(3000),
    });
    const data = await r.json();
    res.json(data);
  } catch (err: unknown) {
    const msg = err instanceof Error ? err.message : String(err);
    res.status(500).json({ error: msg });
  }
});

export default router;
