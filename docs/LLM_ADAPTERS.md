# RoboDE LLM adapters

Open **Configuration → AI Models**. Choose **New AI connection** to enter a Chat Completions-compatible API root, model and optional credentials. For local Ollama use `http://localhost:11434/v1` and the exact installed model name, for example `phi4:14b`. The endpoint is resolved from the machine running the backend.

In Expert mode choose **Custom Python function** to paste Python into Monaco, import a `.py` file, or load/download the included sample. The complete runnable example is `SERVER_CLIENT/server/examples/llm/ollama_adapter.py`.

For **Nemotron through Ollama**, import `SERVER_CLIENT/server/examples/llm/ollama_nemotron.py` using **Custom Python function**. Set the base URL to `http://127.0.0.1:11434` **without `/v1`**, enter an installed, explicit model tag, and allow up to 300 seconds for cold starts. This function uses Ollama's native API, disables Nano/Bolt thinking, and returns only final answer text. It rejects truncated output. It uses a 16,384-token context for Nano/Bolt and Mini's smaller 4,096-token context. These limits are runtime settings, not the models' maximum advertised context sizes. The endpoint runs on the backend machine; a browser user's own localhost is a different machine.

The [Nemotron evaluation](NEMOTRON_MODEL_EVALUATION_20261029.md) records tested tags, successful scenarios and limitations. Selecting a model does not certify its generated plans or SDK drafts; the normal compiler, review and simulated contract checks still apply. Existing tasks with an explicit LLM adapter keep their selection when the global default changes. Recompile affected plans after changing configuration.

```python
async def invoke(input: str, system_prompt: str) -> str:
    # Send the two arguments to your provider and return its answer text.
    ...
```

The IDE supplies task-generation and adapter-generation instructions internally. The UI has no system-prompt editor, test prompt editor or prompt preview. Existing private provider prefixes are preserved when edited through the form and excluded from public configuration and snapshots. A custom function necessarily receives the instructions at runtime; its author must forward them unchanged. This is not a secrecy boundary against trusted server administrators or installed custom code.

Each invocation starts a separate Python worker using the backend's Python environment. It receives only the saved connection settings and selected credential through `ROBOT_IDE_LLM_BASE_URL`, `ROBOT_IDE_LLM_MODEL`, `ROBOT_IDE_LLM_API_KEY`, `ROBOT_IDE_LLM_MAX_TOKENS`, and `ROBOT_IDE_LLM_TIMEOUT`. Workers use a disposable current directory. Timeout and Stop terminate the worker; POSIX also terminates its process group. This is process isolation, not a security sandbox. Install trusted code only. Additional packages must be installed in the backend's Python environment.

**Save AI model**, enter test input, then **Test model**. Test calls contact the selected provider. Return a nonempty string, up to 120,000 characters. Exceptions and invalid results produce a generic error without exposing provider responses, credentials or internal instructions. Choose the saved adapter globally, for a plan's goal drafting, or for an individual task.

RoboDE project IDs appear below the project selector in the explorer, with a copy button. They also appear in each saved project's `project.yaml` and the project-list API. A Google Cloud project ID is separate: find it in Google Cloud's project selector; this installation's configured project is `nvdiavm`.

## Nebius Token Factory: an independent adapter

In every IDE edition, select **Configuration → AI Models → New AI connection → Nebius Token Factory**. Enter a Token Factory key, choose **Check key & find models**, select an exact model ID returned by your account, then save. Select the saved profile for **Planner**, **Converter**, or both, and save those role settings. Changing one role does not change the other. The Business App inherits its server’s selections.

The preset uses `https://api.tokenfactory.nebius.com/v1`. It packages [`nebius_token_factory.py`](../SERVER_CLIENT/server/examples/llm/nebius_token_factory.py), a standalone `invoke(input, system_prompt) -> str` module, and invokes it in the normal isolated Python worker. It does not import the IDE, planning engine, simulator, robot driver or edition code. No Nebius GPU VM, GCP VM or Isaac Sim connection is needed for hosted inference. **Download adapter function** exports the module; Expert mode can customize it as a normal Python connection.

Credentials are kept in the server’s owner-only secrets file, or supplied using `NEBIUS_API_KEY` on that server. They never return in profile APIs, screenshots or exported code. The function receives the selected credential through `ROBOT_IDE_LLM_API_KEY`. It receives request-specific JSON output settings through the optional `ROBOT_IDE_LLM_RESPONSE_FORMAT` environment value while retaining the same two-argument function contract.

Model discovery checks listing/authentication; **Test model** additionally makes an inference request. Neither operation provisions a VM. Hosted inference uses the provider’s account. Available Nemotron model IDs are discovered rather than hardcoded. Structured output support is a saved provider setting, not an assumption that any listed model can follow a robot plan reliably.

