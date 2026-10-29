# RoboDE LLM adapters

Open **Configuration → LLM adapters**. Choose **Configure with UI** to enter a Chat Completions-compatible API root, model and optional credentials. For local Ollama use `http://localhost:11434/v1` and the exact installed model name, for example `phi4:14b`. The endpoint is resolved from the machine running the backend.

Choose **Paste adapter code** to paste Python into Monaco, import a `.py` file, or load/download the included sample. The complete runnable example is `SERVER_CLIENT/server/examples/llm/ollama_adapter.py`.

```python
async def invoke(input: str, system_prompt: str) -> str:
    # Send the two arguments to your provider and return its answer text.
    ...
```

The IDE supplies task-generation and adapter-generation instructions internally. The UI has no system-prompt editor, test prompt editor or prompt preview. Existing private provider prefixes are preserved when edited through the form and excluded from public configuration and snapshots. A custom function necessarily receives the instructions at runtime; its author must forward them unchanged. This is not a secrecy boundary against trusted server administrators or installed custom code.

Each invocation starts a separate Python worker using the backend's Python environment. It receives only the saved connection settings and selected credential through `ROBOT_IDE_LLM_BASE_URL`, `ROBOT_IDE_LLM_MODEL`, `ROBOT_IDE_LLM_API_KEY`, `ROBOT_IDE_LLM_MAX_TOKENS`, and `ROBOT_IDE_LLM_TIMEOUT`. Workers use a disposable current directory. Timeout and Stop terminate the worker; POSIX also terminates its process group. This is process isolation, not a security sandbox. Install trusted code only. Additional packages must be installed in the backend's Python environment.

**Save LLM adapter**, enter test input, then **Invoke saved adapter**. Test calls contact the selected provider. Return a nonempty string, up to 120,000 characters. Exceptions and invalid results produce a generic error without exposing provider responses, credentials or internal instructions. Choose the saved adapter globally, for a plan's goal drafting, or for an individual task.

RoboDE project IDs appear below the project selector in the explorer, with a copy button. They also appear in each saved project's `project.yaml` and the project-list API. A Google Cloud project ID is separate: find it in Google Cloud's project selector; this installation's configured project is `nvdiavm`.
