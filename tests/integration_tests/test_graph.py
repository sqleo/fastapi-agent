import pytest

from agent import graph

pytestmark = pytest.mark.anyio


@pytest.mark.langsmith
@pytest.mark.skip(reason="需要 MySQL 与 /llm/settings/global 已配置聊天厂商与模型")
async def test_agent_simple_passthrough() -> None:
    res = await graph.ainvoke(
        {"messages": [{"role": "user", "content": "ping"}]},
        config={"configurable": {"user_id": 1}},
    )
    assert res is not None
