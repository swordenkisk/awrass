"""
test_awrass.py — Awrass Test Suite (20 tests)
Run: python tests/test_awrass.py
"""
import sys, json, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.prompt.builder  import build_prompt, extract_text
from src.parser.response import (
    parse_response, build_openai_response, build_responses_api,
    ParsedToolCall, ParsedResponse
)
from src.auth.middleware import (
    validate_bearer, check_rate_limit, log_request, get_stats, ALL_KEYS
)

W = 64
passed = failed = 0
results = []

def check(name, cond, detail=""):
    global passed, failed
    msg = f"  [{'PASS' if cond else 'FAIL'}] {name}"
    if detail: msg += f"  --  {detail}"
    print(msg)
    results.append((name, cond))
    if cond: passed += 1
    else:    failed += 1

print("=" * W)
print("  أوراس — Awrass — Test Suite (20 tests)")
print("=" * W)

# ── Block A: Prompt Builder ───────────────────────────────
print("\n[ Block A: Prompt Builder (5 tests) ]\n")

msgs1 = [{"role":"system","content":"You are helpful"},
         {"role":"user","content":"Hello"}]
p1 = build_prompt(msgs1)
check("A1: basic prompt contains system and user content",
      "helpful" in p1 and "Hello" in p1, f"len={len(p1)}")

msgs2 = [{"role":"user","content":"What is 2+2?"}]
tools = [{"function":{"name":"calculator","description":"Calc math",
           "parameters":{"type":"object","properties":{"expr":{"type":"string","description":"expression"}},"required":["expr"]}}}]
p2 = build_prompt(msgs2, tools)
check("A2: tool injection contains tool name and JSON format",
      "calculator" in p2 and "tool_calls" in p2, f"has_calc={'calculator' in p2}")

check("A3: extract_text handles string content",
      extract_text("hello world") == "hello world")

check("A4: extract_text handles list content",
      "part1" in extract_text([{"type":"text","text":"part1"},{"type":"text","text":"part2"}]))

msgs3 = [{"role":"user","content":"سؤال عربي"}]
p3 = build_prompt(msgs3, arabic_mode=True)
check("A5: arabic_mode adds Arabic instruction",
      "العربية" in p3 or "Arabic" in p3, f"arabic_in={'العربية' in p3}")

# ── Block B: Response Parser ──────────────────────────────
print("\n[ Block B: Response Parser (7 tests) ]\n")

# Plain text
r1 = parse_response("Hello, I can help you!")
check("B1: plain text → not tool call",
      not r1.is_tool_call, f"is_tool={r1.is_tool_call}")
check("B2: plain text content preserved",
      "Hello" in r1.content, f"content={r1.content[:30]}")

# Tool call — format 1
tc_json = '{"tool_calls": [{"name": "calculator", "arguments": {"expr": "2+2"}}]}'
r2 = parse_response(tc_json)
check("B3: tool call JSON detected",
      r2.is_tool_call, f"is_tool={r2.is_tool_call}")
check("B4: tool name extracted correctly",
      r2.tool_calls and r2.tool_calls[0].name == "calculator",
      f"name={r2.tool_calls[0].name if r2.tool_calls else None}")

# Tool call wrapped in markdown
tc_md = '```json\n{"tool_calls": [{"name": "search", "arguments": {"q": "test"}}]}\n```'
r3 = parse_response(tc_md)
check("B5: tool call inside markdown fence detected",
      r3.is_tool_call and r3.tool_calls[0].name == "search",
      f"name={r3.tool_calls[0].name if r3.tool_calls else None}")

# Build OpenAI response
plain = ParsedResponse(raw_text="Test answer", is_tool_call=False, content="Test answer")
oa = build_openai_response(plain, model="gpt-4o-mini")
check("B6: openai response has required fields",
      all(k in oa for k in ["id","object","choices","usage"]),
      f"keys={list(oa.keys())}")
check("B7: openai response finish_reason=stop for plain text",
      oa["choices"][0]["finish_reason"] == "stop")

# ── Block C: Auth & Rate Limiting ────────────────────────
print("\n[ Block C: Auth & Rate Limiting (5 tests) ]\n")

valid, key = validate_bearer("Bearer awrass-secret-2026")
check("C1: valid key accepted", valid, f"key_suffix={key[-6:]}")

invalid, msg = validate_bearer("Bearer wrong-key-xyz")
check("C2: invalid key rejected", not invalid, f"msg={msg}")

no_auth, msg2 = validate_bearer(None)
check("C3: missing auth rejected", not no_auth, f"msg={msg2}")

bad_format, msg3 = validate_bearer("Token awrass-secret-2026")
check("C4: wrong format rejected", not bad_format, f"msg={msg3}")

# Rate limit (should allow first request)
allowed, remaining = check_rate_limit("awrass-secret-2026")
check("C5: first request within rate limit",
      allowed, f"remaining={remaining}")

# ── Block D: Responses API format ────────────────────────
print("\n[ Block D: Responses API Format (3 tests) ]\n")

tc_parsed = ParsedResponse(
    raw_text="{}",
    is_tool_call=True,
    tool_calls=[ParsedToolCall(id="call_abc", name="search", arguments={"q":"test"})],
)
ra = build_responses_api(tc_parsed, model="gpt-4o")
check("D1: responses API has output field",   "output" in ra, f"keys={list(ra.keys())}")
check("D2: output is function_call type",
      ra["output"][0]["type"] == "function_call",
      f"type={ra['output'][0]['type']}")
check("D3: tool name preserved in responses API",
      ra["output"][0]["name"] == "search",
      f"name={ra['output'][0].get('name')}")

# ── Summary ───────────────────────────────────────────────
total = passed + failed
print()
print("=" * W)
status = "ALL PASS ✅" if failed == 0 else f"{failed} FAILED ❌"
print(f"  Results  :  {passed}/{total} tests passed  ({status})")
if failed:
    print("  Failures :  " + ", ".join(n for n,ok in results if not ok))
print("=" * W)

import sys as _s; _s.exit(0 if failed == 0 else 1)
