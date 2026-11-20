"""Record, replay and measure the model calls made by the Planner and Converter.

Live and record modes wrap the real adapter. Replay mode returns saved answers, so grading runs
offline and identically in pytest. Recordings hold model answers and timings, never system prompts.
"""
from contextlib import contextmanager
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import threading
import urllib.error
import urllib.request

from services.ai_orchestrator.llm import LLMRegistry


class StaleRecording(RuntimeError):
    """Not a ValueError, so the API does not turn it into an ordinary refusal that would be graded."""


class ModelUnavailable(RuntimeError):
    """The model server did not answer. A refusal case would otherwise 'pass' during an outage, so the run stops."""


def stage_of(system_prompt: str) -> str:
    return 'planner' if 'PLANNER' in system_prompt else 'converter' if 'COMMAND CONVERTER' in system_prompt else 'other'


class Tape:
    """Holds the calls of the case being run. `answers` is set for replay; `calls` collects what happened."""

    def __init__(self, mode='live', relay=None):
        assert mode in {'live','record','replay'}
        self.mode, self.relay = mode, relay
        self.calls, self.answers = [], None

    def start_case(self, answers=None):
        self.calls, self.answers = [], iter(answers) if answers is not None else None

    async def _replay(self, system_prompt):
        try:
            saved = next(self.answers)
        except StopIteration:
            raise StaleRecording('Replay ran out of recorded answers; record this case again') from None
        if saved['stage'] != stage_of(system_prompt):
            raise StaleRecording(f"Replay expected a {saved['stage']} call but the pipeline made a {stage_of(system_prompt)} call; record this case again")
        self.calls.append(saved)
        if saved.get('error'):
            raise ValueError(saved['error'])
        return {'answer':saved['answer'],'adapter_id':'replay','adapter_version':1,'model':saved.get('model','replay'),
                'provider_host':'replay','duration_seconds':saved.get('duration_seconds',0),'usage':saved.get('usage',{}),
                'finish_reason':saved.get('finish_reason')}

    @contextmanager
    def installed(self):
        """Patch the registry for the duration of a run; the app's own registry instance picks it up."""
        original, tape = LLMRegistry.adapter, self

        def adapter(registry, adapter_id=None, response_schema=None, json_object=False):
            if tape.mode == 'replay':
                async def replay(input, system_prompt='', images=None):
                    return await tape._replay(system_prompt)
                return replay
            real = original(registry, adapter_id, response_schema, json_object)

            async def measured(input, system_prompt='', images=None):
                seen = len(tape.relay.entries) if tape.relay else 0
                entry = {'stage':stage_of(system_prompt)}
                try:
                    result = await real(input, system_prompt, images)
                    entry.update(answer=result['answer'], model=result.get('model'), duration_seconds=result.get('duration_seconds'),
                                 finish_reason=result.get('finish_reason'), usage=result.get('usage') or {})
                    return result
                except ValueError as error:
                    entry['error'] = str(error)
                    outage = tape.relay and len(tape.relay.entries) > seen and tape.relay.entries[-1].get('upstream_error')
                    if outage:
                        entry['stage'] = 'unavailable'
                        raise ModelUnavailable(f'Ollama at {tape.relay.upstream} did not answer: {outage}') from error
                    raise
                finally:
                    if tape.relay and len(tape.relay.entries) > seen:
                        # Ollama reports tokens on its native API; the python_function adapter cannot return them itself.
                        last = tape.relay.entries[-1]
                        entry['usage'] = {**entry.get('usage', {}), **{k:v for k,v in last.items() if k.endswith('_tokens')}}
                        if last.get('load_seconds') is not None:
                            entry['load_seconds'] = last['load_seconds']
                    tape.calls.append(entry)
            return measured

        LLMRegistry.adapter = adapter
        try:
            yield self
        finally:
            LLMRegistry.adapter = original


class OllamaRelay:
    """A loopback pass-through to Ollama's /api/chat that keeps token counts and model load time per call."""

    def __init__(self, upstream: str):
        self.upstream, self.entries = upstream.rstrip('/'), []
        relay = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_POST(self):
                body = self.rfile.read(int(self.headers.get('Content-Length', 0)))
                request = urllib.request.Request(relay.upstream+self.path, data=body, headers={'Content-Type':'application/json'})
                try:
                    with urllib.request.urlopen(request, timeout=600) as response:
                        status, data = response.status, response.read()
                except urllib.error.HTTPError as error:
                    # Ollama answers with an HTTP error when it can't serve the model at all (not installed, or an
                    # architecture this runtime can't load). That is unavailability, not a model answer.
                    status, data = error.code, error.read()
                    try:
                        detail = json.loads(data).get('error')
                    except ValueError:
                        detail = None
                    relay.entries.append({'upstream_error':f'HTTP {status}: {detail or error.reason}'})
                    self.send_response(status)
                    self.send_header('Content-Type', 'application/json')
                    self.send_header('Content-Length', str(len(data)))
                    self.end_headers()
                    self.wfile.write(data)
                    return
                except OSError as error:
                    # Connection refused, reset or timed out: an outage, not a model answer.
                    relay.entries.append({'upstream_error':str(getattr(error, 'reason', error))})
                    data = json.dumps({'error':'upstream unavailable'}).encode()
                    self.send_response(502)
                    self.send_header('Content-Type', 'application/json')
                    self.send_header('Content-Length', str(len(data)))
                    self.end_headers()
                    self.wfile.write(data)
                    return
                try:
                    parsed = json.loads(data)
                    relay.entries.append({'prompt_tokens':parsed.get('prompt_eval_count'),'completion_tokens':parsed.get('eval_count'),
                                          'load_seconds':round(parsed['load_duration']/1e9, 3) if parsed.get('load_duration') else None})
                except ValueError:
                    relay.entries.append({})
                self.send_response(status)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(data)))
                self.end_headers()
                self.wfile.write(data)

        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.url = f'http://127.0.0.1:{self.server.server_port}'
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()
