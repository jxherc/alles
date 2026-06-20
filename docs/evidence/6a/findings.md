# 6a audit — files: recover & history

trash (1d) + version history (1e) already fully wired in routes/files.py (/delete→trash, /trash,
/trash/restore, /trash/purge, /versions, /versions/restore — with UI + tests). FileTag(path, tags,
color) has NO starred column; no /star, /starred, or /quota route. 6a only adds starred + quota.
