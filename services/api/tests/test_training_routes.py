"""Isolated SQLite route checks; never connect to the configured production DB."""
import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
import httpx
from fastapi import FastAPI, Request
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from app.database import get_db
from app.routers.training import router
from app.training_models import TrainingExample, TrainingDataset, TrainingEvaluation


class TrainingRouteTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with self.engine.begin() as connection:
            for table in (TrainingExample.__table__, TrainingDataset.__table__, TrainingEvaluation.__table__):
                await connection.run_sync(table.create)
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)
        self.app = FastAPI()
        self.app.include_router(router)
        async def session():
            async with self.sessions() as db:
                yield db
        self.app.dependency_overrides[get_db] = session
        @self.app.middleware("http")
        async def identity(request: Request, next_call):
            role = request.headers.get("x-test-role")
            request.state.user = SimpleNamespace(username="reviewer", role=role) if role else None
            return await next_call(request)
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=self.app), base_url="http://test",
                                       headers={"x-test-role": "admin"})

    async def asyncTearDown(self):
        await self.client.aclose()
        await self.engine.dispose()

    async def test_all_routes_require_admin(self):
        self.assertEqual((await self.client.get("/training", headers={"x-test-role": "viewer"})).status_code, 403)
        self.assertEqual((await self.client.post("/training/examples",
                         headers={"x-test-role": "user"}, json=self.example())).status_code, 403)

    def example(self):
        return {"instruction": "Write an editorial summary", "context": "Verified context",
                "answer": "A human authored answer", "source_ref": "asset-example",
                "group": "episode-one", "rights_approved": False, "required_terms": []}

    async def test_crud_rights_and_edit_reset(self):
        body = self.example()
        response = await self.client.post("/training/examples", json=body)
        self.assertEqual(response.status_code, 201)
        key = response.json()["id"]
        self.assertEqual((await self.client.post(f"/training/examples/{key}/review",
                                                json={"status": "approved"})).status_code, 422)
        body["rights_approved"] = True
        self.assertEqual((await self.client.put(f"/training/examples/{key}", json=body)).status_code, 200)
        await self.client.post(f"/training/examples/{key}/review", json={"status": "approved"})
        state = (await self.client.get("/training")).json()
        self.assertEqual(state["examples"][0]["status"], "approved")
        body["answer"] = "Changed human answer"
        await self.client.put(f"/training/examples/{key}", json=body)
        state = (await self.client.get("/training")).json()
        self.assertEqual(state["examples"][0]["status"], "draft")
        self.assertIsNone(state["examples"][0]["reviewer"])
        self.assertEqual((await self.client.delete(f"/training/examples/{key}")).status_code, 200)
        self.assertEqual((await self.client.get("/training")).json()["examples"], [])

    async def test_no_placeholder_dataset_and_no_blind_approval(self):
        response = await self.client.post("/training/datasets", json={"base_model": "example/base",
                         "base_revision": "a" * 40, "license_note": "Human verified rights"})
        self.assertEqual(response.status_code, 422)
        response = await self.client.post("/training/evaluations/unknown/review",
                                          json={"decision": "approved_for_manual_trial", "note": "I reviewed all evidence and answers",
                                                "checked_grounding_and_style": False})
        self.assertEqual(response.status_code, 422)