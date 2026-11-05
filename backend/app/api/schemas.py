from pydantic import BaseModel, EmailStr, Field, ConfigDict


class UserRegister(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    full_name: str = Field(min_length=2, max_length=150)


class UserLogin(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int


class UserResponse(BaseModel):
    id: int
    email: EmailStr
    full_name: str | None
    is_active: bool

    model_config = ConfigDict(from_attributes=True)


class MeResponse(UserResponse):
    # True for shop owners (MERCHANT_ADMIN_EMAILS); everyone else is a customer.
    is_owner: bool = False

class PayPalExchangeRequest(BaseModel):
    code: str = Field(min_length=20, max_length=128)
    app_nonce: str = Field(min_length=32, max_length=128)