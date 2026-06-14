"""
action-intent detection (ported from opencode/odysseus).

conservative regexes that flag when a plain chat message is actually asking the
assistant to DO something (add a calendar event, send mail, run a command, do
research) vs just asking how a feature works. used to optionally auto-promote a
chat turn into agent mode. intentionally err toward NOT promoting.
"""
import re

_ACTION_Q = r"\b(?:can|could|would|will)\s+you\s+"
_PLEASE = r"^\s*(?:please\s+)?"

_CAL_ACTION = r"(?:add|create|schedule|book|put|set\s+up|make)"
_CAL_THING = r"(?:calendar|event|meeting|appointment|entry|call)"
_PANEL = (r"(?:calendar|notes?|inbox|email|mail|documents?|docs|files?|photos?|gallery|"
          r"settings|cookbook|sessions?|chats?|skills|memories|memory|tasks?|secrets?)")

_PATTERNS = tuple(re.compile(p, re.I) for p in (
    # calendar / events
    rf"{_ACTION_Q}{_CAL_ACTION}\b.{{0,120}}\b{_CAL_THING}\b",
    rf"{_PLEASE}{_CAL_ACTION}\b.{{0,120}}\b(?:to|on|in|into|for)\s+(?:my\s+|the\s+|this\s+)?calendar\b",
    rf"{_PLEASE}{_CAL_ACTION}\s+(?:a\s+|an\s+)?(?:calendar\s+)?(?:event|meeting|appointment|entry|item|call)\b",
    r"\bput\s+.+\bon\s+(?:my\s+)?calendar\b",
    # notes / tasks / reminders
    r"\bremind\s+me\b",
    rf"{_ACTION_Q}(?:add|create|make|take|jot|write\s+down|set)\b.{{0,120}}\b(?:note|todo|task|checklist|reminder)\b",
    rf"{_PLEASE}(?:add|create|make)\s+(?:a\s+|an\s+)?(?:todo|task|reminder|note|checklist)\b",
    rf"{_PLEASE}(?:take|jot|write\s+down)\s+(?:a\s+|an\s+)?note\b",
    rf"{_PLEASE}(?:add|jot|write\s+down)\b.{{0,120}}\b(?:to|in|into)\s+(?:my\s+|the\s+)?(?:todo(?:\s+list)?|task\s+list|notes?|checklist)\b",
    rf"{_PLEASE}set\s+(?:a\s+)?reminder\b",
    rf"{_ACTION_Q}set\s+(?:a\s+)?reminder\b",
    # email
    rf"{_ACTION_Q}(?:send|write|reply|email|message|archive|delete|mark)\b.{{0,120}}\b(?:emails?|mail|messages?|inbox|unread|read)\b",
    rf"{_PLEASE}(?:send|write|reply)\b.{{0,120}}\b(?:emails?|mail|messages?)\b",
    r"\b(?:send|write|reply)\s+(?:an?\s+)?(?:email|message|mail)\b",
    r"\bcheck\s+(?:my\s+)?(?:email|inbox|mail)\b",
    # read-y questions about your stuff — aide should go look, not guess
    r"\bwhat(?:'?s| is| are| do i have| have i got)\b.{0,40}\b(?:on|in)\s+(?:my\s+|the\s+)?(?:calendar|schedule|agenda|inbox)\b",
    r"\b(?:check|look at|pull up|show me|see)\b.{0,25}\b(?:my\s+|the\s+)?(?:calendar|schedule|agenda|inbox|email|mail|tasks?|to-?dos?|reminders?)\b",
    r"\bwhat(?:'?s| is| are)\b.{0,40}\b(?:on\s+)?(?:my\s+)?(?:calendar|schedule|agenda)\b",
    r"\b(?:do\s+i\s+have|have\s+i\s+got|any|got|anything)\b.{0,30}\b(?:meetings?|events?|appointments?|on\s+(?:my\s+)?(?:calendar|schedule|plate|agenda))\b",
    r"\bwhat(?:'?s| is| do i have)\b.{0,30}\b(?:in\s+)?(?:my\s+)?inbox\b",
    r"\bany\s+(?:new\s+|unread\s+)*(?:emails?|mail|messages?)\b",
    r"\bwhat(?:'?s| are| do i have| have i got)\b.{0,30}\b(?:my\s+)?(?:tasks?|to-?dos?|reminders?)\b",
    r"\b(?:do\s+i\s+have|any|got|anything)\b.{0,20}\b(?:tasks?|to-?dos?|reminders?)\b",
    r"\bwhat(?:'?s| do i have| have i got)\b.{0,30}\b(?:going\s+on|happening|planned|coming\s+up)\b",
    # open a panel / flip a toggle
    rf"{_PLEASE}(?:open|show|bring\s+up)\s+(?:me\s+)?(?:my\s+|the\s+)?{_PANEL}\b",
    r"\b(?:disable|enable|turn\s+(?:on|off))\s+(?:the\s+)?(?:shell|search|web|browser|documents?|memory|skills|images?|calendar|email|mail|research|incognito)\b",
    # research jobs
    rf"{_PLEASE}(?:research|deep\s+dive|look\s+into|investigate)\s+.+",
    rf"{_ACTION_Q}(?:research|do\s+research|deep\s+dive|look\s+into|investigate)\s+.+",
    # shell / files — imperative position only, so "what does grep do?" doesn't trip it
    r"\bssh\s+(?:in)?to\b",
    r"\b(?:run|execute)\s+.{1,40}\bon\s+\w+",
    rf"{_ACTION_Q}(?:run|execute|exec)\b",
    rf"{_PLEASE}(?:deploy|build|install|restart|reboot|kill|tail|grep|cat|ls|rm|cp|mv|git|npm|pip|python)\b\s+\S+",
    rf"{_ACTION_Q}(?:deploy|build|install|restart|reboot|kill|tail|grep|cat|ls|rm|cp|mv|git)\b\s+\S+",
    r"\b(?:check|see)\s+(?:if|whether|what)\s+.{1,40}\b(?:running|process|service|port|file|exists?)\b",
    # build-tool commands anywhere in the message ("run npm install", "pip install x")
    r"\b(?:npm|pnpm|yarn|pip|pip3|cargo|go|pytest|docker|make|poetry|uv)\s+(?:install|run|build|test|start|add|i|exec|up|compose)\b",
    # code editing
    rf"{_PLEASE}(?:fix|refactor|implement|add|change|update|edit|rename|delete)\b.{{0,80}}\b(?:file|function|class|bug|code|test|method)\b",
))


def message_needs_tools(text: str) -> bool:
    """True when a plain chat message is really asking the agent to act."""
    if not text:
        return False
    return any(p.search(text) for p in _PATTERNS)
