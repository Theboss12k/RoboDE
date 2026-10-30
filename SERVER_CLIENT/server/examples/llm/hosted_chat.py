"""Standalone Gemini/NVIDIA API adapter using the standard RoboDE function.

The backend injects this connection's URL, model and key. This module has no
robot, simulator, planning-engine or application-edition dependency.
"""
import json
import os
import urllib.request


async def invoke(input: str, system_prompt: str) -> str:
    key = os.environ.get('ROBOT_IDE_LLM_API_KEY', '')
    if not key:
        raise ValueError('An API key is required for this hosted LLM connection')
    messages = ([{'role': 'system', 'content': system_prompt}] if system_prompt else [])
    messages.append({'role': 'user', 'content': input})
    payload = {'model': os.environ['ROBOT_IDE_LLM_MODEL'], 'messages': messages,
               'temperature': 0, 'max_tokens': int(os.environ['ROBOT_IDE_LLM_MAX_TOKENS'])}
    output_format = os.environ.get('ROBOT_IDE_LLM_RESPONSE_FORMAT', '')
    if output_format:
        payload['response_format'] = json.loads(output_format)
    request = urllib.request.Request(
        os.environ['ROBOT_IDE_LLM_BASE_URL'].rstrip('/')+'/chat/completions',
        data=json.dumps(payload).encode(),
        headers={'Content-Type': 'application/json', 'Authorization': 'Bearer '+key})
    with urllib.request.urlopen(request, timeout=float(os.environ['ROBOT_IDE_LLM_TIMEOUT'])) as response:
        result = json.load(response)
    choice = result['choices'][0]
    if choice.get('finish_reason') == 'length':
        raise ValueError('Incomplete response; token limit reached')
    answer = choice['message'].get('content')
    if not isinstance(answer, str) or not answer.strip():
        raise ValueError('Provider returned no final answer text')
    return answer
