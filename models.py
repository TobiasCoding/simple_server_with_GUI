from sqlalchemy import (
    Column,
    Integer,
    String,
    DateTime,
    Float,
    Boolean,
    ForeignKey,
    Text,
    JSON,
    Enum,
)
from sqlalchemy.orm import relationship
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.sql import func
import uuid
from datetime import datetime
from enum import Enum as PyEnum
from typing import Optional

Base = declarative_base()


class PaymentStatus(str, PyEnum):
    PENDING = "pending"
    COMPLETED = "completed"
    FAILED = "failed"
    REFUNDED = "refunded"
    EXPIRED = "expired"


class PaymentMethod(str, PyEnum):
    CREDIT_CARD = "credit_card"
    USDT = "usdt"
    BTC = "bitcoin"
    ETH = "ethereum"
    OTHER_CRYPTO = "other_crypto"


class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(50), unique=True, index=True, nullable=True)
    email = Column(String(100), unique=True, index=True, nullable=True)
    hashed_password = Column(String(128), nullable=True)  # Nullable for anonymous users
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    is_active = Column(Boolean, default=True)
    is_admin = Column(Boolean, default=False)

    # Relationships
    conversions = relationship("Conversion", back_populates="user")
    payments = relationship("Payment", back_populates="user")


class Conversion(Base):
    __tablename__ = "conversions"
    id = Column(Integer, primary_key=True, index=True)
    uuid = Column(String(36), unique=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    original_filename = Column(String(255), nullable=False)
    pdf_filename = Column(String(255), unique=True, nullable=False)
    page_count = Column(Integer, nullable=False)
    file_size = Column(Integer)  # Size in bytes
    is_paid = Column(Boolean, default=False)
    price = Column(Float)  # Price in USD
    currency = Column(String(3), default="USD")
    created_at = Column(DateTime, default=datetime.utcnow)
    expires_at = Column(DateTime)  # When the download link expires

    # Relationships
    user = relationship("User", back_populates="conversions")
    payments = relationship("Payment", back_populates="conversion")


class Payment(Base):
    __tablename__ = "payments"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    conversion_id = Column(Integer, ForeignKey("conversions.id"), nullable=False)
    payment_method = Column(Enum(PaymentMethod), nullable=False)
    amount = Column(Float, nullable=False)  # In the original currency
    amount_usd = Column(Float, nullable=False)  # In USD for consistency
    currency = Column(String(3), default="USD")
    status = Column(Enum(PaymentStatus), default=PaymentStatus.PENDING)

    # Payment provider data
    provider = Column(String(50))  # 'stripe', 'coinbase', 'manual', etc.
    provider_payment_id = Column(String(255))  # External payment ID
    provider_data = Column(JSON)  # Raw response from payment provider

    # For crypto payments
    crypto_address = Column(String(255))
    crypto_amount = Column(Float)
    crypto_received = Column(Float, default=0.0)
    tx_hash = Column(String(255))
    confirmations = Column(Integer, default=0)

    # For card payments
    card_last4 = Column(String(4))
    card_brand = Column(String(50))

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    paid_at = Column(DateTime)
    expires_at = Column(DateTime)

    # Relationships
    user = relationship("User", back_populates="payments")
    conversion = relationship("Conversion", back_populates="payments")


class Metric(Base):
    __tablename__ = "metrics"
    id = Column(Integer, primary_key=True, index=True)
    event = Column(String(100), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    conversion_id = Column(Integer, ForeignKey("conversions.id"), nullable=True)
    payment_id = Column(Integer, ForeignKey("payments.id"), nullable=True)
    value = Column(Float, default=1.0)
    extra_metadata = Column("metadata", JSON)  # Additional data for the event
    timestamp = Column(DateTime, default=datetime.utcnow, index=True)


class SystemSetting(Base):
    __tablename__ = "system_settings"
    id = Column(Integer, primary_key=True, index=True)
    key = Column(String(100), unique=True, index=True, nullable=False)
    value = Column(Text)
    description = Column(Text)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    updated_by = Column(Integer, ForeignKey("users.id"), nullable=True)


class ExchangeRate(Base):
    __tablename__ = "exchange_rates"
    id = Column(Integer, primary_key=True, index=True)
    from_currency = Column(String(3), nullable=False, index=True)  # e.g., 'USD'
    to_currency = Column(String(3), nullable=False, index=True)  # e.g., 'BTC'
    rate = Column(Float, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = ({"sqlite_autoincrement": True},)
