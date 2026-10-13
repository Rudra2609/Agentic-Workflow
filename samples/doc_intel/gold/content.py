"""Gold documents for Sprint 2 (Member 2), authored for this project (no third-party text).

Each document is a list of blocks. A sentence or list item that the extractor must find carries an :class:`Item`
label (R = requirement, C = constraint, D = deliverable); rubric/mark tables carry E (evaluation criterion) labels.
``build_gold.py`` renders the blocks to PDF / DOCX / scanned PDF / photo PNG / text and writes the expected
``RequirementSet``-shaped labels next to them, so the documents and their answers come from one source.
"""

from dataclasses import dataclass, field


@dataclass
class Item:
    kind: str                       # R | C | D
    priority: str = "must"          # R: must | should | could
    rtype: str = "functional"       # R: functional | non_functional
    ckind: str = "other"            # C: technology | format | process | resource | other
    fmt: str = ""                   # D: format
    name: str = ""                  # D: short name (defaults to the text)


def R(priority: str = "must", rtype: str = "functional") -> Item:
    return Item("R", priority=priority, rtype=rtype)


def C(ckind: str = "other") -> Item:
    return Item("C", ckind=ckind)


def D(name: str, fmt: str = "") -> Item:
    return Item("D", name=name, fmt=fmt)


@dataclass
class Crit:
    criterion: str
    marks: float
    levels: list[tuple[str, str, float | None]] = field(default_factory=list)  # (label, description, marks)
    group: str = ""                 # merged "section" cell, rubric tables only


# Block forms:
#   ("h1" | "h2", text)                   heading
#   ("p", [(sentence, Item | None), ...])  paragraph made of sentences
#   ("ul" | "ol", [(text, Item | None), ...])
#   ("marks", [Crit, ...])                 simple two-column marks table (Criterion | Marks)
#   ("rubric", [Crit, ...])                rubric table with level columns (and a merged Section column if groups)
#   ("total", marks)                       "Total: N marks" line
#   ("note", text)                         small print (footnote); never a requirement

TCP_CHAT = [
    ("h1", "IT 314 Assignment 2: Multi-client Chat Server"),
    ("p", [("This assignment asks you to build a small chat system that many clients can use at the same time.",
            None),
           ("Read the whole brief before you start.", None)]),
    ("h2", "1. Functional requirements"),
    ("ol", [("The server must accept at least 10 clients connected at the same time.", R()),
            ("Each client must choose a unique nickname when it connects.", R()),
            ("A message sent by one client must be delivered to every other connected client.", R()),
            ("The server shall announce when a client joins or leaves the chat.", R()),
            ("Clients should be able to send a private message with the command /msg <nickname> <text>.",
             R("should")),
            ("The server may keep a history of the last 50 messages for new clients.", R("could"))]),
    ("h2", "2. Quality requirements"),
    ("ul", [("The server must not crash when a client disconnects without warning.", R(rtype="non_functional")),
            ("Messages should reach other clients within one second on a local network.",
             R("should", "non_functional"))]),
    ("h2", "3. Constraints"),
    ("ul", [("Use Python 3.11 and the standard library only.", C("technology")),
            ("Use TCP sockets; do not use a web framework.", C("technology")),
            ("Work in groups of at most two students.", C("process"))]),
    ("h2", "4. What to submit"),
    ("ul", [("A ZIP file with the source code of the server and the client.", D("Source code", "ZIP")),
            ("A README that explains how to run both programs.", D("README", "Markdown or text")),
            ("A two-page report describing your design and how you tested it.", D("Design report", "PDF"))]),
    ("p", [("Submit everything on the course portal before 23:59 on Friday of week 6.", C("process"))]),
    ("h2", "5. Marking"),
    ("marks", [Crit("Correct message broadcasting", 30), Crit("Nicknames and join/leave notices", 15),
               Crit("Private messages", 15), Crit("Robustness to disconnects", 20),
               Crit("Code quality and README", 10), Crit("Design report", 10)]),
    ("total", 100),
    ("note", "Late submissions lose 10 % per day. This note is information, not a requirement for your program."),
]

