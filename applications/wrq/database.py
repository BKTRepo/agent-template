"""WRQ云库连接配置；不修改服务器全局参数或其它模块配置。"""
from copy import deepcopy

def mysql_connection_options():
    return {'pool_recycle':120,'connect_timeout':10,'read_timeout':15}


def wrq_connections(configured):
    connections = deepcopy(configured)
    for connection in connections.values():
        if isinstance(connection, dict) and connection.get('engine', '').endswith('mysql'):
            # 共享账号最多20连接，不能每个本地服务预占10连接。
            connection['credentials'].update(minsize=1, maxsize=4)
    return connections
