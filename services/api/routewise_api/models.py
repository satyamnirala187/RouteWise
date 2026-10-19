"""Database schema. Phase 1 tables, Phase 2A rider/round configuration (depots, round riders,
rider-chosen destinations and confirmations), Phase 2B planning (modes, locks, priorities,
planning runs, versioned plans and assignment linkage) and Phase 4B rider route revisions
(a rider's own reroute layered on the immutable round plan). No offline structures, and no
column anywhere stores a rider's device position."""

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
    Index,
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
DISTRIBUTION_MODES = ("equal", "smart", "manual")
RUN_STATES = ("queued", "running", "succeeded", "failed", "stale", "interrupted")
ACTIVE_RUN_STATES = ("queued", "running")
PROFILES = ("motor_scooter", "motorcycle")  # scooter → motor_scooter, bike → motorcycle; never bicycle or car
PLAN_ORDER_ROLES = ("active", "postponed", "completed")
RUN_SCOPES = ("round", "rider")  # admin "Optimize all routes" / one rider's own reroute (4B)
ORIGIN_KINDS = ("current_position", "last_completed_stop", "configured_start")
REVISION_TRIGGERS = ("rider_request", "endpoint_change")
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
    statuses). Phase 2B compares it before committing a plan, so stale output cannot win.

    `route_version` (3B) increases with the same changes EXCEPT a rider's own delivery progress
    (Pending → Completed / Postponed, Postponed → Pending through the rider endpoint). A saved
    plan records it; the plan is out of date (not usable as a route) when they differ. Delivery
    progress therefore still makes any in-flight solve stale (`input_version`) without marking
    every rider's remaining saved sequence out of date."""

    __tablename__ = "delivery_rounds"
    __table_args__ = (
        CheckConstraint("input_version >= 1", name="ck_rounds_input_version"),
        CheckConstraint("route_version >= 1", name="ck_rounds_route_version"),
        CheckConstraint("mode IN ('equal','smart','manual')", name="ck_rounds_mode"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = _ts()
    input_version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    route_version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    mode: Mapped[str] = mapped_column(String(16), nullable=False, server_default=text("'smart'"))


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
        CheckConstraint("route_version >= 1", name="ck_round_riders_route_version"),
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
    # 4B: rider-scoped route validity. Increases when something only this rider's route depends on
    # changes (their own destination); the rider's effective route records it (see rider_routes.py).
    route_version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
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
        CheckConstraint("(completed_at IS NULL) = (completed_by IS NULL)", name="ck_orders_completed_pair"),
        CheckConstraint("status = 'Completed' OR completed_at IS NULL", name="ck_orders_completed_only_when_completed"),
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
    locked_rider_id: Mapped[uuid.UUID | None] = mapped_column(  # admin owner lock (manual assignment)
        ForeignKey("riders.id", ondelete="RESTRICT"), nullable=True, index=True)
    first_priority: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default=text("'Pending'"))
    # 4B: when and by whom the order became Completed (NULL before 4B: unknown, never invented).
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    created_at: Mapped[datetime] = _ts()
    updated_at: Mapped[datetime] = _ts()


class Assignment(Base):
    """Exactly one rider owns an assigned order (primary key on order_id). Written by plan
    commits; `plan_id` is the plan version that last confirmed this ownership."""

    __tablename__ = "assignments"

    order_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("orders.id", ondelete="CASCADE"), primary_key=True)
    rider_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("riders.id", ondelete="RESTRICT"), nullable=False, index=True)
    assigned_at: Mapped[datetime] = _ts()
    plan_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("route_plans.id", ondelete="SET NULL"),
                                                      nullable=True, index=True)


class PlanningRun(Base):
    """One optimization request. The input snapshot lives only in the worker's memory; the
    database keeps its versions and keyed fingerprint. A run never becomes `succeeded` without
    its plan (or, for a rider run, its route revision) being committed in the same transaction.

    `scope` 'round' is the admin's "Optimize all routes"; 'rider' (4B) re-sequences one rider's own
    Pending orders on top of `base_plan_id`. At most one active round run per round, and at most
    one active rider run per rider and round. The origin's kind is kept; its position never is."""

    __tablename__ = "planning_runs"
    __table_args__ = (
        CheckConstraint("state IN ('queued','running','succeeded','failed','stale','interrupted')",
                        name="ck_planning_runs_state"),
        CheckConstraint("input_version >= 1", name="ck_planning_runs_input_version"),
        CheckConstraint("scope IN ('round','rider')", name="ck_planning_runs_scope"),
        CheckConstraint("(scope = 'rider') = (rider_id IS NOT NULL)", name="ck_planning_runs_rider_scope"),
        CheckConstraint("scope = 'round' OR (base_plan_id IS NOT NULL AND origin_kind IS NOT NULL)",
                        name="ck_planning_runs_rider_fields"),
        CheckConstraint("origin_kind IS NULL OR origin_kind IN ('current_position','last_completed_stop','configured_start')",
                        name="ck_planning_runs_origin_kind"),
        Index("uq_planning_runs_one_active_round", "round_id", unique=True,
              postgresql_where=text("state IN ('queued','running') AND scope = 'round'")),
        Index("uq_planning_runs_one_active_rider", "round_id", "rider_id", unique=True,
              postgresql_where=text("state IN ('queued','running') AND scope = 'rider'")),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    round_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("delivery_rounds.id", ondelete="CASCADE"), nullable=False,
                                                index=True)
    state: Mapped[str] = mapped_column(String(16), nullable=False)
    requested_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    input_version: Mapped[int] = mapped_column(Integer, nullable=False)
    input_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)  # HMAC-SHA256, hex
    mode: Mapped[str] = mapped_column(String(16), nullable=False)
    scope: Mapped[str] = mapped_column(String(8), nullable=False, server_default=text("'round'"))
    rider_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("riders.id", ondelete="RESTRICT"), nullable=True)
    base_plan_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("route_plans.id", ondelete="CASCADE", use_alter=True,
                                                                      name="fk_planning_runs_base_plan_id"), nullable=True)
    origin_kind: Mapped[str | None] = mapped_column(String(24), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(48), nullable=True)
    error_message: Mapped[str | None] = mapped_column(String(500), nullable=True)
    error_details: Mapped[list | None] = mapped_column(JSONB, nullable=True)  # order codes / rider names only
    timings: Mapped[dict | None] = mapped_column(JSONB, nullable=True)


