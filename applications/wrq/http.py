"""仅作用于WRQ接口，保持平台统一响应字段，并返回实际HTTP错误码。"""
from fastapi.routing import APIRoute
from fastapi import HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.encoders import jsonable_encoder
from starlette.responses import JSONResponse
from applications.wrq.agent.services.developer_skill_crud import DeveloperError
from configure import LOGGER

class WrqRoute(APIRoute):
    def get_route_handler(self):
        handler=super().get_route_handler()
        async def wrapped(request):
            try:
                return await handler(request)
            except DeveloperError as exc:
                data={'errors':[{'field':exc.field,'reason':str(exc)}]} if exc.field else None
                return JSONResponse(status_code=exc.status_code,content={'code':exc.status_code,'status':'failure','message':str(exc),'data':data})
            except RequestValidationError as exc:
                return JSONResponse(status_code=422,content=jsonable_encoder({'code':422,'status':'failure',
                    'message':'请检查必填项和字段格式','data':{'errors':[{'field':'.'.join(map(str,e['loc'][1:])), 'reason':e['msg']} for e in exc.errors()]}}))
            except HTTPException:
                raise
            except Exception:
                # 交给整个项目注册的全局异常处理器，避免局部路由吞掉统一 trace_id 和错误格式。
                LOGGER.exception('WRQ接口处理失败')
                raise
        return wrapped
