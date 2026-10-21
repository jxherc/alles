# Aide: one reading column, live work

## context

The owner called the Aide conversation and code views bad and asked for a lot of visual
feedback and screens that explain themselves (2026-10-21). In the conversation, Aide's text sat
on the left page edge and the owner's messages on the right with a dead middle; the box spanned
the full width and lined up with neither. Every reply carried a separate "context · provider /
model" line and then a copy row. Working, waiting and loading states were barely visible, and
the code view showed a blank screen while it loaded.

## decision

- The conversation uses the code view's 760px reading column. Replies, the owner's messages and
  the box share its two edges; the chat reserves scrollbar room on both sides so the column and
  the box share one center. A new turn gets 32px above it.
- One quiet line under each reply: copy, more, and what Aide used ("model · context") at the far
  end. The context details open as a panel under the line, or above it near the bottom of the
  chat; Escape closes it. The line moves back by copy's padding so the label sits on the text edge.
- Header actions carry a word on wide screens ("work", "call", "more"); a phone keeps the marks.
- A hint under the box names the keys (/ commands, shift+enter, drop a file); it hides while Aide
  works and on a phone.
- Work is live in both views: steps are cards with a mark for the kind of step, a live timer, a
  turning ring that becomes a check or a cross, a dot per step on the folded line, a shimmer on
  whatever is running, a caret on a streaming answer and a moving light on the box. A step waiting
  for the owner says so in the permission color. Empty chats offer real starts; the code view has
  a loading state.
- Motion here is wider than decision 0031's quiet default, by the owner's direction. All of it is
  feedback for a real state, and all of it stops with reduced motion.

## verification

All Aide browser gates (central, composer, coding, continuity and 21 more) and the ui-audit pass
on desktop and phone, both themes, 320px and 200% zoom. The what's new popup skips automated
browsers so it never covers a screen a test drives.
