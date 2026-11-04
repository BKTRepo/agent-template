"""容器中的受控 stdio MCP 桥接器；只转发到部署配置指定的知识库后端。"""
import json
import os
import sys
if __name__ == '__main__' and not __package__:
    # 直接运行本文件时，避免同目录 wrq/http.py 遮蔽标准库 http 包。
    sys.path.pop(0)
from urllib.request import Request, urlopen
from mcp.server.fastmcp import FastMCP

mcp = FastMCP('knowledge')

@mcp.tool()
def knowledge_search(query: str, top_k: int = 5) -> dict:
    """检索本次技能已挂载的知识库，返回原文及来源；无命中时调整关键词。"""
    request = Request(os.environ['KNOWLEDGE_SEARCH_URL'],
        data=json.dumps(dict(query=query, top_k=top_k)).encode(),
        headers={'Content-Type':'application/json', 'Authorization':'Bearer '+os.environ['KNOWLEDGE_RUN_TOKEN']}, method='POST')
    with urlopen(request, timeout=60) as response:
        return json.load(response)

if __name__ == '__main__':
    mcp.run(transport='stdio')
