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
    ACCEPTED = "accepted"         # 🔵 Qabul qilindi (mijoz o'zi servisga boradi)
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
    address = Column(String(500), nullable=True)
    latitude = Column(Float, nullable=True)
    longitude = Column(Float, nullable=True)
    logo_url = Column(Text, nullable=True)  # stores base64 data-URL, can be very long (auto-service uchun logotip, evakuator/benzin uchun mashina rasmi)
    images = Column(Text, nullable=True)  # JSON array of image URLs
    working_hours = Column(String(100), nullable=True)  # e.g., "09:00-18:00"
    day_off = Column(String(50), nullable=True)  # e.g., "Yakshanba"
    # Evakuator/benzin dastavka uchun: mashina rusmi/turi (masalan "Isuzu evakuator", "Damas sisterna").
    # auto_service uchun ishlatilmaydi.
    car_model = Column(String(200), nullable=True)
    # Evakuator/benzin dastavka uchun: xizmat narxi - FAQAT admin belgilaydi
    # (auto_service uchun ishlatilmaydi, chunki uning narxlari ServiceType/
    # ServiceOffered orqali kategoriyalar bo'yicha belgilanadi).
    price = Column(Float, nullable=True)
    rating = Column(Float, default=0.0)
    review_count = Column(Integer, default=0)
    is_active = Column(Boolean, default=True)
    is_verified = Column(Boolean, default=False)
    # Admin moderation workflow: pending -> approved / rejected
    status = Column(String(20), default="pending")
    reject_reason = Column(Text, nullable=True)
    # "auto_service" (oddiy avtoservis), "evacuator" (evakuator), "fuel" (benzin dastavka).
    # Evakuator va benzin dastavka - alohida turdagi provayderlar bo'lib, har doim
    # asosiy kategoriyalar ro'yxatida ko'rinadi va o'z ro'yxatdan o'tish oqimiga ega.
    provider_type = Column(String(20), default="auto_service")
    # Evakuator/benzin dastavka uchun: haydovchi ish boshlagan/tugatganini va
    # joriy (jonli) joylashuvini kuzatish. auto_service uchun ishlatilmaydi -
    # avtoservis xaritada har doim ko'rinadi.
    is_online = Column(Boolean, default=False)
    current_latitude = Column(Float, nullable=True)
    current_longitude = Column(Float, nullable=True)
    location_updated_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    owner = relationship("User")
    services_offered = relationship("ServiceOffered", back_populates="service", cascade="all, delete-orphan")
    orders = relationship("Order", back_populates="service")
    reviews = relationship("Review", back_populates="service")
    favorites = relationship("Favorite", back_populates="service")

class ServiceType(Base):
    """
    Admin tomonidan boshqariladigan umumiy xizmat turlari katalogi (masalan
    "Motor diagnostikasi", "AC to'ldirish" va h.k). Nomi va narxini FAQAT admin
    belgilaydi. Servis egalari bu katalogdan o'zida mavjud bo'lgan turlarni
    tanlab (belgilab) qo'yishi mumkin - ular narx yoki nom kirita olmaydi.
    """
    __tablename__ = "service_types"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(200), nullable=False)  # xizmat turi nomi - admin belgilaydi
    price = Column(Float, nullable=True)  # narxi - admin belgilaydi
    icon = Column(String(50), default="build")  # frontendda ko'rsatiladigan ikonka nomi
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    services_offered = relationship("ServiceOffered", back_populates="service_type")

class ServiceOffered(Base):
    """
    Bitta avtoservis taklif qiladigan xizmat turi. Xizmat turining nomi va narxi
    endi admin boshqaradigan ServiceType katalogidan olinadi (service_type_id) -
    servis egasi faqat o'zida mavjud turlarni belgilab (yoqib/o'chirib) qo'yadi.
    Admin katalogidan tanlangani uchun bunday yozuvlar darhol 'approved' holatda
    yaratiladi - qo'shimcha tasdiqlash shart emas. (Eski erkin-matnli yozuvlar
    bilan orqaga moslik uchun `category` va pending/rejected oqimi saqlab qolindi.)
    """
    __tablename__ = "services_offered"

    id = Column(Integer, primary_key=True, index=True)
    service_id = Column(Integer, ForeignKey("services.id"), nullable=False)
    service_type_id = Column(Integer, ForeignKey("service_types.id"), nullable=True)
    category = Column(String(200), nullable=False)  # xizmat nomi (service_type.name dan nusxa)
    price = Column(Float, nullable=True)
    is_active = Column(Boolean, default=True)
    # Tasdiqlash oqimi: pending -> approved / rejected (eski erkin-matn oqimi uchun)
    status = Column(String(20), default="pending")
    reject_reason = Column(Text, nullable=True)
    added_by_admin = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    service = relationship("Service", back_populates="services_offered")
    service_type = relationship("ServiceType", back_populates="services_offered")

class PricingSettings(Base):
    """
    Evakuator va benzin dastavka uchun GLOBAL narxlar - har bir alohida
    provayder emas, balki admin panelidan bitta joyda butun tizim uchun
    belgilanadi. Har doim yagona qator (id=1) sifatida saqlanadi.
    - evacuator_price: evakuator chaqirish uchun belgilangan narx (so'm).
    - fuel_delivery_fee: benzin yetkazib berish xizmati uchun narx (so'm).
    - fuel_price_per_liter: benzinning har bir litri uchun narx (so'm/litr).
    """
    __tablename__ = "pricing_settings"

    id = Column(Integer, primary_key=True, default=1)
    evacuator_price = Column(Float, default=0)
    fuel_delivery_fee = Column(Float, default=120000)
    fuel_price_per_liter = Column(Float, default=16000)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

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
    # Faqat benzin dastavka (category == "fuel") buyurtmalari uchun: mijoz
    # so'ragan benzin miqdori (litr). Narx shundan kelib chiqib hisoblanadi:
    # price = fuel_delivery_fee + liters * fuel_price_per_liter.
    liters = Column(Float, nullable=True)
    # "now" - mijoz hozir servisga o'zi boradi/chaqiradi (darhol xizmat).
    # "scheduled" - mijoz kelajakdagi sana/vaqtga bron qilyapti.
    # Faqat auto_service (oddiy avtoservis) buyurtmalari uchun ma'noga ega -
    # evakuator/benzin dastavka har doim "now" bo'ladi.
    order_type = Column(String(20), default="now", nullable=False)
    # order_type == "scheduled" bo'lganda mijoz tanlagan sana va vaqt.
    scheduled_at = Column(DateTime(timezone=True), nullable=True)
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

