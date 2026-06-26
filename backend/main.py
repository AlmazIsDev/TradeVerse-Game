import bcrypt
from contextlib import asynccontextmanager
from fastapi import FastAPI, Depends, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database import engine, get_db, Base
from models import User
from schemas import UserCreate, UserResponse


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield


app = FastAPI(title="TradeVerse API", version="1.0.0", lifespan=lifespan)

# CORS — разрешаем запросы с frontend (Vite на порту 5173)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def hash_password(password: str) -> str:
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(password.encode("utf-8"), salt).decode("utf-8")


@app.post(
    "/api/register",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
)
async def register_user(user_data: UserCreate, db: AsyncSession = Depends(get_db)):
    # Проверяем, занято ли имя пользователя
    existing_username = (
        await db.execute(select(User).where(User.username == user_data.username))
    ).scalar_one_or_none()
    if existing_username:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Пользователь с таким именем уже существует",
        )

    # Проверяем, занят ли email
    existing_email = (
        await db.execute(select(User).where(User.email == user_data.email))
    ).scalar_one_or_none()
    if existing_email:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Пользователь с таким email уже существует",
        )

    # Создаём пользователя с захешированным паролем
    new_user = User(
        username=user_data.username,
        email=user_data.email,
        hashed_password=hash_password(user_data.password),
    )
    db.add(new_user)
    await db.commit()
    await db.refresh(new_user)

    return new_user


@app.get("/api/health")
async def health_check():
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
