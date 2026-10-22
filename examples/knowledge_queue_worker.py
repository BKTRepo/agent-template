"""本机独立队列 Worker，生产用原 celery_worker 及正式配置。"""
from examples.knowledge_queue_environment import install_worker_database
install_worker_database()
from celery_scheduler.celery_worker import celery
from examples.knowledge_queue_probe import register
register(celery)
celery.conf.imports = ("celery_scheduler.tasks.task_knowledge",)

if __name__ == "__main__":
    import sys
    celery.start(sys.argv[1:])
