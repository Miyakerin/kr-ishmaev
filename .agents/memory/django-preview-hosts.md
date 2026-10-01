---
name: Django preview hosts
description: Django ALLOWED_HOSTS behavior in the Replit proxied app preview.
---

For Django applications served in Replit's browser preview, include `127.0.0.1` and `localhost` in `ALLOWED_HOSTS` in addition to the Replit domains. The preview browser can request the app using `127.0.0.1`, even when the workflow is bound to `0.0.0.0`.

**Why:** Django otherwise returns `DisallowedHost` before the proxied preview can render, although the configured Replit domain is allowed.

**How to apply:** When setting up or changing Django host validation for a Replit webview, preserve these local preview hosts while keeping production domains explicitly listed.