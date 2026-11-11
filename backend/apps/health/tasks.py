from celery import shared_task


@shared_task
def smoke() -> str:
    return "ok"
