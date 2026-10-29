"""门户应用目录适配；不读写本地应用表。"""
import os
import httpx

async def application_options():
    url = os.getenv('WRQ_PORTAL_APPLICATIONS_URL', '')
    if url:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(url)
            response.raise_for_status()
            payload = response.json()
        rows = payload.get('data', payload) if isinstance(payload, dict) else payload
        options = [{'id': str(r['paso']), 'paso': str(r['paso']), 'name': str(r['name'])} for r in rows]
    else:
        # 当前不接外部目录，只提供系统定义的“全应用适用”，不造应用清单。
        options = []
    return [{'id': '*', 'paso': '*', 'name': '全应用适用'}] + [r for r in options if r['id'] != '*']
