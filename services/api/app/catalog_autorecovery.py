"""Fail-closed, durable recovery for explicitly identified remote LLM outages."""
import asyncio
import json
import os
import re
import time
from datetime import datetime

from sqlalchemy import func, select, text

from .catalog_models import CatalogAsset, CatalogCheckpoint
from .database import AsyncSessionLocal, engine

DELAYS = (60, 120, 300, 600)
PREFIX = "Remote LLM at LLM_BASE_URL unreachable or failed: "


def recoverable(reason):
    # Every semicolon-separated failure must be the same safe class. Never
    # infer safety from a single timeout substring in a mixed storage/GPU error.
    parts = str(reason or "").removeprefix("Shared infrastructure failure: ").split("; ")
    return bool(parts) and all(
        part.startswith(PREFIX) and bool(re.match(
            r"(?:ConnectTimeout|ReadTimeout|ConnectError|ReadError|RemoteProtocolError):",
            part[len(PREFIX):],
        )) for part in parts
    )


def begin_pause(state, reason, now):
    state = dict(state)
    # Once paused, a new unsafe cause must revoke automatic recovery. A later
    # transient failure cannot turn a manual/hardware pause into a safe one.
    if state.get("paused"):
        if not recoverable(reason):
            state.pop("llm_recovery", None)
        return state
    state.pop("llm_recovery", None)
    state.pop("recovery_canary", None)
    state.pop("recovery_alert", None)
    if recoverable(reason):
        times = [t for t in state.get("llm_pause_times", []) if t > now - 3600]
        times.append(now)
        state["llm_pause_times"] = times[-3:]
        state["llm_recovery"] = {
            "started": now, "next_probe": now + 60, "attempt": 0,
            "successes": 0, "locked": len(times) >= 3,
        }
    return state


def alert(row, message):
    row.cursor = {**row.cursor, "recovery_alert": message}
    # Existing admin status UI displays last_error. Do not include endpoint
    # URLs, exception text, authorization headers, or model output.
    row.last_error = message
    print(json.dumps({"event": "catalog_recovery_alert", "message": message}), flush=True)


async def probe_model():
    """Bounded real generation; fresh connection and no local-model fallback."""
    import httpx
    base = os.getenv("LLM_BASE_URL", "").strip().rstrip("/")
    if not base:
        return False, True, "Remote model endpoint is not configured"
    key = os.getenv("LLM_API_KEY", "")
    headers = {"Authorization": f"Bearer {key}"} if key else {}
    try:
        async with asyncio.timeout(45):
            async with httpx.AsyncClient(timeout=httpx.Timeout(40, connect=10), headers=headers) as client:
                model = os.getenv("LLM_REMOTE_MODEL", "").strip()
                if not model:
                    response = await client.get(base + "/models")
                    response.raise_for_status()
                    model = response.json()["data"][0]["id"]
                body = {"model": model, "messages": [{"role": "user", "content": "Reply READY only."}],
                        "max_tokens": 64, "temperature": 0}
                if "gpt-oss" in model.lower():
                    body["reasoning_effort"] = "low"
                elif "qwen" in model.lower():
                    body["chat_template_kwargs"] = {"enable_thinking": False}
                response = await client.post(base + "/chat/completions", json=body)
                response.raise_for_status()
                content = response.json()["choices"][0]["message"]["content"]
                if not isinstance(content, str):
                    return False, True, "Invalid generation content"
                return bool(content and content.strip()), False, "Empty generation response"
    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code
        return False, status not in (408, 429, 500, 502, 503, 504), f"Model probe HTTP {status}"
    except (httpx.TransportError, TimeoutError):
        return False, False, "Model probe connection or generation timeout"
    except (KeyError, IndexError, TypeError, ValueError):
        return False, True, "Invalid model response"


def record_probe(recovery, ok, now):
    recovery = dict(recovery)
    recovery["attempt"] += 1
    recovery["successes"] = recovery["successes"] + 1 if ok else 0
    recovery["next_probe"] = now + (60 if ok else DELAYS[min(recovery["attempt"], 3)])
    return recovery


