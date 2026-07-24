# ============================================
# AUTOSERVICE BACKEND - FastAPI + PostgreSQL
# ============================================
# Run: uvicorn main:app --reload --host 0.0.0.0 --port 8000
# ============================================

import os
import random
import hashlib
import datetime
import logging
import requests
from typing import Optional, List
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Depends, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, validator
from sqlalchemy import create_engine, Column, Integer, String, Boolean, DateTime, Float, Text, ForeignKey, Enum as SQLEnum
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session, relationship
from sqlalchemy.sql import func
import enum

# ============================================
# DATABASE CONFIGURATION (ENV)
# ============================================
DATABASE_URL = os.getenv(
    "DATABASE_URL"
)
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL environment variable is not set. Set it in Railway's Variables tab.")

# Fix for SQLAlchemy asyncpg compatibility
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

engine = create_engine(DATABASE_URL, pool_pre_ping=True, pool_recycle=300)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# ============================================
# ENUMS
# ============================================
class UserRole(str, enum.Enum):
    USER = "user"
    SERVICE_OWNER = "service_owner"
    ADMIN = "admin"

class OrderStatus(str, enum.Enum):
    PENDING = "pending"           # 🟡 Kutilmoqda
    ACCEPTED = "accepted"         # 🔵 Qabul qilindi
    ON_WAY = "on_way"            # 🟠 Yo'lda
    ARRIVED = "arrived"          # 🟢 Yetib keldi
    COMPLETED = "completed"      # ✅ Yakunlandi
    CANCELLED = "cancelled"      # ❌ Bekor qilindi

class ServiceCategory(str, enum.Enum):
    EVACUATOR = "evacuator"
    FUEL = "fuel"
    BATTERY = "battery"
    TIRE = "tire"
    TECH_SUPPORT = "tech_support"
    DIAGNOSTICS = "diagnostics"
    OIL_CHANGE = "oil_change"
    ELECTRICIAN = "electrician"
    ENGINE = "engine"
    AC = "ac"

