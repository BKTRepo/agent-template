"""Developer and published-skill catalogs share the knowledge application provider."""
from applications.wrq.platform_catalog import application_catalog

async def application_options():
    return await application_catalog(include_all=True)
