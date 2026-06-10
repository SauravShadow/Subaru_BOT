# app/graph/email/graph.py
"""Compiled email_graph — async email-driven state machine with interrupt gates."""
import logging

from langgraph.graph import StateGraph, START, END

from app.graph.state import EmailState
from app.graph.email.nodes import (
    verify_node,
    send_challenge_node,
    plan_node,
    execute_node,
    report_node,
    ask_subdomain_node,
    wire_cf_node,
    route_after_verify,
    route_after_execute,
)

logger = logging.getLogger(__name__)


def build_email_graph(checkpointer):
    graph = StateGraph(EmailState)

    graph.add_node("verify_node", verify_node)
    graph.add_node("send_challenge_node", send_challenge_node)
    graph.add_node("plan_node", plan_node)
    graph.add_node("execute_node", execute_node)
    graph.add_node("report_node", report_node)
    graph.add_node("ask_subdomain_node", ask_subdomain_node)
    graph.add_node("wire_cf_node", wire_cf_node)

    graph.add_edge(START, "verify_node")
    graph.add_conditional_edges(
        "verify_node",
        route_after_verify,
        {"plan_node": "plan_node", "send_challenge_node": "send_challenge_node"},
    )
    # send_challenge_node → END: graph pauses, waits for user reply
    graph.add_edge("send_challenge_node", END)
    # plan_node → execute_node: interrupt_before=["execute_node"] pauses for APPROVE
    graph.add_edge("plan_node", "execute_node")
    graph.add_conditional_edges(
        "execute_node",
        route_after_execute,
        {"report_node": "report_node", "ask_subdomain_node": "ask_subdomain_node"},
    )
    graph.add_edge("report_node", END)
    # ask_subdomain_node → wire_cf_node: interrupt_before=["wire_cf_node"] pauses for subdomain
    graph.add_edge("ask_subdomain_node", "wire_cf_node")
    graph.add_edge("wire_cf_node", END)

    return graph.compile(
        checkpointer=checkpointer,
        interrupt_before=["execute_node", "wire_cf_node"],
    )
