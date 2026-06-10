"""Singleton AsyncSqliteSaver shared by nexus_graph and email_graph."""
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from app import config

_checkpointer: AsyncSqliteSaver | None = None
_cm = None


async def get_checkpointer() -> AsyncSqliteSaver:
    global _checkpointer, _cm
    if _checkpointer is None:
        _cm = AsyncSqliteSaver.from_conn_string(str(config.MEMORY_DB))
        _checkpointer = await _cm.__aenter__()
        await _checkpointer.setup()
    return _checkpointer


async def close_checkpointer() -> None:
    global _checkpointer, _cm
    if _cm is not None:
        await _cm.__aexit__(None, None, None)
        _cm = None
        _checkpointer = None
