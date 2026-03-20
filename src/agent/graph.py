"""LangGraph Agent with tool-calling support.

The agent can autonomously decide when to use tools (e.g. Milvus search)
during its reasoning process.
"""

from __future__ import annotations

from typing import Annotated

from langchain_core.messages import AnyMessage
from langgraph.graph import StateGraph, add_messages
from langgraph.prebuilt import ToolNode, tools_condition
from langgraph.runtime import Runtime
from typing_extensions import TypedDict

from agent.tools import milvus_search


class Context(TypedDict):
    """Context parameters for the agent.

    Set these when creating assistants OR when invoking the graph.
    See: https://langchain-ai.github.io/langgraph/cloud/how-tos/configuration_cloud/
    """

    model: str


class State(TypedDict):
    """Agent state carrying the conversation messages."""

    messages: Annotated[list[AnyMessage], add_messages]


tools = [milvus_search]


async def call_model(state: State, runtime: Runtime[Context]) -> dict:
    """Invoke the LLM with tools bound."""
    from langchain.chat_models import init_chat_model

    model_name = (runtime.context or {}).get("model", "openai:gpt-4o-mini")
    llm = init_chat_model(model_name)
    llm_with_tools = llm.bind_tools(tools)
    response = await llm_with_tools.ainvoke(state["messages"])
    return {"messages": [response]}


graph = (
    StateGraph(State, context_schema=Context)
    .add_node("call_model", call_model)
    .add_node("tools", ToolNode(tools))
    .add_edge("__start__", "call_model")
    .add_conditional_edges("call_model", tools_condition)
    .add_edge("tools", "call_model")
    .compile(name="Agent")
)
