import unittest

from tortoise import Tortoise

from applications.agent.models.agent_model import DeveloperApplication, DeveloperSkillClass, Skill
from applications.agent.schemas.agent_schema import DeveloperDebugResult, DeveloperSkillForm
from applications.agent.services.developer_skill_crud import DeveloperSkillCrud
from applications.user.models.user_model import User


class DeveloperCenterCrudTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await Tortoise.init(
            db_url="sqlite://:memory:",
            modules={"models": [
                "applications.user.models.user_model",
                "applications.agent.models.agent_model",
            ]},
        )
        await Tortoise.generate_schemas()
        self.user = await User.create(
            username="developer", password="hashed", alias="开发者", email="developer@example.com"
        )
        await DeveloperSkillClass.create(id="case-generation", name="智能用例生成")
        await DeveloperApplication.create(id="*", name="全应用适用")
        self.crud = DeveloperSkillCrud()

    async def asyncTearDown(self):
        await Tortoise.close_connections()

    @staticmethod
    def form(name="登录功能测试用例生成", description="生成登录场景测试用例"):
        return DeveloperSkillForm(
            name=name, class_id="case-generation", application_ids=["*"],
            description=description, instructions="覆盖正常、异常和边界场景。",
            resource_ids=[], resource_usage="", compatibility="Python 3.12",
            technical_name="login-case-generator", uploaded_resources=[], knowledge_bases=[],
        )

    async def test_complete_developer_center_lifecycle(self):
        metadata = await self.crud.metadata()
        self.assertEqual(metadata["skill_classes"][0]["id"], "case-generation")

        skill = await self.crud.create(self.user, self.form())
        self.assertEqual(skill.display_status, "DRAFT")
        self.assertEqual(len(await self.crud.list(self.user)), 1)

        skill = await self.crud.save(skill.id, self.user, self.form(description="修改后的描述"))
        self.assertEqual(skill.current_revision, 2)
        self.assertEqual(skill.display_status, "DRAFT")

        skill = await self.crud.record_debug_result(skill.id, self.user, DeveloperDebugResult(
            run_id="run-001", status="passed", conversation_input="生成登录测试用例",
        ))
        self.assertIsNotNone(skill.last_debug_passed_at)
        skill = await self.crud.publish(skill.id, self.user)
        self.assertEqual(skill.display_status, "ONLINE")

        skill = await self.crud.save(skill.id, self.user, self.form(description="上线后修改"))
        self.assertEqual(skill.display_status, "DRAFT")
        self.assertIsNone(skill.last_debug_passed_at)
        with self.assertRaises(ValueError):
            await self.crud.publish(skill.id, self.user)

        await self.crud.record_debug_result(skill.id, self.user, DeveloperDebugResult(
            run_id="run-002", status="passed",
        ))
        skill = await self.crud.publish(skill.id, self.user)
        skill = await self.crud.offline(skill.id, self.user)
        self.assertEqual(skill.display_status, "OFFLINE")

        draft = await self.crud.create(self.user, self.form(name="可删除草稿"))
        await self.crud.delete_draft(draft.id, self.user)
        self.assertIsNone(await Skill.get_or_none(id=draft.id, state__not=1))


if __name__ == "__main__":
    unittest.main()
