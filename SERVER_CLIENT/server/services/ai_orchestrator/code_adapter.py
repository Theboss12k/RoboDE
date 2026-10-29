"""Run a user-supplied LLM function outside the API process.

This is process isolation and cancellation, not an operating-system sandbox.
Only trusted workspace administrators should install Python code.
"""
import ast
import asyncio
import json
import os
from pathlib import Path
import signal
import sys


def validate_source(source: str):
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError) as error:
        raise ValueError('Adapter code must be valid Python') from error
    entries = [n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == 'invoke']
    if len(entries) != 1:
        raise ValueError('Define one top-level invoke(input, system_prompt) function returning answer text')
    entry = entries[0]
    args = entry.args
    if ([a.arg for a in args.posonlyargs + args.args] != ['input', 'system_prompt']
            or args.vararg or args.kwarg or args.kwonlyargs or entry.decorator_list):
        raise ValueError('Use the standard signature: async def invoke(input: str, system_prompt: str) -> str')


async def invoke_code(configuration, input: str, system_prompt: str, key: str):
    environment = {k: os.environ[k] for k in ('PATH', 'SYSTEMROOT', 'WINDIR', 'TEMP', 'TMP', 'TMPDIR') if k in os.environ}
    environment.update({
        'ROBOT_IDE_LLM_BASE_URL': configuration['base_url'],
        'ROBOT_IDE_LLM_MODEL': configuration['model'],
        'ROBOT_IDE_LLM_API_KEY': key,
        'ROBOT_IDE_LLM_MAX_TOKENS': str(configuration['max_tokens']),
        'ROBOT_IDE_LLM_TIMEOUT': str(configuration['timeout_seconds']),
    })
    process = await asyncio.create_subprocess_exec(
        sys.executable, '-I', str(Path(__file__).with_name('code_adapter_worker.py')),
        stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
        env=environment, start_new_session=(os.name != 'nt'))
    try:
        payload = json.dumps({'source': configuration['source_code'], 'input': input, 'system_prompt': system_prompt}).encode()
        stdout, _ = await asyncio.wait_for(process.communicate(payload), configuration['timeout_seconds'])
        if process.returncode or len(stdout) > 800000:
            raise ValueError('Adapter worker failed')
        result = json.loads(stdout)
        if not result.get('ok'):
            raise ValueError('Adapter function failed')
        return result['answer']
    except asyncio.TimeoutError as error:
        raise ValueError('Adapter function timed out') from error
    finally:
        if process.returncode is None:
            try:
                if os.name != 'nt':
                    os.killpg(process.pid, signal.SIGKILL)
                else:
                    process.kill()
            except ProcessLookupError:
                pass
            await process.wait()
