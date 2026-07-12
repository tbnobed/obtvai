import { Router, type IRouter } from "express";
import healthRouter from "./health";
import mockRouter from "./mock";

const router: IRouter = Router();

router.use(healthRouter);
router.use(mockRouter);

export default router;
