# 5c audit — mail: rich compose

`_build_message` (services/mail.py:830) builds a plain-text EmailMessage via set_content — no HTML
alternative, no inline images. No `mail_signatures` in settings; compose has no rich toolbar /
signature picker / image upload. All net-new. Testable core = the MIME builder + inline embedding
+ signature CRUD (SMTP send stays best-effort/untestable). Plan: docs/plans/5c.md.
