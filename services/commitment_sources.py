"""Bounded source references for reviewed tasks and calendar events."""

import hashlib
import json
from html.parser import HTMLParser
from typing import Literal

from fastapi import HTTPException
from pydantic import (
    BaseModel,
    Field,
    TypeAdapter,
    ValidationError,
    field_validator,
    model_validator,
)

from core.database import MailAccount


class MailSource(BaseModel):
    kind: Literal["mail"] = "mail"
    account_id: str = Field(min_length=1, max_length=128)
    folder: str = Field(default="INBOX", min_length=1, max_length=1024)
    uid: str = Field(pattern=r"^[0-9]{1,20}$")
    message_id: str = Field(default="", max_length=1000)
    label: str = Field(default="", max_length=500)
    excerpt: str = Field(default="", max_length=6000)
    fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("folder", "account_id")
    @classmethod
    def no_control_characters(cls, value):
        if any(char in value for char in "\r\n\0"):
            raise ValueError("invalid source reference")
        return value


class MailOrigin(BaseModel):
    account_id: str = Field(min_length=1, max_length=128)
    folder: str = Field(default="INBOX", min_length=1, max_length=1024)
    uid: str = Field(pattern=r"^[0-9]{1,20}$")
    message_id: str = Field(default="", max_length=1000)
    sender: str = Field(default="", alias="from", max_length=10000)
    to: str = Field(default="", max_length=10000)
    subject: str = Field(default="", max_length=10000)
    date: str = Field(default="", max_length=1000)
    text: str = Field(default="", max_length=1000000)
    html: str = Field(default="", max_length=1000000)

    @field_validator("folder", "account_id")
    @classmethod
    def no_control_characters(cls, value):
        return MailSource.no_control_characters(value)


class CaptureSource(BaseModel):
    kind: Literal["capture"] = "capture"
    label: Literal["original capture"] = "original capture"
    excerpt: str = Field(min_length=1, max_length=6000)
    fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def matching_text(self):
        if hashlib.sha256(self.excerpt.encode()).hexdigest() != self.fingerprint:
            raise ValueError("capture source does not match its fingerprint")
        return self


CommitmentSource = MailSource | CaptureSource
_SOURCE = TypeAdapter(CommitmentSource)


def capture_source(text: str) -> dict:
    return CaptureSource(
        excerpt=text, fingerprint=hashlib.sha256(text.encode()).hexdigest()
    ).model_dump()


def mail_fingerprint(message: dict) -> str:
    # Hash the full source, not the model's bounded excerpt or an editable proposal.
    fields = {
        name: str(message.get(name) or "")
        for name in ("message_id", "from", "to", "subject", "date", "text", "html")
    }
    encoded = json.dumps(fields, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(encoded.encode()).hexdigest()


class _MailText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.hidden = None
        self.hidden_depth = 0

    def handle_starttag(self, tag, attrs):
        if self.hidden:
            if tag == self.hidden:
                self.hidden_depth += 1
            return
        # The head end tag may be omitted; suppress its text-bearing elements,
        # not the container, so visible body text never depends on </head>.
        if tag in {"title", "script", "style", "template"}:
            self.hidden = tag
            self.hidden_depth = 1
        elif tag in {"br", "p", "div", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6"}:
            self.parts.append("\n")
        elif tag in {"td", "th"}:
            self.parts.append(" ")
        elif tag == "img":
            self.parts.append(dict(attrs).get("alt") or "")

    def handle_endtag(self, tag):
        if self.hidden:
            if tag == self.hidden:
                self.hidden_depth -= 1
                if not self.hidden_depth:
                    self.hidden = None
        elif tag in {"p", "div", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6"}:
            self.parts.append("\n")

    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)


def mail_source_text(origin: MailOrigin) -> str:
    if origin.text.strip():
        return origin.text
    parser = _MailText()
    parser.feed(origin.html)
    parser.close()
    lines = (" ".join(line.split()) for line in "".join(parser.parts).splitlines())
    return "\n".join(line for line in lines if line)


def preview_mail_source(db, origin: MailOrigin | None) -> dict | None:
    if origin is None:
        return None
    if db.get(MailAccount, origin.account_id) is None:
        raise HTTPException(404, "source account is no longer available")
    message = origin.model_dump(by_alias=True)
    source = MailSource(
        account_id=origin.account_id,
        folder=origin.folder,
        uid=origin.uid,
        message_id=origin.message_id,
        label=origin.subject[:500],
        excerpt=mail_source_text(origin)[:6000],
        fingerprint=mail_fingerprint(message),
    )
    return source.model_dump()


def source_dict(value: str) -> dict | None:
    if not value or value == "{}":
        return None
    try:
        return _SOURCE.validate_python(json.loads(value)).model_dump()
    except (ValueError, TypeError, ValidationError):
        return None


def source_json(source: CommitmentSource | dict | None) -> str:
    if source is None:
        return "{}"
    value = _SOURCE.validate_python(source)
    return json.dumps(value.model_dump(), ensure_ascii=False, separators=(",", ":"))
