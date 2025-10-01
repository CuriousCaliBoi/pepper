import os
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.date import DateTrigger
from apscheduler.triggers.interval import IntervalTrigger
from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel, Field

from episodic import ContextStore

REMINDER_JOBS_NAMESPACE = os.environ.get("REMINDER_JOBS_NAMESPACE", "reminder.jobs")
REMINDER_TARGET_NAMESPACE = "reminder.inbox"
CONTEXT_STORE_ENDPOINT = os.environ.get(
    "CONTEXT_STORE_ENDPOINT", "http://localhost:8000"
)
CONTEXT_STORE_API_KEY = os.environ.get("CONTEXT_STORE_API_KEY", "your-api-key-here")


app = FastAPI(title="Reminder Service")
scheduler = AsyncIOScheduler()


class ReminderCreate(BaseModel):
    namespace: Optional[str] = None
    content: str
    send_at_utc: str
    repeat_seconds: Optional[int] = Field(default=None, ge=1)


class ReminderOut(BaseModel):
    id: Optional[str]
    namespace: str
    content: str
    send_at_utc: str
    repeat_seconds: Optional[int] = None
    next_run_at: Optional[str] = None


def get_cs():
    return ContextStore(endpoint=CONTEXT_STORE_ENDPOINT, api_key=CONTEXT_STORE_API_KEY)


async def _store_job(cs, job: Dict[str, Any]):
    await cs.store(
        context_id=job["id"],
        data={
            "namespace": job["namespace"],
            "content": job["content"],
            "send_at_utc": job["send_at_utc"],
            "repeat_seconds": job.get("repeat_seconds"),
        },
        namespace=REMINDER_JOBS_NAMESPACE,
        context_type="reminder_job",
    )


async def _delete_job(cs, reminder_id: str):
    try:
        await cs.delete(reminder_id)
    except Exception:
        pass


async def deliver_reminder(reminder_id: str):
    cs = get_cs()
    try:
        job_ctx = await cs.get(reminder_id)
        job = job_ctx.data
        namespace = job["namespace"]
        content = job["content"]
        # Write delivery to target namespace
        await cs.store(
            context_id=f"delivery_{reminder_id}_{uuid.uuid4().hex}",
            data={
                "content": content,
                "reminder_id": reminder_id,
                "delivered_at": datetime.now(timezone.utc).isoformat(),
            },
            namespace=namespace,
            context_type="reminder_delivery",
        )
        # For one-time jobs, delete after first run
        if not job.get("repeat_seconds"):
            await _delete_job(cs, reminder_id)
    except Exception as e:
        # Swallow errors to avoid killing the scheduler job
        print(f"deliver_reminder error for {reminder_id}: {e}")


def _parse_iso8601(ts: str) -> datetime:
    try:
        # Ensure Z or offset is handled; default to UTC
        if ts.endswith("Z"):
            ts = ts[:-1] + "+00:00"
        return datetime.fromisoformat(ts).astimezone(timezone.utc)
    except Exception:
        raise HTTPException(
            status_code=400,
            detail="Invalid send_at_utc; must be ISO-8601 (e.g., 2025-09-26T16:00:00Z)",
        )


@app.on_event("startup")
async def startup_event():
    # Start scheduler
    if not scheduler.running:
        scheduler.start()
    # Hydrate reminders from context store
    cs = get_cs()
    try:
        # Query all reminders in reminder namespace
        from episodic import ContextFilter

        jobs = await cs.query(
            ContextFilter(namespaces=[REMINDER_JOBS_NAMESPACE], limit=1000)
        )
        now = datetime.now(timezone.utc)
        for ctx in jobs:
            data = ctx.data
            sid = ctx.id
            send_at = _parse_iso8601(data.get("send_at_utc"))
            repeat_seconds = data.get("repeat_seconds")
            if repeat_seconds:
                trigger = IntervalTrigger(
                    seconds=int(repeat_seconds), start_date=max(now, send_at)
                )
            else:
                trigger = DateTrigger(run_date=send_at if send_at > now else now)
            try:
                scheduler.add_job(
                    deliver_reminder,
                    trigger=trigger,
                    id=sid,
                    replace_existing=True,
                    args=[sid],
                )
            except Exception as e:
                print(f"Failed to add reminder {sid} on startup: {e}")
    except Exception as e:
        print(f"Startup hydration error: {e}")
    finally:
        await cs.close()


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/reminders", response_model=Dict[str, str])
async def create_reminder(body: ReminderCreate, cs=Depends(get_cs)):
    send_at = _parse_iso8601(body.send_at_utc)
    now = datetime.now(timezone.utc)

    # Determine target namespace (fallback to default)
    target_namespace = body.namespace or REMINDER_TARGET_NAMESPACE

    # Immediate one-shot
    if not body.repeat_seconds and send_at <= now:
        # Deliver immediately without creating a job
        tmp_id = uuid.uuid4().hex
        await cs.store(
            context_id=f"delivery_{tmp_id}",
            data={
                "content": body.content,
                "reminder_id": None,
                "delivered_at": now.isoformat(),
            },
            namespace=target_namespace,
            context_type="reminder_delivery",
        )
        return {"id": ""}

    reminder_id = uuid.uuid4().hex
    job = {
        "id": reminder_id,
        "namespace": target_namespace,
        "content": body.content,
        "send_at_utc": body.send_at_utc,
        "repeat_seconds": body.repeat_seconds,
    }
    await _store_job(cs, job)

    # Add APS job
    if body.repeat_seconds:
        trigger = IntervalTrigger(
            seconds=int(body.repeat_seconds), start_date=max(now, send_at)
        )
    else:
        trigger = DateTrigger(run_date=send_at)
    scheduler.add_job(
        deliver_reminder,
        trigger=trigger,
        id=reminder_id,
        replace_existing=True,
        args=[reminder_id],
    )

    return {"id": reminder_id}


@app.get("/reminders", response_model=List[ReminderOut])
async def list_reminders(namespace: Optional[str] = None, cs=Depends(get_cs)):
    from episodic import ContextFilter

    contexts = await cs.query(
        ContextFilter(namespaces=[REMINDER_JOBS_NAMESPACE], limit=1000)
    )
    items: List[ReminderOut] = []
    for ctx in contexts:
        data = ctx.data
        if namespace and data.get("namespace") != namespace:
            continue
        job = scheduler.get_job(ctx.id)
        next_run = None
        if job and job.next_run_time:
            next_run = job.next_run_time.astimezone(timezone.utc).isoformat()
        items.append(
            ReminderOut(
                id=ctx.id,
                namespace=data.get("namespace"),
                content=data.get("content"),
                send_at_utc=data.get("send_at_utc"),
                repeat_seconds=data.get("repeat_seconds"),
                next_run_at=next_run,
            )
        )
    return items


@app.delete("/reminders/{reminder_id}", response_model=Dict[str, Any])
async def cancel_reminder(reminder_id: str, cs=Depends(get_cs)):
    # Remove APS job
    try:
        scheduler.remove_job(reminder_id)
    except Exception:
        pass
    # Delete record
    await _delete_job(cs, reminder_id)
    return {"id": reminder_id, "cancelled": True}


# if __name__ == "__main__":
#     import uvicorn
#     uvicorn.run(app, host="0.0.0.0", port=8060)
