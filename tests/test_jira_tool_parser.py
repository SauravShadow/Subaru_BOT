# tests/test_jira_tool_parser.py


def test_parse_jira_get():
    from app.agents.tools import parse_tool_call
    tool, args = parse_tool_call("let me check [JIRA_GET:PROJ-123]")
    assert tool == "jira_get"
    assert args["ticket_id"] == "PROJ-123"


def test_parse_jira_get_whitespace_stripped():
    from app.agents.tools import parse_tool_call
    tool, args = parse_tool_call("[JIRA_GET:  PROJ-99  ]")
    assert tool == "jira_get"
    assert args["ticket_id"] == "PROJ-99"


def test_parse_jira_search_simple_jql():
    from app.agents.tools import parse_tool_call
    tool, args = parse_tool_call('[JIRA_SEARCH:assignee = "Reinhard"]')
    assert tool == "jira_search"
    assert args["jql"] == 'assignee = "Reinhard"'


def test_parse_jira_search_complex_jql():
    from app.agents.tools import parse_tool_call
    tool, args = parse_tool_call("[JIRA_SEARCH:project = NEXUS AND status = 'In Progress']")
    assert tool == "jira_search"
    assert "NEXUS" in args["jql"]
    assert "In Progress" in args["jql"]


def test_parse_jira_status():
    from app.agents.tools import parse_tool_call
    tool, args = parse_tool_call("[JIRA_STATUS:PROJ-123:In Progress]")
    assert tool == "jira_status"
    assert args["ticket_id"]  == "PROJ-123"
    assert args["transition"] == "In Progress"


def test_parse_jira_status_done():
    from app.agents.tools import parse_tool_call
    tool, args = parse_tool_call("[JIRA_STATUS:NEXUS-7:Done]")
    assert tool == "jira_status"
    assert args["ticket_id"]  == "NEXUS-7"
    assert args["transition"] == "Done"


def test_parse_jira_comment():
    from app.agents.tools import parse_tool_call
    tool, args = parse_tool_call("[JIRA_COMMENT:PROJ-123:Looks good, merging now]")
    assert tool == "jira_comment"
    assert args["ticket_id"] == "PROJ-123"
    assert args["body"]      == "Looks good, merging now"


def test_parse_jira_comment_multiword_body():
    from app.agents.tools import parse_tool_call
    tool, args = parse_tool_call("[JIRA_COMMENT:NEXUS-5:This is a longer comment with details]")
    assert tool == "jira_comment"
    assert args["body"] == "This is a longer comment with details"


def test_unrelated_text_returns_none():
    from app.agents.tools import parse_tool_call
    tool, args = parse_tool_call("Just a normal message with no tool call")
    assert tool is None
    assert args is None
