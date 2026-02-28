"""
APScheduler wrapper for background Exchange sync.
"""
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from zoneinfo import ZoneInfo

_scheduler = None
_app = None

JOB_ID = "exchange_sync"


def init_scheduler(app):
    global _scheduler, _app
    _app = app

    config = app.config.get("APP_CONFIG", {})
    if not config.get("sync_enabled"):
        return

    _scheduler = BackgroundScheduler(daemon=True)
    cron_expr = config.get("sync_schedule_cron", "*/15 * * * *")
    tz_name = config.get("display_timezone", "UTC")
    _add_job(cron_expr, tz_name)
    _scheduler.start()
    app.logger.info(f"Scheduler started with cron: {cron_expr} ({tz_name})")


def _add_job(cron_expr, tz_name="UTC"):
    if not _scheduler:
        return
    parts = cron_expr.strip().split()
    if len(parts) == 5:
        minute, hour, day, month, dow = parts
    else:
        minute, hour, day, month, dow = "*/15", "*", "*", "*", "*"

    try:
        tz = ZoneInfo(tz_name)
    except Exception:
        tz = ZoneInfo("UTC")

    trigger = CronTrigger(minute=minute, hour=hour, day=day, month=month, day_of_week=dow, timezone=tz)

    if _scheduler.get_job(JOB_ID):
        _scheduler.reschedule_job(JOB_ID, trigger=trigger)
    else:
        _scheduler.add_job(_run_sync_job, trigger, id=JOB_ID, replace_existing=True)


def _run_sync_job():
    if not _app:
        return
    with _app.app_context():
        from services.sync_service import run_sync
        config = _app.config.get("APP_CONFIG", {})
        run_sync(config)


def update_schedule(cron_expr, tz_name="UTC"):
    if not _scheduler:
        return
    _add_job(cron_expr, tz_name)


def get_scheduler_status():
    if not _scheduler or not _scheduler.running:
        return {"running": False, "next_run": None}

    job = _scheduler.get_job(JOB_ID)
    if job:
        return {
            "running": True,
            "next_run": str(job.next_run_time) if job.next_run_time else None,
        }
    return {"running": True, "next_run": None}


def stop_scheduler():
    global _scheduler
    if _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=False)
        _scheduler = None
