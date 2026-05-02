import { Router, type IRouter } from "express";
import healthRouter from "./health";
import botStatusRouter from "./bot-status";

const router: IRouter = Router();

router.use(healthRouter);
router.use(botStatusRouter);

export default router;
