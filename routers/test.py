from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session
from database.db_connect import get_db

router = APIRouter(
    prefix='/test',
    tags=['Test']
)

@router.get('/db_connection')
async def test_db_connection(db: Session = Depends(get_db)):
    try:
        result = db.execute(text('SELECT 1')).scalar()

        if result == 1:
            return {
                'status': 'success',
                'message': 'Your PostgreSQL connection is working perfectly.'
            }
        else:
            raise HTTPException(
                status_code=500,
                detail='Your PostgreSQL database is connected but returned a abnormal result'
            )

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f'PostgreSQL is not connected properly. E: {str(e)}'
        )
