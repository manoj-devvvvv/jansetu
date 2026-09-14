from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

async def lookup_jurisdiction(db: AsyncSession, lng: float, lat: float) -> dict | None:
    query = text("""
        SELECT j_panchayat.id as panchayat_id, j_mandal.id as mandal_id, j_district.id as district_id
        FROM jurisdictions j_panchayat
        JOIN jurisdictions j_mandal ON j_panchayat.parent_id = j_mandal.id
        JOIN jurisdictions j_district ON j_mandal.parent_id = j_district.id
        WHERE j_panchayat.level = 'panchayat' 
          AND ST_Contains(j_panchayat.boundary, ST_SetSRID(ST_MakePoint(:lng, :lat), 4326))
        LIMIT 1
    """)
    
    result = await db.execute(query, {"lng": lng, "lat": lat})
    row = result.fetchone()
    
    if not row:
        return None
        
    return {
        "panchayat_id": row.panchayat_id,
        "mandal_id": row.mandal_id,
        "district_id": row.district_id
    }
