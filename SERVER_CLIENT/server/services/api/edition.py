"""Product editions share projects, robots and AI models. Each edition keeps its own
simulator connection and first-boot setup, so the NVIDIA build never rewrites the
standard build's GCP or local Isaac connection."""
import os

EDITIONS = ('standard', 'nvidia')
DEFAULTS = {
    'standard': {'simulator': 'builtin', 'compute': 'gcp', 'ai': 'existing'},
    'nvidia': {'simulator': 'isaac_sim', 'compute': 'nebius', 'ai': 'token_factory'},
}
TOKEN_FACTORY_URL = 'https://api.tokenfactory.nebius.com/v1'


def edition():
    value = os.getenv('ROBOT_IDE_EDITION', 'standard')
    return value if value in EDITIONS else 'standard'


def connection_path(store):
    name = 'isaac.json' if edition() == 'standard' else f'isaac.{edition()}.json'
    return store.runtime/'connections'/name


def setup_path(store):
    return store.runtime/'setup'/f'{edition()}.json'
