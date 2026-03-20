"""
prompt/builder.py — Awrass Prompt Builder
==========================================
Improvements over mse_ai_api:
  ✅ Cleaner separation of system / conversation / tool blocks
  ✅ Better multi-turn conversation history rendering
  ✅ Arabic-aware prompt injection
  ✅ Strict JSON schema injection for tool calls
  ✅ Image content extraction (vision)
  ✅ Character-limit trimming with smart truncation

Author: github.com/swordenkisk/awrass
"""

import json
from typing import Any, Optional


MAX_PROMPT_CHARS = 24_000   # safety limit to avoid ChatGPT cutoffs


def extract_text(content: Any) -> str:
    """Extract plain text from a message content (str or list)."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict):
                # OpenAI content parts
                t = item.get("type", "")
                if t == "text":
                    parts.append(item.get("text", ""))
                elif t == "image_url":
                    url = item.get("image_url", {}).get("url", "")
                    parts.append(f"[Image: {url[:80]}...]")
                else:
                    parts.append(item.get("text", item.get("content", str(item))))
            else:
                parts.append(str(item))
        return "\n".join(filter(None, parts))
    return str(content) if content else ""


def build_prompt(messages: list, tools: list = None,
                 arabic_mode: bool = False) -> str:
    """
    Build the final prompt string to inject into ChatGPT.

    Parameters
    ----------
    messages    : OpenAI-format message list
    tools       : OpenAI-format tool definitions (optional)
    arabic_mode : If True, inject Arabic response instruction
    """
    system_parts   : list[str] = []
    conversation   : list[str] = []
    tool_results   : list[str] = []
    has_tool_results = False
    last_user_msg    = ""

    for msg in messages:
        role     = msg.get("role", "")
        mtype    = msg.get("type", "")
        content  = extract_text(msg.get("content", ""))

        # ── System ────────────────────────────────────────────
        if role == "system":
            system_parts.append(content)

        # ── Tool result ────────────────────────────────────────
        elif role == "tool":
            has_tool_results = True
            name = msg.get("name", "tool")
            tool_results.append(f"[نتيجة الأداة / Tool Result — '{name}']:\n{content}")

        elif mtype == "function_call_output":
            has_tool_results = True
            call_id = msg.get("call_id", "")
            output  = msg.get("output", content)
            tool_results.append(f"[Tool Result (call_id: {call_id})]:\n{output}")

        # ── Previous tool call ─────────────────────────────────
        elif mtype == "function_call":
            name = msg.get("name", "?")
            args = msg.get("arguments", "{}")
            conversation.append(f"[Previous tool call: '{name}' with {args}]")

        # ── Assistant ──────────────────────────────────────────
        elif role == "assistant":
            text  = content or ""
            tcall = msg.get("tool_calls", [])
            if tcall:
                tc_descs = "; ".join(
                    f"Called '{tc.get('function',{}).get('name','?')}' "
                    f"with {tc.get('function',{}).get('arguments','{}')}"
                    for tc in tcall
                )
                text += f"\n[Tool calls made: {tc_descs}]"
            if text.strip():
                conversation.append(f"[Assistant]: {text.strip()}")

        # ── User ───────────────────────────────────────────────
        elif role == "user" or (mtype == "message" and role != "system"):
            last_user_msg = content
            has_tool_results = False
            tool_results.clear()
            if content.strip():
                conversation.append(f"[User]: {content.strip()}")

        elif content.strip():
            conversation.append(content.strip())

    # ── Assemble ───────────────────────────────────────────────
    sections: list[str] = []

    # System block
    if system_parts:
        header = "=== دورك / YOUR ROLE ===" if not tools or has_tool_results else "=== تعليمات النظام / SYSTEM ==="
        sections.append(f"{header}\n" + "\n\n".join(system_parts) + "\n=== نهاية التعليمات / END ===")

    # Arabic mode instruction
    if arabic_mode:
        sections.append("⚠ يجب أن تكون إجابتك باللغة العربية إذا كان السؤال بالعربية.\n"
                        "⚠ If the question is in Arabic, reply in Arabic.")

    # Tool injection (only if we have tools and no results yet)
    if tools and not has_tool_results:
        sections.append(_build_tools_block(tools, last_user_msg))

    # Conversation history
    if conversation:
        sections.append("=== المحادثة / CONVERSATION ===\n" + "\n\n".join(conversation))

    # Tool results
    if tool_results:
        sections.append(
            "=== نتائج الأدوات / TOOL RESULTS ===\n"
            "استخدم هذه المعلومات فقط للإجابة. / Use ONLY this information to answer.\n\n"
            + "\n\n".join(tool_results)
            + "\n\n=== التعليمة / INSTRUCTION ===\n"
            "أجب الآن بناءً على النتائج أعلاه فقط. / Answer now based ONLY on the tool results above."
        )

    full = "\n\n".join(sections)

    # Truncate if too long
    if len(full) > MAX_PROMPT_CHARS:
        full = full[:MAX_PROMPT_CHARS] + "\n\n[... تم اقتصار النص / Content truncated ...]"

    return full


def _build_tools_block(tools: list, user_question: str = "") -> str:
    """Build the strict JSON tool-call instruction block."""
    lines = [
        "=== استخدام الأدوات الإلزامي / MANDATORY TOOL USAGE ===",
        "يجب عليك استخدام أحد الأدوات أدناه. / You MUST use one of the tools below.",
        "لا تجب مباشرة. / Do NOT answer directly.",
        "ردّك يجب أن يكون JSON فقط بالتنسيق التالي / Your ENTIRE response must be ONLY this JSON:",
        "",
        '{"tool_calls": [{"name": "TOOL_NAME", "arguments": {"param": "value"}}]}',
        "",
        "القواعد / RULES:",
        "- JSON صالح فقط / Only valid JSON",
        "- بدون نص إضافي / No extra text",
        "- بدون markdown أو تفسير / No markdown or explanation",
        "",
        "الأدوات المتاحة / Available Tools:",
        "",
    ]

    first_tool_name = ""
    for tool in tools:
        fn   = tool.get("function", tool)
        name = fn.get("name", "unknown")
        desc = fn.get("description", "")
        params = fn.get("parameters", {})
        if not first_tool_name:
            first_tool_name = name

        lines.append(f"🔧 {name}")
        lines.append(f"   {desc}")
        props = params.get("properties", {})
        req   = params.get("required", [])
        if props:
            lines.append("   Parameters:")
            for pname, pinfo in props.items():
                ptype = pinfo.get("type", "string")
                pdesc = pinfo.get("description", "")
                status = "required" if pname in req else "optional"
                lines.append(f"     - {pname} ({ptype}, {status}): {pdesc}")
        lines.append("")

    if first_tool_name:
        example_q = user_question[:60].replace('"', "'") or "the user question"
        lines.append("مثال / Example:")
        lines.append(
            '{"tool_calls": [{"name": "'
            + first_tool_name
            + '", "arguments": {"input": "'
            + example_q
            + '"}}]}'
        )
        lines.append("")

    lines.append("=== ردّ الآن بـ JSON / RESPOND NOW WITH JSON ===")
    return "\n".join(lines)
