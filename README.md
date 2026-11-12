# SynergyPlanner API

Event registration for the **Synergy** tech fest. With 50+ events, many overlap in time, so
SynergyPlanner refuses clashing registrations, runs a **waitlist** for full events, **promotes** the
first waiting person when someone cancels, and shows each participant a clash-free schedule.
Five kinds of data, three roles, saved in JSON files. No database.

## Run
    pip install -r requirements.txt
    uvicorn main:app --reload
Open http://127.0.0.1:8000/docs

The first start creates `venues.json`, `events.json`, `participants.json`, `registrations.json` and
`feedback.json` next to `main.py`.
**Clean start:** stop the server, delete those five files, start the server.

The starter events are placed 30 days after the first start: **day 1** and **day 2** below mean
the dates you see in `GET /events/1` and `GET /events/6`.

## Roles
Send a header `X-Role: participant`, `organizer` or `admin` (in /docs, type it into the `x-role` box).
No header or an unknown role gives 401; a known role that is not allowed gives 403.

| Role | May do |
|---|---|
| (none) | `GET /health`, `GET /events`, `GET /events/{id}`, `GET /venues`, `GET /events/{id}/feedback` |
| participant | register, cancel, see schedules, participants, event clashes, give feedback |
| organizer | create/change/delete events, register participants, list registrations, mark attendance, report |
| admin | everything, including venues and listing/deleting participants |

## Models
Venue, Event, Participant, **Registration** (links a participant to an event), Feedback (optional extra).
Registration status moves: `confirmed -> cancelled | attended`, `waitlisted -> confirmed | cancelled`.

## Rules (constants at the top of `main.py`)
1. No confirmed registration for two events that overlap in time (back-to-back is allowed) - 409
2. Full event: you join the waitlist (up to `WAITLIST_CAP`); waitlist full - 409
3. Cancelling a seat promotes the first waitlisted person who would not clash
4. At most `MAX_EVENTS_PER_PARTICIPANT` (5) active events per person - 409
5. Two events cannot overlap in one venue; event capacity cannot exceed the venue - 409
6. No duplicate registration; no registering for an event that already started - 409
7. Attendance only on the event day, only for confirmed registrations - 409
8. An event or participant with registrations that are not cancelled cannot be deleted; an event with registrations cannot be moved or rescheduled - 409
9. (optional) Feedback only after attending, once per event - 409

`?now=2026-12-05` or `?now=2026-12-05T11:30:00` on register, cancel, attend and `GET /stats` pretends
that this is the current moment, so time rules can be tested without waiting.

## Endpoints (22)
`GET /health` | `GET/POST /events` | `GET/PATCH/DELETE /events/{id}` | `GET /events/{id}/conflicts` |
`GET /events/{id}/registrations` | `GET/POST /venues` | `GET/POST /participants` |
`GET/DELETE /participants/{id}` | `GET /participants/{id}/schedule` | `GET/POST /registrations` |
`POST /registrations/{id}/cancel` | `POST /registrations/{id}/attend` | `GET /stats` |
`GET/POST /events/{id}/feedback`

## Testing
1. Clean start (see above).
2. Follow the checklist below in /docs, or run the automatic checks: `python check_synergy.py`
   (123 checks; optional argument: server URL, e.g. `python check_synergy.py http://127.0.0.1:8010`).
3. Restart test by hand: stop the server, start it (do not delete the files), call `GET /events` and
   `GET /registrations` (organizer): the data is still there.
4. Damaged-file test by hand: stop the server, put the text `{ not json` into `events.json`, start the server.
   `GET /events` still answers 200, the bad file is kept as `events.json.broken`, and the server prints a warning.

## Checklist (from a clean start, in order)
Bodies: `{"event_id":E,"participant_id":P}` for registrations. Roles: PART = participant, ORG = organizer, ADM = admin.

