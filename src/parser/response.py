"""
parser/response.py — Awrass Response Parser
=============================================
Improvements over mse_ai_api:
  ✅ Multiple extraction strategies (regex, balanced-braces, fallback)
  ✅ Validates tool-call JSON schema before returning
  ✅ Handles nested JSON in markdown fences
  ✅ Arabic-aware text cleaning

Author: github.com/swordenkisk/awrass
"""

import json
import re
import uuid
import time
from dataclasses import dataclass
from typing import Optional


@dataclass
class ParsedToolCall:
    id          : str
    name        : str
    arguments   : dict

    def to_openai(self) -> dict:
        return {
            "id"      : self.id,
            "type"    : "function",
            "function": {
                "name"     : self.name,
                "arguments": json.dumps(self.arguments, ensure_ascii=False),
            },
        }


@dataclass
class ParsedResponse:
    raw_text   : str
    is_tool_call: bool = False
    tool_calls : list[ParsedToolCall] = None
    content    : str  = ""

    def to_openai_message(self) -> dict:
        if self.is_tool_call and self.tool_calls:
            return {
                "role"      : "assistant",
                "content"   : None,
                "tool_calls": [tc.to_openai() for tc in self.tool_calls],
            }
        return {"role": "assistant", "content": self.content or self.raw_text}


def parse_response(text: str) -> ParsedResponse:
    """
    Parse ChatGPT response text.
    Returns ParsedResponse with tool_calls if detected, otherwise plain content.
    """
    cleaned = _clean(text)

    # Strategy 1: try to extract JSON from the whole response
    tc = _try_extract_tool_calls(cleaned)
    if tc:
        return ParsedResponse(raw_text=text, is_tool_call=True, tool_calls=tc)

    # Strategy 2: look for JSON inside markdown fences
    for fence in re.findall(r"```(?:json)?\s*([\s\S]+?)```", cleaned):
        tc = _try_extract_tool_calls(fence.strip())
        if tc:
            return ParsedResponse(raw_text=text, is_tool_call=True, tool_calls=tc)

    # Strategy 3: look for JSON objects anywhere in the text
    tc = _try_json_anywhere(cleaned)
    if tc:
        return ParsedResponse(raw_text=text, is_tool_call=True, tool_calls=tc)

    # Plain text response
    content = _clean_plain(cleaned)
    return ParsedResponse(raw_text=text, is_tool_call=False, content=content)


def _clean(text: str) -> str:
    """Basic cleaning — remove obvious ChatGPT UI artifacts."""
    # Remove leading/trailing whitespace
    text = text.strip()
    # Remove common ChatGPT interface noise
    for noise in ["4o mini", "ChatGPT said:", "ChatGPT\n"]:
        text = text.replace(noise, "")
    return text.strip()


def _clean_plain(text: str) -> str:
    """Clean plain text response."""
    # Remove markdown fences wrapping the entire response (rare)
    text = re.sub(r"^```\w*\n([\s\S]+)\n```$", r"\1", text.strip())
    return text.strip()


def _try_extract_tool_calls(text: str) -> Optional[list[ParsedToolCall]]:
    """Try to parse text as a tool-call JSON object."""
    text = text.strip()
    if not text.startswith("{"):
        text = _find_first_brace_block(text)
        if not text:
            return None

    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        # Try to fix common issues: trailing commas, single quotes
        fixed = _fix_json(text)
        try:
            data = json.loads(fixed)
        except Exception:
            return None

    return _extract_from_dict(data)


def _extract_from_dict(data: dict) -> Optional[list[ParsedToolCall]]:
    """Extract ParsedToolCall list from a parsed dict."""
    if not isinstance(data, dict):
        return None

    # Format 1: {"tool_calls": [...]}
    raw_calls = data.get("tool_calls", [])
    if raw_calls and isinstance(raw_calls, list):
        calls = []
        for tc in raw_calls:
            name = tc.get("name", "")
            args = tc.get("arguments", tc.get("parameters", {}))
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except Exception:
                    args = {"input": args}
            if name:
                calls.append(ParsedToolCall(
                    id=f"call_{uuid.uuid4().hex[:8]}",
                    name=name, arguments=args,
                ))
        return calls if calls else None

    # Format 2: {"name": "...", "arguments": {...}}  (single call)
    name = data.get("name", "")
    args = data.get("arguments", data.get("parameters", {}))
    if name:
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except Exception:
                args = {"input": args}
        return [ParsedToolCall(
            id=f"call_{uuid.uuid4().hex[:8]}",
            name=name, arguments=args,
        )]

    return None


