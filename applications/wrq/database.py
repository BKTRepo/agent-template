"""WRQ云库连接配置；不修改服务器全局参数或其它模块配置。"""
from copy import deepcopy

def mysql_connection_options():
    return {'pool_recycle':120,'connect_timeout':10,'read_timeout':15}


def wrq_connections(configured):
    # 接口与 Worker 使用 ProjectConfig 中相同的连接池参数；仅隔离配置对象。
    return deepcopy(configured)
