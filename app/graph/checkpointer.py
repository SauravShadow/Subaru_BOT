"""Singleton AsyncSqliteSaver shared by nexus_graph and email_graph."""
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from app import config

_checkpointer: AsyncSqliteSaver | None = None


async def get_checkpointer() -> AsyncSqliteSaver:
    global _checkpointer
    if _checkpointer is None:
        _checkpointer = AsyncSqliteSaver.from_conn_string(str(config.MEMORY_DB))
        await _checkpointer.setup()
    return _checkpointer
