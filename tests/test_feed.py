"""
tests/test_feed.py - Mixtape

Tests for friends listening now feed logic.
"""

import pytest
from datetime import datetime, timedelta, timezone
from app import create_app, db
from models import User, Song, ListeningEvent, friendships
from services.feed_service import get_friends_listening_now


@pytest.fixture
def app():
    app = create_app({"TESTING": True, "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:"})
    with app.app_context():
        db.create_all()
        yield app
        db.drop_all()


def test_listening_now_excludes_friend_active_hours_ago(app):
    """Friends Listening Now should only show genuinely recent listens."""
    with app.app_context():
        current_user = User(username="nova", email="nova@example.com")
        recent_friend = User(username="darius", email="darius@example.com")
        old_friend = User(username="simone", email="simone@example.com")
        db.session.add_all([current_user, recent_friend, old_friend])
        db.session.flush()

        db.session.execute(friendships.insert().values(user_id=current_user.id, friend_id=recent_friend.id))
        db.session.execute(friendships.insert().values(user_id=recent_friend.id, friend_id=current_user.id))
        db.session.execute(friendships.insert().values(user_id=current_user.id, friend_id=old_friend.id))
        db.session.execute(friendships.insert().values(user_id=old_friend.id, friend_id=current_user.id))

        recent_song = Song(title="Fresh Track", artist="The Now", shared_by=current_user.id)
        old_song = Song(title="Yesterday Jam", artist="The Past", shared_by=current_user.id)
        db.session.add_all([recent_song, old_song])
        db.session.flush()

        now = datetime.now(timezone.utc)
        db.session.add_all([
            ListeningEvent(
                user_id=recent_friend.id,
                song_id=recent_song.id,
                listened_at=now - timedelta(minutes=10),
            ),
            ListeningEvent(
                user_id=old_friend.id,
                song_id=old_song.id,
                listened_at=now - timedelta(hours=23),
            ),
        ])
        db.session.commit()

        feed = get_friends_listening_now(current_user.id)
        usernames = [item["friend"]["username"] for item in feed]

        assert usernames == ["darius"]

