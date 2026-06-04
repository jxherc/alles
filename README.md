# aide

self-hosted personal AI workspace. runs on your machine, talks to whatever model you want.

---

## features

**chat**
- streaming chat with any OpenAI-compatible API or Ollama — responses show up word by word as they come in, not all at once
- DeepSeek set up automatically if you drop in a `DEEPSEEK_API_KEY`
- works with Anthropic, OpenRouter, Groq, Ollama — aide figures out which one from the URL/key
- chat history saved automatically; sessions get auto-named and can be starred or archived
- thinking blocks — when you use DeepSeek R1 or Claude extended thinking, you can see the model's reasoning before the answer

**artifacts**
- if the AI writes HTML, SVG, or code, it shows up rendered in a side panel instead of just as text
- HTML/SVG runs in a sandboxed iframe (can't mess with the rest of the page), code gets syntax highlighting

**file uploads**
- drag a file into the chat or use the attach button
- images get sent to the AI as vision context (it can actually see them)
- text/code files get pasted in as context so the AI can read them
- 20MB limit

**projects**
- group your chats into named folders so you can keep different topics separate
- each project can have a shared system prompt — basically standing instructions that get added to every chat in that folder automatically

**message editing**
- click any of your messages to edit and resend it — rewrites the conversation from that point
- regenerate button on AI replies if you don't like what it said

**inline code execution**
- run button appears on Python, JS, and HTML code blocks in chat
- Python runs via your local shell and shows the output right there
- HTML/JS renders in a sandboxed iframe below the block

**research**
- does multiple rounds of web searches and uses the AI to reason over what it finds
- uses Tavily API if you have a key, falls back to DuckDuckGo if not
- streams what it's finding in real time, then produces a full markdown report

**memory**
- aide can remember things across conversations — stores them with semantic search so it can find relevant ones later
- uses fastembed (runs locally, no API) for the semantic part; falls back to keyword search if that's not set up
- you can extract memories from past chats or add them manually with `/remember`

**documents**
- write and store markdown/text files inside aide with a live preview
- "AI-edit" button: type an instruction and it rewrites the document for you, streamed

**model compare**
- send the same message to 2–4 models at the same time
- see their answers side by side as they stream in — useful for seeing which model handles something better

**voice**
- talk to it: uses Whisper API or your browser's built-in speech recognition
- it can talk back: OpenAI TTS or your browser's built-in text-to-speech

**global search**
- Cmd/Ctrl+K to search across everything — all chats, notes, and memories at once

**shell + MCP**
- run shell commands directly from the chat
- connect MCP (Model Context Protocol) servers to give the AI access to external tools

**vault**
- encrypted secret storage (AES-256-GCM) — think password manager built into aide
- protected by a master password; the key is never written to disk

**auth**
- optional login gate so not just anyone can open it if you expose it on a network
- password is bcrypt-hashed; sessions use httponly cookies

**OpenAI-compatible API**
- aide exposes `/v1/models` and `/v1/chat/completions`
- point any app or script that talks to OpenAI at `http://localhost:PORT/v1` and it'll work

**extras**
- notes, tasks, calendar, gallery, contacts — basic productivity stuff built in
- cookbook: save reusable prompt templates
- personas: named AI identities with their own system prompts (switch mid-session)
- webhooks, API tokens
- backup/restore — export everything as a ZIP, import it back
- incognito sessions — nothing gets saved, like private browsing for chats
- light/dark theme

---

## quick start

```
git clone https://github.com/jxherc/aide.git
cd aide
pip install -r requirements.txt
cp .env.example .env        # add your DEEPSEEK_API_KEY
aide start                  # or: python app.py
```

then open http://localhost:8000

> `aide start` requires the project directory on your PATH. if you haven't done that yet, just use `python app.py` or `python cli.py start`.

---

## cli

```
aide start      start server in background
aide stop       stop server
aide restart    restart server
aide status     show running/stopped + url
aide logs       tail server log
aide open       open browser
```

windows: use `aide.cmd` — add the project folder to PATH.  
unix/git bash: use `./aide` — already chmod +x.

---

## slash commands

type these in the chat input:

| command | what it does |
|---|---|
| `/new` | start a new chat |
| `/clear` | clear the chat display (doesn't delete history) |
| `/rename [name]` | rename the chat — leave blank and the AI picks a name |
| `/archive` | archive this chat |
| `/export` | download the chat as a markdown file |
| `/incognito` | start a chat that doesn't save anything |
| `/model` | open the model picker |
| `/persona [name]` | switch to a different persona |
| `/research` | toggle research mode on/off |
| `/agent` | toggle agent mode on/off |
| `/remember <text>` | save something to memory |
| `/memories` | open the memory panel |
| `/forget <id>` | delete a memory by its id |
| `/todo <task>` | add a task |
| `/note <text>` | create a note |
| `/vault` | open the encrypted vault |
| `/compare` | open model compare view |
| `/docs` | open the document editor |
| `/contacts` | open contacts |
| `/search [query]` | open global search |
| `/system <prompt>` | update the system prompt for this chat |
| `/backup` | download a backup zip of everything |
| `/compact` | info about context compaction |
| `/help` | list all commands in chat |

custom slash commands can be added via settings → cookbook.

---

## configuration

copy `.env.example` to `.env` and fill in what you need:

| var | default | what it's for |
|---|---|---|
| `DEEPSEEK_API_KEY` | — | auto-sets up a DeepSeek endpoint on first boot |
| `ANTHROPIC_API_KEY` | — | auto-sets up an Anthropic endpoint on first boot |
| `PORT` | `8000` | what port to run on |
| `SECRET_KEY` | `dev-secret` | used to sign sessions — change this if you expose aide on a network |
| `AUTH_ENABLED` | `false` | set to `true` to require a password to open aide |
| `AUTH_PASSWORD` | — | the password (gets bcrypt-hashed automatically on first boot) |
| `TAVILY_API_KEY` | — | web search for research mode — uses DuckDuckGo if you skip this |

to add Ollama, OpenAI, OpenRouter, etc.: settings → add endpoint.

---

## stack

```
Python 3.11 + FastAPI + SQLite (SQLAlchemy ORM)
vanilla JS ES modules — no bundler, no framework
fastembed (ONNX) for local embeddings
httpx for async LLM streaming
```

all data lives in `data/` — one SQLite file, uploads, settings, everything.

---

## acknowledgments

aide was inspired by [odysseus](https://github.com/pewdiepie-archdaemon/odysseus)
by pewdiepie-archdaemon — the feature set, product vision, and architecture
patterns all originate there. aide is an independent reimplementation written
from scratch. see [ACKNOWLEDGMENTS.md](./ACKNOWLEDGMENTS.md) for full credit.
