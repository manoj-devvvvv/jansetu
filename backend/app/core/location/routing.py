import httpx
import logging
from typing import Dict, Any, List, Tuple
from app.config.settings import settings

logger = logging.getLogger(__name__)

async def get_route(coordinates: List[Tuple[float, float]], profile: str = "driving") -> Dict[str, Any]:
    """
    Get routing information (distance, duration, geometry) between points using OSRM API.
    
    Args:
        coordinates: List of (longitude, latitude) tuples.
        profile: The routing profile to use ('driving', 'walking', 'cycling').
        
    Returns:
        Dictionary containing route distance (meters), duration (seconds), and geometry.
    """
    if len(coordinates) < 2:
        raise ValueError("At least two coordinates (start, end) are required for routing.")
        
    # OSRM expects coordinates in lon,lat format separated by semicolons
    coord_string = ";".join([f"{lon},{lat}" for lon, lat in coordinates])
    
    # Base URL depends on the profile. OSRM public server supports driving/car.
    # Note: public server profile is 'car', 'bike', or 'foot' usually via api/v1/profile
    # The standard public endpoint is: https://router.project-osrm.org/route/v1/{profile}/{coordinates}
    if profile == "driving":
        profile = "car"
    elif profile == "walking":
        profile = "foot"
    elif profile == "cycling":
        profile = "bike"
        
    url = f"{settings.OSRM_URL}/route/v1/{profile}/{coord_string}"
    
    params = {
        "overview": "full",
        "geometries": "geojson",
        "steps": "true"
    }
    
    try:
        logger.info(f"Requesting OSRM route for {len(coordinates)} points using {profile} profile.")
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.get(url, params=params)
            response.raise_for_status()
            
            data = response.json()
            
            if data.get("code") != "Ok" or not data.get("routes"):
                logger.warning(f"OSRM routing failed: {data.get('message', 'No route found')}")
                return {"status": "error", "message": data.get("message", "No route found")}
                
            best_route = data["routes"][0]
            
            return {
                "status": "success",
                "distance_meters": best_route.get("distance", 0.0),
                "duration_seconds": best_route.get("duration", 0.0),
                "geometry": best_route.get("geometry", {}),
                "steps": best_route.get("legs", [{}])[0].get("steps", [])
            }
            
    except Exception as e:
        logger.exception(f"Error communicating with OSRM API: {str(e)}")
        return {"status": "error", "message": str(e)}
