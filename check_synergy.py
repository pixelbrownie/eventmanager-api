"""
check_synergy.py  -  runs the whole test checklist against a RUNNING SynergyPlanner API
======================================================================================
It does by machine what the checklist in the README asks you to do by hand
in /docs: send a request, and compare the status code (and sometimes the
reply) with what we expect.

HOW TO USE IT
    1. Stop the server, delete venues.json, events.json, participants.json,
       registrations.json and feedback.json (the script needs a CLEAN start),
       then start the server again:     uvicorn main:app
    2. In a second terminal (once):     pip install requests
    3. Run:                             python check_synergy.py
       Another port:                    python check_synergy.py http://127.0.0.1:8010
    4. Every line says PASS or FAIL. To run it again, repeat from step 1.

The restart test and the damaged-file test cannot be automated here.
Do them by hand (see the README).
"""
import sys
from datetime import date, timedelta

import requests

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000"
PART = {"X-Role": "participant"}
ORG = {"X-Role": "organizer"}
ADM = {"X-Role": "admin"}

passed = 0
failed = 0


def check(name, response, expected_status, test=None):
    """Compare the status code, and (if `test` is given) the reply body."""
    global passed, failed
    ok = response.status_code == expected_status
    if ok and test is not None:
        ok = test(response.json())
    if ok:
        passed = passed + 1
        print("PASS  " + name)
    else:
        failed = failed + 1
        print("FAIL  " + name + "   (got " + str(response.status_code) +
              ", expected " + str(expected_status) + ")   " + response.text[:150])


def get(path, headers=None):
    return requests.get(BASE + path, headers=headers)


def post(path, body=None, headers=None):
    return requests.post(BASE + path, json=body, headers=headers)


def patch(path, body, headers=None):
    return requests.patch(BASE + path, json=body, headers=headers)


def delete(path, headers=None):
    return requests.delete(BASE + path, headers=headers)


def reg(event_id, participant_id, query=""):
    """Register a participant for an event."""
    return post("/registrations" + query, {"event_id": event_id, "participant_id": participant_id}, PART)


# ---------------------------------------------------------------- clean start?
try:
    start_events = get("/events").json()
    start_venues = get("/venues").json()
    start_participants = get("/participants", ADM).json()
    start_regs = get("/registrations", ORG).json()
except requests.exceptions.ConnectionError:
    print("Cannot reach the server at " + BASE + ". Is it running?")
    sys.exit(1)
if len(start_events) != 6 or len(start_venues) != 3 or len(start_participants) != 3 or len(start_regs) != 0:
    print("The data is not a clean start. Stop the server, delete the five .json files,")
    print("start the server again, then re-run.")
    sys.exit(1)

# The starter events sit on "day 1" and "day 2" of the fest; read them from the server.
day1 = start_events[0]["date"]
day2 = start_events[5]["date"]
today = date.today()

print("\n--- 1. Health and browsing (no role needed) ---")
check("GET /health", get("/health"), 200)
check("GET /events lists 6 events, all seats free", get("/events"), 200,
      lambda d: len(d) == 6 and all(e["seats_left"] == e["capacity"] for e in d))
check("GET /events/1", get("/events/1"), 200, lambda d: d["title"] == "Hackathon Kickoff")
check("GET /events?category=workshop", get("/events?category=workshop"), 200, lambda d: len(d) == 1)
check("GET /events?date=day2", get("/events?date=" + day2), 200, lambda d: len(d) == 1)
check("GET /events?only_open=true", get("/events?only_open=true"), 200, lambda d: len(d) == 6)
check("GET /events?category=bogus -> 422", get("/events?category=bogus"), 422)
check("GET /events/99 -> 404", get("/events/99"), 404)
check("GET /venues lists 3", get("/venues"), 200, lambda d: len(d) == 3)

print("\n--- 2. Creating events: roles ---")
closing = {"title": "Closing Ceremony", "category": "cultural", "venue_id": 1, "date": day1,
           "start": "18:00", "end": "19:00", "capacity": 100, "fee": 0}
check("POST /events without a role -> 401", post("/events", closing), 401)
check("POST /events as participant -> 403", post("/events", closing, PART), 403)
check("POST /events as organizer -> 201", post("/events", closing, ORG), 201,
      lambda d: d["id"] == 7 and d["seats_left"] == 100)

print("\n--- 3. Creating events: validation and rules ---")
clash_venue = dict(closing, title="Clash", start="11:00", end="12:00")
check("venue already used at that time -> 409", post("/events", clash_venue, ORG), 409)
back_to_back = dict(closing, title="Warm-up", start="19:00", end="20:00")
check("venue back-to-back is allowed -> 201", post("/events", back_to_back, ORG), 201,
      lambda d: d["id"] == 8)
