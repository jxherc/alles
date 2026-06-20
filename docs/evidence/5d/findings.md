# 5d audit — mail: rules & AI

No MailRule / mail_vacation / smart-reply exists (grep: none). LLM endpoints are `ModelEndpoint`
rows with `enabled==True` — smart-reply gates on one existing. Live :8845 confirms the routes 404.
All net-new. Testable core: rule matching + cache application (markread/mute) + vacation
once-per-day + smart-reply disabled-when-no-endpoint. Plan: docs/plans/5d.md.