class Notification(Base):
    """
    Ilova ichidagi bildirishnomalar (push emas). Buyurtma holati o'zgarganda,
    yangi chat xabari kelganda, admin umumiy xabar yuborganda va h.k. shu
    jadvalga yozuv qo'shiladi. Foydalanuvchi/servis egasi qo'ng'iroqcha (bell)
    ikonkasi orqali ro'yxatini ko'radi.
    """
    __tablename__ = "notifications"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    title = Column(String(200), nullable=False)
    message = Column(Text, nullable=False)
    # "order_status", "new_order", "chat", "admin", "review" va h.k.
    type = Column(String(30), default="admin")
    related_id = Column(Integer, nullable=True)  # order_id yoki boshqa tegishli yozuv id'si
    is_read = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    user = relationship("User")

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
# ONE-OFF FIX: widen services_offered.category to VARCHAR(200)
# ============================================
# This used to hold a fixed short category slug (e.g. "battery"); now it
# holds a free-text custom service name typed by the service owner, which
# can be longer than the old VARCHAR(50) limit.
def widen_services_offered_category_column():
    import logging
    from sqlalchemy import inspect, text

    inspector = inspect(engine)
    if "services_offered" not in inspector.get_table_names():
        return
    columns = {col["name"]: col for col in inspector.get_columns("services_offered")}
    cat_col = columns.get("category")
    if cat_col is None:
        return
    if "VARCHAR(50)" in str(cat_col["type"]).upper():
        with engine.begin() as conn:
            conn.execute(text('ALTER TABLE "services_offered" ALTER COLUMN "category" TYPE VARCHAR(200)'))
        logging.getLogger("uvicorn.error").warning(
            "[auto-migration] widened services_offered.category from VARCHAR(50) to VARCHAR(200)"
        )

widen_services_offered_category_column()

# ============================================
# SEED: evakuator/benzin dastavka uchun global narxlar (bitta qator)
# ============================================
def seed_pricing_settings():
    from sqlalchemy.orm import Session as _Session
    db = _Session(bind=engine)
    try:
        existing = db.query(PricingSettings).filter(PricingSettings.id == 1).first()
        if existing is None:
            db.add(PricingSettings(id=1, evacuator_price=0, fuel_delivery_fee=120000, fuel_price_per_liter=16000))
            db.commit()
    finally:
        db.close()

seed_pricing_settings()

# ============================================
# ONE-OFF FIX: services.address/latitude/longitude -> NULLABLE
# ============================================
# Evakuator va benzin dastavka provayderlari ro'yxatdan o'tishda manzil/xarita
# nuqtasini kiritmaydi (faqat auto_service uchun majburiy). Ustunlar avval
# NOT NULL edi - buni bazada ham gevshatish kerak, aks holda evakuator/fuel
# ro'yxatdan o'tishda NotNullViolation xatosi chiqadi.
def relax_service_location_columns():
    import logging
    from sqlalchemy import inspect, text

    inspector = inspect(engine)
    if "services" not in inspector.get_table_names():
        return
    columns = {col["name"]: col for col in inspector.get_columns("services")}
    with engine.begin() as conn:
        for col_name in ("address", "latitude", "longitude"):
            col = columns.get(col_name)
            if col is not None and col.get("nullable") is False:
                conn.execute(text(f'ALTER TABLE "services" ALTER COLUMN "{col_name}" DROP NOT NULL'))
                logging.getLogger("uvicorn.error").warning(
                    f"[auto-migration] relaxed services.{col_name} to NULLABLE"
                )

relax_service_location_columns()

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

    @validator('phone')
    def validate_phone(cls, v):
        # Ro'yxatdan o'tishdagi (RegisterRequest) bilan bir xil normalizatsiya.
        # Avval bu yerda validator yo'q edi, shuning uchun agar mijoz telefon
        # raqamni biroz boshqacharoq formatda yuborsa (probel/tire farqi va h.k.),
        # baza bo'yicha aniq (==) qidiruv mos kelmay, "Telefon raqam yoki parol
        # noto'g'ri" xatosi chiqardi - garchi ma'lumotlar to'g'ri bo'lsa ham.
        v = v.replace(' ', '').replace('-', '')
        if not v.startswith('+'):
            raise ValueError('Telefon raqam + bilan boshlanishi kerak')
        return v

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
    provider_type: str = "auto_service"

class ServiceOwnerRegisterRequest(BaseModel):
    phone: str
    first_name: str
    last_name: str
    password: str = Field(..., min_length=6)
    # auto_service uchun majburiy (servis nomi va manzili). Evakuator/fuel uchun
    # bular kerak emas - o'rniga car_model va working_hours ishlatiladi.
    service_name: Optional[str] = None
    address: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    day_off: Optional[str] = None
    working_hours: Optional[str] = None  # masalan "09:00-18:00" - evakuator/fuel ro'yxatdan o'tishda kiritiladi
    logo_base64: Optional[str] = None  # auto_service: servis logotipi. evacuator/fuel: mashina rasmi
    car_model: Optional[str] = None  # evakuator/fuel uchun: mashina rusmi/turi
    # "auto_service" | "evacuator" | "fuel" - qaysi turdagi provayder sifatida
    # royxatdan otayotgani.
    provider_type: str = "auto_service"

    @validator('phone')
    def validate_phone(cls, v):
        v = v.replace(' ', '').replace('-', '')
        if not v.startswith('+'):
            raise ValueError('Telefon raqam + bilan boshlanishi kerak')
        return v

class ServiceEditRequest(BaseModel):
    name: Optional[str] = None
    owner_name: Optional[str] = None  # servis egasi/haydovchining to'liq ismi (Users.name)
    phone: Optional[str] = None
    address: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    day_off: Optional[str] = None
    working_hours: Optional[str] = None
    car_model: Optional[str] = None  # evakuator/fuel uchun: mashina rusmi/turi
    price: Optional[float] = None  # evakuator/fuel uchun: xizmat narxi - admin belgilaydi
    logo_base64: Optional[str] = None

class LocationUpdateRequest(BaseModel):
    latitude: float
    longitude: float

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
    """Servis egasi 'Xizmatlarni boshqarish' bo'limida yangi xizmat (erkin nomli)
    qo'shadi yoki mavjudining narxi/holatini yangilaydi. Yangi xizmat har doim
    admin tasdiqlashini kutadigan 'pending' holatda yaratiladi."""
    category: str  # xizmat nomi, masalan "Motor diagnostikasi" (erkin matn)
    price: Optional[float] = None
    is_active: bool = True

class ServiceOfferedRejectRequest(BaseModel):
    reason: Optional[str] = None

class ServiceTypeCreate(BaseModel):
    """Admin yangi xizmat turi qo'shadi - nomi va narxini admin belgilaydi."""
    name: str
    price: Optional[float] = None
    icon: Optional[str] = "build"

class ServiceTypeUpdate(BaseModel):
    """Admin mavjud xizmat turini tahrirlaydi (nomi, narxi, ikonkasi, holati)."""
    name: Optional[str] = None
    price: Optional[float] = None
    icon: Optional[str] = None
    is_active: Optional[bool] = None

class ServiceOwnerTypeToggle(BaseModel):
    """Servis egasi admin katalogidagi xizmat turini o'zida bor/yo'qligini belgilaydi.
    Nomi va narxini o'zi kirita olmaydi - bular katalogdan (ServiceType) olinadi."""
    service_type_id: int
    is_active: bool = True

