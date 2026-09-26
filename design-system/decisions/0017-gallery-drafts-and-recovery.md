# Gallery drafts and recovery

Gallery keeps its existing Files destination, albums and photo viewer. Uploads
snapshot the selected files before resetting the picker; interrupted uploads keep
their pending files and a visible Retry action. Failed lists show an error and
Retry rather than pretending the library is empty.

Caption and album-name failures retain editable drafts. Success requires a valid
acknowledgement; new-album assignment also checks that the returned name matches
the requested trimmed name. A failed or unrelated acknowledgement never clears
existing photo membership. Names are not unique identifiers: this check does not
establish request correlation for unrelated responses carrying the same name.
An untrusted response after a committed creation can leave an empty album, and
retry can create another. Album creation idempotency remains outside this repair.

Photo entry and selection have labeled keyboard controls. The viewer contains
focus and prevents background actions while open, then returns focus on dismissal.
Long album menus remain bounded, scrollable and dismissible by Escape. Restoring
a deleted photo reports success only after the server confirms it.

The maintained browser gate checks light/dark desktop and phone layouts, actual
pointer/keyboard/emulated touch, exact image bytes and saved metadata after reload,
and explicitly simulated interrupted/rejected/malformed responses. It does not
certify Apple Photos, native Safari/iPhone, or retry after ambiguous committed
photo writes.
