"""应用目录适配点；生产部署用 PLATFORM_APPLICATIONS 替换本地联调初始项。"""


def applications():
    from configure import PROJECT_CONFIG
    return list(PROJECT_CONFIG.PLATFORM_APPLICATIONS)


def validate_application(value, *, allow_all=False):
    if value is None or (allow_all and value == "*"):
        return
    if value not in applications():
        raise ValueError("请选择应用目录中存在的应用")