class AdminAddOfferedServiceRequest(BaseModel):
    """Admin xohlagan servis egasiga (service_id orqali) to'g'ridan-to'g'ri
    xizmat qo'shadi - bunday yozuv avtomatik 'approved' holatda yaratiladi."""
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
    # Faqat category == "fuel" (benzin dastavka) uchun: nechi litr kerakligi.
    # Narx shu asosda avtomatik hisoblanadi (global narxlar sozlamalaridan).
    liters: Optional[float] = None
    # "now" (hozir borish) yoki "scheduled" (bron qilish).
    order_type: str = "now"
    # order_type == "scheduled" bo'lganda majburiy - ISO 8601 format
    # (masalan "2026-08-01T14:00:00").
    scheduled_at: Optional[datetime.datetime] = None

    @validator("order_type")
    def validate_order_type(cls, v):
        if v not in ("now", "scheduled"):
            raise ValueError("order_type faqat 'now' yoki 'scheduled' bo'lishi mumkin")
        return v

    @validator("scheduled_at", always=True)
    def validate_scheduled_at(cls, v, values):
        order_type = values.get("order_type", "now")
        if order_type == "scheduled":
            if v is None:
                raise ValueError("Bron qilish uchun sana va vaqtni tanlang")
            now = datetime.datetime.now(v.tzinfo) if v.tzinfo else datetime.datetime.now()
            if v <= now:
                raise ValueError("Bron vaqti kelajakda bo'lishi kerak")
        return v

class PricingUpdate(BaseModel):
    evacuator_price: Optional[float] = None
    fuel_delivery_fee: Optional[float] = None
    fuel_price_per_liter: Optional[float] = None

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

# ============================================
# BILDIRISHNOMA YORDAMCHI FUNKSIYASI
# ============================================
def create_notification(db: Session, user_id: int, title: str, message: str, type: str = "admin", related_id: Optional[int] = None):
    """Ilova ichidagi bildirishnoma yaratadi. Xatolik bo'lsa asosiy amalni buzmaslik uchun jimgina o'tkazib yuboradi."""
    try:
        notif = Notification(
            user_id=user_id,
            title=title,
            message=message,
            type=type,
            related_id=related_id,
        )
        db.add(notif)
        db.commit()
    except Exception as e:
        logging.error(f"Bildirishnoma yaratishda xatolik: {e}")
        db.rollback()

