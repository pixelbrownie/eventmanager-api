"""
main.py  -  SynergyPlanner API  (tech fest event manager)
=========================================================
WHAT THIS PROGRAM IS
    A backend for a big tech fest (Synergy) with many events and venues.
    Events often overlap in time, so SynergyPlanner:
      * refuses a registration that CLASHES with another event of the same person
      * puts people on a WAITLIST when an event is full
      * PROMOTES the first waitlisted person when someone cancels
      * shows every participant a clash-free schedule
    It has five kinds of data (MODELS): venues, events, participants,
    registrations (the LINK model) and feedback (optional extra).

HOW TO RUN IT
    1. Install once:      pip install -r requirements.txt
    2. Start the server:  uvicorn main:app --reload
    3. Open:              http://127.0.0.1:8000/docs
    4. The first start creates venues.json, events.json, participants.json,
       registrations.json and feedback.json next to this file.
       Clean start: stop the server, delete those five files, start again.

HOW THE ROLES WORK
    Every request may carry a HEADER named X-Role with one of:
        participant   (a student: registers, cancels, sees own schedule)
        organizer     (an event head: manages events, marks attendance)
        admin         (the fest committee: everything)
    no header or an unknown role -> 401 (we do not know who you are)
    a known role that may not do this -> 403

TESTING HELP
    Endpoints that depend on time accept an optional ?now=  (for example
    ?now=2026-12-05 or ?now=2026-12-05T11:30:00). The server then PRETENDS
    that this is the current moment.
"""
import json
import os
from datetime import date, datetime, timedelta
from typing import Literal

from fastapi import FastAPI, Header, HTTPException, Query
from pydantic import BaseModel, Field

app = FastAPI(
    title="SynergyPlanner API",
    description="Event registration for the Synergy tech fest: clash-free "
                "schedules, waitlists, three roles and data saved in JSON files.",
    version="1.0",
)

# =====================================================================
# SECTION 1 - SETTINGS
# Rules that may change live in ONE place, as named constants.
# A live change like "make the limit 3" is a one-line edit here.
# =====================================================================
MAX_EVENTS_PER_PARTICIPANT = 5   # active events (confirmed + waitlisted) per person
WAITLIST_CAP = 10                # how many people may wait for one full event
FEST_STARTS_IN_DAYS = 30         # starter events are placed this many days from the first start

# =====================================================================
# SECTION 2 - STORAGE (file handling)
# One JSON file per kind of data; the same two functions serve all five.
# =====================================================================

# SYNERGY_DATA is an optional setting used only for testing; by default the
# files sit next to this program.
DATA_FOLDER = os.environ.get("SYNERGY_DATA", os.path.dirname(os.path.abspath(__file__)))
VENUES_FILE = os.path.join(DATA_FOLDER, "venues.json")
EVENTS_FILE = os.path.join(DATA_FOLDER, "events.json")
PARTICIPANTS_FILE = os.path.join(DATA_FOLDER, "participants.json")
REGISTRATIONS_FILE = os.path.join(DATA_FOLDER, "registrations.json")
FEEDBACK_FILE = os.path.join(DATA_FOLDER, "feedback.json")

# Starter events are placed relative to the day the data files are first
# created, so the demo data never goes out of date.
DAY_1 = (date.today() + timedelta(days=FEST_STARTS_IN_DAYS)).isoformat()
DAY_2 = (date.today() + timedelta(days=FEST_STARTS_IN_DAYS + 1)).isoformat()

