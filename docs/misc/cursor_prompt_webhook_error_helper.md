# Cursor prompt: Webhook JSON error helper (DRY 1.2)

Refactor ONE DRY pattern in app/api/webhooks.py: repeated JSON error responses.

Do NOT change behavior, status codes, or response body shapes.

## Steps

1) Introduce a small helper in app/api/webhooks.py (or a tiny module app/api/webhook_responses.py) to build error JSONResponses.
   - Must support both shapes currently used:
     a) `{"received": False, "error": "..."}` (WhatsApp)
     b) `{"error": "..."}` (Stripe)
2) Replace repeated JSONResponse(...) calls that match these patterns with the helper.
3) Keep exact message strings and keys as they were at each call site.
4) Do not refactor signature verification logic yet (that's a separate pass).

## After

- List all replaced call sites (file + line-ish).
- Run webhook/admin related tests.