Official references: [Nebius quickstart](https://docs.tokenfactory.nebius.com/quickstart), [model discovery](https://docs.tokenfactory.nebius.com/api-reference/models/list-models), [JSON outputs](https://docs.tokenfactory.nebius.com/ai-models-inference/json).

## Change history and measured comparisons

[`PROJECT_TIMELINE.md`](PROJECT_TIMELINE.md) is the maintained change document. The repository’s `AGENTS.md` requires it to be updated for future functional changes. The [local comparison](LLM_MODEL_COMPARISON_20261030.md) records new plans, actual responses and measurements separately from the earlier GCP evaluation.

## Google Gemini

Choose **Google Gemini** as the connection type in **Configuration → AI Models → New AI connection**. It uses a standalone standard function worker, independent of robot adapters and simulators. A connection named **Google Gemini · evaluation** is also prepared in both local workspaces (normal desktop/web with its Business companion, and the NVIDIA IDE). Existing defaults and Planner/Converter choices are unchanged.

Open **Configuration → AI Models**, edit that connection, enter a Google AI Studio API key in the **API key** field, and choose **Save AI model**. Use **Check key & find models** to verify the key and select an available text-generation model, then **Test model** for inference. Do not paste keys into chat or documents. The prepared API root is `https://generativelanguage.googleapis.com/v1beta/openai`, with optional server environment variable `GEMINI_API_KEY`. The initial candidate is `gemini-3.8-flash`, from Google's current catalog; account discovery and a live call must confirm availability. JSON outputs are enabled; VLM planning remains disabled.

After successful testing, the saved connection can be selected for Planner, Converter or both. Credentials belong to each backend workspace; saving a key in the normal workspace does not populate the separate NVIDIA workspace. The Business App uses its backend's selected roles. Hosted Gemini inference needs no robot GPU VM and is separate from GCP/Isaac lifecycle controls.

No Gemini quality score is claimed yet: no Google API key was configured during preparation. The existing Ollama reference `gemini-3-pro-preview:latest` returned HTTP 404/model not found on 30 October 2026; this is a connection/model-availability failure, not a Gemini planning result. The prior Phi-4/Nemotron comparison remains unchanged pending a live Gemini run.

Official references: [Gemini OpenAI compatibility](https://ai.google.dev/gemini-api/docs/openai), [current models](https://ai.google.dev/gemini-api/docs/models), [Google AI Studio keys](https://aistudio.google.com/apikey).

## NVIDIA hosted API and Nemotron

Choose **NVIDIA API · Nemotron** in **Configuration → AI Models → New AI connection**. This connector uses NVIDIA's hosted API at `https://integrate.api.nvidia.com/v1`. It is available in Simple mode in the normal and NVIDIA IDE editions. The local workspaces also have a prepared profile named **NVIDIA API · Nemotron**.

Enter an NVIDIA API key from the [NVIDIA API catalog](https://build.nvidia.com/) or configure `NVIDIA_API_KEY` on the backend. Use **Check key & find models**, choose the exact model ID offered by the account, save, then select the connection for Planner, Converter or both. The prepared candidate is `nvidia/nemotron-3-nano-30b-a3b`; it is a configuration example, not a tested recommendation. Each additional model can be saved as a separate named connection using the same provider option. Missing credentials are shown as **API key needed** without sending a provider request.

The three Nemotron paths are separate:

| Connection choice | Where inference runs | Credential |
|---|---|---|
| **NVIDIA API · Nemotron** | NVIDIA hosted API | NVIDIA API key |
| **Nebius Token Factory** | Nebius hosted API | Token Factory key |
| **Ollama** with a local Nemotron tag | The RoboDE backend machine | Usually no hosted key |

An Isaac Sim connection or GPU VM does not configure any of these LLM providers. The earlier local model comparison tested Ollama, not NVIDIA-hosted inference. At the user's request, the hosted connectors were configured without a live inference run or new key request.

Both Gemini and NVIDIA expose **Download adapter function**. The shared standalone source is [`hosted_chat.py`](../SERVER_CLIENT/server/examples/llm/hosted_chat.py): `async def invoke(input: str, system_prompt: str) -> str`, with no application, planning, robot or simulator imports. Its worker receives only that connection's URL/model/key and request settings; it forwards the private instructions, returns final answer text and rejects truncated/empty replies. Expert **Customize adapter function** preserves the provider URL and model. Switching to a different provider clears entered keys; changing an existing saved endpoint clears its saved key on Save unless a new key is supplied.

Official reference: [NVIDIA LLM API endpoint and model catalog](https://docs.api.nvidia.com/nim/reference/llm-apis).
