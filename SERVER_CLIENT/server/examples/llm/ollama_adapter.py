"""RoboDE LLM adapter: paste this code in Configuration > LLM adapters.

The IDE supplies both arguments. Forward system_prompt unchanged; return text.
Connection settings and credentials come from the saved adapter configuration.
"""
import os
import httpx


async def invoke(input: str, system_prompt: str) -> str:
    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": input})

    key = os.environ.get("ROBOT_IDE_LLM_API_KEY", "")
    async with httpx.AsyncClient(
        timeout=float(os.environ["ROBOT_IDE_LLM_TIMEOUT"]),
        follow_redirects=False,
    ) as client:
        response = await client.post(
            os.environ["ROBOT_IDE_LLM_BASE_URL"].rstrip("/") + "/chat/completions",
            headers={"Authorization": f"Bearer {key}"} if key else {},
            json={
                "model": os.environ["ROBOT_IDE_LLM_MODEL"],
                "temperature": 0,
                "max_tokens": int(os.environ["ROBOT_IDE_LLM_MAX_TOKENS"]),
                "messages": messages,
            },
        )
        response.raise_for_status()
        return response.json()["choices"][0]["message"]["content"]
