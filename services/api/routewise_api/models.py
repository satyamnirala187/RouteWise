"""Database schema. Phase 1 tables, Phase 2A rider/round configuration (depots, round riders,
rider-chosen destinations and confirmations), and the assignments table Phase 2B fills.
No optimizer, plan, rerouting or offline structures exist yet."""

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
    ForeignKeyConstraint,
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
VEHICLES = ("scooter", "bike")  # bike = motorbike; never routed with a bicycle profile
DEPOT_KINDS = ("office", "warehouse")
START_KINDS = DEPOT_KINDS
DESTINATION_KINDS = ("office", "warehouse", "home", "last_stop", "custom")
MAX_CAPACITY = 1000  # orders (D06); the import limit, so one rider can always hold a whole round


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
    vehicle: Mapped[str | None] = mapped_column(String(16), nullable=True)  # default for new round configurations
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))


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
    """One committed import = one delivery round.

    `input_version` increases with every change to the round's planning input (rider
    configuration, destinations, confirmations, referenced depot coordinates, order pins and
    statuses). Phase 2B compares it before committing a plan, so stale output cannot win."""

    __tablename__ = "delivery_rounds"
    __table_args__ = (CheckConstraint("input_version >= 1", name="ck_rounds_input_version"),)

    id: Mapped[uuid.UUID] = _uuid_pk()
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = _ts()
    input_version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))


class Depot(Base):
    """The Office and the Warehouse: one editable row each. Coordinates are entered by the admin;
    nothing is seeded, so no real business location is ever committed to the repository."""

    __tablename__ = "depots"
    __table_args__ = (
        CheckConstraint("kind IN ('office','warehouse')", name="ck_depots_kind"),
        CheckConstraint("lat BETWEEN -90 AND 90", name="ck_depots_lat"),
        CheckConstraint("lng BETWEEN -180 AND 180", name="ck_depots_lng"),
        CheckConstraint("length(btrim(label)) > 0", name="ck_depots_label"),
        CheckConstraint("version >= 1", name="ck_depots_version"),
    )

    kind: Mapped[str] = mapped_column(String(16), primary_key=True)
    label: Mapped[str] = mapped_column(String(100), nullable=False)
    lat: Mapped[float] = mapped_column(Double, nullable=False)
    lng: Mapped[float] = mapped_column(Double, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    updated_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    updated_at: Mapped[datetime] = _ts()


class RoundRider(Base):
    """A rider's configuration for one round, and their confirmation of it.

    `config_version` increases whenever something the rider confirms changes (participation,
    vehicle, capacity, start, destination, or the coordinates of a depot their start or
    destination uses). A confirmation is current only while confirmed_version == config_version."""

    __tablename__ = "round_riders"
    __table_args__ = (
        CheckConstraint("vehicle IN ('scooter','bike')", name="ck_round_riders_vehicle"),
        CheckConstraint("start_kind IN ('office','warehouse')", name="ck_round_riders_start"),
        CheckConstraint(f"capacity BETWEEN 1 AND {MAX_CAPACITY}", name="ck_round_riders_capacity"),
        CheckConstraint("config_version >= 1", name="ck_round_riders_config_version"),
        CheckConstraint("(confirmed_version IS NULL) = (confirmed_at IS NULL)", name="ck_round_riders_confirmed_pair"),
        CheckConstraint("confirmed_version IS NULL OR confirmed_version BETWEEN 1 AND config_version",
                        name="ck_round_riders_confirmed_version"),
    )

    round_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("delivery_rounds.id", ondelete="CASCADE"), primary_key=True)
    rider_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("riders.id", ondelete="RESTRICT"), primary_key=True, index=True)
    participating: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    vehicle: Mapped[str] = mapped_column(String(16), nullable=False)
    capacity: Mapped[int] = mapped_column(Integer, nullable=False)
    start_kind: Mapped[str] = mapped_column(String(16), nullable=False)
    config_version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    confirmed_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = _ts()
    updated_at: Mapped[datetime] = _ts()


class RiderEndpoint(Base):
    """The destination a rider chose for a round. Home/Custom coordinates are private (R24): they
    are kept here for the planner and the rider, and never included in an admin response."""

    __tablename__ = "rider_endpoints"
    __table_args__ = (
        ForeignKeyConstraint(["round_id", "rider_id"], ["round_riders.round_id", "round_riders.rider_id"],
                             ondelete="CASCADE", name="fk_rider_endpoints_round_rider"),
        CheckConstraint("kind IN ('office','warehouse','home','last_stop','custom')", name="ck_rider_endpoints_kind"),
        CheckConstraint("(kind IN ('home','custom')) = (lat IS NOT NULL AND lng IS NOT NULL)",
                        name="ck_rider_endpoints_location_iff_home_custom"),
        CheckConstraint("(lat IS NULL) = (lng IS NULL)", name="ck_rider_endpoints_coord_pair"),
        CheckConstraint("(location_source IS NULL) = (lat IS NULL)", name="ck_rider_endpoints_source"),
        CheckConstraint(
            "location_source IS NULL OR location_source IN ('place_pin','query','geo_uri','short_link','manual_pin')",
            name="ck_rider_endpoints_source_values"),
        CheckConstraint("lat IS NULL OR (lat BETWEEN -90 AND 90)", name="ck_rider_endpoints_lat"),
        CheckConstraint("lng IS NULL OR (lng BETWEEN -180 AND 180)", name="ck_rider_endpoints_lng"),
    )

    round_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    rider_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    lat: Mapped[float | None] = mapped_column(Double, nullable=True)
    lng: Mapped[float | None] = mapped_column(Double, nullable=True)
    location_source: Mapped[str | None] = mapped_column(String(20), nullable=True)
    updated_at: Mapped[datetime] = _ts()


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
