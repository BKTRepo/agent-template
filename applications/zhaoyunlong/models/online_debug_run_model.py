# -*- coding: utf-8 -*-
"""开发者中心在线调试任务的持久化模型。"""

from tortoise import fields

from applications.base.services.scaffold import ScaffoldModel


class OnlineDebugRun(ScaffoldModel):
    """记录一次在线调试从提交、执行到生成结果文档的完整状态。"""

    # 前端或上游技能服务传入的技能标识；当前项目尚未建立独立技能表。
    skill_id = fields.CharField(max_length=128, index=True, description="被调试技能的标识")
    # 对外返回的随机任务编号，用于查询状态和下载对应结果文件。
    run_id = fields.CharField(max_length=32, unique=True, index=True, description="在线调试任务编号")
    # 状态仅允许由服务端按 queued、running、completed、failed 四种值写入。
    status = fields.CharField(max_length=16, default="queued", index=True, description="任务执行状态")
    # 创建任务时记录当前登录人的姓名；历史任务和无法识别姓名的情况保留为空字符串。
    debugger = fields.CharField(max_length=64, default="", index=True, description="调试人")

    # 仅在任务成功时写入本次运行目录；目录内可包含 Skill 自主生成的一个或多个不同格式文件。
    result_file_path = fields.CharField(max_length=1024, null=True, description="结果文件所在 run_id 目录的服务端路径")

    # 失败信息限定长度，避免把容器日志或模型返回内容无限写入数据库。
    error_message = fields.TextField(null=True, description="任务失败原因")
    started_at = fields.DatetimeField(null=True, index=True, description="开始执行时间")
    finished_at = fields.DatetimeField(null=True, index=True, description="完成或失败时间")
    expires_at = fields.DatetimeField(null=True, index=True, description="结果文件过期时间")

    class Meta:
        table = "keenrobot_online_debug_runs"
        ordering = ["-id"]
