"""Provider-specific AI clients for the eval harness.

- Gold runners use a larger token budget (gold output mustn't be truncated).
- Cheap runner reuses prod's `lib.ai.generate_ai_response` so we measure prod behavior.
- Both providers share the same JSON cleanup pipeline (`_parse_ai_json_string`).
"""

import anthropic
from tenacity import retry, retry_if_result, stop_after_attempt, wait_fixed

from lib.ai import _parse_ai_json_string, build_instructions, generate_ai_response
from lib.config import get_config, get_env
from lib.logger import get_logger
from lib.models import PropertyData

config = get_config()
env = get_env()
logger = get_logger("eval.runners")

GOLD_MAX_TOKENS = 4096


def _is_empty_text(text: str) -> bool:
    return not isinstance(text, str) or not text.strip()


@retry(
    stop=stop_after_attempt(3),
    wait=wait_fixed(5),
    retry=retry_if_result(_is_empty_text),
    reraise=True,
)
def _call_claude(text: str, instructions: str, model_name: str) -> str:
    api_key = getattr(env, "ANTHROPIC_API_KEY", None)
    if not api_key:
        raise ValueError("ANTHROPIC_API_KEY is not set in environment")

    client = anthropic.Anthropic(api_key=api_key)
    response = client.messages.create(
        model=model_name,
        max_tokens=GOLD_MAX_TOKENS,
        system=instructions
        + "\n\nReturn ONLY a JSON object matching the template above. No prose, no markdown fences.",
        messages=[{"role": "user", "content": text}],
    )
    parts = [block.text for block in response.content if getattr(block, "type", None) == "text"]
    return "\n".join(parts)


def run_gemini(text: str, suburbs: list[str], model_name: str) -> PropertyData:
    """Production-style Gemini call. Uses prod's token budget (1024) so cheap-model
    runs in eval.run match what production sees."""
    instructions = build_instructions(config.google.ai.instructions_file, suburbs)
    # save instructions to a text file for debugging
    with open("ai_instructions_input.txt", "w", encoding="utf-8") as f:
        f.write(instructions)

    response = generate_ai_response(text, instructions, model_name=model_name)
    return _parse_ai_json_string(response.text)


def run_gemini_gold(text: str, suburbs: list[str], model_name: str) -> PropertyData:
    """Same as run_gemini but with a larger output budget so the gold model is never
    truncated. Used by build.py."""
    from google import genai
    from google.genai import types

    api_key = getattr(env, "GOOGLE__AI__API_KEY", None)
    if not api_key:
        raise ValueError("GOOGLE__AI__API_KEY is not set in environment")

    instructions = build_instructions(config.google.ai.instructions_file, suburbs)
    # save instructions to a text file for debugging
    with open("ai_instructions_input.txt", "w", encoding="utf-8") as f:
        f.write(instructions)
    
    client = genai.Client(api_key=api_key)
    response: types.GenerateContentResponse = client.models.generate_content(  # type: ignore
        model=model_name,
        contents=text,
        config=types.GenerateContentConfig(
            temperature=0.6,
            top_p=1,
            max_output_tokens=GOLD_MAX_TOKENS,
            system_instruction=instructions,
            response_mime_type="application/json",
        ),
    )
    return _parse_ai_json_string(response.text or "")


def run_claude_gold(text: str, suburbs: list[str], model_name: str) -> PropertyData:
    instructions = build_instructions(config.google.ai.instructions_file, suburbs)
    response_text = _call_claude(text, instructions, model_name)
    return _parse_ai_json_string(response_text)