STARTER_VENUES = [
    {"id": 1, "name": "Main Auditorium", "capacity": 200},
    {"id": 2, "name": "CS Lab 1", "capacity": 60},
    {"id": 3, "name": "Seminar Hall", "capacity": 100},
]
# Events 1 and 2 overlap in time (a deliberate clash). Event 3 starts exactly
# when event 1 ends (back-to-back, allowed). Event 4 has only 2 seats
# (to test the waitlist).
STARTER_EVENTS = [
    {"id": 1, "title": "Hackathon Kickoff", "category": "technical", "venue_id": 1,
     "date": DAY_1, "start": "10:00", "end": "12:00", "capacity": 100, "fee": 100},
    {"id": 2, "title": "Robotics Workshop", "category": "workshop", "venue_id": 2,
     "date": DAY_1, "start": "11:00", "end": "13:00", "capacity": 40, "fee": 200},
    {"id": 3, "title": "AI Talk", "category": "talk", "venue_id": 3,
     "date": DAY_1, "start": "12:00", "end": "13:00", "capacity": 80, "fee": 0},
    {"id": 4, "title": "Code Quiz", "category": "technical", "venue_id": 2,
     "date": DAY_1, "start": "14:00", "end": "15:00", "capacity": 2, "fee": 50},
    {"id": 5, "title": "Gaming Finals", "category": "gaming", "venue_id": 1,
     "date": DAY_1, "start": "15:00", "end": "17:00", "capacity": 100, "fee": 100},
    {"id": 6, "title": "Startup Pitch", "category": "talk", "venue_id": 3,
     "date": DAY_2, "start": "10:00", "end": "12:00", "capacity": 50, "fee": 0},
]
STARTER_PARTICIPANTS = [
    {"id": 1, "name": "Riya Sharma", "email": "riya@example.com", "college": "BMS College"},
    {"id": 2, "name": "Arjun Mehta", "email": "arjun@example.com", "college": "RV College"},
    {"id": 3, "name": "Sana Khan", "email": "sana@example.com", "college": "PES University"},
]
# A registration looks like this (dates are saved as text):
#   {"id": 1, "event_id": 1, "participant_id": 2, "status": "confirmed",
#    "registered_on": "2026-11-11"}
# status moves:  confirmed -> cancelled | attended
#                waitlisted -> confirmed | cancelled


def save_data(path, data):
    """Write a whole list into a JSON file (replacing what was there)."""
    with open(path, "w", encoding="utf-8") as file:
        json.dump(data, file, indent=2, ensure_ascii=False)


def make_starter_copy(starter):
    """A copy of the starter list, so that the starter itself never changes."""
    starting_list = []
    for item in starter:
        starting_list.append(dict(item))
    return starting_list


def load_data(path, starter, required_keys):
    """Read a list from a JSON file.
    * File missing  -> create it from `starter`.
    * File damaged  -> EXCEPTION HANDLING: keep the damaged file under the
      name <file>.broken, print a warning, and start again from `starter`.
      The server never crashes because of a bad data file.
    `required_keys` lists the keys every record must have."""
    if not os.path.exists(path):
        starting_list = make_starter_copy(starter)
        save_data(path, starting_list)
        return starting_list
    try:
        with open(path, "r", encoding="utf-8") as file:
            data = json.load(file)
        if not isinstance(data, list):
            raise ValueError("the file must contain a list")
        for item in data:
            if not isinstance(item, dict):
                raise ValueError("every record must be a dictionary")
            for key in required_keys:
                if key not in item:
                    raise ValueError("a record is missing the key " + key)
        return data
    except (ValueError, OSError) as problem:
        # json.JSONDecodeError is a kind of ValueError, so it is caught here too.
        print("WARNING: " + os.path.basename(path) + " is damaged (" + str(problem) +
              "). Saved as .broken and restarted with starter data.")
        try:
            os.replace(path, path + ".broken")
        except OSError:
            pass
        starting_list = make_starter_copy(starter)
        save_data(path, starting_list)
        return starting_list


# Load everything ONCE when the server starts. From now on these five lists
# are the working copy; every change is also saved to its file.
venues = load_data(VENUES_FILE, STARTER_VENUES, ["id", "name", "capacity"])
events = load_data(EVENTS_FILE, STARTER_EVENTS,
                   ["id", "title", "category", "venue_id", "date", "start", "end", "capacity", "fee"])
participants = load_data(PARTICIPANTS_FILE, STARTER_PARTICIPANTS, ["id", "name", "email", "college"])
registrations = load_data(REGISTRATIONS_FILE, [],
                          ["id", "event_id", "participant_id", "status", "registered_on"])
feedback_list = load_data(FEEDBACK_FILE, [],
                          ["id", "event_id", "participant_id", "rating", "comment"])


# =====================================================================
# SECTION 3 - MODELS (Pydantic)
# "In" models describe what a caller SENDS. "Out" models describe what we
# send BACK. FastAPI checks both automatically.
# =====================================================================
Category = Literal["technical", "cultural", "gaming", "workshop", "talk", "sports"]
Status = Literal["confirmed", "waitlisted", "cancelled", "attended"]
DATE_PATTERN = r"^\d{4}-\d{2}-\d{2}$"                 # 2026-12-05
TIME_PATTERN = r"^([01]\d|2[0-3]):[0-5]\d$"           # 14:30


