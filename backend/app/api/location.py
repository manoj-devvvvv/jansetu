from fastapi import APIRouter, Depends, Query, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List, Tuple
from app.db.session import get_db
from app.core.location.reverse_geocode import reverse_geocode
from app.core.location.routing import get_route

router = APIRouter(prefix="/location", tags=["location"])

@router.get("/reverse-geocode")
async def api_reverse_geocode(
    lat: float = Query(..., description="Latitude of the point"),
    lng: float = Query(..., description="Longitude of the point"),
    db: AsyncSession = Depends(get_db)
):
    """
    Reverse geocodes a latitude/longitude point to a physical address 
    using Nominatim, and enriches it with internal jurisdiction data.
    """
    try:
        result = await reverse_geocode(db, lng, lat)
        return result
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Reverse geocoding failed: {str(e)}"
        )

@router.get("/route")
async def api_get_route(
    start_lat: float = Query(...),
    start_lng: float = Query(...),
    end_lat: float = Query(...),
    end_lng: float = Query(...),
    profile: str = Query("driving", description="Routing profile (driving, walking, cycling)")
):
    """
    Calculates the best route between two points using OSRM.
    Returns distance, ETA (duration), and GeoJSON geometry for rendering.
    """
    try:
        # OSRM expects (lon, lat)
        coords = [(start_lng, start_lat), (end_lng, end_lat)]
        result = await get_route(coords, profile)
        
        if result.get("status") == "error":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=result.get("message", "Routing failed")
            )
            
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Routing request failed: {str(e)}"
        )