| # | Request (role) | State needed | Status | Expected reply or effect |
|---|---|---|---|---|
| 1 | GET /events | clean start | 200 | 6 events, seats_left = capacity |
| 2 | GET /events?category=workshop | any | 200 | 1 event |
| 3 | GET /events?category=bogus | any | 422 | invalid category |
| 4 | GET /events/99 | none | 404 | |
| 5 | POST /events (no role), valid body | any | 401 | |
| 6 | POST /events (PART) | any | 403 | |
| 7 | POST /events (ORG) `{"title":"Closing Ceremony","category":"cultural","venue_id":1,"date":day1,"start":"18:00","end":"19:00","capacity":100,"fee":0}` | clean start | 201 | id 7 |
| 8 | POST /events (ORG) in venue 1, day1, 11:00-12:00 | event 1 exists | 409 | venue clash |
| 9 | POST /events (ORG) in venue 1, day1, 19:00-20:00 | event 7 exists | 201 | back-to-back allowed |
| 10 | POST /events (ORG) venue 2, capacity 100 | any | 409 | above venue capacity (60) |
| 11 | POST /events (ORG) start 15:00, end 14:00 | any | 422 | end must be later |
| 12 | POST /events (ORG) with venue_id 99 | any | 404 | |
| 13 | PATCH /events/7 `{"title":"Grand Closing"}` (ORG) | event 7 exists | 200 | title changed |
| 14 | PATCH /events/7 `{"capacity":0}` (ORG) | any | 422 | |
| 15 | PATCH /events/99 (ORG) | none | 404 | |
| 16 | POST /venues (ADM) `{"name":"Open Air Theatre","capacity":300}` | clean start | 201 | id 4 |
| 17 | POST /venues (ORG) | any | 403 | |
| 18 | POST /venues same name, other case (ADM) | venue exists | 409 | |
| 19 | POST /participants (ORG) `{"name":"Meera Nair","email":"meera@example.com","college":"BMS College"}` | clean start | 201 | id 4 |
| 20 | POST /participants same email, other case (ORG) | participant exists | 409 | |
| 21 | POST /participants with email "nope" (ORG) | any | 422 | |
| 22 | GET /participants (ORG) | any | 403 | |
| 23 | GET /participants/1 (no role) | any | 401 | |
| 24 | POST /registrations (PART) event 1, participant 1 | clean start | 201 | confirmed, registered_on today |
| 25 | POST /registrations event 1, participant 1 again | row 24 | 409 | already registered |
| 26 | POST /registrations event 2, participant 1 | row 24 | 409 | time clash with event 1 |
| 27 | POST /registrations event 3, participant 1 | row 24 | 201 | back-to-back allowed |
| 28 | POST /registrations event 99, participant 1 | none | 404 | |
| 29 | POST /registrations with event_id 0 | any | 422 | |
| 30 | POST /registrations (ORG) | any | 403 | |
| 31 | POST /registrations?now=day1T11:00:00 event 1, participant 3 | event 1 starts 10:00 | 409 | already started |
| 32 | POST /registrations event 4, participant 1, then participant 2 | event 4 has 2 seats | 201, 201 | both confirmed |
| 33 | POST /registrations event 4, participant 3 | event 4 full | 201 | status waitlisted |
| 34 | GET /events/4 | row 33 | 200 | seats_left 0, waitlist_count 1 |
| 35 | POST /registrations events 5 and 6, participant 1 | holds 3 events | 201, 201 | the 4th and 5th are allowed |
| 36 | POST /registrations event 7, participant 1 | holds 5 events | 409 | limit (boundary) |
| 37 | GET /participants/1/schedule (PART) | rows 24-35 | 200 | 5 items in time order |
| 38 | GET /events/1/conflicts (PART) | any | 200 | only event 2 |
| 39 | DELETE /events/1 (ORG) | event 1 has registrations | 409 | |
| 40 | DELETE /participants/1 (ADM) | participant 1 has registrations | 409 | |
| 41 | POST /registrations/3/cancel (PART) | registration 3 = participant 1 in event 4 | 200 | cancelled; promoted_registration_id 5 |
| 42 | POST /registrations/3/cancel again | row 41 | 409 | |
| 43 | POST /registrations/4/cancel?now=2000-01-01 | registration 4 exists | 400 | before it was made |
| 44 | POST /registrations/1/attend?now=day1 (ORG) | registration 1 confirmed | 200 | attended |
| 45 | POST /registrations/2/attend (ORG), no ?now | not the event day | 409 | |
| 46 | POST /events/1/feedback (PART) `{"participant_id":1,"rating":5}` | row 44 | 201 | |
| 47 | POST /events/1/feedback participant 2 | participant 2 did not attend | 409 | |
| 48 | GET /stats (PART) | any | 403 | |
| 49 | GET /stats (ORG) | after the steps above | 200 | counts by status, fullest_event_id, total_fees_collected |
| 50 | DELETE /events/7 (ORG) | no registrations | 204 | then GET /events/7 gives 404 |
| 51 | Restart test (see Testing) | data exists | 200 | same data as before |
| 52 | Damaged-file test (see Testing) | broken events.json | 200 | no crash, `.broken` copy kept |

The waitlist-skipping rule has its own rows in `check_synergy.py` (section 14): a waiting person who
now clashes with something they confirmed is skipped, and the next person gets the seat.

## Files
- `main.py` - the whole API, five sections: settings, storage, models, helpers, endpoints
- `check_synergy.py` - automatic test checklist
- `requirements.txt`, `.gitignore`