check("capacity above venue capacity -> 409",
      post("/events", dict(closing, venue_id=2, start="20:00", end="21:00", capacity=100), ORG), 409)
check("end before start -> 422", post("/events", dict(closing, start="15:00", end="14:00"), ORG), 422)
check("impossible date -> 422", post("/events", dict(closing, date="2026-13-45"), ORG), 422)
check("time 25:00 -> 422", post("/events", dict(closing, start="25:00"), ORG), 422)
check("unknown venue -> 404", post("/events", dict(closing, venue_id=99), ORG), 404)
check("bad category -> 422", post("/events", dict(closing, category="dance"), ORG), 422)
check("negative fee -> 422", post("/events", dict(closing, fee=-5), ORG), 422)
check("title missing -> 422", post("/events", {"category": "talk", "venue_id": 1}, ORG), 422)

print("\n--- 4. Changing an event ---")
check("PATCH title as organizer", patch("/events/7", {"title": "Grand Closing"}, ORG), 200,
      lambda d: d["title"] == "Grand Closing")
check("PATCH as participant -> 403", patch("/events/7", {"title": "X Y"}, PART), 403)
check("PATCH unknown event -> 404", patch("/events/99", {"title": "X Y"}, ORG), 404)
check("PATCH capacity 0 -> 422", patch("/events/7", {"capacity": 0}, ORG), 422)
check("PATCH capacity above venue -> 409", patch("/events/7", {"capacity": 500}, ORG), 409)
check("PATCH into a clash in the same venue -> 409", patch("/events/7", {"start": "16:00"}, ORG), 409)

print("\n--- 5. Venues ---")
check("POST /venues as admin", post("/venues", {"name": "Open Air Theatre", "capacity": 300}, ADM), 201,
      lambda d: d["id"] == 4)
check("POST /venues as organizer -> 403", post("/venues", {"name": "Another Hall", "capacity": 50}, ORG), 403)
check("POST /venues duplicate name (any case) -> 409",
      post("/venues", {"name": "open air THEATRE", "capacity": 50}, ADM), 409)
check("POST /venues capacity 0 -> 422", post("/venues", {"name": "Tiny Hall", "capacity": 0}, ADM), 422)

print("\n--- 6. Participants ---")
meera = {"name": "Meera Nair", "email": "meera@example.com", "college": "BMS College"}
check("POST /participants as organizer", post("/participants", meera, ORG), 201, lambda d: d["id"] == 4)
check("POST /participants duplicate email (any case) -> 409",
      post("/participants", dict(meera, name="Meera N", email="MEERA@example.com"), ORG), 409)
check("POST /participants bad email -> 422", post("/participants", dict(meera, email="nope"), ORG), 422)
check("POST /participants as participant -> 403", post("/participants", meera, PART), 403)
check("POST /participants without a role -> 401", post("/participants", meera), 401)
check("register a fifth participant",
      post("/participants", {"name": "Karan Joshi", "email": "karan@example.com", "college": "RV College"}, ADM),
      201, lambda d: d["id"] == 5)
check("GET /participants as admin", get("/participants", ADM), 200, lambda d: len(d) == 5)
check("GET /participants as organizer -> 403", get("/participants", ORG), 403)
check("GET /participants/1 as participant", get("/participants/1", PART), 200)
check("GET /participants/1 without a role -> 401", get("/participants/1"), 401)
check("GET /participants/99 -> 404", get("/participants/99", PART), 404)

print("\n--- 7. Registering: happy path ---")
check("participant 1 registers for event 1", reg(1, 1), 201,
      lambda d: d["id"] == 1 and d["status"] == "confirmed" and d["registered_on"] == today.isoformat())
check("event 1 now has one seat taken", get("/events/1"), 200,
      lambda d: d["confirmed_count"] == 1 and d["seats_left"] == d["capacity"] - 1)
check("same person, same event again -> 409", reg(1, 1), 409)
check("event 2 overlaps event 1 -> 409 (time clash)", reg(2, 1), 409)
check("event 3 starts when event 1 ends -> 201 (back-to-back)", reg(3, 1), 201)

print("\n--- 8. Registering: errors ---")
check("unknown event -> 404", reg(99, 1), 404)
check("unknown participant -> 404", reg(1, 99), 404)
check("event_id 0 -> 422", post("/registrations", {"event_id": 0, "participant_id": 1}, PART), 422)
check("no role -> 401", post("/registrations", {"event_id": 1, "participant_id": 2}), 401)
check("organizer may not register -> 403",
      post("/registrations", {"event_id": 1, "participant_id": 2}, ORG), 403)
check("event already started -> 409", reg(1, 3, "?now=" + day1 + "T11:00:00"), 409)