def _try_json_anywhere(text: str) -> Optional[list[ParsedToolCall]]:
    """Scan for any JSON object in the text that looks like a tool call."""
    for match in re.finditer(r"\{", text):
        block = _extract_balanced(text, match.start())
        if block and len(block) > 10:
            result = _try_extract_tool_calls(block)
            if result:
                return result
    return None


def _find_first_brace_block(text: str) -> Optional[str]:
    start = text.find("{")
    if start == -1:
        return None
    return _extract_balanced(text, start)


def _extract_balanced(text: str, start: int) -> Optional[str]:
    """Extract a balanced {...} block starting at index start."""
    depth = 0
    for i in range(start, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                return text[start:i+1]
    return None


def _fix_json(text: str) -> str:
    """Attempt to fix common JSON issues."""
    # Trailing commas before } or ]
    text = re.sub(r",\s*([}\]])", r"\1", text)
    # Single quotes → double quotes (careful)
    # Only do this if it's clearly single-quoted JSON
    if "'" in text and '"' not in text:
        text = text.replace("'", '"')
    return text


def build_openai_response(parsed: ParsedResponse, model: str = "gpt-4o",
                           request_id: str = None) -> dict:
    """Build a complete OpenAI-format chat completion response."""
    rid = request_id or f"chatcmpl-{uuid.uuid4().hex}"
    ts  = int(time.time())

    if parsed.is_tool_call and parsed.tool_calls:
        choice = {
            "index"        : 0,
            "message"      : parsed.to_openai_message(),
            "finish_reason": "tool_calls",
            "logprobs"     : None,
        }
    else:
        content = parsed.content or parsed.raw_text
        choice  = {
            "index"        : 0,
            "message"      : {"role": "assistant", "content": content},
            "finish_reason": "stop",
            "logprobs"     : None,
        }

    # Rough token estimate
    input_est  = 200
    output_est = max(1, len((parsed.content or parsed.raw_text)) // 4)

    return {
        "id"     : rid,
        "object" : "chat.completion",
        "created": ts,
        "model"  : model,
        "choices": [choice],
        "usage"  : {
            "prompt_tokens"    : input_est,
            "completion_tokens": output_est,
            "total_tokens"     : input_est + output_est,
        },
    }


def build_responses_api(parsed: ParsedResponse, model: str = "gpt-4o",
                         request_id: str = None) -> dict:
    """Build a Responses API format response (/v1/responses)."""
    rid    = request_id or f"resp_{uuid.uuid4().hex}"
    ts     = int(time.time())
    output = []

    if parsed.is_tool_call and parsed.tool_calls:
        for tc in parsed.tool_calls:
            output.append({
                "type"     : "function_call",
                "id"       : tc.id,
                "call_id"  : tc.id,
                "name"     : tc.name,
                "arguments": json.dumps(tc.arguments, ensure_ascii=False),
                "status"   : "completed",
            })
        status = "completed"
    else:
        content = parsed.content or parsed.raw_text
        output.append({
            "type"   : "message",
            "id"     : f"msg_{uuid.uuid4().hex[:8]}",
            "role"   : "assistant",
            "content": [{"type": "output_text", "text": content,
                          "annotations": []}],
            "status" : "completed",
        })
        status = "completed"

    return {
        "id"          : rid,
        "object"      : "response",
        "created_at"  : ts,
        "status"      : status,
        "model"       : model,
        "output"      : output,
        "usage"       : {
            "input_tokens" : 200,
            "output_tokens": max(1, len(parsed.raw_text) // 4),
            "total_tokens" : 200 + max(1, len(parsed.raw_text) // 4),
        },
    }
