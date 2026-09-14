from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from starlette.concurrency import run_in_threadpool
from app.db.session import get_db, supabase
from app.models.officer import Officer

security = HTTPBearer()

async def get_current_officer(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: AsyncSession = Depends(get_db)
) -> Officer:
    token = credentials.credentials
    try:
        user_response = await run_in_threadpool(supabase.auth.get_user, token)
        if not user_response or not user_response.user:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
        user_id = user_response.user.id
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
    
    result = await db.execute(select(Officer).where(Officer.id == user_id))
    officer = result.scalar_one_or_none()
    
    if not officer:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Officer not found")
        
    if not officer.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Officer is inactive")
        
    return officer
