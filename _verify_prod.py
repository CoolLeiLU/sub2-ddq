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
    for gid in ("56", "36", "57"):
        try:
            payload = port._request_json(
                f"https://zhisuanapi.cn/api/v1/admin/groups/{gid}/api-keys?page=1&page_size=10"
            )
            print(f"=== group {gid} keys ===")
            print(json.dumps(payload.get("data"), ensure_ascii=False)[:1500])
        except Exception as exc:
            print(gid, "ERR", str(exc)[:150])

asyncio.run(main())
