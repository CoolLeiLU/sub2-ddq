import asyncio
import json
import sys

sys.path.insert(0, "/opt/sub2api-core")
sys.path.insert(0, "/opt/sub2api-mcp")

from sub2api_mcp.adapters.sub2api import build_sub2api_adapter
from sub2api_mcp.config import Settings


async def main() -> None:
    settings = Settings()
    adapter = build_sub2api_adapter(settings)
    port = adapter._client._maintenance_adapter._request_port
    groups = port._request_json(
        "https://zhisuanapi.cn/api/v1/admin/groups/all?include_inactive=true"
    ).get("data") or []
    g36 = next(g for g in groups if str(g.get("id")) == "36")
    print("item keys:", sorted(g36.keys()))
    print(json.dumps(g36, ensure_ascii=False)[:1500])

asyncio.run(main())
