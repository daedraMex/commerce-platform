from celery import shared_task


@shared_task(name="apps.health.tasks.smoke")
def smoke() -> str:
    return "ok"