class RoutePlan(Base):
    """A committed plan version. At most one current plan per round (partial unique index)."""

    __tablename__ = "route_plans"
    __table_args__ = (
        UniqueConstraint("round_id", "version", name="uq_route_plans_round_version"),
        CheckConstraint("version >= 1", name="ck_route_plans_version"),
        CheckConstraint("mode IN ('equal','smart','manual')", name="ck_route_plans_mode"),
        CheckConstraint("route_version >= 1", name="ck_route_plans_route_version"),
        Index("uq_route_plans_one_current", "round_id", unique=True, postgresql_where=text("is_current")),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    round_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("delivery_rounds.id", ondelete="CASCADE"), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("planning_runs.id", ondelete="CASCADE"), nullable=False,
                                              unique=True)
    is_current: Mapped[bool] = mapped_column(Boolean, nullable=False)
    mode: Mapped[str] = mapped_column(String(16), nullable=False)
    input_version: Mapped[int] = mapped_column(Integer, nullable=False)
    input_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    route_version: Mapped[int] = mapped_column(Integer, nullable=False)  # the round's route_version at commit
    distance_label: Mapped[str] = mapped_column(String(300), nullable=False)
    provenance: Mapped[dict] = mapped_column(JSONB, nullable=False)  # provider, profiles, real_road, recorded, solver; no coordinates
    warnings: Mapped[list] = mapped_column(JSONB, nullable=False)
    summary: Mapped[dict] = mapped_column(JSONB, nullable=False)
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    superseded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class PlanRoute(Base):
    """One rider's route in a plan. Distances count real road edges only; an open (Last stop)
    route's artificial final arc is never included."""

    __tablename__ = "plan_routes"
    __table_args__ = (
        CheckConstraint("vehicle IN ('scooter','bike')", name="ck_plan_routes_vehicle"),
        CheckConstraint("profile IN ('motor_scooter','motorcycle')", name="ck_plan_routes_profile"),
        CheckConstraint("(vehicle = 'scooter') = (profile = 'motor_scooter')", name="ck_plan_routes_vehicle_profile"),
        CheckConstraint("start_kind IN ('office','warehouse')", name="ck_plan_routes_start"),
        CheckConstraint("endpoint_kind IN ('office','warehouse','home','last_stop','custom')",
                        name="ck_plan_routes_endpoint"),
        CheckConstraint("open_route = (endpoint_kind = 'last_stop')", name="ck_plan_routes_open_route"),
        CheckConstraint("road_distance_m >= 0 AND road_duration_s >= 0", name="ck_plan_routes_costs"),
    )

    plan_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("route_plans.id", ondelete="CASCADE"), primary_key=True)
    rider_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("riders.id", ondelete="RESTRICT"), primary_key=True)
    vehicle: Mapped[str] = mapped_column(String(16), nullable=False)
    profile: Mapped[str] = mapped_column(String(16), nullable=False)
    capacity: Mapped[int] = mapped_column(Integer, nullable=False)
    start_kind: Mapped[str] = mapped_column(String(16), nullable=False)
    endpoint_kind: Mapped[str] = mapped_column(String(16), nullable=False)
    open_route: Mapped[bool] = mapped_column(Boolean, nullable=False)
    road_distance_m: Mapped[int] = mapped_column(Integer, nullable=False)
    road_duration_s: Mapped[int] = mapped_column(Integer, nullable=False)
    rider_route_version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))  # 4B: the rider's route_version at commit


