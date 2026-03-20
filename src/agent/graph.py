"""LangGraph Agent with tool-calling support.

The agent can autonomously decide when to use tools (e.g. Milvus search)
during its reasoning process.
"""

from __future__ import annotations

import os
from typing import Annotated

from langchain_core.messages import AnyMessage
from langchain_openai import ChatOpenAI
from langgraph.graph import StateGraph, add_messages
from langgraph.prebuilt import ToolNode, tools_condition
from typing_extensions import TypedDict

from agent.tools import milvus_search


class State(TypedDict):
    """Agent state carrying the conversation messages."""

    messages: Annotated[list[AnyMessage], add_messages]


tools = [milvus_search]

llm = ChatOpenAI(
    model=os.getenv("LLM_MODEL", "deepseek-chat"),
    api_key=os.getenv("LLM_API_KEY"),
    base_url=os.getenv("LLM_BASE_URL", "https://api.deepseek.com"),
)

graph = (
    StateGraph(State)
    .add_node("call_model", lambda state: {"messages": [llm.bind_tools(tools).invoke(state["messages"])]})
    .add_node("tools", ToolNode(tools))
    .add_edge("__start__", "call_model")
    .add_conditional_edges("call_model", tools_condition)
    .add_edge("tools", "call_model")
    .compile(name="Agent")
)
