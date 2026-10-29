"""兼容启动入口；业务和生命周期在 applications/wrq/main.py。"""
from applications.wrq.main import app
if __name__ == "__main__":
    import uvicorn
    from configure import PROJECT_CONFIG
    uvicorn.run(app, host=PROJECT_CONFIG.SERVER_HOST, port=PROJECT_CONFIG.SERVER_PORT)
