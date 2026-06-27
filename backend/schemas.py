import re

from pydantic import BaseModel, field_validator

USERNAME_RE = re.compile(r"^[A-Za-z0-9_-]+$")


class UserCreate(BaseModel):
    username: str
    password: str
    confirm_password: str

    @field_validator("username")
    @classmethod
    def username_min_length(cls, v):
        if len(v) < 3:
            raise ValueError("Имя пользователя должно содержать минимум 3 символа")
        if len(v) > 32:
            raise ValueError("Имя пользователя должно содержать максимум 32 символа")
        if not USERNAME_RE.match(v):
            raise ValueError(
                "Имя пользователя может содержать только латинские буквы, цифры, _ и -"
            )
        return v

    @field_validator("password")
    @classmethod
    def password_min_length(cls, v):
        if len(v) < 6:
            raise ValueError("Пароль должен содержать минимум 6 символов")
        return v

    @field_validator("confirm_password")
    @classmethod
    def passwords_match(cls, v, info):
        if "password" in info.data and v != info.data["password"]:
            raise ValueError("Пароли не совпадают")
        return v


class UserLogin(BaseModel):
    username: str
    password: str

    @field_validator("username")
    @classmethod
    def username_format(cls, v):
        if not USERNAME_RE.match(v):
            raise ValueError(
                "Имя пользователя может содержать только латинские буквы, цифры, _ и -"
            )
        return v


class UserResponse(BaseModel):
    id: str
    username: str
