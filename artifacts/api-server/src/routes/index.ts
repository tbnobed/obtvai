import { Router, type IRouter } from "express";
import healthRouter from "./health";
import mockRouter from "./mock";
import authRouter, { authMiddleware } from "./auth";
import trainingRouter from "./training";

const router: IRouter = Router();

router.use(healthRouter);
router.use(authMiddleware);
router.use(authRouter);
router.use(trainingRouter);
router.use(mockRouter);

export default router;
