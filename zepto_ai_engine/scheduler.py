"""
Daily scheduler for the Zepto AI Discovery Engine pipeline.

Runs collection → analysis every day (default 06:00 local time).
Chatbot reads the latest rows from feedback.db automatically.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

# Ensure project root is on path when run as a script
ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

from src.config import DAILY_SCHEDULE_HOUR
from src.data_pipeline import run_full_pipeline
from src.database import init_db

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("scheduler")


def daily_job() -> None:
    logger.info("Scheduled daily pipeline triggered")
    result = run_full_pipeline()
    logger.info("Daily pipeline result: %s", result)


def main(run_once: bool = False) -> None:
    init_db()
    if run_once:
        daily_job()
        return

    scheduler = BlockingScheduler()
    scheduler.add_job(
        daily_job,
        CronTrigger(hour=DAILY_SCHEDULE_HOUR, minute=0),
        id="zepto_daily_pipeline",
        replace_existing=True,
        max_instances=1,
    )
    logger.info(
        "Scheduler started — daily pipeline at %02d:00 (Ctrl+C to stop)",
        DAILY_SCHEDULE_HOUR,
    )
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info("Scheduler stopped")


if __name__ == "__main__":
    run_once = "--once" in sys.argv
    main(run_once=run_once)