# ---------- venues ----------
class VenueIn(BaseModel):
    name: str = Field(min_length=2, max_length=60, examples=["Open Air Theatre"])
    capacity: int = Field(ge=1, le=2000, examples=[150])


class VenueOut(BaseModel):
    id: int
    name: str
    capacity: int


# ---------- events ----------
class EventIn(BaseModel):
    """What an organizer sends to create an event."""
    title: str = Field(min_length=2, max_length=100, examples=["Closing Ceremony"])
    category: Category = Field(examples=["cultural"])
    venue_id: int = Field(gt=0, examples=[1])
    date: str = Field(pattern=DATE_PATTERN, examples=["2026-12-05"])
    start: str = Field(pattern=TIME_PATTERN, examples=["18:00"])
    end: str = Field(pattern=TIME_PATTERN, examples=["19:00"])
    capacity: int = Field(ge=1, le=2000, examples=[100])
    fee: int = Field(default=0, ge=0, le=100000, examples=[0])      # whole rupees


class EventUpdate(BaseModel):
    """What an organizer may send to change SOME fields of an event (PATCH)."""
    title: str | None = Field(default=None, min_length=2, max_length=100)
    category: Category | None = None
    venue_id: int | None = Field(default=None, gt=0)
    date: str | None = Field(default=None, pattern=DATE_PATTERN)
    start: str | None = Field(default=None, pattern=TIME_PATTERN)
    end: str | None = Field(default=None, pattern=TIME_PATTERN)
    capacity: int | None = Field(default=None, ge=1, le=2000)
    fee: int | None = Field(default=None, ge=0, le=100000)


class EventOut(BaseModel):
    """An event as we send it back. The last three fields are CALCULATED."""
    id: int
    title: str
    category: str
    venue_id: int
    date: str
    start: str
    end: str
    capacity: int
    fee: int
    confirmed_count: int      # people holding a seat (confirmed or attended)
    waitlist_count: int       # people waiting
    seats_left: int           # capacity minus confirmed_count


