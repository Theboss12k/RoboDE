"""Provider presets supply settings/code; they do not select models or start compute."""
from pathlib import Path

TOKEN_FACTORY_URL = 'https://api.tokenfactory.nebius.com/v1'
HOSTED_PROVIDERS = {
    'nebius': ('Nebius Token Factory', 'NEBIUS_API_KEY', 'nebius_token_factory.py'),
    'gemini': ('Google Gemini', 'GEMINI_API_KEY', 'hosted_chat.py'),
    'nvidia': ('NVIDIA', 'NVIDIA_API_KEY', 'hosted_chat.py'),
}


def provider_preset(configuration):
    preset = HOSTED_PROVIDERS.get(configuration.connection_type)
    if not preset:
        return configuration
    source = configuration.source_code or (Path(__file__).resolve().parents[2]/'examples/llm'/preset[2]).read_text()
    return configuration.model_copy(update={'protocol': 'python_function', 'source_code': source,
                                           'api_key_env': configuration.api_key_env or preset[1]})
