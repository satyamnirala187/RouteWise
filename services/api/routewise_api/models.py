"""Database schema. Phase 1 tables plus the minimal structures later phases build on
(riders, delivery rounds, assignments). No later-phase behaviour is implemented here."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Double,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

ORDER_STATUSES = ("Pending", "Postponed", "Completed")
ROLES = ("admin", "rider")
LOCATION_STATES = ("resolved", "needs_correction")
LOCATION_SOURCES = ("place_pin", "query", "geo_uri", "short_link", "manual_pin")


class Base(DeclarativeBase):
    pass


def _uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)


def _ts(nullable: bool = False) -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), nullable=nullable, server_default=None if nullable else func.now())


class User(Base):
    __tablename__ = "users"
    __table_args__ = (CheckConstraint("role IN ('admin','rider')", name="ck_users_role"),)

    id: Mapped[uuid.UUID] = _uuid_pk()
    username: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)  # stored lower-case
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    created_at: Mapped[datetime] = _ts()


class Rider(Base):
    """Rider profile (vehicle used later to pick motor_scooter / motorcycle routing)."""

    __tablename__ = "riders"
    __table_args__ = (CheckConstraint("vehicle IS NULL OR vehicle IN ('scooter','bike')", name="ck_riders_vehicle"),)

    id: Mapped[uuid.UUID] = _uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True)
    display_name: Mapped[str] = mapped_column(String(100), nullable=False)
    vehicle: Mapped[str | None] = mapped_column(String(16), nullable=True)


class Session(Base):
    __tablename__ = "sessions"

    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)  # HMAC-SHA256(secret, token), hex
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    csrf_token: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class LoginFailure(Base):
    __tablename__ = "login_failures"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    username_key: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    ip: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)


class ImportBatch(Base):
    """An uploaded spreadsheet. Preview rows live here until commit/discard/expiry."""

    __tablename__ = "import_batches"
    __table_args__ = (CheckConstraint("state IN ('preview','committed','discarded')", name="ck_import_state"),)

    id: Mapped[uuid.UUID] = _uuid_pk()
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = _ts()
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    state: Mapped[str] = mapped_column(String(16), nullable=False)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    summary: Mapped[dict] = mapped_column(JSONB, nullable=False)
    rows: Mapped[list | None] = mapped_column(JSONB, nullable=True)  # cleared after commit/discard
    round_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("delivery_rounds.id"), nullable=True)


class DeliveryRound(Base):
    """One committed import = one delivery round. Rider configuration/optimization is Phase 2."""

    __tablename__ = "delivery_rounds"

    id: Mapped[uuid.UUID] = _uuid_pk()
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = _ts()


class Order(Base):
    __tablename__ = "orders"
    __table_args__ = (
        CheckConstraint("status IN ('Pending','Postponed','Completed')", name="ck_orders_status"),
        CheckConstraint("location_state IN ('resolved','needs_correction')", name="ck_orders_location_state"),
        CheckConstraint(
            "location_source IS NULL OR location_source IN ('place_pin','query','geo_uri','short_link','manual_pin')",
            name="ck_orders_location_source",
        ),
        CheckConstraint(
            "(location_state = 'resolved') = (lat IS NOT NULL AND lng IS NOT NULL)", name="ck_orders_resolved_has_coords"
        ),
        CheckConstraint("lat IS NULL OR (lat BETWEEN -90 AND 90)", name="ck_orders_lat"),
        CheckConstraint("lng IS NULL OR (lng BETWEEN -180 AND 180)", name="ck_orders_lng"),
        UniqueConstraint("order_code", name="uq_orders_order_code"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    order_code: Mapped[str] = mapped_column(String(32), nullable=False)
    round_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("delivery_rounds.id", ondelete="CASCADE"), nullable=False, index=True)
    source_row: Mapped[int] = mapped_column(Integer, nullable=False)
    customer_name: Mapped[str] = mapped_column(String(200), nullable=False)
    product: Mapped[str] = mapped_column(String(500), nullable=False)
    contact: Mapped[str] = mapped_column(String(40), nullable=False)
    instructions: Mapped[str | None] = mapped_column(Text, nullable=True)
    location_link: Mapped[str] = mapped_column(String(2048), nullable=False)
    location_state: Mapped[str] = mapped_column(String(20), nullable=False)
    location_source: Mapped[str | None] = mapped_column(String(20), nullable=True)
    location_note: Mapped[str | None] = mapped_column(String(300), nullable=True)
    lat: Mapped[float | None] = mapped_column(Double, nullable=True)
    lng: Mapped[float | None] = mapped_column(Double, nullable=True)
    building_id: Mapped[str | None] = mapped_column(String(64), nullable=True)  # validated shared entrance (Phase 4)
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default=text("'Pending'"))
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    created_at: Mapped[datetime] = _ts()
    updated_at: Mapped[datetime] = _ts()


class Assignment(Base):
    """Exactly one rider owns an assigned order. Populated by Phase 2 planning."""

    __tablename__ = "assignments"

    order_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("orders.id", ondelete="CASCADE"), primary_key=True)
    rider_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("riders.id", ondelete="RESTRICT"), nullable=False, index=True)
    assigned_at: Mapped[datetime] = _ts()
