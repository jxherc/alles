# Decision — Aide has one mode

- **Status:** accepted
- **Accepted:** July 13, 2026
- **Replaces:** Chat/Agent switches, Chat/Jarvis switches, Answer only mode, and Jarvis as an in-app runtime name

## The simple rule

**Aide is one assistant.** It can answer normally, use tools, ask questions, make plans, and keep longer
work running in the background. The owner should not have to choose what kind of assistant it is before
asking for help.

## Aide behavior

- Aide always has its tool ability available.
- A simple question can receive a simple text answer without starting unnecessary work.
- A task can use approved tools automatically when they are useful.
- Anything that changes data, sends something, spends money, or affects an outside system still follows
  the permission and approval rules.
- Long work can move into a durable background Aide run without changing product, mode, Project, thread,
  attachments, or model context.
- Research is not a mode or permanent button. When Aide detects that deeper research would help, it asks
  the owner first and, if approved, continues the research inside the same task.
- Background progress, questions, approvals, errors, recovery, and the final result stay inside the same
  Aide conversation.
- Aide is a general personal assistant. Coding is one capability, not its identity.

## What is removed

- no Chat/Agent selector;
- no Chat/Jarvis selector;
- no Answer only mode;
- no default Chat-versus-Agent setting;
- no Jarvis app, Aide sub-mode, task mode, runtime label, model role, or handoff button;
- no separate user-visible deep-research runtime name.
- no Compare destination or action;
- no Ask Docs or manual Research control;
- no Cookbook tool in the task interface. Cookbook moves under **Settings → AI and models**.

Settings can still control permissions, allowed tools, approved folders, model choice, memory, effort,
and background limits. These are safety and resource controls, not assistant modes.

## Interface shape

Aide uses a compact KOKUEN assistant canvas. Codex is a reference for task organization and control
placement, not a source for copied colors, proportions, or coding-only chrome.

- The task sidebar is open by default on desktop and collapses through a split-sidebar icon. On mobile
  it is a closed-by-default overlay. **Tasks** lists loose conversations directly; **Projects** lists
  folder-backed Projects and their tasks. General is not shown as a category, label, or Project.
  **New task**, **scheduled** (including recurring automations), **Brain**, **Skills**, and **Reminders**
  share one primary navigation group. The capability rows use one restrained matching icon each and have
  no separate Tools heading. Background checks live in Settings instead of a separate Proactive page.
  Tasks and Projects use stronger headings and clear group spacing than their conversation rows.
  Settings remains easy to reach. Connections stay under the composer's `+` menu.
- Search is one quiet icon until activated. It then grows a transform-only field leftward across the
  Aide wordmark, and Escape closes it without shifting or repainting the workspace. The sidebar footer
  keeps text-only **Settings** at the left and **Home** at the right.
- The top bar's primary label is the conversation name. A Project conversation also shows a folder icon
  and muted Project name beside it. A loose task shows neither the folder icon nor a Project name. Each
  Project folder glyph visibly changes between closed and open with its `aria-expanded` state.
- Aide uses normal 1-pixel borders and restrained 3–5-pixel corner radii. Spacing and tone provide the
  rest of the hierarchy; controls must not drift into soft, pill-like shapes.
- Desktop top-bar icon controls use compact 32-pixel boxes; mobile keeps 44-pixel touch targets. The
  composer has one 1-pixel outer border, and focusing its textarea must not add a second inset outline.
  Structural sidebar controls never use an active fill or hover box to repeat their open/closed state;
  the visible panel is the feedback.
- There is no Chat/Agent/Jarvis selector and there are no suggested prompt cards.
- The composer always shows one text-only permission button with no icon and exactly **auto mode** (full
  permission), **ask for approval** (default), and **plan** (read and plan without changes). Only Auto
  mode is purple; the other states remain neutral. These are task permission profiles, not assistant
  modes.
- The composer has a compact per-task model and effort control. Full provider catalogs, defaults, and
  Cookbook stay in Settings.
- The `+` button is a custom menu for files, photos, apps, and connections. Speech remains directly
  reachable beside the composer. Microphone and send controls align at 36 pixels on desktop and 44
  pixels on mobile, use matching 18-pixel glyphs, and do not shift position on hover.
- A hidden-by-default right task-tools sidebar is a real edge column on desktop, not a floating window.
  Its compact launcher exposes Review, Terminal, Browser, Files, and Side task. There is no pinned summary.
  Selecting Terminal replaces the body with only the terminal surface and minimal panel chrome.
- Messages do not repeat **you** or **Aide** author labels. Thinking, progress, and tool steps appear in
  order before the answer; completed details may collapse, but their disclosure stays before the
  answer. The top bar owns the conversation title and Project context, so threads never repeat them as
  a heading inside the message stream.
- The message rail stays absent until a conversation has at least three user messages. It then appears
  as a slim, vertically centered rail with one keyboard-accessible tick per user message. The bright
  tick follows the message closest to the reading position, with exact first/last behavior at the top
  and bottom. Selecting another leaves only that tick bright. Pointer proximity grows the nearest tick
  most and nearby ticks less through transform-only scaling, without moving or blanking the page. A focused tick gets extra reach, and
  selecting one jumps to that message without taking over scrolling. The starter includes five messages
  so this behavior is easy to inspect.

## Background work

Background work is still **Aide**. The interface may say **keep running**, **working in background**, or
**Aide is working**. It must never rename the task to Jarvis.

The durable scheduler, run records, leases, prompts, delivery outbox, and recovery rules remain useful.
Old database tables and API paths containing `jarvis` may remain temporarily for compatibility, but
they are internal migration details and must not leak into normal product copy.

## Jarvis

**Jarvis is only the Discord bot's name.**

- The owner pairs Jarvis with one Discord account or approved server/channel.
- Messages sent to Jarvis are handled by Aide's normal assistant and background system.
- Jarvis may report progress or deliver a finished result in Discord.
- Jarvis does not define a second personality, tool runtime, model role, Project type, or in-app mode.
- Disconnecting Discord removes Jarvis without changing Aide.

## Andromeda and other apps

- **Explain in Aide** opens the selected search context in Aide.
- For a query that needs deeper research, Aide detects the need, asks the owner, and continues with the
  same query and optional Project after approval.
- Home shows **Aide work**, not Jarvis runs.
- Projects contain Aide conversations and background Aide work.
- Automations, schedules, heartbeat checks, and News use the background Aide system. Discord delivery may
  come from the Jarvis bot when that connection is enabled.

## Compatibility rule

Old `agent`, `cowork`, and in-app `jarvis` links open the single Aide interface. They do not select or
recreate an old mode. Historical Phase 2–4 evidence may keep old names because it records what those
commits actually shipped; this decision controls all new product planning and implementation.
