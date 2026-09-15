import httpx
import logging
from typing import Optional, Dict, Any
from app.config.settings import settings
from .jurisdiction_lookup import lookup_jurisdiction
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

async def reverse_geocode(db: AsyncSession, lng: float, lat: float) -> Dict[str, Any]:
    """
    Reverse geocodes coordinates into a human-readable address using Nominatim API.
    Also injects the jurisdiction IDs from the local PostGIS database as a fallback/enhancement.
    
    Nominatim requires a User-Agent header. We use 'JanSetu-App' to comply with OSM terms.
    """
    result = {
        "display_name": "",
        "address": {},
        "jurisdictions": await lookup_jurisdiction(db, lng, lat),
        "source": "postgis"
    }
    
    try:
        url = f"{settings.NOMINATIM_URL}/reverse"
        params = {
            "format": "jsonv2",
            "lat": lat,
            "lon": lng,
            "zoom": 18,
            "addressdetails": 1
        }
        headers = {
            "User-Agent": "JanSetu-App/1.0 (contact@jansetu.org)"
        }
        
        logger.info(f"Reverse geocoding with Nominatim for ({lat}, {lng})")
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(url, params=params, headers=headers)
            response.raise_for_status()
            
            data = response.json()
            if data and "display_name" in data:
                result["display_name"] = data["display_name"]
                result["address"] = data.get("address", {})
                result["source"] = "nominatim"
                
    except Exception as e:
        logger.warning(f"Nominatim reverse geocode failed for ({lat}, {lng}): {str(e)}")
        # Fallback to local DB jurisdictions
        jur_data = result["jurisdictions"]
        parts = []
        if jur_data:
            if jur_data.get("panchayat_id"):
                parts.append("Panchayat")
            if jur_data.get("mandal_id"):
                parts.append("Mandal")
            if jur_data.get("district_id"):
                parts.append("District")
        result["display_name"] = f"Unknown Address within {'/'.join(parts)} jurisdiction"
        
    return result