LAB_MANUAL = [
    ("h1", "Lab 4: Unit Testing with pytest"),
    ("h2", "Objectives"),
    ("p", [("In this lab you practise writing small, independent unit tests.", None)]),
    ("h2", "Setup"),
    ("ol", [("Create a virtual environment for the lab.", None),
            ("Install pytest version 8 or newer in that environment.", C("technology")),
            ("Clone the starter repository from the course page.", None)]),
    ("h2", "Tasks"),
    ("ol", [("Write at least five unit tests for the function parse_date in dates.py.", R()),
            ("Each test must check exactly one behaviour and have a descriptive name.", R(rtype="non_functional")),
            ("Add a test that checks parse_date raises ValueError for the input 31/02/2024.", R()),
            ("Use pytest.mark.parametrize for the tests of valid dates.", R("should")),
            ("Measure statement coverage and reach at least 80 % for dates.py.", R(rtype="non_functional")),
            ("You may also add property-based tests with Hypothesis for extra credit.", R("could"))]),
    ("h2", "Rules"),
    ("ul", [("Do not change the code in dates.py; only add tests.", C("process")),
            ("All tests must run with the single command pytest -q.", C("process"))]),
    ("h2", "Hand-in"),
    ("ul", [("The tests folder as a ZIP file.", D("Tests folder", "ZIP")),
            ("A screenshot of the coverage report.", D("Coverage screenshot", "PNG"))]),
    ("h2", "Assessment"),
    ("marks", [Crit("Tests for valid dates", 4), Crit("Test for the invalid date", 2),
               Crit("Coverage of at least 80 %", 2), Crit("Test names and structure", 2)]),
    ("total", 10),
]

RUBRIC = [
    ("h1", "Software Design Project: Marking Scheme"),
    ("p", [("This document explains how the final project is marked.", None),
           ("The project is worth 50 marks in total.", None)]),
    ("rubric", [
        Crit("Use-case diagram covers all actors", 6,
             [("Excellent", "All actors and use cases, correct notation", 6),
              ("Adequate", "Most actors, minor notation errors", 4),
              ("Weak", "Missing actors or wrong notation", 1)], group="Analysis"),
        Crit("Requirements are testable", 8,
             [("Excellent", "Every requirement has a measurable acceptance test", 8),
              ("Adequate", "Most requirements are testable", 5),
              ("Weak", "Few requirements are testable", 2)], group="Analysis"),
        Crit("Class diagram matches the code", 10,
             [("Excellent", "Diagram and code agree completely", 10),
              ("Adequate", "Small differences", 6),
              ("Weak", "Diagram does not match the code", 2)], group="Design"),
        Crit("Design patterns are justified", 6,
             [("Excellent", "Each pattern is explained with a reason", 6),
              ("Adequate", "Patterns named but not justified", 3),
              ("Weak", "No patterns or wrong use", 0)], group="Design"),
        Crit("Working implementation", 12,
             [("Excellent", "All features work in the demo", 12),
              ("Adequate", "Main features work", 7),
              ("Weak", "Demo fails", 2)], group="Implementation"),
        Crit("Automated tests", 8,
             [("Excellent", "Tests cover all main features and pass", 8),
              ("Adequate", "Some tests", 4),
              ("Weak", "No tests", 0)], group="Implementation"),
    ]),
    ("total", 50),
    ("h2", "Rules"),
    ("ul", [("The design document must be submitted as a single PDF file.", D("Design document", "PDF")),
            ("The demo video must not be longer than five minutes.", C("format")),
            ("Every team member must present part of the demo.", R())]),
]

SCANNED = [
    ("h1", "Assignment 3: Library Management System"),
    ("p", [("You will build a command-line program that a small library can use to manage its books.", None)]),
    ("h2", "Requirements"),
    ("ol", [("The program must let a librarian add, edit and remove books.", R()),
            ("Each book must have a title, an author, an ISBN and a number of copies.", R()),
            ("Members must be able to borrow and return books.", R()),
            ("The program must refuse a loan when no copies are left.", R()),
            ("The program should show the list of overdue loans.", R("should")),
            ("Data must be saved to a file so that it is kept after the program closes.",
             R(rtype="non_functional"))]),
    ("h2", "Constraints"),
    ("ul", [("Write the program in Java 17.", C("technology")),
            ("Store the data in a CSV or JSON file, not in a database.", C("technology"))]),
    ("h2", "Submission"),
    ("ul", [("Submit the source code as a ZIP file.", D("Source code", "ZIP")),
            ("Submit a user guide of at most three pages.", D("User guide", "PDF"))]),
    ("marks", [Crit("Book management", 10), Crit("Borrowing and returning", 10), Crit("Saving data", 5),
               Crit("User guide", 5)]),
    ("total", 30),
]

