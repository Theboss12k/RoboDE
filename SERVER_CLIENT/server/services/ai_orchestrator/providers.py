"""Providers propose a bounded task intent, never code or actuator commands."""
import json
import os
import re
from typing import Literal, Protocol
import httpx
from services.ai_orchestrator.llm import json_answer
from pydantic import Field
from shared.models.domain import Contract, WorldObject


class Intent(Contract):
    template: Literal["pick_place", "move_home"]
    object_id: str | None = None
    target_id: str | None = None


class IntentProvider(Protocol):
    name: str
    async def interpret(self, prompt: str, objects: list[WorldObject]) -> Intent: ...


class TemplateProvider:
    name = "Local templates"

    async def interpret(self, prompt: str, objects: list[WorldObject]) -> Intent:
        text = prompt.lower().strip()
        if re.search(r"\b(throw|catch|toss|navigate|hardware|physical|real robot|not|don't|without|instead|avoid|unless|if|then|twice|repeat)\b", text):
            raise ValueError("This request needs planning beyond the local templates. Try ‘Pick up the apple and place it in the basket’ or ‘Move home’. Throwing, catching, conditional tasks and physical execution are unavailable.")
        if re.fullmatch(r"(?:please )?(?:move|go|return)(?: the (?:robot|arm))?(?: to)? (?:home|the initial (?:pose|configuration))[.!]?", text):
            return Intent(template="move_home")
        matches = []
        for item_object in (o for o in objects if o.kind == "object"):
            for target_object in (o for o in objects if o.kind == "region"):
                item, target = re.escape(item_object.name.lower()), re.escape(target_object.name.lower())
                pattern = rf"(?:please )?(?:(?:pick up|pick|grab|take) (?:the )?{item} and (?:place|put|move) (?:it|the {item})|(?:place|put|move) (?:the )?{item}) (?:in|into|inside|to) (?:the )?{target}[.!]?"
                if re.fullmatch(pattern, text):
                    matches.append(Intent(template="pick_place", object_id=item_object.id, target_id=target_object.id))
        if len(matches) == 1:
            return matches[0]
        raise ValueError("I could not resolve a supported task unambiguously. Name one known object and one target region, for example ‘Pick up the apple and place it in the basket’. For other phrasing, configure an AI provider in .env.")


class CompatibleProvider:
    name = "Configured AI provider"

    async def interpret(self, prompt: str, objects: list[WorldObject]) -> Intent:
        base = os.environ["AI_BASE_URL"].rstrip("/")
        model = os.environ["AI_MODEL"]
        system = ("Translate requests to one supported robotics task. Allowed templates: pick_place, move_home. "
                  "Return only JSON with template, object_id, target_id. Never approximate throwing, catching, "
                  "multi-robot, conditional, repeated or physical tasks as pick_place. For unsupported, ambiguous or missing resources return {\"error\":\"explanation\"}. "
                  f"Available objects: {json.dumps([o.model_dump() for o in objects])}")
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(f"{base}/chat/completions", headers={"Authorization": f"Bearer {os.getenv('AI_API_KEY', '')}"},
                                         json={"model": model, "temperature": 0, "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}]})
            response.raise_for_status()
            data = json_answer(response.json()["choices"][0]["message"]["content"])
        if "error" in data:
            raise ValueError(str(data["error"]))
        return Intent.model_validate(data)


class RegisteredProvider:
    def __init__(self, registry, adapter_id=None):
        self.invoke = registry.adapter(adapter_id)
        self.name = registry.resolve(adapter_id)['name']

    async def interpret(self, prompt, objects):
        system = ('Translate to one robotics intent. Allowed templates: pick_place, move_home. '
                  'Return only JSON with template, object_id, target_id. Never invent resources or approximate unsupported tasks. '
                  'For unsupported or ambiguous requests return {"error":"explanation"}. '
                  f'Available objects: {json.dumps([o.model_dump() for o in objects])}')
        answer = await self.invoke(prompt,system)
        try:
            data = json_answer(answer['answer'])
        except (ValueError,TypeError) as error:
            raise ValueError('LLM task draft must be a JSON intent; no changes were saved') from error
        if isinstance(data,dict) and 'error' in data:
            raise ValueError(str(data['error']))
        return Intent.model_validate(data)


def get_provider(registry=None, adapter_id=None) -> IntentProvider:
    if registry is not None:
        if adapter_id or registry.all()['default_id']:
            return RegisteredProvider(registry,adapter_id)
        return TemplateProvider()
    if os.getenv("AI_BASE_URL") and os.getenv("AI_MODEL"):
        return CompatibleProvider()
    return TemplateProvider()
