"""separate a lexeme's prior from its derived confidence

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-06

Why this exists, because the column name does not say it:

`conf_alpha`/`conf_beta` are *derived* — the projector recomputes them from the
observation log on every load. That was fine as long as every lexeme's whole
history was in the log. It is not true of a lexeme that arrives with evidence
already attached: a seeded persona, an imported dictionary, a profile migrated
from another device.

For those, the projection had to choose between the stored number and the log,
and it chose the log the moment a single observation existed. The visible
symptom was the opposite of the intent: correcting an imported term *lowered*
its confidence and could demote it from active to proposed, because a history
of four sightings was replaced by an arithmetic over one.

`prior_alpha`/`prior_beta` hold that pre-log evidence explicitly. The
projection is now `prior + log`, a pure function of both, with Beta(1, 1) — the
uniform prior, believing nothing — as the default for a lexeme that genuinely
started here. Existing rows are backfilled to Beta(1, 1) rather than to their
current confidence: their confidence was already derived from a log that is
still present, so copying it forward would double-count that evidence.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "lexeme",
        sa.Column("prior_alpha", sa.Float(), nullable=False, server_default="1.0"),
    )
    op.add_column(
        "lexeme",
        sa.Column("prior_beta", sa.Float(), nullable=False, server_default="1.0"),
    )


def downgrade() -> None:
    op.drop_column("lexeme", "prior_beta")
    op.drop_column("lexeme", "prior_alpha")