ORDER_STATUS_LABELS = {
    "pending": "Kutilmoqda",
    "accepted": "Qabul qilindi",
    "completed": "Yakunlandi",
    "cancelled": "Bekor qilindi",
}

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
    """Servis egasini / evakuator / benzin dastavka provayderini ro'yxatdan o'tkazish
    (telefon OTP orqali oldindan tasdiqlangan bo'lishi kerak). Yaratilgan servis
    'pending' holatida bo'ladi va admin tasdig'ini kutadi."""

    if request.provider_type not in ("auto_service", "evacuator", "fuel"):
        raise HTTPException(status_code=400, detail="Noto'g'ri provider_type")

    if request.provider_type == "auto_service":
        if not request.service_name or not request.address or request.latitude is None or request.longitude is None:
            raise HTTPException(status_code=400, detail="Servis nomi va manzil kiritilishi shart")
    else:
        if not request.car_model:
            raise HTTPException(status_code=400, detail="Mashina rusmi (turi) kiritilishi shart")

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

    # Evakuator/fuel uchun alohida "servis nomi" kiritilmaydi - haydovchi ismi
    # to'liq nomi sifatida ishlatiladi (masalan mijozga "Evakuator - Bobur Aliyev" kabi ko'rsatish uchun).
    display_name = request.service_name.strip() if request.service_name else full_name

    service = Service(
        owner_id=user.id,
        name=display_name,
        phone=request.phone,
        address=request.address,
        latitude=request.latitude,
        longitude=request.longitude,
        day_off=request.day_off,
        working_hours=request.working_hours,
        logo_url=request.logo_base64,
        car_model=request.car_model,
        provider_type=request.provider_type,
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
        "provider_type": service.provider_type,
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
        "provider_type": service.provider_type,
        "car_model": service.car_model,
        "is_online": service.is_online,
        "current_latitude": service.current_latitude,
        "current_longitude": service.current_longitude,
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

    def _car_info(o):
        # Mijozning asosiy (yoki birinchi) mashinasi - evakuator/benzin dastavka
        # buyurtma qabul qilishdan oldin mashina turini ko'rishi uchun.
        if not o.user:
            return None
        car = (
            db.query(Car)
            .filter(Car.user_id == o.user_id)
            .order_by(Car.is_primary.desc(), Car.id.desc())
            .first()
        )
        if not car:
            return None
        parts = [car.model]
        if car.color:
            parts.append(car.color)
        return " · ".join(p for p in parts if p)

    return [
        {
            "id": o.id,
            "customer_name": o.user.name if o.user else None,
            "customer_phone": o.user.phone if o.user else None,
            "category": o.category,
            "description": o.description,
            "status": o.status,
            "price": o.price,
            "order_type": o.order_type,
            "scheduled_at": o.scheduled_at,
            "user_latitude": o.user_latitude,
            "user_longitude": o.user_longitude,
            "car_info": _car_info(o),
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
    """Servis egasi boshqaradigan xizmatlar ro'yxati (narx, holat va tasdiqlash statusi).
    Bu yerda pending/rejected xizmatlar ham ko'rsatiladi - servis egasi ularning
    holatini ko'rib turishi uchun. Foydalanuvchilarga esa faqat 'approved' bo'lganlari
    chiqadi (bunga /api/services va /api/services/{id} javob beradi)."""
    service = db.query(Service).filter(Service.owner_id == owner_id).order_by(Service.id.desc()).first()
    if not service:
        return []
    items = db.query(ServiceOffered).filter(ServiceOffered.service_id == service.id).order_by(ServiceOffered.id.desc()).all()
    return [
        {
            "id": i.id,
            "category": i.category,
            "price": i.price,
            "is_active": i.is_active,
            "status": i.status,
            "reject_reason": i.reject_reason,
            "added_by_admin": i.added_by_admin,
            "service_type_id": i.service_type_id,
        }
        for i in items
    ]

@app.post("/api/service-owner/services-offered")
def upsert_service_offered(owner_id: int, request: ServiceOfferedUpsert, db: Session = Depends(get_db)):
    """Yangi xizmat qo'shadi (har doim 'pending' holatda - admin tasdiqlashi kerak),
    yoki mavjud bo'lsa (bir xil nom) narxi/faol-nofaol holatini yangilaydi (bu holat
    o'zgarishi qayta tasdiqlashni talab qilmaydi)."""
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
        item = ServiceOffered(
            service_id=service.id,
            category=request.category,
            price=request.price,
            is_active=request.is_active,
            status="pending",
            added_by_admin=False,
        )
        db.add(item)
    db.commit()
    db.refresh(item)
    return {
        "id": item.id,
        "category": item.category,
        "price": item.price,
        "is_active": item.is_active,
        "status": item.status,
    }

@app.delete("/api/service-owner/services-offered/{item_id}")
def delete_service_offered(item_id: int, db: Session = Depends(get_db)):
    item = db.query(ServiceOffered).filter(ServiceOffered.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Xizmat topilmadi")
    db.delete(item)
    db.commit()
    return {"success": True}

# ============================================
# XIZMAT TURLARI KATALOGI (ServiceType)
# ============================================
# Nomi va narxini FAQAT admin belgilaydi. Servis egalari shu katalogdan
# o'zida mavjud bo'lgan turlarni tanlab (belgilab) qo'yadi, foydalanuvchilar
# esa shu turlar bo'yicha qidiradi/filtrlaydi.

@app.get("/api/service-types")
def list_active_service_types(db: Session = Depends(get_db)):
    """Barcha faol xizmat turlari (servis egalari tanlashi va foydalanuvchilar
    ko'rishi uchun ochiq ro'yxat)."""
    types = db.query(ServiceType).filter(ServiceType.is_active == True).order_by(ServiceType.id.asc()).all()
    return [{"id": t.id, "name": t.name, "price": t.price, "icon": t.icon} for t in types]

@app.get("/api/service-owner/service-types")
def list_service_types_for_owner(owner_id: int, db: Session = Depends(get_db)):
    """Servis egasi uchun: admin katalogidagi barcha faol xizmat turlari,
    har biri uchun shu servisda yoqilgan/yoqilmaganligi bilan birga."""
    service = db.query(Service).filter(Service.owner_id == owner_id).order_by(Service.id.desc()).first()
    selected = {}
    if service:
        offered = db.query(ServiceOffered).filter(
            ServiceOffered.service_id == service.id, ServiceOffered.service_type_id.isnot(None)
        ).all()
        selected = {o.service_type_id: o for o in offered}

    types = db.query(ServiceType).filter(ServiceType.is_active == True).order_by(ServiceType.id.asc()).all()
    return [
        {
            "id": t.id,
            "name": t.name,
            "price": t.price,
            "icon": t.icon,
            "is_selected": t.id in selected and selected[t.id].is_active,
        }
        for t in types
    ]

@app.post("/api/service-owner/service-types")
def toggle_service_type(owner_id: int, request: ServiceOwnerTypeToggle, db: Session = Depends(get_db)):
    """Servis egasi admin katalogidagi bir xizmat turini o'zida bor deb belgilaydi
    (yoki o'chiradi). Nomi va narxi katalogdan (ServiceType) ko'chiriladi - servis
    egasi ularni o'zgartira olmaydi. Katalogdan tanlangani uchun darhol 'approved'
    holatda saqlanadi - qo'shimcha admin tasdiqlash shart emas."""
    service = db.query(Service).filter(Service.owner_id == owner_id).order_by(Service.id.desc()).first()
    if not service:
        raise HTTPException(status_code=404, detail="Servis topilmadi")

    stype = db.query(ServiceType).filter(ServiceType.id == request.service_type_id).first()
    if not stype:
        raise HTTPException(status_code=404, detail="Xizmat turi topilmadi")

    item = (
        db.query(ServiceOffered)
        .filter(ServiceOffered.service_id == service.id, ServiceOffered.service_type_id == stype.id)
        .first()
    )
    if item:
        item.is_active = request.is_active
        item.category = stype.name
        item.price = stype.price
        item.status = "approved"
        item.reject_reason = None
    else:
        item = ServiceOffered(
            service_id=service.id,
            service_type_id=stype.id,
            category=stype.name,
            price=stype.price,
            is_active=request.is_active,
            status="approved",
            added_by_admin=False,
        )
        db.add(item)
    db.commit()
    db.refresh(item)
    return {
        "id": item.id,
        "service_type_id": stype.id,
        "category": item.category,
        "price": item.price,
        "is_active": item.is_active,
    }

# ============================================
# ADMIN: XIZMAT TURLARI KATALOGINI BOSHQARISH
# ============================================

@app.get("/api/admin/service-types")
def admin_list_service_types(db: Session = Depends(get_db)):
    """Admin panelidagi xizmat turlari katalogi - faol va nofaol turlar ham chiqadi."""
    types = db.query(ServiceType).order_by(ServiceType.id.desc()).all()
    return [
        {"id": t.id, "name": t.name, "price": t.price, "icon": t.icon, "is_active": t.is_active}
        for t in types
    ]

@app.post("/api/admin/service-types")
def admin_create_service_type(request: ServiceTypeCreate, db: Session = Depends(get_db)):
    """Admin yangi xizmat turi (nomi va narxi bilan) qo'shadi."""
    name = request.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Xizmat turi nomi bo'sh bo'lishi mumkin emas")
    existing = db.query(ServiceType).filter(func.lower(ServiceType.name) == name.lower()).first()
    if existing:
        raise HTTPException(status_code=400, detail="Bu nomdagi xizmat turi allaqachon mavjud")
    stype = ServiceType(name=name, price=request.price, icon=request.icon or "build", is_active=True)
    db.add(stype)
    db.commit()
    db.refresh(stype)
    return {"id": stype.id, "name": stype.name, "price": stype.price, "icon": stype.icon, "is_active": stype.is_active}

@app.put("/api/admin/service-types/{type_id}")
def admin_update_service_type(type_id: int, request: ServiceTypeUpdate, db: Session = Depends(get_db)):
    """Admin mavjud xizmat turini (nomi/narxi/ikonkasi/holati) tahrirlaydi.
    O'zgarish shu turni tanlagan barcha servislarga ham darhol qo'llanadi."""
    stype = db.query(ServiceType).filter(ServiceType.id == type_id).first()
    if not stype:
        raise HTTPException(status_code=404, detail="Xizmat turi topilmadi")

    if request.name is not None and request.name.strip():
        stype.name = request.name.strip()
    if request.price is not None:
        stype.price = request.price
    if request.icon is not None:
        stype.icon = request.icon
    if request.is_active is not None:
        stype.is_active = request.is_active
    db.commit()
    db.refresh(stype)

    # Bu turni tanlagan servislardagi nomi/narxini ham katalog bilan sinxronlaymiz
    db.query(ServiceOffered).filter(ServiceOffered.service_type_id == stype.id).update(
        {"category": stype.name, "price": stype.price}, synchronize_session=False
    )
    db.commit()
    return {"id": stype.id, "name": stype.name, "price": stype.price, "icon": stype.icon, "is_active": stype.is_active}

@app.delete("/api/admin/service-types/{type_id}")
def admin_delete_service_type(type_id: int, db: Session = Depends(get_db)):
    """Admin xizmat turini katalogdan butunlay o'chiradi (uni tanlagan servislardagi
    yozuvlar ham birga o'chadi)."""
    stype = db.query(ServiceType).filter(ServiceType.id == type_id).first()
    if not stype:
        raise HTTPException(status_code=404, detail="Xizmat turi topilmadi")
    db.query(ServiceOffered).filter(ServiceOffered.service_type_id == stype.id).delete(synchronize_session=False)
    db.delete(stype)
    db.commit()
    return {"success": True}

# ============================================
# ADMIN: XIZMATLARNI TASDIQLASH (services_offered)
# ============================================
@app.get("/api/admin/services-offered/pending")
def admin_list_pending_offered_services(db: Session = Depends(get_db)):
    """Admin tasdiqlashini kutayotgan barcha xizmatlar ro'yxati (barcha servislar bo'yicha)."""
    items = (
        db.query(ServiceOffered)
        .filter(ServiceOffered.status == "pending")
        .order_by(ServiceOffered.created_at.asc())
        .all()
    )
    return [
        {
            "id": i.id,
            "category": i.category,
            "price": i.price,
            "service_id": i.service_id,
            "service_name": i.service.name if i.service else None,
            "owner_name": i.service.owner.name if i.service and i.service.owner else None,
            "created_at": i.created_at,
        }
        for i in items
    ]

@app.put("/api/admin/services-offered/{item_id}/approve")
def admin_approve_offered_service(item_id: int, db: Session = Depends(get_db)):
    item = db.query(ServiceOffered).filter(ServiceOffered.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Xizmat topilmadi")
    item.status = "approved"
    item.reject_reason = None
    db.commit()
    return {"id": item.id, "status": item.status}

@app.put("/api/admin/services-offered/{item_id}/reject")
def admin_reject_offered_service(item_id: int, request: ServiceOfferedRejectRequest, db: Session = Depends(get_db)):
    item = db.query(ServiceOffered).filter(ServiceOffered.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Xizmat topilmadi")
    item.status = "rejected"
    item.reject_reason = request.reason
    db.commit()
    return {"id": item.id, "status": item.status, "reject_reason": item.reject_reason}

@app.post("/api/admin/services/{service_id}/services-offered")
def admin_add_offered_service(service_id: int, request: AdminAddOfferedServiceRequest, db: Session = Depends(get_db)):
    """Admin xohlagan servis egasiga (service_id bo'yicha) to'g'ridan-to'g'ri xizmat
    qo'shadi. Bunday yozuv qo'shimcha tasdiqlashsiz darhol 'approved' bo'ladi."""
    service = db.query(Service).filter(Service.id == service_id).first()
    if not service:
        raise HTTPException(status_code=404, detail="Servis topilmadi")

    item = (
        db.query(ServiceOffered)
        .filter(ServiceOffered.service_id == service_id, ServiceOffered.category == request.category)
        .first()
    )
    if item:
        item.price = request.price
        item.is_active = request.is_active
        item.status = "approved"
        item.reject_reason = None
    else:
        item = ServiceOffered(
            service_id=service_id,
            category=request.category,
            price=request.price,
            is_active=request.is_active,
            status="approved",
            added_by_admin=True,
        )
        db.add(item)
    db.commit()
    db.refresh(item)
    return {"id": item.id, "category": item.category, "price": item.price, "status": item.status}

@app.get("/api/service-owner/dashboard")
def service_owner_dashboard(owner_id: int, db: Session = Depends(get_db)):
    """Dashboard: bugungi/faol/yakunlangan buyurtmalar va daromad statistikasi."""
    service = db.query(Service).filter(Service.owner_id == owner_id).order_by(Service.id.desc()).first()
    if not service:
        raise HTTPException(status_code=404, detail="Servis topilmadi")

    orders = db.query(Order).filter(Order.service_id == service.id).all()
    today = datetime.datetime.now(datetime.timezone.utc).date()
    active_statuses = {"pending", "accepted"}

    today_count = sum(1 for o in orders if o.created_at and o.created_at.date() == today)
    active_count = sum(1 for o in orders if o.status in active_statuses)
    completed_count = sum(1 for o in orders if o.status == "completed")
    revenue = sum(o.price or 0 for o in orders if o.status == "completed")

    recent = sorted(orders, key=lambda o: o.created_at or datetime.datetime.min, reverse=True)[:5]

    return {
        "service_name": service.name,
        "status": service.status,
        "provider_type": service.provider_type,
        "working_hours": service.working_hours,
        "day_off": service.day_off,
        "is_online": service.is_online,
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
        provider_type=service.provider_type,
        is_active=True,
        is_verified=False
    )
    db.add(new_service)
    db.commit()
    db.refresh(new_service)

    # Add offered services (servis egasi tomonidan - tasdiqlanishi kerak)
    for cat in service.categories:
        offered = ServiceOffered(service_id=new_service.id, category=cat, status="pending")
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
    """
    - category == "evacuator" yoki "fuel": shu turdagi provayderlarni qaytaradi
      (Service.provider_type bo'yicha) - bular har doim mavjud, alohida ro'yxatdan
      o'tgan provayderlar.
    - category == "auto_service" yoki berilmasa: oddiy avtoservislar ro'yxati
      (provider_type == "auto_service").
    - category raqamli qiymat (masalan "3"): admin katalogidagi shu ServiceType.id
      xizmat turini taklif qiladigan (va uni yoqib qo'ygan) avtoservislar - foydalanuvchi
      bosh ekrandagi xizmat turini tanlaganda aynan shu filtr ishlaydi.
    - boshqa (eski, erkin-matnli) category qiymati: shu nomni tasdiqlangan holda
      taklif qiladigan avtoservislar (orqaga moslik uchun).
    """
    query = db.query(Service).filter(Service.is_active == True)

    if category in ("evacuator", "fuel"):
        # Faqat hozir ish ustida (ish vaqtini boshlagan va joylashuvi yoniq)
        # evakuator/benzin dastavkalar xaritada/ro'yxatda ko'rinadi.
        query = query.filter(Service.provider_type == category, Service.is_online == True)
    elif category == "auto_service":
        query = query.filter(Service.provider_type == "auto_service")
    elif category and category.isdigit():
        query = query.join(ServiceOffered).filter(
            ServiceOffered.service_type_id == int(category),
            ServiceOffered.status == "approved",
            ServiceOffered.is_active == True,
        )
    elif category:
        query = query.join(ServiceOffered).filter(
            ServiceOffered.category == category, ServiceOffered.status == "approved"
        )
    else:
        query = query.filter(Service.provider_type == "auto_service")

    services = query.all()

    # Calculate distance if coordinates provided
    result = []
    for s in services:
        # Evakuator/fuel uchun statik latitude/longitude yo'q (registratsiyada
        # kiritilmaydi) - o'rniga ish vaqtida yuborilgan jonli joylashuv ishlatiladi.
        display_lat = s.current_latitude if s.provider_type in ("evacuator", "fuel") else s.latitude
        display_lng = s.current_longitude if s.provider_type in ("evacuator", "fuel") else s.longitude

        distance = None
        if lat is not None and lng is not None and display_lat is not None and display_lng is not None:
            # Simple Euclidean distance (for production use Haversine)
            distance = ((display_lat - lat) ** 2 + (display_lng - lng) ** 2) ** 0.5 * 111  # km approx

        result.append({
            "id": s.id,
            "name": s.name,
            "description": s.description,
            "phone": s.phone,
            "address": s.address,
            "latitude": display_lat,
            "longitude": display_lng,
            "rating": s.rating,
            "review_count": s.review_count,
            "working_hours": s.working_hours,
            "day_off": s.day_off,
            "provider_type": s.provider_type,
            "car_model": s.car_model,
            "price": s.price,
            "logo_url": s.logo_url,
            "is_online": s.is_online,
            "distance": round(distance, 2) if distance else None,
            "categories": [o.category for o in s.services_offered if o.is_active and o.status == "approved"]
        })

    if lat is not None and lng is not None:
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
        "day_off": service.day_off,
        "provider_type": service.provider_type,
        "car_model": service.car_model,
        "price": service.price,
        "is_online": service.is_online,
        "images": service.images,
        # Foydalanuvchiga faqat admin tomonidan tasdiqlangan (approved) xizmatlar
        # ko'rinadi - servis egasi yoki admin qo'shgan va tasdiqlangan xizmatlar.
        "categories": [
            {"category": o.category, "price": o.price, "is_active": o.is_active}
            for o in service.services_offered
            if o.status == "approved"
        ],
        "reviews": [
            {"rating": r.rating, "comment": r.comment, "user_name": r.user.name, "created_at": r.created_at}
            for r in service.reviews
        ]
    }

# ============================================
# BRON VAQTINI SERVIS ISH VAQTI/DAM OLISH KUNIGA TEKSHIRISH
# ============================================
# Frontend'dagi isAutoServiceOpenNow() bilan bir xil format va mantiq:
# - day_off: "Yakshanba" kabi hafta kuni nomi (yoki "Dam olish kuni yo'q" /
#   bo'sh - cheklov yo'q)
# - working_hours: "09:00-18:00" formatida. Agar boshlanish tugashdan
#   katta bo'lsa (masalan "22:00-06:00"), bu tungi smena deb hisoblanadi.
_WEEKDAY_NAMES_UZ = ["Dushanba", "Seshanba", "Chorshanba", "Payshanba", "Juma", "Shanba", "Yakshanba"]


def _validate_scheduled_within_service_hours(service: "Service", scheduled_at: datetime.datetime) -> None:
    day_off = (service.day_off or "").strip()
    if day_off and day_off != "Dam olish kuni yo'q":
        if _WEEKDAY_NAMES_UZ[scheduled_at.weekday()] == day_off:
            raise HTTPException(
                status_code=400,
                detail=f"Bu servis {day_off} kunlari dam oladi, shu kunga bron qilib bo'lmaydi",
            )

    working_hours = (service.working_hours or "").strip()
    if not working_hours or "-" not in working_hours:
        return  # ish vaqti belgilanmagan - cheklamaymiz

    parts = working_hours.split("-")
    if len(parts) != 2:
        return

    def _parse_hm(s: str):
        s = s.strip()
        hm = s.split(":")
        if len(hm) != 2:
            return None
        try:
            return int(hm[0]), int(hm[1])
        except ValueError:
            return None

    start = _parse_hm(parts[0])
    end = _parse_hm(parts[1])
    if start is None or end is None:
        return

    scheduled_min = scheduled_at.hour * 60 + scheduled_at.minute
    start_min = start[0] * 60 + start[1]
    end_min = end[0] * 60 + end[1]

    if start_min <= end_min:
        in_hours = start_min <= scheduled_min < end_min
    else:
        in_hours = scheduled_min >= start_min or scheduled_min < end_min  # tungi smena

    if not in_hours:
        raise HTTPException(
            status_code=400,
            detail=f"Bu servis ish vaqti {working_hours}, shu vaqt oralig'ida bron qiling",
        )


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

    # Evakuator va benzin dastavka uchun narx mijoz yoki servis egasi tomonidan
    # emas, balki admin panelida belgilangan GLOBAL narxlardan avtomatik
    # hisoblanadi - shuning uchun bu yerda qayta hisoblanadi (frontenddan
    # kelgan narxga ishonilmaydi).
    computed_price = None
    liters = None
    if service.provider_type == "evacuator":
        pricing = db.query(PricingSettings).filter(PricingSettings.id == 1).first()
        computed_price = pricing.evacuator_price if pricing else None
    elif service.provider_type == "fuel":
        if order.liters is None or order.liters <= 0:
            raise HTTPException(status_code=400, detail="Benzin miqdorini (litr) kiriting")
        pricing = db.query(PricingSettings).filter(PricingSettings.id == 1).first()
        delivery_fee = pricing.fuel_delivery_fee if pricing else 0
        price_per_liter = pricing.fuel_price_per_liter if pricing else 0
        liters = order.liters
        computed_price = delivery_fee + liters * price_per_liter

    # Evakuator/benzin dastavka - har doim "hozir" turidagi chaqiruv,
    # bron qilib bo'lmaydi (mijoz frontend orqali order_type yubormasa ham
    # xavfsizlik uchun bu yerda majburlab qo'yiladi).
    order_type = order.order_type
    scheduled_at = order.scheduled_at
    if service.provider_type in ("evacuator", "fuel"):
        order_type = "now"
        scheduled_at = None

    # Bron qilinayotgan vaqt servisning dam olish kuniga yoki ish vaqtidan
    # tashqariga to'g'ri kelmasligini tekshiramiz (faqat oddiy avtoservis
    # uchun - evakuator/benzin yuqorida allaqachon "now"ga majburlangan).
    if order_type == "scheduled" and scheduled_at:
        _validate_scheduled_within_service_hours(service, scheduled_at)

    new_order = Order(
        user_id=user_id,
        service_id=order.service_id,
        category=order.category,
        description=order.description,
        user_latitude=order.user_latitude,
        user_longitude=order.user_longitude,
        price=computed_price,
        liters=liters,
        order_type=order_type,
        scheduled_at=scheduled_at,
        status=OrderStatus.PENDING.value
    )
    db.add(new_order)
    db.commit()
    db.refresh(new_order)

    notif_text = f"{user.name} sizga yangi buyurtma berdi: {service.name}"
    if order_type == "scheduled" and scheduled_at:
        notif_text = f"{user.name} sizga bron qildi ({scheduled_at.strftime('%d.%m.%Y %H:%M')}): {service.name}"

    create_notification(
        db, service.owner_id,
        "Yangi buyurtma",
        notif_text,
        type="new_order", related_id=new_order.id,
    )

    return {
        "id": new_order.id,
        "status": new_order.status,
        "order_type": new_order.order_type,
        "scheduled_at": new_order.scheduled_at,
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
            "order_type": o.order_type,
            "scheduled_at": o.scheduled_at,
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

    # Evakuator/benzin dastavka qabul qilingandan so'ng haydovchining jonli
    # joylashuvi (agar u ish ustida joylashuvini yuborib turgan bo'lsa) -
    # MapTrackingScreen va OrderDetailScreen shu maydonni kutadi.
    driver_location = None
    if (
        order.service.provider_type in ("evacuator", "fuel")
        and order.status == OrderStatus.ACCEPTED.value
        and order.service.current_latitude is not None
        and order.service.current_longitude is not None
    ):
        driver_location = {
            "lat": order.service.current_latitude,
            "lng": order.service.current_longitude,
        }

    return {
        "id": order.id,
        "service": {
            "id": order.service.id,
            "name": order.service.name,
            "phone": order.service.phone,
            "address": order.service.address,
            "latitude": order.service.latitude,
            "longitude": order.service.longitude,
            "provider_type": order.service.provider_type,
        },
        "category": order.category,
        "status": order.status,
        "order_type": order.order_type,
        "scheduled_at": order.scheduled_at,
        "description": order.description,
        "user_latitude": order.user_latitude,
        "user_longitude": order.user_longitude,
        "price": order.price,
        "liters": order.liters,
        "driver_location": driver_location,
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

    status_label = ORDER_STATUS_LABELS.get(order.status, order.status)
    create_notification(
        db, order.user_id,
        "Buyurtma holati yangilandi",
        f"Buyurtmangiz holati: {status_label}",
        type="order_status", related_id=order.id,
    )

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

    # Xabar qarama-qarshi tomonga (mijoz <-> servis egasi) yuboriladi
    recipient_id = order.service.owner_id if sender_id == order.user_id else order.user_id
    sender = db.query(User).filter(User.id == sender_id).first()
    create_notification(
        db, recipient_id,
        f"Yangi xabar: {sender.name if sender else ''}",
        msg.message[:150],
        type="chat", related_id=msg.order_id,
    )

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
    active_orders = db.query(Order).filter(Order.status.in_(["pending", "accepted"])).count()
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

@app.get("/api/admin/users/{user_id}")
def admin_get_user_detail(user_id: int, db: Session = Depends(get_db)):
    """Admin panelida foydalanuvchilar ro'yxatidan bittasini bosganda uning
    barcha ma'lumotlarini (mashinalari, buyurtmalari, agar servis egasi bo'lsa
    - o'z servisi) ko'rsatish uchun."""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Foydalanuvchi topilmadi")

    own_service = db.query(Service).filter(Service.owner_id == user.id).first()

    return {
        "id": user.id,
        "name": user.name,
        "phone": user.phone,
        "city": user.city,
        "role": user.role,
        "is_active": user.is_active,
        "created_at": user.created_at,
        "cars": [
            {
                "id": c.id,
                "model": c.model,
                "plate_number": c.plate_number,
                "year": c.year,
                "color": c.color,
                "fuel_type": c.fuel_type,
                "is_primary": c.is_primary,
            }
            for c in user.cars
        ],
        "orders": [
            {
                "id": o.id,
                "service_name": o.service.name if o.service else None,
                "category": o.category,
                "status": o.status,
                "price": o.price,
                "created_at": o.created_at,
            }
            for o in sorted(user.orders, key=lambda o: o.created_at or datetime.datetime.min, reverse=True)
        ],
        "favorite_count": len(user.favorites),
        "review_count": len(user.reviews),
        "own_service": (
            {
                "id": own_service.id,
                "name": own_service.name,
                "provider_type": own_service.provider_type,
                "status": own_service.status,
            }
            if own_service else None
        ),
    }

@app.put("/api/admin/users/{user_id}/block")
def admin_block_user(user_id: int, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Foydalanuvchi topilmadi")
    user.is_active = not user.is_active
    db.commit()
    return {"id": user.id, "is_active": user.is_active}

@app.get("/api/admin/orders")
def admin_get_orders(status: Optional[str] = None, scope: Optional[str] = None, db: Session = Depends(get_db)):
    """status: aniq bitta holat ('pending' | 'accepted' | 'completed' | 'cancelled').
    scope: dashboard statistik kartalari uchun qulay filtrlar -
      'active' -> 'Faol buyurtmalar' kartasi bilan bir xil (pending + accepted),
      'today'  -> 'Bugungi buyurtmalar' kartasi bilan bir xil (bugun yaratilganlar)."""
    query = db.query(Order)
    if scope == "active":
        query = query.filter(Order.status.in_(["pending", "accepted"]))
    elif scope == "today":
        query = query.filter(func.date(Order.created_at) == func.date(func.now()))
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
            "price": o.price,
            "order_type": o.order_type,
            "scheduled_at": o.scheduled_at,
            "created_at": o.created_at
        }
        for o in orders
    ]

@app.get("/api/admin/orders/{order_id}")
def admin_get_order_detail(order_id: int, db: Session = Depends(get_db)):
    """Admin panelida buyurtmalar ro'yxatidan bittasini bosganda uning barcha
    ma'lumotlarini (mijoz, servis, narx, holat) ko'rsatish uchun."""
    order = db.query(Order).filter(Order.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Buyurtma topilmadi")

    return {
        "id": order.id,
        "user": {
            "id": order.user.id,
            "name": order.user.name,
            "phone": order.user.phone,
        } if order.user else None,
        "service": {
            "id": order.service.id,
            "name": order.service.name,
            "phone": order.service.phone,
            "provider_type": order.service.provider_type,
        } if order.service else None,
        "category": order.category,
        "status": order.status,
        "order_type": order.order_type,
        "scheduled_at": order.scheduled_at,
        "description": order.description,
        "user_latitude": order.user_latitude,
        "user_longitude": order.user_longitude,
        "price": order.price,
        "created_at": order.created_at,
        "updated_at": order.updated_at,
        "completed_at": order.completed_at,
    }

@app.get("/api/admin/services")
def admin_get_services(status: Optional[str] = None, provider_type: Optional[str] = None, db: Session = Depends(get_db)):
    """status: 'pending' | 'approved' | 'rejected' | None (hammasi)
    provider_type: 'auto_service' | 'evacuator' | 'fuel' | None (hammasi)"""
    query = db.query(Service)
    if status:
        query = query.filter(Service.status == status)
    if provider_type:
        query = query.filter(Service.provider_type == provider_type)
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
            "provider_type": s.provider_type,
            "car_model": s.car_model,
            "price": s.price,
            "is_online": s.is_online,
            "current_latitude": s.current_latitude,
            "current_longitude": s.current_longitude,
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
    if request.car_model is not None:
        service.car_model = request.car_model
    if request.price is not None:
        service.price = request.price
    if request.logo_base64 is not None:
        service.logo_url = request.logo_base64
    if request.owner_name is not None and service.owner is not None:
        service.owner.name = request.owner_name

    db.commit()
    db.refresh(service)
    return {"id": service.id, "message": "Servis ma'lumotlari yangilandi"}

@app.put("/api/service-owner/go-online")
def service_owner_go_online(owner_id: int, request: LocationUpdateRequest, db: Session = Depends(get_db)):
    """Evakuator/benzin dastavka ish boshlaydi: joriy joylashuvini yuborib,
    xaritada ko'rinadigan (is_online=True) holatga o'tadi."""
    service = db.query(Service).filter(Service.owner_id == owner_id).first()
    if not service:
        raise HTTPException(status_code=404, detail="Servis topilmadi")
    if service.provider_type not in ("evacuator", "fuel"):
        raise HTTPException(status_code=400, detail="Bu faqat evakuator/benzin dastavka uchun")
    service.is_online = True
    service.current_latitude = request.latitude
    service.current_longitude = request.longitude
    service.location_updated_at = func.now()
    db.commit()
    return {"is_online": True}

@app.put("/api/service-owner/go-offline")
def service_owner_go_offline(owner_id: int, db: Session = Depends(get_db)):
    """Evakuator/benzin dastavka ish tugatadi: xaritadan yashiriladi (is_online=False)."""
    service = db.query(Service).filter(Service.owner_id == owner_id).first()
    if not service:
        raise HTTPException(status_code=404, detail="Servis topilmadi")
    service.is_online = False
    db.commit()
    return {"is_online": False}

@app.put("/api/service-owner/location")
def service_owner_update_location(owner_id: int, request: LocationUpdateRequest, db: Session = Depends(get_db)):
    """Ish vaqti davomida joriy joylashuvni davriy yangilab turish uchun."""
    service = db.query(Service).filter(Service.owner_id == owner_id).first()
    if not service:
        raise HTTPException(status_code=404, detail="Servis topilmadi")
    service.current_latitude = request.latitude
    service.current_longitude = request.longitude
    service.location_updated_at = func.now()
    db.commit()
    return {"success": True, "is_online": service.is_online}

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
            "provider_type": service.provider_type,
            "car_model": service.car_model,
        }
    }

# ---- Umumiy: kategoriyalar ro'yxati ----
@app.get("/api/categories")
def get_categories(db: Session = Depends(get_db)):
    """
    Asosiy ekrandagi 'Xizmat turlari' ro'yxati. Endi bu ro'yxat admin tomonidan
    boshqariladigan ServiceType katalogidan dinamik tarzda olinadi - admin qanday
    xizmat turi (nomi va narxi bilan) qo'shsa, shu yerda ko'rinadi. Foydalanuvchi
    birortasini tanlasa, aynan shu turni taklif qiladigan (va yoqib qo'ygan)
    avtoservislar unga ko'rinadi.
    Evakuator, Benzin dastavka va Avtoservislar - har doim mavjud bo'lgan, alohida
    provayder turlari, shuning uchun har doim ro'yxat boshida turadi.
    """
    result = [
        {"id": "evacuator", "name": "Evakuator", "icon": "local_shipping"},
        {"id": "fuel", "name": "Benzin yetkazish", "icon": "local_gas_station"},
        {"id": "auto_service", "name": "Avtoservislar", "icon": "build"},
    ]
    types = db.query(ServiceType).filter(ServiceType.is_active == True).order_by(ServiceType.id.asc()).all()
    for t in types:
        result.append({"id": str(t.id), "name": t.name, "icon": t.icon or "build", "price": t.price})
    return result

# ---- Evakuator/benzin dastavka uchun GLOBAL narxlar ----
def _get_or_create_pricing(db: Session) -> PricingSettings:
    pricing = db.query(PricingSettings).filter(PricingSettings.id == 1).first()
    if pricing is None:
        pricing = PricingSettings(id=1, evacuator_price=0, fuel_delivery_fee=120000, fuel_price_per_liter=16000)
        db.add(pricing)
        db.commit()
        db.refresh(pricing)
    return pricing

@app.get("/api/pricing")
def get_pricing(db: Session = Depends(get_db)):
    """
    Evakuator va benzin dastavka narxlari - foydalanuvchi ilovasi "Chaqirish"
    dan oldin narxni shu yerdan olib ko'rsatadi. Ushbu narxlarni FAQAT admin
    o'zgartira oladi (/api/admin/pricing orqali).
    """
    pricing = _get_or_create_pricing(db)
    return {
        "evacuator_price": pricing.evacuator_price,
        "fuel_delivery_fee": pricing.fuel_delivery_fee,
        "fuel_price_per_liter": pricing.fuel_price_per_liter,
    }

@app.put("/api/admin/pricing")
def admin_update_pricing(request: PricingUpdate, db: Session = Depends(get_db)):
    """Admin panel: evakuator va benzin dastavka uchun global narxlarni belgilash."""
    pricing = _get_or_create_pricing(db)
    if request.evacuator_price is not None:
        pricing.evacuator_price = request.evacuator_price
    if request.fuel_delivery_fee is not None:
        pricing.fuel_delivery_fee = request.fuel_delivery_fee
    if request.fuel_price_per_liter is not None:
        pricing.fuel_price_per_liter = request.fuel_price_per_liter
    db.commit()
    db.refresh(pricing)
    return {
        "evacuator_price": pricing.evacuator_price,
        "fuel_delivery_fee": pricing.fuel_delivery_fee,
        "fuel_price_per_liter": pricing.fuel_price_per_liter,
    }

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
    query = db.query(User)
    if request.target == "users":
        query = query.filter(User.role == UserRole.USER.value)
    elif request.target == "services":
        query = query.filter(User.role == UserRole.SERVICE_OWNER.value)

    users = query.all()
    for u in users:
        create_notification(db, u.id, request.title, request.message, type="admin")

    return {"success": True, "sent_count": len(users), "title": request.title}

# ============================================
# ILOVA ICHI BILDIRISHNOMALARI (IN-APP)
# ============================================
@app.get("/api/notifications")
def get_notifications(user_id: int, db: Session = Depends(get_db)):
    notifs = db.query(Notification).filter(Notification.user_id == user_id).order_by(Notification.created_at.desc()).limit(100).all()
    return [
        {
            "id": n.id,
            "title": n.title,
            "message": n.message,
            "type": n.type,
            "related_id": n.related_id,
            "is_read": n.is_read,
            "created_at": n.created_at,
        }
        for n in notifs
    ]

@app.get("/api/notifications/unread-count")
def get_unread_notifications_count(user_id: int, db: Session = Depends(get_db)):
    count = db.query(Notification).filter(Notification.user_id == user_id, Notification.is_read == False).count()
    return {"unread_count": count}

@app.put("/api/notifications/{notification_id}/read")
def mark_notification_read(notification_id: int, db: Session = Depends(get_db)):
    notif = db.query(Notification).filter(Notification.id == notification_id).first()
    if not notif:
        raise HTTPException(status_code=404, detail="Bildirishnoma topilmadi")
    notif.is_read = True
    db.commit()
    return {"success": True}

@app.put("/api/notifications/read-all")
def mark_all_notifications_read(user_id: int, db: Session = Depends(get_db)):
    db.query(Notification).filter(Notification.user_id == user_id, Notification.is_read == False).update({"is_read": True})
    db.commit()
    return {"success": True}

@app.delete("/api/notifications/{notification_id}")
def delete_notification(notification_id: int, db: Session = Depends(get_db)):
    notif = db.query(Notification).filter(Notification.id == notification_id).first()
    if not notif:
        raise HTTPException(status_code=404, detail="Bildirishnoma topilmadi")
    db.delete(notif)
    db.commit()
    return {"success": True}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
