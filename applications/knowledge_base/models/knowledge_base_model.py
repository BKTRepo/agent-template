"""兼容导入；业务实现已迁至 applications.wrq.knowledge_base.models.knowledge_base_model。"""
from applications.wrq.knowledge_base.models.knowledge_base_model import *  # noqa: F401,F403
__models__ = []  # 由 applications.wrq.models 统一注册，避免重复模型
