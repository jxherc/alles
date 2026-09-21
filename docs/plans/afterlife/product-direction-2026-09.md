# a useful direction for alles

Status: proposal, not implemented or approved.

## recommendation

Make Alles the place where personal work becomes organized, visible, and recoverable. Let an agent
engine such as DeepSeek Harness do general agent execution. A second broad chat/coding harness is a
weak reason to maintain all of Alles. Its stronger assets are owned records, linked documents, local
files, calendars, safe changes, and a usable interface on a phone.

DeepSeek describes DSH as a developer preview with replaceable plugins for models, tools, sessions,
storage, scheduling, and UI, plus inspectable run history. That is substantial overlap with Aide's
general-purpose runtime. It also gives a possible integration boundary. No DSH adapter exists in this
repair, and compatibility needs a bounded technical experiment before any engine replacement.

Sources checked on 2026-09-21: [official overview](https://deepseek.com/harness/en/) and
[official repository](https://github.com/deepseek-ai/deepseek-harness).

## three possible products

| direction | a reason to open it daily | first complete workflow | main risk |
|---|---|---|---|
| personal operations inbox (recommended) | know what needs a decision and what happens next | capture a document or message, suggest a deadline and tasks, review them, save with the source attached | noisy inferred tasks; suggestions must stay separate from committed records |
| study and research workspace | turn a folder of sources into a plan and retained knowledge | import sources, ask cited questions, create a study plan, review practice answers against those sources | becoming another generic notes/chat app |
| home services desk | see whether files, backups, and services are healthy | detect a failed backup, show its cause, preview recovery, verify the restored result | infrastructure work can overwhelm the everyday product |

## start with the personal operations inbox

Three destinations would carry the main flow:

- **Now:** actual commitments, the next action, and decisions waiting for approval. Suppress empty
  sections. Show one helpful starting action when no data exists.
- **Inbox:** captures from text, files, links, and optional connected mail. Each item has a source,
  suggested destination, and an explicit processed state.
- **Library:** owned documents and files, with related tasks, decisions, and activity attached.

The assistant sits beside a record or workflow with visible scope. Its useful output is a proposed
change to real records, with preview, confirmation where needed, a result, and recovery. General chat
remains available, but the homepage is useful before configuring a model. Specialist tools remain
reachable; hide unused destinations through preferences instead of deleting data or capabilities.

Example: drop in an assignment PDF, review its extracted due date, accept a three-session study plan,
open the linked sources during each session, and mark work complete. The task and source remain usable
when the agent is offline or replaced. The same flow can handle a renewal notice or project brief.

## bounded first release

1. Prove capture → review → task + linked source → complete using existing Docs, Files, and Plan APIs.
2. Make Home show that flow and actionable state, with quick capture always reachable.
3. Trial a DSH adapter on disposable data: scoped read access first, then one reviewed task mutation.
   Confirm authentication, cancellation, errors, duplicate prevention, and recoverability.
4. Keep the current runtime until the adapter proves parity for those workflows. Do not migrate
   every module or replace the database as part of an interface redesign.

Success means the owner uses it to finish real work repeatedly: captures become organized records,
commitments are met, and errors are recoverable. Chat volume and the number of installed features do
not measure that outcome.
