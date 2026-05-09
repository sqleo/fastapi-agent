import requests

url = "https://dashscope.aliyuncs.com/api/v1/services/rerank/text-rerank/text-rerank"
headers = {
    "Authorization": "Bearer fake_token",
    "Content-Type": "application/json"
}

# Test 1: string query, list of strings
payload1 = {
    "model": "qwen3-rerank",
    "input": {
        "query": "hello",
        "documents": ["doc1", "doc2"]
    }
}

r1 = requests.post(url, headers=headers, json=payload1)
print("Test 1:", r1.status_code, r1.text)

# Test 2: dict query, list of dicts
payload2 = {
    "model": "qwen3-rerank",
    "input": {
        "query": "hello",
        "documents": [{"text": "doc1"}, {"text": "doc2"}]
    }
}
r2 = requests.post(url, headers=headers, json=payload2)
print("Test 2:", r2.status_code, r2.text)