PHOTO = [
    ("h1", "Quiz Practice Task"),
    ("ul", [("Write a function that returns the largest of three numbers.", R()),
            ("The function must work for negative numbers.", R()),
            ("Add at least three test cases.", R()),
            ("Send the file as answer.py.", D("Answer file", "Python file"))]),
]

PROJECT_BRIEF = [
    ("h1", "Client Brief: Campus Event Booking Website"),
    ("h2", "Background"),
    ("p", [("The student council wants a website where students can find and book campus events.", None),
           ("Today bookings happen through a shared spreadsheet, which often leads to double bookings.", None)]),
    ("h2", "Scope"),
    ("ul", [("Students must be able to browse upcoming events by date and category.", R()),
            ("Students must be able to book a seat and cancel a booking.", R()),
            ("The website must stop bookings when an event is full.", R()),
            ("Organisers must be able to create and edit their own events.", R()),
            ("Organisers should be able to download the list of attendees as a CSV file.", R("should")),
            ("The website could send reminder emails one day before an event.", R("could"))]),
    ("h2", "Non-functional requirements"),
    ("ul", [("Pages must load in under two seconds on the campus network.", R(rtype="non_functional")),
            ("The website must work on mobile phones.", R(rtype="non_functional")),
            ("Personal data must only be visible to the event organiser.", R(rtype="non_functional"))]),
    ("h2", "Constraints"),
    ("ul", [("The backend must be written in Python with Django or FastAPI.", C("technology")),
            ("The project budget for hosting is zero; use the university server.", C("resource")),
            ("The first version must be ready by 15 November.", C("process"))]),
    ("h2", "Deliverables"),
    ("deliverables_table", [("Deliverable", "Format", "Due"),
                            ("Requirements specification", "PDF", "Week 8"),
                            ("Working website", "Source code repository", "Week 12"),
                            ("Test report", "PDF", "Week 12")]),
]
PROJECT_BRIEF_DELIVERABLES = [D("Requirements specification", "PDF"), D("Working website", "Source code repository"),
                              D("Test report", "PDF")]

MESSY = [
    ("h1", "Mini Project: Weather Data Dashboard"),
    ("p", [("Weather stations on campus record temperature, humidity and wind speed every ten minutes.", None),
           ("Your team will turn these readings into a simple dashboard.", None)]),
    ("h2", "What the dashboard has to do"),
    ("p", [("The dashboard must read the CSV files that the stations produce.", R()),
           ("It must show a line chart of temperature for any chosen day.", R()),
           ("Users should be able to compare two stations on the same chart.", R("should")),
           ("The dashboard must flag readings that are missing for more than one hour.", R())]),
    ("h2", "Technical notes"),
    ("p", [("Use Python with pandas and matplotlib or Plotly.", C("technology")),
           ("The dashboard must open in under five seconds for one month of data.", R(rtype="non_functional"))]),
    ("h2", "Hand-in"),
    ("p", [("Hand in a Jupyter notebook or a small web app, plus a one-page summary of your findings.",
            D("Dashboard and summary", "Notebook or web app, PDF"))]),
    ("marks", [Crit("Reading and cleaning the data", 8), Crit("Charts", 8), Crit("Missing-data flags", 4)]),
    ("total", 20),
    ("note", "1 The station files use UTC timestamps. Footnotes give context only."),
]

