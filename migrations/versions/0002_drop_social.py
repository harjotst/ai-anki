"""Friends, leaderboards and deck sharing are gone.

Decks are personal again: a deck belongs to whoever uploaded the material, and
nobody else studies it. Everything that existed only to connect two accounts
goes with the feature — the friendship and deck_member tables, and the
username and friend_code columns on account.

The review log is untouched. Reviews a person made on a deck somebody shared
with them stay in their history; only the scheduling rows for those cards go,
because the deck they point at is no longer theirs to study.

Revision ID: 0002_drop_social
Revises: 0001_baseline
"""

from alembic import op

revision = "0002_drop_social"
down_revision = "0001_baseline"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # IF EXISTS throughout: the baseline runs the current schema, so a database
    # built fresh never had any of this.
    op.execute(
        "DELETE FROM study_card s USING deck d"
        " WHERE s.deck_id = d.id AND d.account_id IS DISTINCT FROM s.account_id"
    )
    op.execute("DROP TABLE IF EXISTS friendship")
    op.execute("DROP TABLE IF EXISTS deck_member")
    op.execute("DROP INDEX IF EXISTS account_username_idx")
    op.execute("ALTER TABLE account DROP COLUMN IF EXISTS username")
    op.execute("ALTER TABLE account DROP COLUMN IF EXISTS friend_code")


def downgrade() -> None:
    # The shape comes back; the friendships and shares themselves do not.
    op.execute("ALTER TABLE account ADD COLUMN IF NOT EXISTS friend_code TEXT UNIQUE")
    op.execute("ALTER TABLE account ADD COLUMN IF NOT EXISTS username TEXT")
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS account_username_idx ON account(lower(username))"
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS deck_member (
            deck_id     TEXT NOT NULL REFERENCES deck(id) ON DELETE CASCADE,
            account_id  UUID NOT NULL REFERENCES account(id) ON DELETE CASCADE,
            shared_by   UUID NOT NULL REFERENCES account(id) ON DELETE CASCADE,
            created_at  TIMESTAMPTZ NOT NULL,
            PRIMARY KEY (deck_id, account_id)
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS deck_member_account_idx ON deck_member(account_id)")
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS friendship (
            account_low   UUID NOT NULL REFERENCES account(id) ON DELETE CASCADE,
            account_high  UUID NOT NULL REFERENCES account(id) ON DELETE CASCADE,
            state         TEXT NOT NULL,
            requested_by  UUID NOT NULL REFERENCES account(id) ON DELETE CASCADE,
            created_at    TIMESTAMPTZ NOT NULL,
            PRIMARY KEY (account_low, account_high),
            CHECK (account_low < account_high)
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS friendship_high_idx ON friendship(account_high)")
