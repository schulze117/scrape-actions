import json
import re
from typing import Any

from google import genai
from google.genai import types
from pydantic import BaseModel, TypeAdapter, ValidationError
from tenacity import RetryError, retry, retry_if_result, stop_after_attempt, wait_fixed

from lib.config import get_config, get_env
from lib.logger import get_logger
from lib.models import PropertyData

config = get_config()
env = get_env()
logger = get_logger("ai")

JSON_NULL_VALUES = ["None", "NaN", "inf", "-inf", "NaT"]
PATHS_TO_REMOVE = {"general.title", "financial.price_per_sqm", "location.admin_area_id"}


def _is_empty_response(response: Any) -> bool:
    return not hasattr(response, "text") or not isinstance(response.text, str) or not response.text.strip()


def build_instructions(instruction_file_path: str, suburbs: list[str]) -> str:
    with open(instruction_file_path, "r", encoding="utf-8") as f:
        txt_content = f.read()

    json_data = remove_paths(PropertyData, paths=PATHS_TO_REMOVE)
    json_data = schema_to_commented_string(json_data)
    json_data = append_comment(json_data, "suburb", f'ENUM: {"|".join(suburbs)}')

    lines = [
        txt_content,
        "Here is the response template with keys, their types and the explanation:\n",
        json_data,
    ]
    return "\n".join(lines)


@retry(
    stop=stop_after_attempt(config.google.ai.request.max_retries),
    wait=wait_fixed(config.google.ai.request.retry_delay),
    retry=retry_if_result(_is_empty_response),
    reraise=True,
)
def generate_ai_response(
    text: str, instructions: str, model_name: str | None = None
) -> types.GenerateContentResponse:
    api_key = getattr(env, "GOOGLE__AI__API_KEY", None)
    if not api_key:
        raise ValueError("GOOGLE__AI__API_KEY is not set in environment")

    client = genai.Client(api_key=api_key)
    response: types.GenerateContentResponse = client.models.generate_content(  # type: ignore
        model=model_name or config.google.ai.model_name,
        contents=text,
        config=types.GenerateContentConfig(
            temperature=0.6,
            top_p=1,
            max_output_tokens=1024,
            system_instruction=instructions,
            response_mime_type="application/json",
        ),
    )
    return response


def get_first_json_block(text: str) -> str:
    if not text.startswith("["):
        return extract_json_block(text)

    brace_count = 0
    start_index = None
    end_index = None
    for i, char in enumerate(text):
        if char == "{":
            if brace_count == 0:
                start_index = i
            brace_count += 1
        elif char == "}":
            brace_count -= 1
            if brace_count == 0:
                end_index = i
                break

    if start_index is not None and end_index is not None:
        return text[start_index : end_index + 1]

    raise ValueError("No valid JSON object found in the text")


def extract_json_block(text: str) -> str:
    start = text.find("{")
    end = text.rfind("}")
    return text[start : end + 1] if start != -1 and end != -1 and end > start else ""


def fix_json_values(json_str: str) -> str:
    for null_value in JSON_NULL_VALUES:
        json_str = json_str.replace(null_value, "null")

    json_str = json_str.replace('"null"', "null")
    json_str = json_str.replace("True", "true").replace("False", "false")
    json_str = re.sub(r",(\s*[}\]])", r"\1", json_str)
    json_str = re.sub(r'\\[^"\\/bfnrtu]', "", json_str)
    return json_str


def _parse_ai_json_string(response_text: str | None) -> PropertyData:
    if not response_text:
        raise ValueError("AI response is empty or invalid")

    extracted_json = get_first_json_block(response_text.strip())
    cleaned_data_str = fix_json_values(extracted_json)

    try:
        cleaned_data = json.loads(cleaned_data_str)
        set_paths_to_none(cleaned_data, paths=PATHS_TO_REMOVE)
        return PropertyData(**cleaned_data)
    except (json.JSONDecodeError, ValidationError) as e:
        details: dict[str, Any] = {
            "response_text": response_text,
            "cleaned_data": cleaned_data_str,
            "error": e.errors() if isinstance(e, ValidationError) else str(e),
        }
        raise ValueError(json.dumps(details)) from e


@retry(
    stop=stop_after_attempt(config.google.ai.parse_retries),
    wait=wait_fixed(1),
    reraise=True,
)
def parse_property_with_ai(text: str, suburbs: list[str]) -> PropertyData:
    instructions = build_instructions(config.google.ai.instructions_file, suburbs)
    response = generate_ai_response(text, instructions)
    return _parse_ai_json_string(response.text)


def schema_to_commented_string(schema: dict[str, Any]) -> str:
    defs = schema.get("$defs", {})

    def get_type_str(any_of: list[dict[str, str]]) -> str:
        types: list[str] = []
        for entry in any_of:
            if "type" in entry:
                types.append(entry["type"])
            elif "enum" in entry:
                types.append(entry.get("type", "string"))
        return " | ".join(types)

    def process_properties(props: dict[str, Any], indent: int = 2) -> list[str]:
        lines: list[str] = []
        pad = " " * indent
        for key, prop in props.items():
            if "$ref" in prop:
                ref_name = prop["$ref"].split("/")[-1]
                sub_props = defs[ref_name]["properties"]
                lines.append(f'{pad}"{key}": ' + "{")
                lines.extend(process_properties(sub_props, indent + 2))
                lines.append(f"{pad}" + "},")
            else:
                type_str = get_type_str(prop.get("anyOf", [])) or prop.get("type", "unknown")
                desc = prop.get("description", "").replace('"', '\\"')
                lines.append(f'{pad}"{key}": "{type_str}",{desc and f"  // {desc}" or ''}')
        return lines

    output_lines = ["{"]
    output_lines += process_properties(schema["properties"], indent=2)
    output_lines[-1] = output_lines[-1][:-1]
    output_lines.append("}")
    return "\n".join(output_lines)


def remove_paths(model: type[BaseModel], paths: set[str]) -> dict[str, Any]:
    schema = TypeAdapter(model).json_schema(ref_template="#/$defs/{model}")
    defs = schema.get("$defs", {})

    def drop_field(schema_obj: dict[str, Any], path_parts: list[str]):
        if not path_parts or "properties" not in schema_obj:
            return

        field = path_parts[0]
        if len(path_parts) == 1:
            if field in schema_obj["properties"]:
                schema_obj["properties"].pop(field)
            if "required" in schema_obj:
                schema_obj["required"] = [f for f in schema_obj["required"] if f != field]
            return

        next_obj = schema_obj["properties"].get(field)
        if next_obj and "$ref" in next_obj:
            ref = next_obj["$ref"].removeprefix("#/$defs/")
            ref_schema = defs.get(ref)
            if ref_schema:
                drop_field(ref_schema, path_parts[1:])

    for path in paths:
        drop_field(schema, path.split("."))

    return schema


def set_paths_to_none(data: dict[str, Any], paths: set[str]) -> None:
    for path in paths:
        parts = path.split(".")
        obj = data
        for key in parts[:-1]:
            if not isinstance(obj, dict):
                break
            obj = obj.get(key)  # type: ignore
            if obj is None:
                break
        else:
            if isinstance(obj, dict):
                obj[parts[-1]] = None


def append_comment(json_data: str, field: str, comment: str) -> str:
    lines = json_data.splitlines()
    for i, line in enumerate(lines):
        if f'"{field}":' in line:
            lines[i] = line.rstrip() + f" {comment}"
            break
    return "\n".join(lines)
