"""按版本读取唯一表单；执行入口不读取主表缓存中的正文。"""
from applications.wrq.agent.models.agent_model import SkillVersion, SkillForm

async def version_and_form(version_id, db=None):
    vq = SkillVersion.filter(id=version_id)
    fq = SkillForm.filter(skill_version_id=version_id)
    if db:
        vq, fq = vq.using_db(db), fq.using_db(db)
    return await vq.first(), await fq.first()
