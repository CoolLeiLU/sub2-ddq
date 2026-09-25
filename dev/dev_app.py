"""Import target for the ``uvicorn --reload`` development server.

``sub2api_mcp.__main__`` builds the runtime inside ``main()`` and then calls
``uvicorn.run``, which cannot be imported as a reload target.  This module
performs the same two steps at import time so ``uvicorn`` can watch the source
tree and rebuild the application on every save.

It lives outside ``src/`` on purpose: ``pyproject.toml`` points pyright at
``src`` and the release image copies only that tree, so development scaffolding
kept here stays out of both the production image and the CI type check.
"""

from __future__ import annotations

from sub2api_mcp.app import build_runtime, create_app
from sub2api_mcp.bootstrap import bootstrap_legacy_core
from sub2api_mcp.config import load_settings

_settings = load_settings()
bootstrap_legacy_core(_settings.legacy_core_root)

app = create_app(build_runtime(_settings))
