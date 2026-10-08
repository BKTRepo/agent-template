"""裁剪器联调入口：持久化 SQLite；原 backend_main 使用既有 MySQL 配置。"""
import os
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from core.responses import ParameterResponse
from tortoise import Tortoise

from applications.strategy_trimmer.views import strategy_trimmer_router
from applications.strategy_trimmer.services import init_trimmer_data

def create_app(database_url=None):
    @asynccontextmanager
    async def lifespan(application):
        database = Path(__file__).resolve().parent / 'output' / 'trimmer.sqlite3'
        database.parent.mkdir(parents=True, exist_ok=True)
        await Tortoise.init(db_url=database_url or os.environ.get('TRIMMER_DB_URL', 'sqlite://' + database.as_posix()),
            modules={'models': ['applications.strategy_trimmer.models.strategy_trimmer_model']},
            use_tz=True, timezone='Asia/Shanghai')
        try:
            # 仅联调入口创建本模块的三张表，不涉及原项目其他表。
            await Tortoise.generate_schemas(safe=True)
            await init_trimmer_data()
            yield
        finally:
            await Tortoise.close_connections()

    application = FastAPI(title='裁剪器数据库联调服务', lifespan=lifespan)
    application.include_router(strategy_trimmer_router, prefix='/strategy-trimmer', tags=['信创测试策略裁剪器'])
    application.add_exception_handler(RequestValidationError, validation_error)
    return application


async def validation_error(request, exc):
    message = '; '.join('.'.join(map(str, e['loc'])) + ':' + e['msg'] for e in exc.errors())
    return ParameterResponse(message=message)


app = create_app()
