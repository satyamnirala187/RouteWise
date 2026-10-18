"""Account changes that affect planning. The CLI calls these; the rules live only here.

Deactivation. A rider's account state is planning input (an inactive rider cannot be planned),
so deactivating a rider advances `input_version` of every round they currently participate in.
That one bump marks those rounds' saved plans out of date and makes any in-flight run end
`stale` at commit. Sessions are revoked as before. Ownership (assignments) and Completed
history are not touched; the round simply needs re-planning (readiness reports the inactive
account). A password or display-name change is not planning input and invalidates nothing.

Locking order, the same as plan commits and optimize requests:
    depots (FOR SHARE) → affected rounds (FOR UPDATE, sorted by id) → the user row (FOR UPDATE)
Plan commits and optimize requests read account state while holding the round lock and the
user row FOR SHARE (see `planning.capture`), so a deactivation and a plan commit serialise:
either the commit finishes first and the deactivation's bump then marks the new plan out of
date, or the deactivation commits first and the commit sees the inactive account and the new
`input_version` and ends `stale`.

A rider could be added to another round between reading the affected rounds and locking the
user row. The set is therefore read again once the user row is held; if it grew, everything is
rolled back and the deactivation retries with the larger set. Any round joined after that
point cannot get a valid plan: its commit waits for the user row and then sees the inactive
account.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.orm import Session as DBSession

from .models import Rider, RoundRider, Session, User
from .riders import bump_round_input, lock_depots_shared, lock_round

MAX_ATTEMPTS = 5


@dataclass(frozen=True)
class Deactivated:
    changed: bool                         # False when the account was already inactive
    rounds_invalidated: tuple[uuid.UUID, ...]
    sessions_revoked: int


def revoke_sessions(db: DBSession, user_id: uuid.UUID, now: datetime) -> int:
    return db.execute(update(Session).where(Session.user_id == user_id, Session.revoked_at.is_(None))
                      .values(revoked_at=now)).rowcount


def participating_rounds(db: DBSession, user_id: uuid.UUID) -> set[uuid.UUID]:
    return set(db.scalars(select(RoundRider.round_id).join(Rider, Rider.id == RoundRider.rider_id)
                          .where(Rider.user_id == user_id, RoundRider.participating.is_(True))).all())


def deactivate_user(db: DBSession, user_id: uuid.UUID, now: datetime) -> Deactivated:
    """Deactivate an account and invalidate the planning input it affects. Commits `db`
    (it may roll back and retry internally, so the caller must not hold other work in it)."""
    rounds = participating_rounds(db, user_id)
    db.rollback()
    for _ in range(MAX_ATTEMPTS):
        lock_depots_shared(db)
        for round_id in sorted(rounds):
            lock_round(db, round_id)
        user = db.get(User, user_id, with_for_update=True, populate_existing=True)
        if user is None:
            db.rollback()
            raise LookupError("no such user")
        now_rounds = participating_rounds(db, user_id)
        if not now_rounds <= rounds:
            rounds |= now_rounds
            db.rollback()  # a round was joined meanwhile; take its lock in order and retry
            continue
        changed = user.active
        invalidated: tuple[uuid.UUID, ...] = ()
        if changed:
            user.active = False
            invalidated = tuple(sorted(now_rounds))
            for round_id in invalidated:
                bump_round_input(db, round_id)
        revoked = revoke_sessions(db, user_id, now)
        db.commit()
        return Deactivated(changed, invalidated, revoked)
    db.rollback()
    raise RuntimeError("the rider kept joining rounds during deactivation; try again")
