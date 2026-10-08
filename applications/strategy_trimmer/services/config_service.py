import copy
import json
from pathlib import Path

from tortoise.transactions import in_transaction
from ..models import TrimmerConfig, SystemAutomationAsset

CONFIG_KEY = 'strategy_catalog'
ASSET_LABELS = {True: '有自动化资产', False: '无自动化资产'}


async def init_trimmer_data():
    """JSON 仅在首次初始化时写入配置表；重启不覆盖配置或已导入关系。"""
    async with in_transaction() as connection:
        config = await TrimmerConfig.filter(key=CONFIG_KEY).using_db(connection).first()
        if config is not None:
            return
        seed = json.loads((Path(__file__).parent.parent / 'catalog.json').read_text(encoding='utf-8'))
        await TrimmerConfig.create(key=CONFIG_KEY, version=seed['version'], value=seed, using_db=connection)
        for name in seed['systems']:
            await SystemAutomationAsset.get_or_create(system_name=name, defaults={
                'has_automation': name in ('核心交易系统', '渠道门户')}, using_db=connection)


async def get_catalog():
    async with in_transaction() as connection:
        config = await TrimmerConfig.filter(key=CONFIG_KEY).using_db(connection).first()
        if config is None:
            raise ValueError('裁剪规则未初始化，请先执行数据库初始化')
        catalog = copy.deepcopy(config.value)
        catalog['version'] = config.version
        assets = await SystemAutomationAsset.all().using_db(connection).order_by('id')
        catalog['systems'] = [row.system_name for row in assets]
        catalog['systemAssets'] = {row.system_name: ASSET_LABELS[row.has_automation] for row in assets}
        return catalog
