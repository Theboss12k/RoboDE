"""Private JSON-over-stdio worker for trusted LLM adapter functions."""
import asyncio
import contextlib
import inspect
import json
import tempfile
import os
import sys


class DiscardOutput:
    def write(self, value):
        return len(value)

    def flush(self):
        pass


async def main():
    data = json.loads(sys.stdin.buffer.read(18000000))
    namespace = {'__name__': 'robot_ide_llm_adapter'}
    # A disposable working directory avoids accidental writes into a project.
    with tempfile.TemporaryDirectory(prefix='robot-ide-llm-') as folder:
        os.chdir(folder)
        with contextlib.redirect_stdout(DiscardOutput()), contextlib.redirect_stderr(DiscardOutput()):
            exec(compile(data['source'], '<llm-adapter>', 'exec'), namespace)
            answer = (namespace['invoke_multimodal'](data['input'],data['system_prompt'],data['images']) if data.get('images')
                      else namespace['invoke'](data['input'], data['system_prompt']))
            if inspect.isawaitable(answer):
                answer = await answer
        if not isinstance(answer, str) or not answer.strip() or len(answer) > 120000:
            raise ValueError('Return non-empty answer text of at most 120000 characters')
    return {'ok': True, 'answer': answer}


if __name__ == '__main__':
    try:
        result = asyncio.run(main())
    except BaseException:
        # Never return exception text: it could contain credentials or internal instructions.
        result = {'ok': False}
    sys.stdout.write(json.dumps(result))
