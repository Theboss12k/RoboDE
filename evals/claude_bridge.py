"""A loopback server that answers Ollama's chat API with the Claude Code CLI, so the eval suite can grade Claude.

  python -m evals.claude_bridge --claude /path/to/claude &
  npm run eval -- --model claude-opus-5-5 --ollama-url http://127.0.0.1:11436

Each /api/chat request runs one `claude -p` call: the pipeline's system prompt replaces Claude Code's own, tools,
MCP servers, slash commands, settings and session history are off, and the working directory is empty, so no
project instructions are read. The CLI uses its own login. It has no temperature setting, so repeats can differ.
A CLI error (not logged in, rate limit, unknown model) is answered with HTTP 500, which the eval suite treats as
the model being unavailable and stops instead of grading.
"""
import argparse
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import pwd
import subprocess
import tempfile
import time

MODELS = ('claude-opus-5-5', 'claude-sonnet-5-5', 'claude-haiku-5-5')


def ask_claude(cli, model, effort, system_prompt, prompt, timeout):
    """One CLI call with a clean environment; returns the parsed `--output-format json` result."""
    home = pwd.getpwuid(os.getuid()).pw_dir
    environment = {'HOME':home, 'USER':os.environ.get('USER', ''), 'PATH':'/usr/bin:/bin:/usr/sbin:/sbin',
                   'TMPDIR':os.environ.get('TMPDIR', '/tmp')}
    with tempfile.TemporaryDirectory(prefix='robode-claude-') as empty:
        system_file = os.path.join(empty, '.system-prompt')
        with open(system_file, 'w') as f:
            f.write(system_prompt)
        command = [cli, '-p', '--system-prompt-file', system_file, '--tools', '', '--output-format', 'json',
                   '--model', model, '--no-session-persistence', '--strict-mcp-config', '--disable-slash-commands',
                   '--setting-sources', '', *(['--effort', effort] if effort else [])]
        done = subprocess.run(command, input=prompt, capture_output=True, text=True, cwd=empty, env=environment, timeout=timeout)
    try:
        return json.loads(done.stdout)
    except ValueError:
        return {'is_error':True, 'result':(done.stderr or done.stdout or f'exit {done.returncode}').strip()[:500]}


def serve(cli, port, effort, timeout):
    version = subprocess.run([cli, '--version'], capture_output=True, text=True).stdout.strip()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def reply(self, status, body):
            data = json.dumps(body).encode()
            self.send_response(status)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            if self.path == '/api/version':
                return self.reply(200, {'version':version})
            if self.path == '/api/tags':
                return self.reply(200, {'models':[{'name':m, 'digest':None, 'size':None,
                    'details':{'provider':'Claude Code CLI', 'effort':effort or 'CLI default'}} for m in MODELS]})
            self.reply(404, {'error':'not found'})

        def do_POST(self):
            if self.path != '/api/chat':
                return self.reply(404, {'error':'not found'})
            request = json.loads(self.rfile.read(int(self.headers.get('Content-Length', 0))))
            if request.get('model') not in MODELS:
                return self.reply(404, {'error':f"model '{request.get('model')}' not found"})
            messages = request.get('messages', [])
            system = '\n\n'.join(m['content'] for m in messages if m['role'] == 'system')
            prompt = '\n\n'.join(m['content'] for m in messages if m['role'] != 'system')
            started = time.monotonic()
            try:
                result = ask_claude(cli, request['model'], effort, system, prompt, timeout)
            except subprocess.TimeoutExpired:
                return self.reply(500, {'error':f'Claude CLI timed out after {timeout} s'})
            if result.get('is_error') or not isinstance(result.get('result'), str):
                return self.reply(500, {'error':'Claude CLI: '+str(result.get('result'))[:300]})
            usage = result.get('usage', {})
            prompt_tokens = sum(usage.get(k) or 0 for k in ('input_tokens', 'cache_creation_input_tokens', 'cache_read_input_tokens'))
            self.reply(200, {'model':request['model'], 'message':{'role':'assistant', 'content':result['result']}, 'done':True,
                'done_reason':'length' if result.get('stop_reason') == 'max_tokens' else 'stop',
                'prompt_eval_count':prompt_tokens, 'eval_count':usage.get('output_tokens'),
                'total_duration':int((time.monotonic()-started)*1e9)})

    server = ThreadingHTTPServer(('127.0.0.1', port), Handler)
    print(f'Claude bridge ({version}) on http://127.0.0.1:{port}', flush=True)
    server.serve_forever()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--claude', default='claude', help='path to the Claude Code CLI')
    parser.add_argument('--port', type=int, default=11436)
    parser.add_argument('--effort', help='low, medium or high; default: the CLI default')
    parser.add_argument('--timeout', type=int, default=280, help='seconds per call, under the adapter timeout of 300')
    args = parser.parse_args()
    serve(args.claude, args.port, args.effort, args.timeout)
