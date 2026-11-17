"""Write pipeline log events for a job (shown on the job page under Logs).

Each call uses its own short DB session, so logging never interferes with the job's
own transaction and still works while a job is failing or being cancelled.
"""
import json
import logging
from app.db import SessionLocal
from app.models import JobEvent

logger=logging.getLogger("app.joblog")
MAX_TEXT=2000


def _clip(v):
    if isinstance(v,str) and len(v)>MAX_TEXT:return v[:MAX_TEXT]+"…"
    if isinstance(v,dict):return {k:_clip(x) for k,x in v.items()}
    if isinstance(v,list):return [_clip(x) for x in v]
    return v


def log_event(job_id:str,stage:str,message:str,level:str="info",seconds:float|None=None,**data):
    getattr(logger,"warning" if level=="warning" else "error" if level=="error" else "info")(
        "job %s [%s] %s%s",job_id[:8],stage,message,f" ({seconds:.1f}s)" if seconds is not None else "")
    try:
        with SessionLocal() as db:
            db.add(JobEvent(job_id=job_id,stage=stage,level=level,message=message[:MAX_TEXT],
                            seconds=round(seconds,3) if seconds is not None else None,
                            data=json.dumps(_clip(data),ensure_ascii=False,default=str) if data else None))
            db.commit()
    except Exception as exc:   # logging must never break the pipeline
        logger.warning("Could not store job event: %s",exc)


def log_llm_tasks(job_id:str,tasks:list[dict]):
    """One event per LLM post-edit line, written in a single transaction."""
    if not tasks:return
    try:
        with SessionLocal() as db:
            for t in tasks:
                level="info" if t.get("status") in ("edited","unchanged") else "warning"
                db.add(JobEvent(job_id=job_id,stage="llm",level=level,
                                message=f"Line {t.get('index',0)+1}: {t.get('status')}",
                                seconds=t.get("seconds"),data=json.dumps(_clip(t),ensure_ascii=False,default=str)))
            db.commit()
    except Exception as exc:
        logger.warning("Could not store LLM task events: %s",exc)