# ============================================
# DATABASE MODELS
# ============================================
class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    phone = Column(String(20), unique=True, index=True, nullable=False)
    name = Column(String(100), nullable=False)
    city = Column(String(100), nullable=True)
    password_hash = Column(String(256), nullable=False)
    role = Column(String(20), default=UserRole.USER.value)
    avatar_url = Column(String(500), nullable=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # Relationships
    cars = relationship("Car", back_populates="owner", cascade="all, delete-orphan")
    orders = relationship("Order", back_populates="user", cascade="all, delete-orphan")
    favorites = relationship("Favorite", back_populates="user", cascade="all, delete-orphan")
    reviews = relationship("Review", back_populates="user", cascade="all, delete-orphan")

class Car(Base):
    __tablename__ = "cars"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    model = Column(String(100), nullable=False)
    plate_number = Column(String(20), nullable=True)
    year = Column(Integer, nullable=True)
    color = Column(String(50), nullable=True)
    fuel_type = Column(String(20), nullable=True)
    is_primary = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    owner = relationship("User", back_populates="cars")

class Service(Base):
    __tablename__ = "services"

    id = Column(Integer, primary_key=True, index=True)
    owner_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    name = Column(String(200), nullable=False)
    description = Column(Text, nullable=True)
    phone = Column(String(20), nullable=False)
    address = Column(String(500), nullable=False)
    latitude = Column(Float, nullable=False)
    longitude = Column(Float, nullable=False)
    logo_url = Column(Text, nullable=True)  # stores base64 data-URL, can be very long
    images = Column(Text, nullable=True)  # JSON array of image URLs
    working_hours = Column(String(100), nullable=True)  # e.g., "09:00-18:00"
    day_off = Column(String(50), nullable=True)  # e.g., "Yakshanba"
    rating = Column(Float, default=0.0)
    review_count = Column(Integer, default=0)
    is_active = Column(Boolean, default=True)
    is_verified = Column(Boolean, default=False)
    # Admin moderation workflow: pending -> approved / rejected
    status = Column(String(20), default="pending")
    reject_reason = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    owner = relationship("User")
    services_offered = relationship("ServiceOffered", back_populates="service", cascade="all, delete-orphan")
    orders = relationship("Order", back_populates="service")
    reviews = relationship("Review", back_populates="service")
    favorites = relationship("Favorite", back_populates="service")

class ServiceOffered(Base):
    __tablename__ = "services_offered"

    id = Column(Integer, primary_key=True, index=True)
    service_id = Column(Integer, ForeignKey("services.id"), nullable=False)
    category = Column(String(50), nullable=False)
    price = Column(Float, nullable=True)
    is_active = Column(Boolean, default=True)

    service = relationship("Service", back_populates="services_offered")

class Order(Base):
    __tablename__ = "orders"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    service_id = Column(Integer, ForeignKey("services.id"), nullable=False)
    category = Column(String(50), nullable=False)
    status = Column(String(20), default=OrderStatus.PENDING.value)
    description = Column(Text, nullable=True)
    user_latitude = Column(Float, nullable=True)
    user_longitude = Column(Float, nullable=True)
    price = Column(Float, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    completed_at = Column(DateTime(timezone=True), nullable=True)

    user = relationship("User", back_populates="orders")
    service = relationship("Service", back_populates="orders")
    chat_messages = relationship("ChatMessage", back_populates="order", cascade="all, delete-orphan")
    review = relationship("Review", back_populates="order", uselist=False)

class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id = Column(Integer, primary_key=True, index=True)
    order_id = Column(Integer, ForeignKey("orders.id"), nullable=False)
    sender_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    message = Column(Text, nullable=False)
    is_read = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    order = relationship("Order", back_populates="chat_messages")
    sender = relationship("User")

class Review(Base):
    __tablename__ = "reviews"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    service_id = Column(Integer, ForeignKey("services.id"), nullable=False)
    order_id = Column(Integer, ForeignKey("orders.id"), nullable=False)
    rating = Column(Integer, nullable=False)
    comment = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    user = relationship("User", back_populates="reviews")
    service = relationship("Service", back_populates="reviews")
    order = relationship("Order", back_populates="review")

class Favorite(Base):
    __tablename__ = "favorites"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    service_id = Column(Integer, ForeignKey("services.id"), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    user = relationship("User", back_populates="favorites")
    service = relationship("Service", back_populates="favorites")

class OTPCode(Base):
    __tablename__ = "otp_codes"

    id = Column(Integer, primary_key=True, index=True)
    phone = Column(String(20), nullable=False, index=True)
    code = Column(String(6), nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    is_used = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

# Create tables
Base.metadata.create_all(bind=engine)

# ============================================
# LIGHTWEIGHT AUTO-MIGRATION
# ============================================
# Base.metadata.create_all() only creates tables that don't exist yet — it
# never adds new columns to a table that already exists in the database.
# So whenever a Column is added to a model above, the live Postgres table
# on Railway falls out of sync and queries fail with UndefinedColumn.
#
# This scans every model's columns against the real database schema and
# ALTER TABLE ... ADD COLUMN's anything that's missing, so a code deploy
# alone keeps the schema in sync. This is a pragmatic stopgap, not a
# replacement for a real migration tool (Alembic) — it can't rename/drop
# columns, change types, or safely backfill a NOT NULL column with no
# default on a table that already has rows (those are always added as
# nullable here so the ALTER doesn't fail).
def sync_missing_columns():
    import logging
    from sqlalchemy import inspect, text

    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())

    with engine.begin() as conn:
        for table in Base.metadata.sorted_tables:
            if table.name not in existing_tables:
                continue  # brand-new table: create_all already built it in full
            existing_cols = {col["name"] for col in inspector.get_columns(table.name)}
            for column in table.columns:
                if column.name in existing_cols:
                    continue
                col_type = column.type.compile(dialect=engine.dialect)
                ddl = f'ALTER TABLE "{table.name}" ADD COLUMN IF NOT EXISTS "{column.name}" {col_type}'
                conn.execute(text(ddl))
                logging.getLogger("uvicorn.error").warning(
                    f"[auto-migration] added missing column {table.name}.{column.name} ({col_type})"
                )

sync_missing_columns()

# ============================================
# ONE-OFF FIX: widen services.logo_url to TEXT
# ============================================
# This column used to be VARCHAR(500), but the app stores full base64
# data-URLs (often 50k+ characters) in it, which caused
# "StringDataRightTruncation" errors on /api/service-owner/register.
# sync_missing_columns() only adds columns that don't exist yet — it can't
# change the type of a column that's already there — so that has to be
# done explicitly here.
def widen_logo_url_column():
    import logging
    from sqlalchemy import inspect, text

    inspector = inspect(engine)
    if "services" not in inspector.get_table_names():
        return
    columns = {col["name"]: col for col in inspector.get_columns("services")}
    logo_col = columns.get("logo_url")
    if logo_col is None:
        return
    # get_columns() reports the SQLAlchemy-mapped python type string in
    # col["type"]; only run the ALTER if it's still a bounded VARCHAR.
    if "VARCHAR" in str(logo_col["type"]).upper():
        with engine.begin() as conn:
            conn.execute(text('ALTER TABLE "services" ALTER COLUMN "logo_url" TYPE TEXT'))
        logging.getLogger("uvicorn.error").warning(
            "[auto-migration] widened services.logo_url from VARCHAR(500) to TEXT"
        )

widen_logo_url_column()

# ============================================
# PYDANTIC SCHEMAS
# ============================================
class PhoneRequest(BaseModel):
    phone: str

    @validator('phone')
    def validate_phone(cls, v):
        v = v.replace(' ', '').replace('-', '')
        if not v.startswith('+'):
            raise ValueError('Telefon raqam + bilan boshlanishi kerak')
        return v

class OTPVerifyRequest(BaseModel):
    phone: str
    code: str

class RegisterRequest(BaseModel):
    phone: str
    name: str
    password: str = Field(..., min_length=6)
    city: Optional[str] = None
    car_model: Optional[str] = None
    plate_number: Optional[str] = None
    year: Optional[int] = None
    color: Optional[str] = None
    fuel_type: Optional[str] = None

    @validator('phone')
    def validate_phone(cls, v):
        v = v.replace(' ', '').replace('-', '')
        if not v.startswith('+'):
            raise ValueError('Telefon raqam + bilan boshlanishi kerak')
        return v

class LoginRequest(BaseModel):
    phone: str
    password: str

class UserResponse(BaseModel):
    id: int
    phone: str
    name: str
    role: str
    is_active: bool
    created_at: datetime.datetime

    class Config:
        from_attributes = True

class CarCreate(BaseModel):
    model: str
    plate_number: Optional[str] = None
    year: Optional[int] = None
    color: Optional[str] = None
    fuel_type: Optional[str] = None
    is_primary: bool = False

class ServiceCreate(BaseModel):
    name: str
    description: Optional[str] = None
    phone: str
    address: str
    latitude: float
    longitude: float
    working_hours: Optional[str] = None
    categories: List[str] = []

class ServiceOwnerRegisterRequest(BaseModel):
    phone: str
    first_name: str
    last_name: str
    password: str = Field(..., min_length=6)
    service_name: str
    address: str
    latitude: float
    longitude: float
    day_off: Optional[str] = None
    logo_base64: Optional[str] = None  # data-URL or raw base64 of the logo image

    @validator('phone')
    def validate_phone(cls, v):
        v = v.replace(' ', '').replace('-', '')
        if not v.startswith('+'):
            raise ValueError('Telefon raqam + bilan boshlanishi kerak')
        return v

class ServiceEditRequest(BaseModel):
    name: Optional[str] = None
    phone: Optional[str] = None
    address: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    day_off: Optional[str] = None
    working_hours: Optional[str] = None
    logo_base64: Optional[str] = None

class ServiceRejectRequest(BaseModel):
    reason: Optional[str] = None

class ServiceOwnerProfileUpdate(BaseModel):
    """Servis egasi 'Profil' bo'limidan o'zi to'ldiradigan maydonlar."""
    name: Optional[str] = None
    phone: Optional[str] = None
    address: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    working_hours: Optional[str] = None
    day_off: Optional[str] = None
    description: Optional[str] = None
    logo_base64: Optional[str] = None

class ServiceOfferedUpsert(BaseModel):
    """Servis egasi 'Xizmatlarni boshqarish' bo'limida bitta xizmat narxi/holatini yuboradi."""
    category: str
    price: Optional[float] = None
    is_active: bool = True

class ServiceResponse(BaseModel):
    id: int
    name: str
    description: Optional[str]
    phone: str
    address: str
    latitude: float
    longitude: float
    rating: float
    review_count: int
    is_active: bool
    working_hours: Optional[str]

    class Config:
        from_attributes = True

class OrderCreate(BaseModel):
    service_id: int
    category: str
    description: Optional[str] = None
    user_latitude: Optional[float] = None
    user_longitude: Optional[float] = None

class OrderStatusUpdate(BaseModel):
    status: str

class ReviewCreate(BaseModel):
    service_id: int
    order_id: int
    rating: int = Field(..., ge=1, le=5)
    comment: Optional[str] = None

class ChatMessageCreate(BaseModel):
    order_id: int
    message: str

# ============================================
# DEPENDENCIES
# ============================================
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()

def generate_token(user_id: int) -> str:
    return hashlib.sha256(f"{user_id}{random.randint(100000, 999999)}{datetime.datetime.now()}".encode()).hexdigest()

def generate_otp() -> str:
    return str(random.randint(1000, 9999))

# ============================================
# ADMIN BOOTSTRAP
# ============================================
# There's no /api/admin/register endpoint on purpose (admin accounts
# shouldn't be self-serve), so a default admin account is created here on
# startup if it doesn't exist yet. Login is via the normal /api/login
# endpoint with the phone + password below; the response's `role` field
# will be "admin" and admin_main.dart's AdminApi.login() accepts it.
DEFAULT_ADMIN_PHONE = "+998901234567"
DEFAULT_ADMIN_PASSWORD = "avtoservis"

def bootstrap_admin():
    db = SessionLocal()
    try:
        existing = db.query(User).filter(User.phone == DEFAULT_ADMIN_PHONE).first()
        if existing:
            # Make sure it stays an admin even if something else changed it.
            if existing.role != UserRole.ADMIN.value:
                existing.role = UserRole.ADMIN.value
                db.commit()
            return
        admin = User(
            phone=DEFAULT_ADMIN_PHONE,
            name="Admin",
            password_hash=hash_password(DEFAULT_ADMIN_PASSWORD),
            role=UserRole.ADMIN.value,
            is_active=True,
        )
        db.add(admin)
        db.commit()
        logging.getLogger("uvicorn.error").warning(
            f"[bootstrap] created default admin account: {DEFAULT_ADMIN_PHONE}"
        )
    finally:
        db.close()

bootstrap_admin()

# ============================================
# SMS YUBORISH (ESKIZ.UZ)
# ============================================
# Ro'yxatdan o'ting: https://eskiz.uz -> akkaunt oching, "nickname" (jo'natuvchi nomi)
# tasdiqlatib oling, so'ng quyidagi ENV o'zgaruvchilarini serveringizga qo'ying:
#   ESKIZ_EMAIL, ESKIZ_PASSWORD, ESKIZ_SMS_FROM (masalan "4546" yoki tasdiqlangan nickname)
ESKIZ_EMAIL = os.getenv("ESKIZ_EMAIL")
ESKIZ_PASSWORD = os.getenv("ESKIZ_PASSWORD")
ESKIZ_SMS_FROM = os.getenv("ESKIZ_SMS_FROM", "4546")  # 4546 - Eskiz test nickname
ESKIZ_BASE_URL = "https://notify.eskiz.uz/api"

_eskiz_token_cache = {"token": None, "expires_at": None}


def _get_eskiz_token() -> str:
    """Eskiz.uz uchun bearer token olish (kesh bilan, har safar login qilmaslik uchun)"""
    now = datetime.datetime.utcnow()
    if (
        _eskiz_token_cache["token"]
        and _eskiz_token_cache["expires_at"]
        and now < _eskiz_token_cache["expires_at"]
    ):
        return _eskiz_token_cache["token"]

    resp = requests.post(
        f"{ESKIZ_BASE_URL}/auth/login",
        data={"email": ESKIZ_EMAIL, "password": ESKIZ_PASSWORD},
        timeout=10,
    )
    resp.raise_for_status()
    token = resp.json()["data"]["token"]

    _eskiz_token_cache["token"] = token
    _eskiz_token_cache["expires_at"] = now + datetime.timedelta(days=25)
    return token


def send_sms(phone: str, message: str) -> bool:
    """
    Haqiqiy SMS yuborish. ESKIZ_EMAIL/ESKIZ_PASSWORD sozlanmagan bo'lsa
    (masalan local dev muhitida), faqat konsolga chiqaradi - demo rejim.
    """
    if not ESKIZ_EMAIL or not ESKIZ_PASSWORD:
        print(f"[SMS DEMO REJIM] {phone} -> {message}")
        return True

    try:
        token = _get_eskiz_token()
        clean_phone = phone.replace("+", "")
        resp = requests.post(
            f"{ESKIZ_BASE_URL}/message/sms/send",
            headers={"Authorization": f"Bearer {token}"},
            data={
                "mobile_phone": clean_phone,
                "message": message,
                "from": ESKIZ_SMS_FROM,
            },
            timeout=10,
        )
        resp.raise_for_status()
        return True
    except Exception as e:
        print(f"SMS yuborishda xatolik: {e}")
        return False

# ============================================
# FASTAPI APP
# ============================================
app = FastAPI(
    title="AutoService API",
    description="Avtoservis ilovasi uchun backend API",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Catch-all handler for unhandled exceptions. Without this, an uncaught
# error (DB issue, bad env var, bug in a handler, etc.) propagates past
# CORSMiddleware and Starlette's default error response never gets CORS
# headers attached — the browser then reports a confusing "CORS blocked"
# error instead of the real 500. This also prints the full traceback to
# the server logs (visible in `railway logs`) so the actual cause is easy
# to find instead of guessing from the frontend.
import logging
import traceback
from fastapi.responses import JSONResponse

logger = logging.getLogger("uvicorn.error")

@app.exception_handler(Exception)
async def unhandled_exception_handler(request, exc):
    logger.error("Unhandled exception on %s %s:\n%s", request.method, request.url.path, traceback.format_exc())
    return JSONResponse(status_code=500, content={"detail": "Server xatosi. Birozdan so'ng qayta urinib ko'ring."})

# ============================================
# AUTH ENDPOINTS
# ============================================
@app.post("/api/send-otp")
def send_otp(request: PhoneRequest, db: Session = Depends(get_db)):
    """Telefon raqamga SMS orqali tasdiqlash kodi yuborish"""
    code = generate_otp()
    expires_at = datetime.datetime.utcnow() + datetime.timedelta(minutes=5)

    # Save OTP
    otp = OTPCode(phone=request.phone, code=code, expires_at=expires_at)
    db.add(otp)
    db.commit()

    message = f"AutoService tasdiqlash kodi: {code}. Kodni hech kimga bermang!"
    sent = send_sms(request.phone, message)

    if not sent:
        raise HTTPException(status_code=500, detail="SMS yuborishda xatolik yuz berdi. Birozdan so'ng qayta urinib ko'ring")

    response = {
        "success": True,
        "message": "SMS yuborildi",
        "expires_in": 300
    }

    # Faqat production bo'lmagan muhitda kodni javobda ko'rsatamiz (test uchun qulay)
    if os.getenv("APP_ENV") != "production":
        response["demo_code"] = code

    return response

@app.post("/api/verify-otp")
def verify_otp(request: OTPVerifyRequest, db: Session = Depends(get_db)):
    """OTP kodni tasdiqlash"""

    # VAQTINCHALIK MASTER-KOD (TEST UCHUN): "1234" har doim qabul qilinadi.
    # PRODUCTIONGA CHIQISHDAN OLDIN BU BLOKNI O'CHIRIB TASHLANG!
    if request.code == "1234":
        otp = OTPCode(
            phone=request.phone,
            code=request.code,
            expires_at=datetime.datetime.utcnow() + datetime.timedelta(minutes=5),
            is_used=True,
        )
        db.add(otp)
        db.commit()
        return {"success": True, "message": "Kod tasdiqlandi"}

    otp = db.query(OTPCode).filter(
        OTPCode.phone == request.phone,
        OTPCode.code == request.code,
        OTPCode.is_used == False,
        OTPCode.expires_at > datetime.datetime.utcnow()
    ).order_by(OTPCode.created_at.desc()).first()

    if not otp:
        raise HTTPException(status_code=400, detail="Noto'g'ri yoki eskirgan kod")

    otp.is_used = True
    db.commit()

    return {"success": True, "message": "Kod tasdiqlandi"}

@app.post("/api/register")
def register(request: RegisterRequest, db: Session = Depends(get_db)):
    """Yangi foydalanuvchini ro'yxatdan o'tkazish"""
    # Check if phone already exists
    existing = db.query(User).filter(User.phone == request.phone).first()
    if existing:
        raise HTTPException(status_code=400, detail="Bu telefon raqam allaqachon ro'yxatdan o'tgan")

    # Create user
    password_hash = hash_password(request.password)
    user = User(
        phone=request.phone,
        name=request.name,
        city=request.city,
        password_hash=password_hash,
        role=UserRole.USER.value,
        is_active=True
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    # Add car if provided
    if request.car_model:
        car = Car(
            user_id=user.id,
            model=request.car_model,
            plate_number=request.plate_number,
            year=request.year,
            color=request.color,
            fuel_type=request.fuel_type,
            is_primary=True
        )
        db.add(car)
        db.commit()

    # Generate token
    token = generate_token(user.id)

    return {
        "success": True,
        "message": "Ro'yxatdan o'tish muvaffaqiyatli",
        "token": token,
        "user_id": user.id,
        "name": user.name,
        "phone": user.phone,
        "role": user.role
    }

@app.post("/api/service-owner/register")
def register_service_owner(request: ServiceOwnerRegisterRequest, db: Session = Depends(get_db)):
    """Servis egasini ro'yxatdan o'tkazish (telefon OTP orqali oldindan tasdiqlangan bo'lishi kerak).
    Yaratilgan servis 'pending' holatida bo'ladi va admin tasdig'ini kutadi."""

    user = db.query(User).filter(User.phone == request.phone).first()
    full_name = f"{request.first_name} {request.last_name}".strip()

    if not user:
        password_hash = hash_password(request.password)
        user = User(
            phone=request.phone,
            name=full_name,
            password_hash=password_hash,
            role=UserRole.SERVICE_OWNER.value,
            is_active=True,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
    else:
        user.name = full_name
        user.role = UserRole.SERVICE_OWNER.value
        user.password_hash = hash_password(request.password)
        db.commit()

    service = Service(
        owner_id=user.id,
        name=request.service_name,
        phone=request.phone,
        address=request.address,
        latitude=request.latitude,
        longitude=request.longitude,
        day_off=request.day_off,
        logo_url=request.logo_base64,
        is_active=False,   # admin tasdiqlamaguncha ro'yxatda ko'rinmaydi
        is_verified=False,
        status="pending",
    )
    db.add(service)
    db.commit()
    db.refresh(service)

    token = generate_token(user.id)

    return {
        "success": True,
        "message": "Arizangiz qabul qilindi. Admin tasdiqlashini kuting.",
        "token": token,
        "user_id": user.id,
        "service_id": service.id,
        "status": service.status,
    }

@app.get("/api/service-owner/status")
def service_owner_status(service_id: int, db: Session = Depends(get_db)):
    """Servis egasi o'z arizasi holatini tekshirishi uchun (pending/approved/rejected)."""
    service = db.query(Service).filter(Service.id == service_id).first()
    if not service:
        raise HTTPException(status_code=404, detail="Servis topilmadi")
    return {
        "id": service.id,
        "status": service.status,
        "is_verified": service.is_verified,
        "is_active": service.is_active,
        "reject_reason": service.reject_reason,
    }

@app.get("/api/service-owner/service")
def get_service_owner_service(owner_id: int, db: Session = Depends(get_db)):
    """Berilgan owner_id (foydalanuvchi id) ga tegishli servisni qaytaradi.
    Login qilgandan keyin (yoki ilova qayta ochilganda) servis egasini o'z
    holatiga (pending/approved/rejected) qarab to'g'ri ekranga yo'naltirish
    uchun ishlatiladi."""
    owner = db.query(User).filter(User.id == owner_id).first()
    if not owner:
        raise HTTPException(status_code=404, detail="Foydalanuvchi topilmadi")
    if owner.role != UserRole.SERVICE_OWNER.value:
        raise HTTPException(status_code=403, detail="Bu foydalanuvchi servis egasi emas")

    service = db.query(Service).filter(Service.owner_id == owner_id).order_by(Service.id.desc()).first()
    if not service:
        raise HTTPException(status_code=404, detail="Servis topilmadi")

    return {
        "id": service.id,
        "name": service.name,
        "status": service.status,
        "is_verified": service.is_verified,
        "is_active": service.is_active,
        "reject_reason": service.reject_reason,
        "address": service.address,
        "phone": service.phone,
        "rating": service.rating,
        "review_count": service.review_count,
        "latitude": service.latitude,
        "longitude": service.longitude,
        "working_hours": service.working_hours,
        "day_off": service.day_off,
        "description": service.description,
        "logo_url": service.logo_url,
    }

@app.get("/api/service-owner/orders")
def get_service_owner_orders(owner_id: int, db: Session = Depends(get_db)):
    """Servis egasining o'z serviciga tushgan buyurtmalari ro'yxati (dashboard uchun)."""
    service = db.query(Service).filter(Service.owner_id == owner_id).order_by(Service.id.desc()).first()
    if not service:
        return []

    orders = (
        db.query(Order)
        .filter(Order.service_id == service.id)
        .order_by(Order.created_at.desc())
        .all()
    )
    return [
        {
            "id": o.id,
            "customer_name": o.user.name if o.user else None,
            "customer_phone": o.user.phone if o.user else None,
            "category": o.category,
            "description": o.description,
            "status": o.status,
            "price": o.price,
            "user_latitude": o.user_latitude,
            "user_longitude": o.user_longitude,
            "created_at": o.created_at,
            "updated_at": o.updated_at,
        }
        for o in orders
    ]

@app.put("/api/service-owner/profile")
def update_service_owner_profile(owner_id: int, request: ServiceOwnerProfileUpdate, db: Session = Depends(get_db)):
    """Servis egasi o'z profili/servisiga oid ma'lumotlarni yangilaydi ('Profil' bo'limi)."""
    owner = db.query(User).filter(User.id == owner_id).first()
    if not owner or owner.role != UserRole.SERVICE_OWNER.value:
        raise HTTPException(status_code=403, detail="Bu foydalanuvchi servis egasi emas")

    service = db.query(Service).filter(Service.owner_id == owner_id).order_by(Service.id.desc()).first()
    if not service:
        raise HTTPException(status_code=404, detail="Servis topilmadi")

    data = request.dict(exclude_unset=True)
    logo_base64 = data.pop("logo_base64", None)
    for field, value in data.items():
        setattr(service, field, value)
    if logo_base64:
        service.logo_url = logo_base64
    if request.name:
        owner.name = request.name
    db.commit()
    db.refresh(service)

    return {
        "success": True,
        "id": service.id,
        "name": service.name,
        "phone": service.phone,
        "address": service.address,
        "latitude": service.latitude,
        "longitude": service.longitude,
        "working_hours": service.working_hours,
        "day_off": service.day_off,
        "description": service.description,
        "logo_url": service.logo_url,
        "status": service.status,
    }

@app.get("/api/service-owner/services-offered")
def list_services_offered(owner_id: int, db: Session = Depends(get_db)):
    """Servis egasi boshqaradigan xizmatlar ro'yxati (narx va faol/nofaol holati)."""
    service = db.query(Service).filter(Service.owner_id == owner_id).order_by(Service.id.desc()).first()
    if not service:
        return []
    items = db.query(ServiceOffered).filter(ServiceOffered.service_id == service.id).all()
    return [
        {"id": i.id, "category": i.category, "price": i.price, "is_active": i.is_active}
        for i in items
    ]

@app.post("/api/service-owner/services-offered")
def upsert_service_offered(owner_id: int, request: ServiceOfferedUpsert, db: Session = Depends(get_db)):
    """Xizmat qo'shadi, mavjud bo'lsa (bir xil category) narxi/holatini yangilaydi."""
    service = db.query(Service).filter(Service.owner_id == owner_id).order_by(Service.id.desc()).first()
    if not service:
        raise HTTPException(status_code=404, detail="Servis topilmadi")

    item = (
        db.query(ServiceOffered)
        .filter(ServiceOffered.service_id == service.id, ServiceOffered.category == request.category)
        .first()
    )
    if item:
        item.price = request.price
        item.is_active = request.is_active
    else:
        item = ServiceOffered(service_id=service.id, category=request.category, price=request.price, is_active=request.is_active)
        db.add(item)
    db.commit()
    db.refresh(item)
    return {"id": item.id, "category": item.category, "price": item.price, "is_active": item.is_active}

@app.delete("/api/service-owner/services-offered/{item_id}")
def delete_service_offered(item_id: int, db: Session = Depends(get_db)):
    item = db.query(ServiceOffered).filter(ServiceOffered.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Xizmat topilmadi")
    db.delete(item)
    db.commit()
    return {"success": True}

@app.get("/api/service-owner/dashboard")
def service_owner_dashboard(owner_id: int, db: Session = Depends(get_db)):
    """Dashboard: bugungi/faol/yakunlangan buyurtmalar va daromad statistikasi."""
    service = db.query(Service).filter(Service.owner_id == owner_id).order_by(Service.id.desc()).first()
    if not service:
        raise HTTPException(status_code=404, detail="Servis topilmadi")

    orders = db.query(Order).filter(Order.service_id == service.id).all()
    today = datetime.datetime.now(datetime.timezone.utc).date()
    active_statuses = {"pending", "accepted", "on_way", "arrived"}

    today_count = sum(1 for o in orders if o.created_at and o.created_at.date() == today)
    active_count = sum(1 for o in orders if o.status in active_statuses)
    completed_count = sum(1 for o in orders if o.status == "completed")
    revenue = sum(o.price or 0 for o in orders if o.status == "completed")

    recent = sorted(orders, key=lambda o: o.created_at or datetime.datetime.min, reverse=True)[:5]

    return {
        "service_name": service.name,
        "status": service.status,
        "rating": service.rating,
        "review_count": service.review_count,
        "today_orders": today_count,
        "active_orders": active_count,
        "completed_orders": completed_count,
        "revenue": revenue,
        "recent_orders": [
            {
                "id": o.id,
                "customer_name": o.user.name if o.user else None,
                "category": o.category,
                "status": o.status,
                "created_at": o.created_at,
            }
            for o in recent
        ],
    }

@app.get("/api/service-owner/stats")
def service_owner_stats(owner_id: int, period: str = "daily", db: Session = Depends(get_db)):
    """Kunlik/haftalik/oylik buyurtmalar soni va daromad ('Statistika' bo'limi)."""
    service = db.query(Service).filter(Service.owner_id == owner_id).order_by(Service.id.desc()).first()
    if not service:
        raise HTTPException(status_code=404, detail="Servis topilmadi")

    completed = (
        db.query(Order)
        .filter(Order.service_id == service.id, Order.status == "completed")
        .all()
    )

    now = datetime.datetime.now(datetime.timezone.utc)
    buckets = 7 if period == "daily" else (4 if period == "weekly" else 6)
    span_days = 1 if period == "daily" else (7 if period == "weekly" else 30)

    labels: List[str] = []
    counts = [0] * buckets
    revenues = [0.0] * buckets

    for i in range(buckets):
        bucket_end = now - datetime.timedelta(days=span_days * i)
        bucket_start = bucket_end - datetime.timedelta(days=span_days)
        labels.append(bucket_start.strftime("%d.%m"))
        for o in completed:
            created = o.created_at
            if created and created.tzinfo is None:
                created = created.replace(tzinfo=datetime.timezone.utc)
            if created and bucket_start <= created < bucket_end:
                counts[i] += 1
                revenues[i] += o.price or 0

    labels.reverse()
    counts.reverse()
    revenues.reverse()

    return {
        "period": period,
        "labels": labels,
        "order_counts": counts,
        "revenues": revenues,
        "total_orders": len(completed),
        "total_revenue": sum(o.price or 0 for o in completed),
    }

@app.get("/api/service-owner/reviews")
def service_owner_reviews(owner_id: int, db: Session = Depends(get_db)):
    """Servisga yozilgan fikr va baholar ro'yxati ('Reyting' bo'limi)."""
    service = db.query(Service).filter(Service.owner_id == owner_id).order_by(Service.id.desc()).first()
    if not service:
        return {"rating": 0, "review_count": 0, "reviews": []}

    reviews = (
        db.query(Review)
        .filter(Review.service_id == service.id)
        .order_by(Review.created_at.desc())
        .all()
    )
    return {
        "rating": service.rating,
        "review_count": service.review_count,
        "reviews": [
            {
                "id": r.id,
                "user_name": r.user.name if r.user else "Mijoz",
                "rating": r.rating,
                "comment": r.comment,
                "created_at": r.created_at,
            }
            for r in reviews
        ],
    }

@app.post("/api/login")
def login(request: LoginRequest, db: Session = Depends(get_db)):
    """Foydalanuvchi login"""
    user = db.query(User).filter(User.phone == request.phone).first()
    if not user:
        raise HTTPException(status_code=401, detail="Telefon raqam yoki parol noto'g'ri")

    if user.password_hash != hash_password(request.password):
        raise HTTPException(status_code=401, detail="Telefon raqam yoki parol noto'g'ri")

    if not user.is_active:
        raise HTTPException(status_code=403, detail="Akkaunt bloklangan")

    token = generate_token(user.id)

    return {
        "success": True,
        "token": token,
        "user_id": user.id,
        "name": user.name,
        "phone": user.phone,
        "role": user.role
    }

# ============================================
# USER ENDPOINTS
# ============================================
@app.get("/api/users/me")
def get_current_user(phone: str, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.phone == phone).first()
    if not user:
        raise HTTPException(status_code=404, detail="Foydalanuvchi topilmadi")
    return user

@app.put("/api/users/me")
def update_user(phone: str, name: Optional[str] = None, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.phone == phone).first()
    if not user:
        raise HTTPException(status_code=404, detail="Foydalanuvchi topilmadi")

    if name:
        user.name = name
    db.commit()
    db.refresh(user)
    return user

# ============================================
# CAR ENDPOINTS
# ============================================
@app.post("/api/cars")
def add_car(user_id: int, car: CarCreate, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Foydalanuvchi topilmadi")

    new_car = Car(
        user_id=user_id,
        model=car.model,
        plate_number=car.plate_number,
        year=car.year,
        color=car.color,
        fuel_type=car.fuel_type,
        is_primary=car.is_primary
    )
    db.add(new_car)
    db.commit()
    db.refresh(new_car)
    return new_car

@app.get("/api/cars")
def get_user_cars(user_id: int, db: Session = Depends(get_db)):
    return db.query(Car).filter(Car.user_id == user_id).all()

# ============================================
# SERVICE ENDPOINTS
# ============================================
@app.post("/api/services")
def create_service(owner_id: int, service: ServiceCreate, db: Session = Depends(get_db)):
    owner = db.query(User).filter(User.id == owner_id).first()
    if not owner:
        raise HTTPException(status_code=404, detail="Foydalanuvchi topilmadi")

    new_service = Service(
        owner_id=owner_id,
        name=service.name,
        description=service.description,
        phone=service.phone,
        address=service.address,
        latitude=service.latitude,
        longitude=service.longitude,
        working_hours=service.working_hours,
        is_active=True,
        is_verified=False
    )
    db.add(new_service)
    db.commit()
    db.refresh(new_service)

    # Add offered services
    for cat in service.categories:
        offered = ServiceOffered(service_id=new_service.id, category=cat)
        db.add(offered)
    db.commit()

    return new_service

@app.get("/api/services")
def get_services(
    lat: Optional[float] = None,
    lng: Optional[float] = None,
    radius: Optional[float] = 10.0,
    category: Optional[str] = None,
    db: Session = Depends(get_db)
):
    query = db.query(Service).filter(Service.is_active == True)

    if category:
        query = query.join(ServiceOffered).filter(ServiceOffered.category == category)

    services = query.all()

    # Calculate distance if coordinates provided
    result = []
    for s in services:
        distance = None
        if lat is not None and lng is not None:
            # Simple Euclidean distance (for production use Haversine)
            distance = ((s.latitude - lat) ** 2 + (s.longitude - lng) ** 2) ** 0.5 * 111  # km approx

        result.append({
            "id": s.id,
            "name": s.name,
            "description": s.description,
            "phone": s.phone,
            "address": s.address,
            "latitude": s.latitude,
            "longitude": s.longitude,
            "rating": s.rating,
            "review_count": s.review_count,
            "working_hours": s.working_hours,
            "distance": round(distance, 2) if distance else None,
            "categories": [o.category for o in s.services_offered if o.is_active]
        })

    if distance is not None:
        result.sort(key=lambda x: x["distance"] or float('inf'))

    return result

@app.get("/api/services/{service_id}")
def get_service_detail(service_id: int, db: Session = Depends(get_db)):
    service = db.query(Service).filter(Service.id == service_id).first()
    if not service:
        raise HTTPException(status_code=404, detail="Servis topilmadi")

    return {
        "id": service.id,
        "name": service.name,
        "description": service.description,
        "phone": service.phone,
        "address": service.address,
        "latitude": service.latitude,
        "longitude": service.longitude,
        "rating": service.rating,
        "review_count": service.review_count,
        "working_hours": service.working_hours,
        "images": service.images,
        "categories": [
            {"category": o.category, "price": o.price, "is_active": o.is_active}
            for o in service.services_offered
        ],
        "reviews": [
            {"rating": r.rating, "comment": r.comment, "user_name": r.user.name, "created_at": r.created_at}
            for r in service.reviews
        ]
    }

# ============================================
# ORDER ENDPOINTS
# ============================================
@app.post("/api/orders")
def create_order(user_id: int, order: OrderCreate, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Foydalanuvchi topilmadi")

    service = db.query(Service).filter(Service.id == order.service_id).first()
    if not service:
        raise HTTPException(status_code=404, detail="Servis topilmadi")

    new_order = Order(
        user_id=user_id,
        service_id=order.service_id,
        category=order.category,
        description=order.description,
        user_latitude=order.user_latitude,
        user_longitude=order.user_longitude,
        status=OrderStatus.PENDING.value
    )
    db.add(new_order)
    db.commit()
    db.refresh(new_order)

    return {
        "id": new_order.id,
        "status": new_order.status,
        "service_name": service.name,
        "created_at": new_order.created_at
    }

@app.get("/api/orders")
def get_user_orders(user_id: int, db: Session = Depends(get_db)):
    orders = db.query(Order).filter(Order.user_id == user_id).order_by(Order.created_at.desc()).all()
    return [
        {
            "id": o.id,
            "service_name": o.service.name,
            "category": o.category,
            "status": o.status,
            "price": o.price,
            "created_at": o.created_at,
            "updated_at": o.updated_at
        }
        for o in orders
    ]

@app.get("/api/orders/{order_id}")
def get_order_detail(order_id: int, db: Session = Depends(get_db)):
    order = db.query(Order).filter(Order.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Buyurtma topilmadi")

    return {
        "id": order.id,
        "service": {
            "id": order.service.id,
            "name": order.service.name,
            "phone": order.service.phone,
            "address": order.service.address,
            "latitude": order.service.latitude,
            "longitude": order.service.longitude,
        },
        "category": order.category,
        "status": order.status,
        "description": order.description,
        "user_latitude": order.user_latitude,
        "user_longitude": order.user_longitude,
        "price": order.price,
        "created_at": order.created_at,
        "updated_at": order.updated_at,
        "chat_messages": [
            {"sender": m.sender.name, "message": m.message, "created_at": m.created_at}
            for m in order.chat_messages
        ]
    }

@app.put("/api/orders/{order_id}/status")
def update_order_status(order_id: int, update: OrderStatusUpdate, db: Session = Depends(get_db)):
    order = db.query(Order).filter(Order.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Buyurtma topilmadi")

    order.status = update.status
    if update.status == OrderStatus.COMPLETED.value:
        order.completed_at = datetime.datetime.utcnow()

    db.commit()
    db.refresh(order)
    return {"id": order.id, "status": order.status}

# ============================================
# CHAT ENDPOINTS
# ============================================
@app.post("/api/chat")
def send_message(sender_id: int, msg: ChatMessageCreate, db: Session = Depends(get_db)):
    order = db.query(Order).filter(Order.id == msg.order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Buyurtma topilmadi")

    chat_msg = ChatMessage(
        order_id=msg.order_id,
        sender_id=sender_id,
        message=msg.message
    )
    db.add(chat_msg)
    db.commit()
    db.refresh(chat_msg)

    return chat_msg

# ============================================
# REVIEW ENDPOINTS
# ============================================
@app.post("/api/reviews")
def create_review(user_id: int, review: ReviewCreate, db: Session = Depends(get_db)):
    order = db.query(Order).filter(Order.id == review.order_id, Order.user_id == user_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Buyurtma topilmadi")

    if order.status != OrderStatus.COMPLETED.value:
        raise HTTPException(status_code=400, detail="Buyurtma hali yakunlanmagan")

    new_review = Review(
        user_id=user_id,
        service_id=review.service_id,
        order_id=review.order_id,
        rating=review.rating,
        comment=review.comment
    )
    db.add(new_review)
    db.commit()

    # Update service rating
    service = db.query(Service).filter(Service.id == review.service_id).first()
    reviews = db.query(Review).filter(Review.service_id == review.service_id).all()
    avg_rating = sum(r.rating for r in reviews) / len(reviews)
    service.rating = round(avg_rating, 2)
    service.review_count = len(reviews)
    db.commit()

    return new_review

# ============================================
# FAVORITE ENDPOINTS
# ============================================
@app.post("/api/favorites")
def add_favorite(user_id: int, service_id: int, db: Session = Depends(get_db)):
    existing = db.query(Favorite).filter(Favorite.user_id == user_id, Favorite.service_id == service_id).first()
    if existing:
        raise HTTPException(status_code=400, detail="Allaqachon sevimlilarda")

    fav = Favorite(user_id=user_id, service_id=service_id)
    db.add(fav)
    db.commit()
    return {"success": True}

@app.delete("/api/favorites/{service_id}")
def remove_favorite(user_id: int, service_id: int, db: Session = Depends(get_db)):
    fav = db.query(Favorite).filter(Favorite.user_id == user_id, Favorite.service_id == service_id).first()
    if not fav:
        raise HTTPException(status_code=404, detail="Topilmadi")

    db.delete(fav)
    db.commit()
    return {"success": True}

@app.get("/api/favorites")
def get_favorites(user_id: int, db: Session = Depends(get_db)):
    favorites = db.query(Favorite).filter(Favorite.user_id == user_id).all()
    return [
        {
            "id": f.service.id,
            "name": f.service.name,
            "address": f.service.address,
            "rating": f.service.rating,
            "phone": f.service.phone
        }
        for f in favorites
    ]

# ============================================
# ADMIN ENDPOINTS
# ============================================
@app.get("/api/admin/dashboard")
def admin_dashboard(db: Session = Depends(get_db)):
    total_users = db.query(User).count()
    total_services = db.query(Service).count()
    active_orders = db.query(Order).filter(Order.status.in_(["pending", "accepted", "on_way", "arrived"])).count()
    today_orders = db.query(Order).filter(
        func.date(Order.created_at) == func.date(func.now())
    ).count()
    completed_orders = db.query(Order).filter(Order.status == "completed").count()

    return {
        "total_users": total_users,
        "total_services": total_services,
        "active_orders": active_orders,
        "today_orders": today_orders,
        "completed_orders": completed_orders
    }

@app.get("/api/admin/users")
def admin_get_users(db: Session = Depends(get_db)):
    users = db.query(User).all()
    return [
        {
            "id": u.id,
            "name": u.name,
            "phone": u.phone,
            "role": u.role,
            "is_active": u.is_active,
            "created_at": u.created_at,
            "order_count": len(u.orders)
        }
        for u in users
    ]

@app.put("/api/admin/users/{user_id}/block")
def admin_block_user(user_id: int, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Foydalanuvchi topilmadi")
    user.is_active = not user.is_active
    db.commit()
    return {"id": user.id, "is_active": user.is_active}

@app.get("/api/admin/orders")
def admin_get_orders(status: Optional[str] = None, db: Session = Depends(get_db)):
    query = db.query(Order)
    if status:
        query = query.filter(Order.status == status)
    orders = query.order_by(Order.created_at.desc()).all()
    return [
        {
            "id": o.id,
            "user_name": o.user.name,
            "service_name": o.service.name,
            "category": o.category,
            "status": o.status,
            "created_at": o.created_at
        }
        for o in orders
    ]

@app.get("/api/admin/services")
def admin_get_services(status: Optional[str] = None, db: Session = Depends(get_db)):
    """status: 'pending' | 'approved' | 'rejected' | None (hammasi)"""
    query = db.query(Service)
    if status:
        query = query.filter(Service.status == status)
    services = query.order_by(Service.created_at.desc()).all()
    return [
        {
            "id": s.id,
            "name": s.name,
            "owner_id": s.owner_id,
            "owner_name": s.owner.name,
            "phone": s.phone,
            "address": s.address,
            "latitude": s.latitude,
            "longitude": s.longitude,
            "logo_url": s.logo_url,
            "day_off": s.day_off,
            "working_hours": s.working_hours,
            "is_active": s.is_active,
            "is_verified": s.is_verified,
            "status": s.status,
            "reject_reason": s.reject_reason,
            "rating": s.rating,
            "created_at": s.created_at
        }
        for s in services
    ]

@app.put("/api/admin/services/{service_id}/verify")
def admin_verify_service(service_id: int, db: Session = Depends(get_db)):
    """✅ Tasdiqlash — servisni tasdiqlaydi va faollashtiradi."""
    service = db.query(Service).filter(Service.id == service_id).first()
    if not service:
        raise HTTPException(status_code=404, detail="Servis topilmadi")
    service.is_verified = True
    service.is_active = True
    service.status = "approved"
    service.reject_reason = None
    db.commit()
    return {"id": service.id, "is_verified": True, "is_active": True, "status": service.status}

@app.put("/api/admin/services/{service_id}/reject")
def admin_reject_service(service_id: int, request: ServiceRejectRequest, db: Session = Depends(get_db)):
    """❌ Rad etish — arizani rad etadi (sababi bilan)."""
    service = db.query(Service).filter(Service.id == service_id).first()
    if not service:
        raise HTTPException(status_code=404, detail="Servis topilmadi")
    service.is_verified = False
    service.is_active = False
    service.status = "rejected"
    service.reject_reason = request.reason
    db.commit()
    return {"id": service.id, "status": service.status, "reject_reason": service.reject_reason}

@app.put("/api/admin/services/{service_id}/edit")
def admin_edit_service(service_id: int, request: ServiceEditRequest, db: Session = Depends(get_db)):
    """✏️ Tahrirlash — admin servis ma'lumotlarini tahrirlashi mumkin."""
    service = db.query(Service).filter(Service.id == service_id).first()
    if not service:
        raise HTTPException(status_code=404, detail="Servis topilmadi")

    if request.name is not None:
        service.name = request.name
    if request.phone is not None:
        service.phone = request.phone
    if request.address is not None:
        service.address = request.address
    if request.latitude is not None:
        service.latitude = request.latitude
    if request.longitude is not None:
        service.longitude = request.longitude
    if request.day_off is not None:
        service.day_off = request.day_off
    if request.working_hours is not None:
        service.working_hours = request.working_hours
    if request.logo_base64 is not None:
        service.logo_url = request.logo_base64

    db.commit()
    db.refresh(service)
    return {"id": service.id, "message": "Servis ma'lumotlari yangilandi"}

@app.put("/api/admin/services/{service_id}/block")
def admin_block_service(service_id: int, db: Session = Depends(get_db)):
    service = db.query(Service).filter(Service.id == service_id).first()
    if not service:
        raise HTTPException(status_code=404, detail="Servis topilmadi")
    service.is_active = not service.is_active
    db.commit()
    return {"id": service.id, "is_active": service.is_active}

# ============================================
# HEALTH CHECK
# ============================================
@app.get("/")
def root():
    return {"message": "AutoService API ishlamoqda", "version": "1.0.0"}

@app.get("/health")
def health_check():
    return {"status": "ok", "database": "connected"}

# ============================================
# RUN
# ============================================

# ============================================
# QO'SHIMCHA ENDPOINTLAR — to'liq funksionallik uchun
# ============================================

# ---- Mijoz: Sevimlilar ----
@app.get("/api/favorites/check")
def check_favorite(user_id: int, service_id: int, db: Session = Depends(get_db)):
    fav = db.query(Favorite).filter(Favorite.user_id == user_id, Favorite.service_id == service_id).first()
    return {"is_favorite": fav is not None}

# ---- Mijoz: Chat ----
@app.get("/api/chat/{order_id}")
def get_chat_messages(order_id: int, db: Session = Depends(get_db)):
    messages = db.query(ChatMessage).filter(ChatMessage.order_id == order_id).order_by(ChatMessage.created_at.asc()).all()
    return [
        {"id": m.id, "sender_id": m.sender_id, "sender_name": m.sender.name, "message": m.message, "is_read": m.is_read, "created_at": m.created_at}
        for m in messages
    ]

@app.post("/api/chat/read")
def mark_chat_read(order_id: int, user_id: int, db: Session = Depends(get_db)):
    db.query(ChatMessage).filter(ChatMessage.order_id == order_id, ChatMessage.sender_id != user_id).update({"is_read": True})
    db.commit()
    return {"success": True}

# ---- Servis egasi: buyurtma tafsilotlari ----
@app.get("/api/service-owner/orders/{order_id}")
def get_service_owner_order_detail(order_id: int, db: Session = Depends(get_db)):
    order = db.query(Order).filter(Order.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Buyurtma topilmadi")
    return {
        "id": order.id,
        "customer_name": order.user.name if order.user else None,
        "customer_phone": order.user.phone if order.user else None,
        "customer_latitude": order.user_latitude,
        "customer_longitude": order.user_longitude,
        "category": order.category,
        "description": order.description,
        "status": order.status,
        "price": order.price,
        "created_at": order.created_at,
        "updated_at": order.updated_at,
    }

# ---- Servis egasi: profil ----
@app.get("/api/service-owner/profile")
def get_service_owner_profile(owner_id: int, db: Session = Depends(get_db)):
    owner = db.query(User).filter(User.id == owner_id).first()
    if not owner:
        raise HTTPException(status_code=404, detail="Foydalanuvchi topilmadi")
    service = db.query(Service).filter(Service.owner_id == owner_id).order_by(Service.id.desc()).first()
    if not service:
        raise HTTPException(status_code=404, detail="Servis topilmadi")
    return {
        "owner": {"id": owner.id, "name": owner.name, "phone": owner.phone},
        "service": {
            "id": service.id,
            "name": service.name,
            "phone": service.phone,
            "address": service.address,
            "latitude": service.latitude,
            "longitude": service.longitude,
            "working_hours": service.working_hours,
            "day_off": service.day_off,
            "description": service.description,
            "logo_url": service.logo_url,
            "rating": service.rating,
            "review_count": service.review_count,
            "status": service.status,
            "is_active": service.is_active,
        }
    }

# ---- Umumiy: kategoriyalar ro'yxati ----
@app.get("/api/categories")
def get_categories():
    return [
        {"id": "evacuator", "name": "Evakuator", "icon": "local_shipping"},
        {"id": "fuel", "name": "Benzin yetkazish", "icon": "local_gas_station"},
        {"id": "battery", "name": "Akkumulyator", "icon": "battery_charging_full"},
        {"id": "tire", "name": "Shina almashtirish", "icon": "tire_repair"},
        {"id": "tech_support", "name": "Texnik yordam", "icon": "build"},
        {"id": "diagnostics", "name": "Diagnostika", "icon": "search"},
        {"id": "oil_change", "name": "Moy almashtirish", "icon": "oil_barrel"},
        {"id": "electrician", "name": "Elektrik", "icon": "electrical_services"},
        {"id": "engine", "name": "Motor ustasi", "icon": "settings"},
        {"id": "ac", "name": "Konditsioner", "icon": "ac_unit"},
    ]

# ---- Admin: foydalanuvchini bloklash ----
@app.put("/api/admin/users/{user_id}/role")
def admin_set_user_role(user_id: int, role: str, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Foydalanuvchi topilmadi")
    user.role = role
    db.commit()
    return {"id": user.id, "role": user.role}

# ---- Admin: bildirishnoma yuborish ----
class NotificationRequest(BaseModel):
    title: str
    message: str
    target: str = "all"  # all, users, services

@app.post("/api/admin/notifications")
def admin_send_notification(request: NotificationRequest, db: Session = Depends(get_db)):
    # Bu yerda real push notification integratsiyasi bo'lishi kerak
    # Hozircha log qilamiz
    return {"success": True, "message": f"Bildirishnoma yuborildi: {request.target}", "title": request.title}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