async def recovery_tick(options):
    """Only recurring apply invokes this. Same lock as admission/reconciliation."""
    from .catalog_service import reconcile
    async with engine.connect() as lock:
        held = (await lock.execute(text(
            "SELECT pg_try_advisory_lock(hashtext('obtv_catalog_run'))"
        ))).scalar()
        await lock.commit()
        if not held:
            return
        try:
            async with AsyncSessionLocal() as db:
                row = await db.get(CatalogCheckpoint, "runner")
                if not row or not row.cursor.get("paused"):
                    return
                recovery = dict(row.cursor.get("llm_recovery") or {})
                if not recovery:
                    return  # Legacy and operator pauses require acknowledgment.
                now = time.time()
                if recovery["locked"]:
                    if not row.cursor.get("recovery_alert"):
                        alert(row, "Automatic recovery locked: three model outages within one hour. Operator review required.")
                        await db.commit()
                    return
                if now - recovery["started"] >= 1800 and not row.cursor.get("recovery_alert"):
                    alert(row, "Remote model unavailable for 30 minutes; automatic probes continue.")
                    await db.commit()
                if now < recovery["next_probe"]:
                    return
                ok, permanent, detail = await probe_model()
                recovery = record_probe(recovery, ok, time.time())
                row.cursor = {**row.cursor, "llm_recovery": recovery}
                if permanent:
                    recovery["locked"] = True
                    row.cursor = {**row.cursor, "llm_recovery": recovery}
                    alert(row, detail + "; automatic recovery disabled. Operator review required.")
                await db.commit()
                print(json.dumps({"event": "catalog_model_probe", "success": ok,
                                  "consecutive_successes": recovery["successes"],
                                  "locked": recovery["locked"]}), flush=True)
                if not ok or recovery["successes"] < 2 or permanent:
                    return
                # Reconcile all rotating eligible states before retry admission.
                count = (await db.execute(select(func.count()).select_from(CatalogAsset).where(
                    CatalogAsset.status.in_(("queued", "existing", "retry", "failed"))
                ))).scalar()
                for _ in range((count + 99) // 100):
                    await reconcile(db, options)
                await db.refresh(row)
                if row.cursor.get("llm_recovery") != recovery:
                    return  # A newly discovered unsafe failure revoked recovery.
                row.cursor = {**row.cursor, "paused": False, "state": "resumed",
                              "consecutive_errors": 0, "llm_recovery": None,
                              "recovery_alert": None,
                              "recovery_canary": {"started": time.time(), "asset_id": None}}
                row.last_error = None
                row.updated_at = datetime.utcnow()
                await db.commit()
                print(json.dumps({"event": "catalog_auto_resumed", "mode": "single_video_canary"}), flush=True)
        finally:
            await lock.execute(text("SELECT pg_advisory_unlock(hashtext('obtv_catalog_run'))"))
            await lock.commit()


async def canary_waiting(db, row):
    """Run inside admission's lock. Existing work is never interrupted."""
    from .models import ProcessingJob
    canary = row.cursor.get("recovery_canary") if row else None
    if not canary:
        return False
    if not canary.get("asset_id"):
        if time.time() - canary["started"] >= 1800:
            from .catalog_recovery import pause
            await pause(db, "Recovery validation could not admit an asset within 30 minutes; operator review required.")
            alert(row, "Recovery validation could not admit an asset; operator review required.")
            await db.commit()
            return True
        return False
    candidate = await db.get(CatalogAsset, canary["asset_id"])
    analysis = (await db.execute(select(ProcessingJob).where(
        ProcessingJob.media_id == candidate.media_id,
        ProcessingJob.job_type == "analyze", ProcessingJob.status == "success",
        ProcessingJob.created_at >= datetime.utcfromtimestamp(canary["started"]),
    ).limit(1))).scalar() if candidate else None
    if analysis and any(str(line).startswith("Analysis complete:") for line in (analysis.logs or [])):
        row.cursor = {**row.cursor, "recovery_canary": None, "recovery_alert": None}
        await db.commit()
        print(json.dumps({"event": "catalog_canary_passed"}), flush=True)
        return False
    if not candidate or candidate.status in ("retry", "failed") or time.time() - canary["started"] >= 1800:
        from .catalog_recovery import pause
        await pause(db, "Recovery validation asset failed or exceeded 30 minutes; operator review required.")
        alert(row, "Recovery validation asset did not finish model analysis; operator review required.")
        await db.commit()
    return True
