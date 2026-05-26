"""Vercel serverless entrypoint.

Vercel's @vercel/python runtime serves the ASGI ``app`` exposed here. All
routes (API + static UI) are handled by the FastAPI app.

Required environment variables in Vercel:
  DATABASE_URL         Supabase Postgres connection string (use the pooler URL)
  MGS_SECRET_KEY       Fernet key for encrypting integration secrets
  MGS_ADMIN_PASSWORD   Admin login password
  MGS_CORS_ORIGINS     (optional) comma-separated allowed origins
"""

from api.app import app  # noqa: F401
