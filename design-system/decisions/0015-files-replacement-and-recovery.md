# Files replacement and recovery

Uploading different content over a local file requires an explicit decision.
The existing dialog offers cancellation, a new name, or replacement. Replacement
requires a recovery version of the current file. If the original exceeds the
25 MiB snapshot limit, keep it and choose a new name instead.

Details exposes version history with a labeled Restore action. Restoring checks
that the current file still matches the owner's decision and keeps the previous
current version. Errors stay beside the action; rejected uploads retain the
selected file and proposed name for retry.

Transfer failures show a wrapping, 14px reason. A failed operation does not claim
that its transfer was verified. The retained transfer panel has bounded height
and reserves its measured height in the file list's scroll area. Last rows and
selection actions remain reachable without dismissing an error. On phones, the
list uses its natural height inside the page's scrolling pane.

The browser checks exercise local and connected managed folders, pointer and
keyboard input, reload, stale decisions from a second tab, canceled replacement,
lost responses, retry, and retained failures in light/dark and constrained-height
layouts. Browser phone emulation does not establish native iPhone acceptance.

Mutation claims coordinate Alles operations that share a location or an aliased
root. They cannot guarantee atomic replacement against arbitrary external writers
between the final identity check and filesystem rename. Remote providers retain
their existing contracts and require separate live integration acceptance.
