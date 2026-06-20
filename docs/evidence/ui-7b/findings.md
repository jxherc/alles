# ui-7b — CardDAV into settings (findings)

## Audit
CardDAV sat as a bare toolbar button opening an in-list modal with no scheduling — manual sync only.

## Fix
Re-homed it behind a contacts settings cog (the shared app-cog/appsettings pattern). The pane is a real
settings surface: connection status, explainer, connect/sync/disconnect, and an auto-sync interval
(off/hourly/daily) backed by a new `/api/carddav/interval` endpoint + a `carddav_auto` background job
that syncs only when due.

## Verify
Backend: `test_carddav_interval.py` exercises the interval storage, connect/disconnect persistence, and
the due-for-sync math (hourly/daily windows). Frontend `verify.py` drives the cog → popover → CardDAV
pane and confirms picking "daily" persists to the backend. 0 console errors.
