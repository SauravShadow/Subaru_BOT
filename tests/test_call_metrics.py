from app.services.call_metrics import TurnTimer

def test_marks_and_gap():
    t = TurnTimer()
    t.mark("final", at=100.0)
    t.mark("llm_done", at=100.5)
    t.mark("speak", at=100.8)
    assert t.gap_ms("final", "llm_done") == 500
    assert t.gap_ms("final", "speak") == 800
    assert t.gap_ms("final", "missing") == -1

def test_summary_line_contains_stages():
    t = TurnTimer()
    for n, a in [("last_interim", 0.0), ("final", 1.0), ("llm_done", 1.4), ("speak", 1.6)]:
        t.mark(n, at=a)
    line = t.summary_line()
    assert "stt_gap=1000ms" in line
    assert "llm=400ms" in line
    assert "total=600ms" in line
