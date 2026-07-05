"""
tests/test_notifications.py - Mixtape

Tests for notification creation.
"""

import pytest
from app import create_app, db
from models import User, Song, Notification
from services.notification_service import rate_song


@pytest.fixture
def app():
    app = create_app({"TESTING": True, "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:"})
    with app.app_context():
        db.create_all()
        yield app
        db.drop_all()


def test_rating_friend_song_creates_notification_for_sharer(app):
    """Rating a friend's shared song should notify the original sharer."""
    with app.app_context():
        sharer = User(username="nova", email="nova@example.com")
        rater = User(username="darius", email="darius@example.com")
        db.session.add_all([sharer, rater])
        db.session.flush()

        song = Song(title="Golden Hour", artist="Solange K", shared_by=sharer.id)
        db.session.add(song)
        db.session.commit()

        rate_song(rater.id, song.id, 5)

        notifications = db.session.query(Notification).filter_by(user_id=sharer.id).all()
        assert len(notifications) == 1
        assert notifications[0].notification_type == "song_rated"
        assert "darius" in notifications[0].body
        assert "Golden Hour" in notifications[0].body


def test_rating_own_song_does_not_create_notification(app):
    """Users should not be notified about rating their own shared songs."""
    with app.app_context():
        user = User(username="nova", email="nova@example.com")
        db.session.add(user)
        db.session.flush()

        song = Song(title="Self Spin", artist="Nova", shared_by=user.id)
        db.session.add(song)
        db.session.commit()

        rate_song(user.id, song.id, 4)

        notifications = db.session.query(Notification).filter_by(user_id=user.id).all()
        assert notifications == []
