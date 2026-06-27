import bcrypt
from contextlib import asynccontextmanager
from fastapi import FastAPI, Depends, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorDatabase

from database import get_db
from schemas import UserCreate, UserLogin, UserResponse


@asynccontextmanager
async def lifespan(app: FastAPI):
    db = get_db()
    await db.users.create_index("username", unique=True)
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


def verify_password(password: str, hashed: str) -> bool:
    return bcrypt.checkpw(password.encode("utf-8"), hashed.encode("utf-8"))


def get_users_collection(db: AsyncIOMotorDatabase = Depends(get_db)):
    return db.users


@app.post(
    "/api/register",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
)
async def register_user(
    user_data: UserCreate,
    users=Depends(get_users_collection),
):
    existing = await users.find_one({"username": user_data.username})
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Пользователь с таким именем уже существует",
        )

    new_user = {
        "username": user_data.username,
        "hashed_password": hash_password(user_data.password),
    }
    result = await users.insert_one(new_user)
    return UserResponse(id=str(result.inserted_id), username=user_data.username)


@app.post("/api/login")
async def login_user(
    user_data: UserLogin,
    users=Depends(get_users_collection),
):
    user = await users.find_one({"username": user_data.username})
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Неверное имя пользователя или пароль",
        )

    if not verify_password(user_data.password, user["hashed_password"]):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Неверное имя пользователя или пароль",
        )

    return {"id": str(user["_id"]), "username": user["username"]}


@app.get("/api/health")
async def health_check():
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
