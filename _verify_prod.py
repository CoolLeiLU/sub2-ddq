import asyncio
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
    )
    print("=== groups ===")
    for g in groups.get("data") or []:
        print(g.get("id"), g.get("name"), g.get("platform"), g.get("status"))

    channels = port._request_json(
        "https://zhisuanapi.cn/api/v1/admin/channels?page=1&page_size=50"
    )
    print("=== channels ===")
    data = channels.get("data") or {}
    items = data.get("items") if isinstance(data, dict) else data
    for ch in items or []:
        print(
            ch.get("id"), ch.get("name"), ch.get("status"),
            "groups:", ch.get("group_ids"),
        )

asyncio.run(main())
