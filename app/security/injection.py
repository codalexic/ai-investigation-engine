import re

PATTERNS = {
    "override": (
        r"(?i)(?:ignore|disregard)\s+(?:all\s+)?"
        r"(?:previous|above|prior|the)\s+instructions[^\n.]*"
    ),
    "role": (
        r"(?i)(?:you are now|act as|new instructions|system\s*(?:prompt|message)|"
        r"<\|(?:system|assistant)\|>)[^\n.]*"
    ),
    "exfiltration": r"(?i)(?:reveal|exfiltrate|send (?:the|your) secret)[^\n.]*",
    "tool": r'(?i)(?:<tool_call>|"tool_calls"|function_call)[^\n]*',
    "link": r"(?i)\[[^\]]*\]\(https?://[^)]*(?:secret|prompt|token|exfil)[^)]*\)",
    "multilingual": (
        r"(?i)(?:ignora (?:las )?instrucciones|ignorez les instructions|"
        r"\u0438\u0433\u043d\u043e\u0440\u0438\u0440\u0443\u0439|"
        r"\u5ffd\u7565\u4e4b\u524d)[^\n.]*"
    ),
    "encoded": r"(?<![A-Za-z0-9+/])[A-Za-z0-9+/]{201,}={0,2}",
}


def scan(text: str) -> list[str]:
    return [name for name, pattern in PATTERNS.items() if re.search(pattern, text)]


def sanitize_evidence(text: str) -> tuple[str, list[str]]:
    flags = scan(text)
    for name in flags:
        text = re.sub(PATTERNS[name], "[flagged instruction-like text removed]", text)
    return text.replace("</evidence>", "&lt;/evidence&gt;"), flags