print("\n--- 9. Waitlist (event 4 has only 2 seats) ---")
check("participant 1 takes seat 1 of event 4", reg(4, 1), 201, lambda d: d["id"] == 3 and d["status"] == "confirmed")
check("participant 2 takes seat 2 of event 4", reg(4, 2), 201, lambda d: d["id"] == 4 and d["status"] == "confirmed")
check("participant 3 is waitlisted", reg(4, 3), 201, lambda d: d["id"] == 5 and d["status"] == "waitlisted")
check("event 4 shows 0 seats left and 1 waiting", get("/events/4"), 200,
      lambda d: d["seats_left"] == 0 and d["confirmed_count"] == 2 and d["waitlist_count"] == 1)
check("only_open hides the full event 4", get("/events?only_open=true"), 200,
      lambda d: 4 not in [e["id"] for e in d])
check("GET /registrations?status=waitlisted", get("/registrations?status=waitlisted", ORG), 200,
      lambda d: len(d) == 1 and d[0]["participant_id"] == 3)

print("\n--- 10. The 5-event limit (test both sides) ---")
check("4th event for participant 1 (event 5)", reg(5, 1), 201)
check("5th event for participant 1 (event 6)", reg(6, 1), 201)
check("6th event for participant 1 -> 409 (limit)", reg(7, 1), 409)

print("\n--- 11. Looking at registrations ---")
check("GET /participants/1/schedule has 5 items, in time order", get("/participants/1/schedule", PART), 200,
      lambda d: len(d) == 5 and [i["event_id"] for i in d] == [1, 3, 4, 5, 6])
check("GET /participants/99/schedule -> 404", get("/participants/99/schedule", PART), 404)
check("GET /participants/1/schedule without a role -> 401", get("/participants/1/schedule"), 401)
check("GET /events/1/conflicts lists only event 2", get("/events/1/conflicts", PART), 200,
      lambda d: [e["id"] for e in d] == [2])
check("GET /events/1/conflicts without a role -> 401", get("/events/1/conflicts"), 401)
check("GET /events/99/conflicts -> 404", get("/events/99/conflicts", PART), 404)
check("GET /registrations as participant -> 403", get("/registrations", PART), 403)
check("GET /registrations?status=bogus -> 422", get("/registrations?status=bogus", ORG), 422)
check("GET /events/4/registrations as organizer", get("/events/4/registrations", ORG), 200, lambda d: len(d) == 3)
check("GET /events/4/registrations as participant -> 403", get("/events/4/registrations", PART), 403)
check("GET /events/99/registrations -> 404", get("/events/99/registrations", ORG), 404)

print("\n--- 12. Changing or deleting an event that has registrations ---")
check("delete event 1 with registrations -> 409", delete("/events/1", ORG), 409)
check("reschedule event 1 with registrations -> 409", patch("/events/1", {"start": "09:00"}, ORG), 409)
check("capacity of event 4 below its seats taken -> 409", patch("/events/4", {"capacity": 1}, ORG), 409)
check("delete participant 1 with registrations -> 409", delete("/participants/1", ADM), 409)
check("delete an event as participant -> 403", delete("/events/7", PART), 403)
check("delete unknown event -> 404", delete("/events/99", ORG), 404)

print("\n--- 13. Cancelling and the waitlist moving up ---")
check("cancel participant 1's seat in event 4 (registration 3)",
      post("/registrations/3/cancel", None, PART), 200,
      lambda d: d["registration"]["status"] == "cancelled" and d["promoted_registration_id"] == 5)
check("waitlisted participant 3 is now confirmed", get("/events/4/registrations?status=confirmed", ORG), 200,
      lambda d: sorted([r["id"] for r in d]) == [4, 5])
check("cancel the same registration again -> 409", post("/registrations/3/cancel", None, PART), 409)
check("cancel unknown registration -> 404", post("/registrations/99/cancel", None, PART), 404)
check("cancel without a role -> 401", post("/registrations/4/cancel"), 401)
check("cancel as organizer -> 403", post("/registrations/4/cancel", None, ORG), 403)
check("cancel with ?now= before the registration date -> 400",
      post("/registrations/4/cancel?now=2000-01-01", None, PART), 400)
check("participant 5 joins the waitlist of event 4 (registration 8)", reg(4, 5), 201,
      lambda d: d["id"] == 8 and d["status"] == "waitlisted")
check("cancelling a WAITLISTED registration moves nobody", post("/registrations/8/cancel", None, PART), 200,
      lambda d: d["promoted_registration_id"] is None)

print("\n--- 14. The waitlist skips someone who would now clash ---")
debug = {"title": "Debug Dash", "category": "gaming", "venue_id": 3, "date": day1,
         "start": "14:30", "end": "15:30", "capacity": 50, "fee": 30}
