# product

## what Alles is

Alles is a self-hosted, single-user personal system. It combines daily planning, knowledge, files, communication, finance, health, server tools, AI assistance, and current web search without making a remote cloud service the owner of the user's data.

The shipped product contract lives in `specifications.md`. Afterlife plans describe future or in-progress behavior and must not be presented as shipped.

## primary user

The owner uses Alles often, usually alone, on a laptop and phone. They need fast scanning, direct actions, plain language, reliable local behavior, and enough advanced control without constant setup or crowded navigation.

## core jobs

- see what needs attention now;
- ask Aide for an answer or real work in one continuing task;
- search the current web through Andromeda and inspect normal results;
- plan events, tasks, reminders, and habits;
- read and edit owned Markdown knowledge;
- manage approved local and online files safely;
- use specialist apps without relearning the shell;
- understand permissions, failures, offline state, and data location.

## primary spaces

- **Home** coordinates the day.
- **Aide** chats and uses approved tools in one automatic assistant experience.
- **Andromeda** gives a grounded overview and normal web results.
- **Apps** opens specialist tools.

Specialist destinations include Plan, Docs, Files, Finance, Inbox, Library, Health, Passwords, and Server. Compatibility routes may keep older app names while migrations are proven.

## experience goals

- calm, compact, and readable rather than sparse or tiny;
- one shared interaction grammar across apps;
- AI-first where useful, never AI-required for core local tools;
- local-first and private by default;
- visible state and recoverable errors;
- short paths with advanced controls available in context;
- keyboard, zoom, mobile, light theme, dark theme, and reduced motion treated as normal use.

## product constraints

- FastAPI, SQLite/SQLAlchemy, vanilla JavaScript, and plain CSS remain;
- no frontend framework migration or build step;
- no remote font, image, or cloud dependency is required;
- no visible browser- or OS-native choice controls;
- owner data, credentials, vaults, databases, and normal `ALLES_DATA` never become test fixtures;
- a material app rework needs its own standalone KOKUEN HTML starter and explicit approval;
- specialist behavior and compatibility routes survive visual migration.

## success

A screen succeeds when the owner can understand its state at a glance, complete the main task, recover from realistic failures, and move to another Alles app without learning a new visual language.
