# aide

a self-hosted personal AI assistant. your own chatbot, running locally.

## quick start

```bash
# 1. install deps
pip install -r requirements.txt

# 2. configure
cp .env.example .env
# edit .env and add your DEEPSEEK_API_KEY

# 3. run
python app.py
# open http://localhost:8000
```

## features (phase 1)
- streaming chat with any OpenAI-compatible API, DeepSeek, Ollama, or Anthropic
- persistent sessions with history
- model/endpoint management — add as many providers as you want
- thinking block support (DeepSeek R1, Claude extended thinking, Qwen3, etc.)
- light/dark theme

## coming next
- memory + semantic search (phase 2)
- deep research mode (phase 3)
- shell + MCP server support (phase 4)

## providers

works with anything OpenAI-compatible. tested with:
- DeepSeek (default)
- Ollama (local)
- OpenAI
- Anthropic
- OpenRouter

add endpoints via the model picker → **+ add endpoint**.

---

*inspired by [Odysseus](https://github.com/pewdiepie-archdaemon/odysseus) — see [ACKNOWLEDGMENTS.md](./ACKNOWLEDGMENTS.md)*