check("create event 9 (14:30 to 15:30, overlaps event 4)", post("/events", debug, ORG), 201,
      lambda d: d["id"] == 9)
check("participant 4 joins the waitlist of event 4 (registration 9)", reg(4, 4), 201,
      lambda d: d["id"] == 9 and d["status"] == "waitlisted")
check("participant 4 confirms event 9 (a waitlisted event does not clash)", reg(9, 4), 201,
      lambda d: d["id"] == 10 and d["status"] == "confirmed")
check("participant 5 joins the waitlist behind participant 4 (registration 11)", reg(4, 5), 201,
      lambda d: d["id"] == 11 and d["status"] == "waitlisted")
check("participant 5 cannot join the same waitlist twice -> 409", reg(4, 5), 409)
check("cancel registration 4 -> seat goes to 11, skipping 9 (clash)",
      post("/registrations/4/cancel", None, PART), 200,
      lambda d: d["promoted_registration_id"] == 11)
check("registration 9 is still waiting", get("/registrations?status=waitlisted", ORG), 200,
      lambda d: [r["id"] for r in d] == [9])

print("\n--- 15. Attendance ---")
check("mark registration 1 attended on the event day",
      post("/registrations/1/attend?now=" + day1, None, ORG), 200, lambda d: d["status"] == "attended")
check("attend again -> 409", post("/registrations/1/attend?now=" + day1, None, ORG), 409)
check("attend on the wrong day -> 409", post("/registrations/2/attend", None, ORG), 409)
check("attend as participant -> 403", post("/registrations/2/attend?now=" + day1, None, PART), 403)
check("attend unknown registration -> 404", post("/registrations/99/attend?now=" + day1, None, ORG), 404)
check("attend a cancelled registration -> 409", post("/registrations/3/attend?now=" + day1, None, ORG), 409)
check("attend a waitlisted registration -> 409", post("/registrations/9/attend?now=" + day1, None, ORG), 409)
check("mark registration 2 attended at 12:30", post("/registrations/2/attend?now=" + day1 + "T12:30:00", None, ORG),
      200)
check("an attended registration cannot be cancelled -> 409", post("/registrations/1/cancel", None, PART), 409)
check("an attended seat still counts", get("/events/1"), 200, lambda d: d["confirmed_count"] == 1)

print("\n--- 16. Feedback (optional extra) ---")
check("participant 1 gives feedback on event 1",
      post("/events/1/feedback", {"participant_id": 1, "rating": 5, "comment": "Great!"}, PART), 201,
      lambda d: d["id"] == 1)
check("feedback twice -> 409",
      post("/events/1/feedback", {"participant_id": 1, "rating": 4}, PART), 409)
check("feedback without attending -> 409",
      post("/events/1/feedback", {"participant_id": 2, "rating": 4}, PART), 409)
check("rating 6 -> 422", post("/events/1/feedback", {"participant_id": 1, "rating": 6}, PART), 422)
check("feedback on unknown event -> 404", post("/events/99/feedback", {"participant_id": 1, "rating": 4}, PART), 404)
check("feedback as organizer -> 403", post("/events/1/feedback", {"participant_id": 1, "rating": 4}, ORG), 403)
check("feedback without a role -> 401", post("/events/1/feedback", {"participant_id": 1, "rating": 4}), 401)
check("GET /events/1/feedback", get("/events/1/feedback"), 200, lambda d: len(d) == 1)

print("\n--- 17. The report ---")
check("GET /stats as participant -> 403", get("/stats", PART), 403)
check("GET /stats without a role -> 401", get("/stats"), 401)
check("GET /stats as organizer", get("/stats", ORG), 200,
      lambda d: d == {"events": 9, "upcoming_events": 9, "venues": 4, "participants": 5,
                      "registrations": {"confirmed": 5, "waitlisted": 1, "cancelled": 3, "attended": 2},
                      "fullest_event_id": 4, "most_active_participant_id": 1,
                      "total_fees_collected": 330})
check("GET /stats?now= far in the future: no upcoming events", get("/stats?now=2100-01-01", ADM), 200,
      lambda d: d["upcoming_events"] == 0)

print("\n--- 18. Deleting when allowed ---")
check("delete event 7 (no registrations)", delete("/events/7", ORG), 204)
check("event 7 is gone", get("/events/7"), 404)
check("delete participant 2 (only a cancelled registration)", delete("/participants/2", ADM), 204)
check("participant 2 is gone", get("/participants/2", ADM), 404)
check("participant 2's cancelled registration went with them", get("/registrations?status=cancelled", ORG), 200,
      lambda d: sorted([r["id"] for r in d]) == [3, 8])

print("\nPassed: " + str(passed) + "   Failed: " + str(failed))
print("Now do the restart test and the damaged-file test by hand (see the README).")
sys.exit(1 if failed > 0 else 0)
