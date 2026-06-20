"""rich-compose helpers (5c): turn the editor's `<img src="/api/uploads/ID">` references
into cid: inline attachments so they render in the recipient's client."""

import re

_IMG_SRC = re.compile(r'src="/api/uploads/([^"]+)"')


def embed_inline(html, get_bytes):
    """rewrite uploaded-image srcs to cid: refs and collect the inline parts.
    get_bytes(upload_id) -> (data_bytes, subtype) or (None, None) to skip."""
    inline = []
    seen = {}

    def repl(m):
        uid = m.group(1)
        if uid not in seen:
            data, subtype = get_bytes(uid)
            if data is None:
                return m.group(0)
            inline.append({"cid": uid, "data": data, "subtype": subtype or "png"})
            seen[uid] = True
        return f'src="cid:{uid}"'

    return _IMG_SRC.sub(repl, html or ""), inline
