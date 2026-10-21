# Aide: quieter steps, a box that sits in the page

## context

The owner still found the conversation and code views worse than Claude Code, opencode and their
own dsh harness (2026-10-21). Reading dsh's and opencode's source showed three differences that
carried most of the weight: they read at 14px where Aide used 15-16px; a step is one plain line
where Aide drew a 44px filled card per step; edits stay closed and a finished turn folds away.

## decision

- Code view answers and box read at 14px/1.65; the conversation at 15px/1.7.
- A step in the code view is one 32px line (44px on touch): mark, verb, where. No fill. The
  running line has a light passing through it and a live timer. A finished line hides its check
  and time until pointed at. Opened, its output sits indented under it with a hairline, at most
  240px tall (diffs 320px).
- Edits start closed and their line says how much changed (`+4 −1`).
- When pi answers, every finished step before the answer, edits and thinking included, folds into
  one line with a hairline under it: "worked 42s · 9 steps · 2 edits". This replaces the old
  "four or more steps, edits stay out" rule.
- Both boxes lose their drawn border: a raised fill with a hairline that firms up while you type,
  and a 32px fade above them so the transcript slides under. The conversation's send fills only
  when there's something to send.
- KOKUEN's 2-4px corners stay; the references use 10-22px, but the sharp edge is Alles's own.

## verification

The Aide browser gates (central, coding, composer, continuity, send preflight, stream completion,
response retry, scoped draft) and the ui-audit pass. The fake pi's "multi" turn covers the fold
and the edit count.
