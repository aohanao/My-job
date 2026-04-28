import os
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()
client = OpenAI(
    api_key=os.getenv("DASHSCOPE_API_KEY"),
    base_url=os.getenv("OPENAI_API_BASE")
)

try:
    res = client.chat.completions.create(
        model="qwen-plus",
        messages=[{"role": "user", "content": "hello"}]
    )
    print(res.choices[0].message.content)
    print("SUCCESS")
except Exception as e:
    print(f"FAILED: {e}")
