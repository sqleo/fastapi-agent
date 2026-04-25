RunnableConfig = {
    "configurable": {
        "user_id": 2
    }
}

ROUTING_TABLE = {
    "human_review_intent": {
        "revise": "intent",
        "__default__": "planner"
    },
    "human_review": {
        "revise": "outliner",
        "replan": "planner",
        "__default__": "writer"
    }
}