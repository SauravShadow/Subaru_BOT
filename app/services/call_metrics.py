"""Per-turn latency timing for live calls."""
import time


class TurnTimer:
    """Records monotonic marks for one conversational turn and formats a log line."""

    def __init__(self) -> None:
        self._marks: dict[str, float] = {}

    def mark(self, name: str, at: float | None = None) -> None:
        self._marks[name] = time.monotonic() if at is None else at

    def gap_ms(self, a: str, b: str) -> int:
        if a in self._marks and b in self._marks:
            return int(round((self._marks[b] - self._marks[a]) * 1000))
        return -1

    def summary_line(self) -> str:
        return (
            f"turn latency: stt_gap={self.gap_ms('last_interim', 'final')}ms "
            f"llm={self.gap_ms('final', 'llm_done')}ms "
            f"tts_issue={self.gap_ms('llm_done', 'speak')}ms "
            f"total={self.gap_ms('final', 'speak')}ms"
        )
