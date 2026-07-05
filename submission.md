# Project 5 — Mixtape Bug Hunt (Submission)

**Author:** Sunny Liu
**Branch:** `bugfix/mixtape`
**Bugs fixed:** all 5 (Issues #1–#5)

---

## AI Usage

I used AI coding tools (Codex and Claude Code) throughout this project, mostly for
**navigation and verification**, and I read every change myself before committing it.

**Where AI genuinely helped:**

- **Codebase orientation.** I pasted each `services/*.py` file and asked "what is this module
  responsible for and what does each function do?" This let me build the codebase map below
  quickly instead of reverse-engineering every file cold.
- **Call-chain tracing.** I asked the AI to trace "route → service" for rating a song and for
  viewing a playlist. It correctly identified that `routes/` do nothing but parse input and
  format responses, and that all logic lives in `services/`. I confirmed this by reading the
  blueprints in `app.py` and each route file.
- **Comparing two similar code paths (Issue #4).** The most useful single prompt was giving the
  AI `add_to_playlist()` and `rate_song()` side by side and asking "what's the structural
  difference?" It pointed straight at the missing `create_notification(...)` call in `rate_song`.
- **`datetime` semantics (Issue #1).** I asked what `datetime.weekday()` returns for each day.
  Confirmed Sunday = 6, which is exactly what the buggy guard `today.weekday() != 6` was keying on.

**Where I had to verify or override the AI:**

- For Issue #2 the AI first suggested the bug might be a timezone mismatch. Reading the code
  showed the query and cutoff were both UTC — the real problem was simply that
  `RECENT_THRESHOLD` was 24 hours, which is not "now." I overrode the AI's first guess after
  reproducing with the seed data.
- For Issue #3 the AI initially proposed adding `.distinct()`. That would have masked the
  symptom. Reading the query showed the duplication came from an unnecessary `outerjoin` on
  `song_tags`; removing the join fixes the root cause and still returns tags (via the
  `Song.tags` relationship in `to_dict()`), so `.distinct()` was unnecessary.
- I confirmed every fix by running `pytest tests/` (16 passing) rather than trusting that the
  edits were correct.

---

## Codebase Map

Mixtape is a Flask app using the **app-factory pattern** (`create_app` in `app.py`) with
Flask-SQLAlchemy. It is organized in three clean layers: **models → services → routes**.

### Main files and their roles

- **`app.py`** — The application factory. Creates the Flask app, configures the SQLite database
  (`mixtape.db`), initializes `db`, and registers the four blueprints under URL prefixes
  (`/songs`, `/playlists`, `/users`, `/feed`). Also calls `db.create_all()`.
- **`models.py`** — All SQLAlchemy models plus three association tables:
  - `User` — has `listening_streak`, `last_listened_at`, and a self-referential many-to-many
    `friends` relationship via the `friendships` table.
  - `Song` — shared by a user (`shared_by` FK); has a many-to-many `tags` relationship via
    `song_tags`. Its `to_dict()` embeds `"tags": [tag.name for tag in self.tags]`.
  - `Tag`, `ListeningEvent`, `Rating` (unique per user+song), `Playlist`, `Notification`.
  - `playlist_entries` — the join table between playlists and songs; it carries an explicit
    **`position`** column, so playlist order is stored, not just insertion order.
- **`routes/`** — Thin HTTP layer. Every route parses input, calls exactly one service function,
  and formats the JSON response. No business logic lives here.
  - `songs.py` — `/search`, `/<id>` detail, `/<id>/rate`, `/<id>/listen`.
  - `playlists.py` — create, get, list songs, add song.
  - `users.py` — profile, `/streak`, `/notifications`, mark-read.
  - `feed.py` — `/<user_id>/listening-now`, `/<user_id>/activity`.
- **`services/`** — All business logic. One file per feature: `streak_service`, `feed_service`,
  `search_service`, `notification_service`, `playlist_service`. **All five bugs live here.**
- **`seed_data.py`** — Populates realistic test data: 5 users with friendships, 25 songs with
  **0, 1, and 3+ tags** (the multi-tag songs are what expose Issue #3), playlists, recent and
  old listening events, and one existing playlist-add notification (the working example for
  Issue #4).
- **`tests/`** — `test_streaks.py`, `test_search.py`, `test_playlists.py`, plus regression tests
  I added: `test_feed.py` and `test_notifications.py`.

### Data flow — rating a song triggers a notification

1. `POST /songs/<song_id>/rate` hits `rate()` in `routes/songs.py`, which reads `user_id` and
   `score` from the JSON body.
2. It calls `notification_service.rate_song(user_id, song_id, score)`.
3. `rate_song` validates the score (1–5), loads the `Song` and the rating `User`, and either
   updates the existing `Rating` or creates a new one.
4. **If the rater is not the original sharer** (`song.shared_by != user_id`), it creates a
   `Notification` of type `"song_rated"` addressed to `song.shared_by`.
5. It commits and returns the `Rating`; the route serializes it with `to_dict()` as `201`.

This mirrors the existing `add_to_playlist()` flow, which notifies the sharer with type
`"song_added_to_playlist"` — the pattern Issue #4 was supposed to follow but didn't.

### Patterns I noticed

- **Strict layering.** Routes never touch the DB directly (except a trivial user lookup);
  everything goes through a service. This made tracing every bug straightforward: start at the
  route, follow the single service call.
- **`to_dict()` everywhere.** Each model owns its serialization, so services return model
  objects/lists and routes call `to_dict()`.
- **Relationships over manual joins.** `Song.tags` and `Playlist.songs` use SQLAlchemy
  relationships. Issue #3 was caused by a *manual* join fighting the relationship layer.

---

## Root Cause Analysis

### Issue #1 — My listening streak keeps resetting

- **How I reproduced it:** In `flask shell` I called `update_listening_streak(user, now)` for a
  user whose `last_listened_at` was exactly one day earlier, with `now` set to a **Sunday**. The
  streak reset to 1 instead of incrementing. On any other weekday with the same one-day gap, it
  incremented correctly. That "Sunday only" split confirmed the report.
- **How I found the root cause:** README pointed Issue #1 at `streak_service.py`. Reading
  `update_listening_streak`, the increment branch was
  `elif days_since_last == 1 and today.weekday() != 6:`. I confirmed with a quick check that
  `datetime.weekday()` returns **6 for Sunday** — so the guard specifically excluded Sundays
  from the "consecutive day" case.
- **The root cause:** The increment branch required both a one-day gap **and** that today was not
  Sunday. Python's `datetime.weekday()` returns 6 for Sunday, so any streak update on a Sunday
  failed the `today.weekday() != 6` condition, fell through to the `else`, and reset the streak
  to 1 — even though the user had listened the day before. Day-of-week should have no bearing on
  whether consecutive-day listening extends a streak; the condition was spurious.
- **My fix and side-effect check:** Removed the `and today.weekday() != 6` clause, so the branch
  is now `elif days_since_last == 1:`. I verified both sides of the boundary: a one-day gap now
  increments on every weekday including Sunday, `days_since_last == 0` still no-ops, and a gap of
  2+ days still resets to 1. `test_streaks.py` still passes.

### Issue #2 — Friends Listening Now shows people from yesterday

- **How I reproduced it:** After `python seed_data.py`, I hit
  `GET /feed/<nova_id>/listening-now`. The feed included friends whose most recent listen was
  hours ago, not people actively listening "now."
- **How I found the root cause:** README pointed Issue #2 at `feed_service.py`.
  `get_friends_listening_now` computes `cutoff = now - RECENT_THRESHOLD` and filters
  `ListeningEvent.listened_at >= cutoff`. The query logic was correct; the constant
  `RECENT_THRESHOLD = timedelta(hours=24)` was the problem — a 24-hour window counts a listen
  from yesterday as "now."
- **The root cause:** The recency window for "listening now" was set to 24 hours. "Now" should
  mean the last several minutes, so anyone who listened at any point in the previous day
  qualified, producing the stale-looking feed.
- **My fix and side-effect check:** Changed `RECENT_THRESHOLD` to `timedelta(minutes=30)`. I
  checked both sides of the boundary with `test_feed.py` (added): a friend active 10 minutes ago
  appears, a friend active 23 hours ago does not. I deliberately left `get_activity_feed`
  untouched — its docstring says it is intentionally *not* recency-filtered, so it should keep
  returning the most recent N events regardless of age.

### Issue #3 — The same song keeps showing up twice in search

- **How I reproduced it:** After seeding, I hit `GET /songs/search?q=a`. Songs with **3+ tags**
  (e.g. "Crown Heights Anthem") appeared multiple times, while songs with 0 or 1 tag appeared
  once. The duplication count matched each song's tag count — the tell-tale sign of a join
  fan-out.
- **How I found the root cause:** README pointed Issue #3 at `search_service.py`. The query was
  `db.session.query(Song).outerjoin(song_tags, Song.id == song_tags.c.song_id).filter(...)`.
  Joining `Song` to the `song_tags` association table produces **one row per (song, tag)** pair,
  so a song with 3 tags comes back 3 times. This explains why the bug is *conditional*: songs
  with 0 or 1 tag can't fan out.
- **The root cause:** An unnecessary `outerjoin` on `song_tags` multiplied result rows by the
  number of tags per song. The join wasn't even needed — `Song.to_dict()` already loads tag
  names through the `Song.tags` relationship, so search never had to join the tag table itself.
- **My fix and side-effect check:** Removed the `.outerjoin(song_tags, ...)` line (and the now
  unused `Tag, song_tags` import). Search now returns each matching `Song` exactly once, and
  `to_dict()` still populates the `"tags"` list via the relationship. I confirmed with
  `test_search.py` and by re-querying a multi-tag song. I intentionally did **not** paper over it
  with `.distinct()`, which would hide the fan-out rather than remove its cause.

### Issue #4 — Notified when a friend added my song to a playlist but not when they rated it

- **How I reproduced it:** As nova I checked `GET /users/<nova_id>/notifications` (the seed
  includes a working `song_added_to_playlist` notification). Then darius rated one of nova's
  songs via `POST /songs/<song_id>/rate`. Re-checking nova's notifications showed **no new
  entry** — the playlist-add path notified, the rating path did not.
- **How I found the root cause:** README pointed Issue #4 at `notification_service.py`, and the
  hint said the cause is architectural, not a typo. I put `add_to_playlist()` and `rate_song()`
  side by side. `add_to_playlist` ends with a `song.shared_by != added_by_user_id` guard and a
  `create_notification(...)` call; `rate_song` saved the `Rating`, committed, and returned —
  with **no notification step at all**. That missing block was the whole bug.
- **The root cause:** `rate_song` never created a `Notification`. The parallel action
  (adding to a playlist) correctly notified the song's original sharer, but the rating action
  simply omitted the equivalent step, so sharers were never told their songs had been rated.
- **My fix and side-effect check:** Added a notification block to `rate_song`, mirroring the
  working pattern: guarded by `song.shared_by != user_id` (so you never notify yourself for
  rating your own song), type `"song_rated"`, addressed to `song.shared_by`, added to the
  session before the existing commit. I checked I didn't double-notify (the single `commit()` at
  the end still covers both the rating and the notification) and that re-rating an existing song
  still works. Covered by `test_notifications.py` (added): rating a friend's song creates exactly
  one notification for the sharer; rating your own song creates none.

### Issue #5 — The last song in a playlist never shows up

- **How I reproduced it:** After seeding, I hit `GET /playlists/<id>/songs`. The `count` and the
  returned list were always one short of the songs actually in the playlist (the highest-position
  song was missing every time).
- **How I found the root cause:** README pointed Issue #5 at `playlist_service.py`.
  `get_playlist_songs` builds the correctly-ordered list of `songs`, then returns
  `[song.to_dict() for song in songs[:-1]]`. The `[:-1]` slice drops the final element of the
  ordered list.
- **The root cause:** An off-by-one slice. `songs[:-1]` returns every song **except the last
  one**, so the song with the highest `position` was always excluded from the response — even
  though the query itself fetched it correctly.
- **My fix and side-effect check:** Changed `songs[:-1]` to `songs` so all songs are returned. I
  verified both boundaries: a playlist with N songs now returns N (last song included), and the
  ordering by `playlist_entries.position` is unchanged. `test_playlists.py` passes.

---

## Regression Tests

I added two new test files that would have caught these bugs before they were introduced:

- **`tests/test_feed.py`** — `test_listening_now_excludes_friend_active_hours_ago` seeds one
  friend active 10 minutes ago and one active 23 hours ago and asserts only the recent friend
  appears. With the old 24-hour `RECENT_THRESHOLD`, both would appear — the test fails on the
  buggy code (Issue #2).
- **`tests/test_notifications.py`** —
  `test_rating_friend_song_creates_notification_for_sharer` asserts a `song_rated` notification
  is created for the sharer, and `test_rating_own_song_does_not_create_notification` asserts you
  are not notified for rating your own song. The first test fails on the buggy code, which
  created no notification at all (Issue #4).

Full suite: `pytest tests/` → **16 passed**.

---

## Commit History (`git log --oneline` on `bugfix/mixtape`)

```
44503bc fix: include final song in playlists          # Issue #5
4208ef1 fix: notify sharers when songs are rated       # Issue #4
0243e36 fix: avoid duplicate song search results       # Issue #3
74008ef fix: limit listening now to recent activity    # Issue #2
dddc23d fix: correct Sunday streak boundary            # Issue #1
```

One commit per fix, each with a conventional `fix:` message.
*(Attach a screenshot of `git log --oneline` here for the portal submission.)*
