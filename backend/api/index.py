"""
Vercel serverless entry point.

Mangum wraps the FastAPI ASGI app as an AWS Lambda / Vercel handler.
Vercel's Python runtime calls handler(event, context) for every request.
"""

from app.main import app
from mangum import Mangum

handler = Mangum(app, lifespan="off")