PART_A = [
    ("h1", "Part A: Database Design"),
    ("ol", [("Draw an ER diagram for the hostel booking system.", R()),
            ("The schema must be in third normal form.", R(rtype="non_functional")),
            ("Submit the diagram as a PDF.", D("ER diagram", "PDF"))]),
    ("marks", [Crit("ER diagram", 10), Crit("Normalisation", 5)]),
    ("total", 15),
]
PART_B = [
    ("h1", "Part B: REST API"),
    ("ol", [("Implement endpoints to create, list and cancel bookings.", R()),
            ("Every endpoint must return JSON and proper HTTP status codes.", R()),
            ("Protect the endpoints with token authentication.", R(rtype="non_functional"))]),
    ("ul", [("Use the schema from Part A.", C("process"))]),
    ("marks", [Crit("Endpoints", 15), Crit("Authentication", 5)]),
    ("total", 20),
]
PART_C = [
    ("h1", "Part C: Testing"),
    ("ol", [("Write integration tests for every endpoint of Part B.", R()),
            ("Tests should run in the CI pipeline.", R("should")),
            ("Submit the test report as a PDF.", D("Test report", "PDF"))]),
    ("marks", [Crit("Integration tests", 10), Crit("CI pipeline", 5)]),
    ("total", 15),
]

REQUEST = [
    ("p", [("Build a to-do list web app where I can add tasks, mark them as done and delete them.", R()),
           ("Tasks should be saved so they are still there after I refresh the page.", R("should")),
           ("Use React for the front end.", C("technology"))]),
]

# A longer lab sheet (more than one model call) whose requirements sit in lists under lead-in sentences, the case a
# real IT 314 lab showed: "At minimum, your code needs to support:" is context, each list item is a requirement.
_FILLER = ("This part builds on the previous one, so keep your earlier notes at hand and reuse the names you chose. "
           "Read the whole part before you start writing anything. The garage in this lab is a fictional multi-level "
           "building next to the campus library; it has three levels, and each level has spots for motorcycles, "
           "compact cars and large cars. Drivers take a ticket at the entrance barrier and pay at the exit barrier "
           "before leaving. The examples in the lecture slides use a simpler garage with only one level, which is a "
           "good starting point for your own thinking. Discuss your ideas with your lab partner, sketch them on paper "
           "first, and only then move on to the computer.")
LONG_LAB = [
    ("h1", "Lab 8: Parking Garage Management System"),
    ("p", [("This lab walks you through the analysis, design and implementation of a small parking garage system.",
            None), (_FILLER, None)]),
    ("h2", "Part A: Requirements analysis"),
    ("p", [(_FILLER, None), ("Identify the actors that interact with the garage system.", R()),
           ("For each actor, describe at least two goals in one sentence each.", R())]),
    ("h2", "Part B: Domain model"),
    ("p", [(_FILLER, None), ("Your domain model must cover at least the following concepts:", None)]),
    ("ul", [("Levels and parking spots of different sizes", R()), ("Vehicles and their size classes", R()),
            ("Tickets with entry and exit times", R()), ("Payments for a ticket", R())]),
    ("h2", "Part C: Implementation"),
    ("p", [(_FILLER, None), ("Implement the domain model in an object-oriented language of your choice.", R()),
           ("At minimum, your program needs to support:", None)]),
    ("ol", [("Assigning the smallest free spot that fits a vehicle", R()),
            ("Issuing a ticket when a vehicle enters", R()),
            ("Calculating the fee from the entry and exit times", R()),
            ("Freeing the spot when the vehicle leaves", R())]),
    ("p", [("The fee rules should be easy to change without editing the ticket class.", R("should", "non_functional"))]),
    ("h2", "Part D: Command-line interface"),
    ("p", [(_FILLER, None), ("Your command-line interface should support these operations:", None)]),
    ("ul", [("Park a vehicle", R("should")), ("Remove a vehicle and print its fee", R("should")),
            ("Show the free spots on each level", R("should"))]),
    ("h2", "Part E: Testing and submission"),
    ("p", [(_FILLER, None), ("Write unit tests for the spot assignment and the fee calculation.", R()),
           ("Use only the standard library of your language.", C("technology"))]),
    ("ul", [("Submit the source code as a ZIP file.", D("Source code", "ZIP")),
            ("Submit the class diagram as a PDF.", D("Class diagram", "PDF"))]),
    ("marks", [Crit("Requirements analysis", 4), Crit("Domain model", 6), Crit("Implementation", 10),
               Crit("Command-line interface", 4), Crit("Tests", 6)]),
    ("total", 30),
]