class PlanOrder(Base):
    """Every order a plan covers, exactly once per plan (primary key). `active` orders carry
    their stop position; Postponed and Completed orders are held by their existing owner."""

    __tablename__ = "plan_orders"
    __table_args__ = (
        ForeignKeyConstraint(["plan_id", "rider_id"], ["plan_routes.plan_id", "plan_routes.rider_id"],
                             ondelete="CASCADE", name="fk_plan_orders_route"),
        CheckConstraint("role IN ('active','postponed','completed')", name="ck_plan_orders_role"),
        CheckConstraint("(role = 'active') = (stop_seq IS NOT NULL)", name="ck_plan_orders_seq_iff_active"),
        CheckConstraint("stop_seq IS NULL OR stop_seq >= 1", name="ck_plan_orders_seq"),
        Index("ix_plan_orders_route_seq", "plan_id", "rider_id", "stop_seq"),
    )

    plan_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    order_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("orders.id", ondelete="CASCADE"), primary_key=True)
    rider_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    stop_seq: Mapped[int | None] = mapped_column(Integer, nullable=True)


class RouteRevision(Base):
    """4B: one rider's own recalculated route, layered on the round plan `plan_id`, which stays
    immutable. A rider's effective route is their current revision for the round's current plan,
    or else their `plan_routes` row. A newer round plan makes every older revision ineffective
    (it is also marked superseded). Distances count real road edges only, from the origin; an
    open (Last stop) route excludes the virtual final arc. The origin's position is never stored:
    only its kind and, for the last-completed-stop fallback, that order."""

    __tablename__ = "route_revisions"
    __table_args__ = (
        ForeignKeyConstraint(["plan_id", "rider_id"], ["plan_routes.plan_id", "plan_routes.rider_id"],
                             ondelete="CASCADE", name="fk_route_revisions_plan_route"),
        UniqueConstraint("plan_id", "rider_id", "revision", name="uq_route_revisions_number"),
        CheckConstraint("revision >= 1", name="ck_route_revisions_revision"),
        CheckConstraint("trigger IN ('rider_request','endpoint_change')", name="ck_route_revisions_trigger"),
        CheckConstraint("origin_kind IN ('current_position','last_completed_stop','configured_start')",
                        name="ck_route_revisions_origin_kind"),
        CheckConstraint("(origin_kind = 'last_completed_stop') = (origin_order_id IS NOT NULL)",
                        name="ck_route_revisions_origin_order"),
        CheckConstraint("vehicle IN ('scooter','bike')", name="ck_route_revisions_vehicle"),
        CheckConstraint("(vehicle = 'scooter') = (profile = 'motor_scooter')", name="ck_route_revisions_vehicle_profile"),
        CheckConstraint("endpoint_kind IN ('office','warehouse','home','last_stop','custom')",
                        name="ck_route_revisions_endpoint"),
        CheckConstraint("open_route = (endpoint_kind = 'last_stop')", name="ck_route_revisions_open_route"),
        CheckConstraint("road_distance_m >= 0 AND road_duration_s >= 0", name="ck_route_revisions_costs"),
        CheckConstraint("rider_route_version >= 1 AND round_route_version >= 1", name="ck_route_revisions_versions"),
        Index("uq_route_revisions_one_current", "plan_id", "rider_id", unique=True, postgresql_where=text("is_current")),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    round_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("delivery_rounds.id", ondelete="CASCADE"), nullable=False,
                                                index=True)
    plan_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    rider_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("planning_runs.id", ondelete="CASCADE"), nullable=False,
                                              unique=True)
    is_current: Mapped[bool] = mapped_column(Boolean, nullable=False)
    trigger: Mapped[str] = mapped_column(String(16), nullable=False)
    origin_kind: Mapped[str] = mapped_column(String(24), nullable=False)
    origin_order_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("orders.id", ondelete="SET NULL"),
                                                              nullable=True)
    vehicle: Mapped[str] = mapped_column(String(16), nullable=False)
    profile: Mapped[str] = mapped_column(String(16), nullable=False)
    capacity: Mapped[int] = mapped_column(Integer, nullable=False)
    endpoint_kind: Mapped[str] = mapped_column(String(16), nullable=False)
    open_route: Mapped[bool] = mapped_column(Boolean, nullable=False)
    road_distance_m: Mapped[int] = mapped_column(Integer, nullable=False)
    road_duration_s: Mapped[int] = mapped_column(Integer, nullable=False)
    rider_route_version: Mapped[int] = mapped_column(Integer, nullable=False)
    round_route_version: Mapped[int] = mapped_column(Integer, nullable=False)
    input_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)  # keyed HMAC of the rider-scoped input
    provenance: Mapped[dict] = mapped_column(JSONB, nullable=False)  # provider, profile, real_road, recorded; no coordinates
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    superseded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class RevisionOrder(Base):
    """The rider's active Pending sequence in one revision. Postponed and Completed orders keep
    their owner through `assignments` and are not listed (they are not part of the sequence)."""

    __tablename__ = "revision_orders"
    __table_args__ = (
        CheckConstraint("stop_seq >= 1", name="ck_revision_orders_seq"),
        Index("ix_revision_orders_seq", "revision_id", "stop_seq"),
    )

    revision_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("route_revisions.id", ondelete="CASCADE"),
                                                   primary_key=True)
    order_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("orders.id", ondelete="CASCADE"), primary_key=True)
    stop_seq: Mapped[int] = mapped_column(Integer, nullable=False)
