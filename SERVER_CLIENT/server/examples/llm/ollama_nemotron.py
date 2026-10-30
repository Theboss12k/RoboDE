"""RoboDE Python function adapter for server-local Ollama Nemotron.

Base URL: http://127.0.0.1:11434 (without /v1).
Model: an explicitly installed Nemotron tag. RoboDE supplies the private prompt.
"""
import json
import os
import urllib.request


async def invoke(input: str, system_prompt: str) -> str:
    model = os.environ['ROBOT_IDE_LLM_MODEL']
    messages = ([{'role': 'system', 'content': system_prompt}] if system_prompt else [])
    messages.append({'role': 'user', 'content': input})
    payload = {
        'model': model, 'messages': messages, 'stream': False,
        'options': {'temperature': 0, 'num_ctx': 4096 if 'nemotron-mini' in model else 16384,
                    'num_predict': int(os.environ['ROBOT_IDE_LLM_MAX_TOKENS'])},
        'keep_alive': '60s',
    }
    # Return final content, never the separate reasoning stream. Mini is an
    # older model without Nano's think flag and has a smaller context window.
    if 'nemotron-mini' not in model:
        payload['think'] = False
    request = urllib.request.Request(
        os.environ['ROBOT_IDE_LLM_BASE_URL'].rstrip('/') + '/api/chat',
        data=json.dumps(payload).encode(), headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(request, timeout=float(os.environ['ROBOT_IDE_LLM_TIMEOUT'])) as response:
        result = json.load(response)
    if result.get('error'):
        raise ValueError('Ollama reported an inference error')
    answer = result.get('message', {}).get('content')
    if result.get('done_reason') == 'length':
        raise ValueError('Ollama output reached its token limit; no partial result accepted')
    if not isinstance(answer, str) or not answer.strip():
        raise ValueError('Ollama did not return a final answer')
    return answer
