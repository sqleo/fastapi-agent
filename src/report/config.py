ROUTING_TABLE = {
    "human_review_intent": {
        "revise": "intent",
        "__default__": "planner"
    },
    "human_review": {
        "revise": "writer",
        "replan": "planner",
        "__default__": "writer"
    }
}