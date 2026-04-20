import asyncio
from contextlib import asynccontextmanager

from session_service.browser_manager import BrowserSessionManager
from session_service.store import SessionStore
from session_service.settings import settings


@asynccontextmanager
async def build_service():
    store = SessionStore(settings.sqlite_path)
    manager = BrowserSessionManager(store)
    await manager.start()
    try:
        yield manager
    finally:
        await manager.stop()
