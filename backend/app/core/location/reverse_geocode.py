from .jurisdiction_lookup import lookup_jurisdiction
from sqlalchemy.ext.asyncio import AsyncSession

async def reverse_geocode(db: AsyncSession, lng: float, lat: float) -> dict | None:
    # Currently just wraps the PostGIS jurisdiction lookup
    # Nominatim integration can come later
    return await lookup_jurisdiction(db, lng, lat)