# ---------- participants ----------
class ParticipantIn(BaseModel):
    name: str = Field(min_length=2, max_length=60, examples=["Meera Nair"])
    # pattern= is a REGULAR EXPRESSION: here "something@something.something".
    email: str = Field(pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$", examples=["meera@example.com"])
    college: str = Field(min_length=2, max_length=80, examples=["BMS College"])


class ParticipantOut(BaseModel):
    id: int
    name: str
    email: str
    college: str


# ---------- registrations (the LINK model) ----------
class RegistrationIn(BaseModel):
    event_id: int = Field(gt=0, examples=[1])
    participant_id: int = Field(gt=0, examples=[1])


class RegistrationOut(BaseModel):
    id: int
    event_id: int
    participant_id: int
    status: str
    registered_on: str


class CancelOut(BaseModel):
    """Reply of a cancellation: the cancelled registration, and the id of the
    waitlisted registration that moved up (None if nobody moved up)."""
    registration: RegistrationOut
    promoted_registration_id: int | None


class ScheduleItem(BaseModel):
    """One line of a participant's schedule."""
    registration_id: int
    status: str
    event_id: int
    title: str
    date: str
    start: str
    end: str
    venue_id: int


# ---------- feedback (OPTIONAL extra) ----------
class FeedbackIn(BaseModel):
    participant_id: int = Field(gt=0, examples=[1])
    rating: int = Field(ge=1, le=5, examples=[5])
    comment: str = Field(default="", max_length=300, examples=["Great event!"])


class FeedbackOut(BaseModel):
    id: int
    event_id: int
    participant_id: int
    rating: int
    comment: str


# =====================================================================
# SECTION 4 - HELPER FUNCTIONS
# Small functions that the endpoints share. Writing each idea ONCE keeps
# the endpoints short and the rules consistent.
# =====================================================================
def check_role(x_role, allowed):
    """Stop the request unless the X-Role header is one of the `allowed` roles."""
    if x_role not in ("participant", "organizer", "admin"):
        raise HTTPException(status_code=401,
                            detail="Send the header X-Role with the value participant, organizer or admin")
    if x_role not in allowed:
        raise HTTPException(status_code=403,
                            detail="The role '" + x_role + "' is not allowed to do this")


# ---------- one lookup per model; each raises the 404 ----------
def find_venue(venue_id):
    for venue in venues:
        if venue["id"] == venue_id:
            return venue
    raise HTTPException(status_code=404, detail="Venue not found")


def find_event(event_id):
    for event in events:
        if event["id"] == event_id:
            return event
    raise HTTPException(status_code=404, detail="Event not found")


def find_participant(participant_id):
    for participant in participants:
        if participant["id"] == participant_id:
            return participant
    raise HTTPException(status_code=404, detail="Participant not found")


def find_registration(registration_id):
    for registration in registrations:
        if registration["id"] == registration_id:
            return registration
    raise HTTPException(status_code=404, detail="Registration not found")


def next_id(items):
    """The next free id for a list of dictionaries: highest id + 1."""
    return max([item["id"] for item in items], default=0) + 1


# ---------- time helpers ----------
def pick_now(now):
    """The current moment, unless the caller asked us to pretend it is another."""
    if now is None:
        return datetime.now()
    return now.replace(tzinfo=None)


def to_minutes(hhmm):
    """'14:30' -> 870 (minutes since midnight), so times can be compared."""
    hours, minutes = hhmm.split(":")
    return int(hours) * 60 + int(minutes)


def times_overlap(start_a, end_a, start_b, end_b):
    """True if the two time ranges share any minutes.
    Back-to-back (end of one = start of the other) is NOT an overlap."""
    return to_minutes(start_a) < to_minutes(end_b) and to_minutes(start_b) < to_minutes(end_a)


def events_overlap(a, b):
    """True if two events are on the same date and their times overlap."""
    return a["date"] == b["date"] and times_overlap(a["start"], a["end"], b["start"], b["end"])


def event_has_started(event, current):
    """True if the event's start moment is now or in the past."""
    day = date.fromisoformat(event["date"])
    start_moment = datetime(day.year, day.month, day.day) + timedelta(minutes=to_minutes(event["start"]))
    return start_moment <= current


# ---------- counting helpers ----------
def seats_taken(event_id):
    """People holding a seat: confirmed or already attended."""
    count = 0
    for registration in registrations:
        if registration["event_id"] == event_id and registration["status"] in ("confirmed", "attended"):
            count = count + 1
    return count


def waitlist_size(event_id):
    count = 0
    for registration in registrations:
        if registration["event_id"] == event_id and registration["status"] == "waitlisted":
            count = count + 1
    return count


def active_events_of(participant_id):
    """Events this person is confirmed or waitlisted for (these count to the limit)."""
    count = 0
    for registration in registrations:
        if registration["participant_id"] == participant_id and \
                registration["status"] in ("confirmed", "waitlisted"):
            count = count + 1
    return count


def has_live_registrations(key, value):
    """True if any registration with registration[key] == value is not cancelled.
    Used to protect deletes: key is 'event_id' or 'participant_id'."""
    for registration in registrations:
        if registration[key] == value and registration["status"] != "cancelled":
            return True
    return False


def remove_cancelled_registrations(key, value):
    """When something is deleted, its cancelled registrations go with it."""
    for registration in list(registrations):          # list(...) = a copy to loop over
        if registration[key] == value and registration["status"] == "cancelled":
            registrations.remove(registration)
    save_data(REGISTRATIONS_FILE, registrations)


def event_view(event):
    """An event plus its calculated fields (the stored event is unchanged)."""
    view = dict(event)
    taken = seats_taken(event["id"])
    view["confirmed_count"] = taken
    view["waitlist_count"] = waitlist_size(event["id"])
    view["seats_left"] = event["capacity"] - taken
    return view


# ---------- the clash rule, shared by registering and by the waitlist ----------
def find_clash(participant_id, event):
    """Return an event of this participant (confirmed or attended) that overlaps
    `event` in time, or None if there is no clash."""
    for registration in registrations:
        if registration["participant_id"] == participant_id and \
                registration["status"] in ("confirmed", "attended"):
            other = find_event(registration["event_id"])
            if other["id"] != event["id"] and events_overlap(other, event):
                return other
    return None


def promote_from_waitlist(event):
    """A seat is free: give it to the FIRST waitlisted person (lowest registration
    id) who would not clash with something they already hold. Return the id of the
    promoted registration, or None if nobody could be promoted."""
    if seats_taken(event["id"]) >= event["capacity"]:
        return None
    for registration in registrations:
        if registration["event_id"] == event["id"] and registration["status"] == "waitlisted":
            if find_clash(registration["participant_id"], event) is None:
                registration["status"] = "confirmed"
                return registration["id"]
    return None


def check_event_fields(data, ignore_id=None):
    """Rules every event must obey, for a new event and for a changed one.
    `data` is a full event dictionary; `ignore_id` is the event itself when editing."""
    try:
        date.fromisoformat(data["date"])
    except ValueError:
        raise HTTPException(status_code=422, detail="date is not a real calendar date")
    if to_minutes(data["start"]) >= to_minutes(data["end"]):
        raise HTTPException(status_code=422, detail="end must be later than start")
    venue = find_venue(data["venue_id"])                               # 404
    if data["capacity"] > venue["capacity"]:
        raise HTTPException(status_code=409,
                            detail="Capacity is more than the venue holds (" + str(venue["capacity"]) + ")")
    for other in events:
        if other["id"] != ignore_id and other["venue_id"] == data["venue_id"] and events_overlap(other, data):
            raise HTTPException(status_code=409,
                                detail="The venue is already used by '" + other["title"] + "' at that time")


def time_order(item):
    """Sort key for a schedule: by date, then by start time."""
    return (item["date"], item["start"])


# =====================================================================
# SECTION 5 - ENDPOINTS
# Each endpoint: (1) check the role, (2) check everything exists (404),
# (3) check the rules (409), (4) change the data and SAVE, (5) reply.
# =====================================================================

# ---------- health (no role needed) ----------
# OWNER: Marali
@app.get("/health", tags=["system"], summary="Is the server alive?")
def health():
    return {"status": "ok"}


# ---------- events ----------
# OWNER: Ananya
# Browsing events needs no role: anyone may look at the programme.
@app.get("/events", response_model=list[EventOut], tags=["events"], summary="List events")
def list_events(category: Category | None = None,
                on_date: date | None = Query(default=None, alias="date"),
                only_open: bool = False):
    result = []
    for event in events:
        if category is not None and event["category"] != category:
            continue
        if on_date is not None and event["date"] != on_date.isoformat():
            continue
        view = event_view(event)
        if only_open and view["seats_left"] == 0:
            continue
        result.append(view)
    return result


@app.get("/events/{event_id}", response_model=EventOut, tags=["events"], summary="Get one event")
def get_event(event_id: int):
    return event_view(find_event(event_id))


@app.post("/events", status_code=201, response_model=EventOut, tags=["events"],
          summary="Create an event (organizer or admin)")
def add_event(body: EventIn, x_role: str | None = Header(default=None)):
    check_role(x_role, ["organizer", "admin"])
    data = body.model_dump()
    check_event_fields(data)
    event = dict(data)
    event["id"] = next_id(events)
    events.append(event)
    save_data(EVENTS_FILE, events)
    return event_view(event)


@app.patch("/events/{event_id}", response_model=EventOut, tags=["events"],
           summary="Change some fields of an event (organizer or admin)")
def update_event(event_id: int, body: EventUpdate, x_role: str | None = Header(default=None)):
    check_role(x_role, ["organizer", "admin"])
    event = find_event(event_id)
    changes = body.model_dump(exclude_none=True)         # only the fields that were sent
    candidate = dict(event)                              # try the change on a COPY first
    candidate.update(changes)
    check_event_fields(candidate, ignore_id=event_id)
    for key in ("date", "start", "end", "venue_id"):
        if key in changes and changes[key] != event[key] and has_live_registrations("event_id", event_id):
            raise HTTPException(status_code=409,
                                detail="An event with registrations cannot be moved or rescheduled")
    if "capacity" in changes and changes["capacity"] < seats_taken(event_id):
        raise HTTPException(status_code=409, detail="More people hold a seat than the new capacity")
    event.update(changes)
    # If the capacity grew, waiting people may now get a seat.
    promoted_any = True
    while promoted_any:
        promoted_any = promote_from_waitlist(event) is not None
    save_data(EVENTS_FILE, events)
    save_data(REGISTRATIONS_FILE, registrations)
    return event_view(event)


@app.delete("/events/{event_id}", status_code=204, tags=["events"],
            summary="Delete an event (organizer or admin)")
def delete_event(event_id: int, x_role: str | None = Header(default=None)):
    check_role(x_role, ["organizer", "admin"])
    event = find_event(event_id)
    if has_live_registrations("event_id", event_id):
        raise HTTPException(status_code=409, detail="This event still has registrations")
    remove_cancelled_registrations("event_id", event_id)
    events.remove(event)
    save_data(EVENTS_FILE, events)


@app.get("/events/{event_id}/conflicts", response_model=list[EventOut], tags=["events"],
         summary="Events that overlap this one in time (any role)")
def event_conflicts(event_id: int, x_role: str | None = Header(default=None)):
    check_role(x_role, ["participant", "organizer", "admin"])
    event = find_event(event_id)
    result = []
    for other in events:
        if other["id"] != event_id and events_overlap(other, event):
            result.append(event_view(other))
    return result


# ---------- venues ----------
# OWNER: Tehzeeb
@app.get("/venues", response_model=list[VenueOut], tags=["venues"], summary="List venues")
def list_venues():
    return venues


@app.post("/venues", status_code=201, response_model=VenueOut, tags=["venues"],
          summary="Add a venue (admin)")
def add_venue(body: VenueIn, x_role: str | None = Header(default=None)):
    check_role(x_role, ["admin"])
    for venue in venues:
        if venue["name"].lower() == body.name.lower():
            raise HTTPException(status_code=409, detail="A venue with this name already exists")
    venue = {"id": next_id(venues), "name": body.name, "capacity": body.capacity}
    venues.append(venue)
    save_data(VENUES_FILE, venues)
    return venue


# ---------- participants ----------
# OWNER: Tehzeeb
@app.post("/participants", status_code=201, response_model=ParticipantOut, tags=["participants"],
          summary="Register a participant (organizer or admin)")
def add_participant(body: ParticipantIn, x_role: str | None = Header(default=None)):
    check_role(x_role, ["organizer", "admin"])
    email = body.email.lower()
    for participant in participants:
        if participant["email"] == email:
            raise HTTPException(status_code=409, detail="This email is already registered")
    participant = {"id": next_id(participants), "name": body.name, "email": email,
                   "college": body.college}
    participants.append(participant)
    save_data(PARTICIPANTS_FILE, participants)
    return participant


@app.get("/participants", response_model=list[ParticipantOut], tags=["participants"],
         summary="List participants (admin)")
def list_participants(x_role: str | None = Header(default=None)):
    check_role(x_role, ["admin"])
    return participants


@app.get("/participants/{participant_id}", response_model=ParticipantOut, tags=["participants"],
         summary="Get one participant (any role)")
def get_participant(participant_id: int, x_role: str | None = Header(default=None)):
    check_role(x_role, ["participant", "organizer", "admin"])
    return find_participant(participant_id)


@app.delete("/participants/{participant_id}", status_code=204, tags=["participants"],
            summary="Delete a participant (admin)")
def delete_participant(participant_id: int, x_role: str | None = Header(default=None)):
    check_role(x_role, ["admin"])
    participant = find_participant(participant_id)
    if has_live_registrations("participant_id", participant_id):
        raise HTTPException(status_code=409, detail="This participant still has registrations")
    remove_cancelled_registrations("participant_id", participant_id)
    participants.remove(participant)
    save_data(PARTICIPANTS_FILE, participants)


# ---------- registrations: creating and listing ----------
# OWNER: Lagan
@app.post("/registrations", status_code=201, response_model=RegistrationOut, tags=["registrations"],
          summary="Register for an event (participant or admin)")
def register(body: RegistrationIn, x_role: str | None = Header(default=None),
             now: datetime | None = None):
    check_role(x_role, ["participant", "admin"])
    event = find_event(body.event_id)                   # 404 if unknown
    find_participant(body.participant_id)               # 404 if unknown
    current = pick_now(now)

    # The rules, checked in this order; the FIRST one that fails stops the request.
    if event_has_started(event, current):
        raise HTTPException(status_code=409, detail="This event has already started")
    for registration in registrations:
        if (registration["event_id"] == body.event_id
                and registration["participant_id"] == body.participant_id
                and registration["status"] != "cancelled"):
            raise HTTPException(status_code=409, detail="Already registered for this event")
    if active_events_of(body.participant_id) >= MAX_EVENTS_PER_PARTICIPANT:
        raise HTTPException(status_code=409,
                            detail="Limit reached: at most " + str(MAX_EVENTS_PER_PARTICIPANT) + " events per person")
    clash = find_clash(body.participant_id, event)
    if clash is not None:
        raise HTTPException(status_code=409,
                            detail="Time clash with '" + clash["title"] + "' which you already hold")

    # Seat or waitlist?
    if seats_taken(event["id"]) < event["capacity"]:
        status = "confirmed"
    elif waitlist_size(event["id"]) < WAITLIST_CAP:
        status = "waitlisted"
    else:
        raise HTTPException(status_code=409, detail="The event and its waitlist are full")

    registration = {"id": next_id(registrations), "event_id": body.event_id,
                    "participant_id": body.participant_id, "status": status,
                    "registered_on": current.date().isoformat()}
    registrations.append(registration)
    save_data(REGISTRATIONS_FILE, registrations)
    return registration


# `Literal[...]` limits a value to a fixed list. Anything else gives 422 for free,
# and /docs shows a drop-down.
@app.get("/registrations", response_model=list[RegistrationOut], tags=["registrations"],
         summary="List registrations, optionally filtered (organizer or admin)")
def list_registrations(status: Status | None = None, event_id: int | None = None,
                       x_role: str | None = Header(default=None)):
    check_role(x_role, ["organizer", "admin"])
    result = []
    for registration in registrations:
        if status is not None and registration["status"] != status:
            continue
        if event_id is not None and registration["event_id"] != event_id:
            continue
        result.append(registration)
    return result


@app.get("/participants/{participant_id}/schedule", response_model=list[ScheduleItem],
         tags=["registrations"], summary="A participant's schedule (any role)")
def participant_schedule(participant_id: int, x_role: str | None = Header(default=None)):
    check_role(x_role, ["participant", "organizer", "admin"])
    find_participant(participant_id)
    result = []
    for registration in registrations:
        if registration["participant_id"] == participant_id and registration["status"] != "cancelled":
            event = find_event(registration["event_id"])
            result.append({"registration_id": registration["id"], "status": registration["status"],
                           "event_id": event["id"], "title": event["title"], "date": event["date"],
                           "start": event["start"], "end": event["end"], "venue_id": event["venue_id"]})
    result.sort(key=time_order)
    return result


# ---------- registrations: status changes ----------
# OWNER: Marali
@app.post("/registrations/{registration_id}/cancel", response_model=CancelOut, tags=["registrations"],
          summary="Cancel a registration; the waitlist moves up (participant or admin)")
def cancel_registration(registration_id: int, x_role: str | None = Header(default=None),
                        now: datetime | None = None):
    check_role(x_role, ["participant", "admin"])
    registration = find_registration(registration_id)
    if registration["status"] == "cancelled":
        raise HTTPException(status_code=409, detail="This registration is already cancelled")
    if registration["status"] == "attended":
        raise HTTPException(status_code=409, detail="An attended registration cannot be cancelled")
    current = pick_now(now)
    if current.date() < date.fromisoformat(registration["registered_on"]):
        raise HTTPException(status_code=400, detail="Cannot cancel before the registration was made")

    held_a_seat = registration["status"] == "confirmed"
    registration["status"] = "cancelled"
    promoted_id = None
    if held_a_seat:                                      # a seat is free now
        promoted_id = promote_from_waitlist(find_event(registration["event_id"]))
    save_data(REGISTRATIONS_FILE, registrations)
    return {"registration": registration, "promoted_registration_id": promoted_id}


@app.post("/registrations/{registration_id}/attend", response_model=RegistrationOut,
          tags=["registrations"], summary="Mark attendance (organizer or admin)")
def mark_attended(registration_id: int, x_role: str | None = Header(default=None),
                  now: datetime | None = None):
    check_role(x_role, ["organizer", "admin"])
    registration = find_registration(registration_id)
    if registration["status"] != "confirmed":
        raise HTTPException(status_code=409, detail="Only a confirmed registration can be marked attended")
    event = find_event(registration["event_id"])
    if pick_now(now).date() != date.fromisoformat(event["date"]):
        raise HTTPException(status_code=409, detail="Attendance can only be marked on the event day")
    registration["status"] = "attended"
    save_data(REGISTRATIONS_FILE, registrations)
    return registration


@app.get("/events/{event_id}/registrations", response_model=list[RegistrationOut],
         tags=["registrations"], summary="Registrations of one event (organizer or admin)")
def event_registrations(event_id: int, status: Status | None = None,
                        x_role: str | None = Header(default=None)):
    check_role(x_role, ["organizer", "admin"])
    find_event(event_id)
    result = []
    for registration in registrations:
        if registration["event_id"] != event_id:
            continue
        if status is not None and registration["status"] != status:
            continue
        result.append(registration)
    return result


# ---------- report ----------
# OWNER: Marali
@app.get("/stats", tags=["system"], summary="Fest report (organizer or admin)")
def stats(now: datetime | None = None, x_role: str | None = Header(default=None)):
    check_role(x_role, ["organizer", "admin"])
    current = pick_now(now)

    by_status = {"confirmed": 0, "waitlisted": 0, "cancelled": 0, "attended": 0}
    live_per_person = {}                                 # participant_id -> not-cancelled registrations
    fees_collected = 0
    for registration in registrations:
        by_status[registration["status"]] = by_status[registration["status"]] + 1
        if registration["status"] != "cancelled":
            pid = registration["participant_id"]
            live_per_person[pid] = live_per_person.get(pid, 0) + 1
        if registration["status"] in ("confirmed", "attended"):
            fees_collected = fees_collected + find_event(registration["event_id"])["fee"]

    # Fullest event: highest (seats taken / capacity). Fractions are compared by
    # cross-multiplying, so no decimals are needed. On a tie the smaller id wins.
    fullest_id = None
    best_taken = 0
    best_capacity = 1
    for event in events:
        taken = seats_taken(event["id"])
        if taken * best_capacity > best_taken * event["capacity"]:
            fullest_id = event["id"]
            best_taken = taken
            best_capacity = event["capacity"]

    # Most active participant: most not-cancelled registrations; on a tie the smaller id wins.
    most_active = None
    best_count = 0
    for pid in sorted(live_per_person):
        if live_per_person[pid] > best_count:
            best_count = live_per_person[pid]
            most_active = pid

    upcoming = 0
    for event in events:
        if date.fromisoformat(event["date"]) >= current.date():
            upcoming = upcoming + 1

    return {
        "events": len(events),
        "upcoming_events": upcoming,
        "venues": len(venues),
        "participants": len(participants),
        "registrations": by_status,
        "fullest_event_id": fullest_id,
        "most_active_participant_id": most_active,
        "total_fees_collected": fees_collected,
    }


# ---------- feedback (OPTIONAL extra: delete this block if time is short) ----------
# OWNER: Tehzeeb
@app.post("/events/{event_id}/feedback", status_code=201, response_model=FeedbackOut,
          tags=["feedback"], summary="Give feedback on an attended event (participant or admin)")
def add_feedback(event_id: int, body: FeedbackIn, x_role: str | None = Header(default=None)):
    check_role(x_role, ["participant", "admin"])
    find_event(event_id)
    find_participant(body.participant_id)
    attended = False
    for registration in registrations:
        if (registration["event_id"] == event_id and registration["participant_id"] == body.participant_id
                and registration["status"] == "attended"):
            attended = True
    if not attended:
        raise HTTPException(status_code=409, detail="Only a participant who attended can give feedback")
    for item in feedback_list:
        if item["event_id"] == event_id and item["participant_id"] == body.participant_id:
            raise HTTPException(status_code=409, detail="Feedback was already given for this event")
    item = {"id": next_id(feedback_list), "event_id": event_id,
            "participant_id": body.participant_id, "rating": body.rating, "comment": body.comment}
    feedback_list.append(item)
    save_data(FEEDBACK_FILE, feedback_list)
    return item


@app.get("/events/{event_id}/feedback", response_model=list[FeedbackOut], tags=["feedback"],
         summary="Feedback of one event")
def list_feedback(event_id: int):
    find_event(event_id)
    result = []
    for item in feedback_list:
        if item["event_id"] == event_id:
            result.append(item)
    return result
