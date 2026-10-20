import logging

from apscheduler.schedulers.background import BackgroundScheduler

from app.config import SCHEDULER_INTERVAL_SECONDS
from app.database import SessionLocal
from app.services.reminder_service import run_scheduler_cycle

logger = logging.getLogger(__name__)
scheduler = BackgroundScheduler(timezone="UTC")


def scheduler_cycle(recover: bool = False) -> None:
    database = SessionLocal()
    try:
        run_scheduler_cycle(database, recover=recover)
    except Exception:
        logger.exception("Medication reminder scheduler cycle failed.")
        raise
    finally:
        database.close()


def start_scheduler() -> None:
    if scheduler.running:
        return
    scheduler_cycle(recover=True)
    scheduler.add_job(
        scheduler_cycle,
        trigger="interval",
        seconds=SCHEDULER_INTERVAL_SECONDS,
        id="medication-reminder-cycle",
        replace_existing=True,
        coalesce=True,
        max_instances=1,
    )
    scheduler.start()


def stop_scheduler() -> None:
    if scheduler.running:
        scheduler.shutdown(wait=False)
