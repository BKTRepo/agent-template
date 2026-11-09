"""Match the maintainer shown by KnowledgeService.detail, plus their account."""
from tortoise import connections


async def matching_maintainer_ids(value):
    db = connections.get('default')
    sqlite = db.capabilities.dialect == 'sqlite'
    path = '$[#-1]' if sqlite else '$[last]'
    def extract(field):
        expression = f"JSON_EXTRACT(k.history, '{path}.{field}')"
        return expression if sqlite else f'JSON_UNQUOTE({expression})'
    display = f"COALESCE(NULLIF({extract('maintainer')}, ''), NULLIF(creator.alias, ''), creator.username, '')"
    account = f"CASE WHEN NULLIF({extract('maintainer')}, '') IS NULL THEN creator.username ELSE editor.username END"
    placeholder = '?' if sqlite else '%s'
    pattern = '%' + value.strip().lower().replace('^', '^^').replace('%', '^%').replace('_', '^_') + '%'
    _, rows = await db.execute_query(f'''
        SELECT k.id FROM keenrobot_knowledge_bases k
        LEFT JOIN keenrobot_user creator ON creator.id=k.user_id
        LEFT JOIN keenrobot_user editor ON editor.id={extract('maintainer_id')}
        WHERE LOWER({display}) LIKE {placeholder} ESCAPE '^'
           OR LOWER(COALESCE({account}, '')) LIKE {placeholder} ESCAPE '^'
    ''', [pattern, pattern])
    return [row['id'] for row in rows]
