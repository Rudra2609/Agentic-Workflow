"""Planning gold set (Member 3), written for this project. Inputs: Member 2's outputs on Member 2's gold documents
(``FROM_DOC_INTEL``) and two hand-written requirement sets (``HANDWRITTEN``). ``REFERENCES`` (in
``references.py``) holds our hand-made reference plans and the dependencies every good plan must have."""

from typing import Any

# planning case -> Member 2 gold case it is made from
FROM_DOC_INTEL: dict[str, str] = {
    "tcp_chat": "g01_tcp_chat",          # guide §32: the golden scenario
    "lab_manual": "g02_lab_manual",
    "rubric": "g03_rubric",
    "project_brief": "g06_project_brief",
    "multipart": "g08_multipart",
    "request": "g09_request",
    "long_lab": "g10_long_lab",
}


def _req(rid: str, text: str, *, priority: str = "must", type_: str = "functional",
         confidence: float = 0.95) -> dict[str, Any]:
    return {"id": rid, "text": text, "priority": priority, "type": type_, "confidence": confidence,
            "source_ref": {"doc_id": "doc-1", "quote": text}}


HANDWRITTEN: dict[str, dict[str, Any]] = {
    # things no agent may plan (a demo in person, uploading to Moodle), a low-confidence requirement, open questions
    "adversarial": {
        "project_id": "P-adversarial",
        "requirements": [
            _req("R1", "The web app must let users register with an email address."),
            _req("R2", "Users must be able to reset their password by email.", confidence=0.9),
            _req("R3", "The app should be deployed to AWS.", priority="should", confidence=0.6),
            _req("R4", "Demonstrate the working app to your TA in person during week 8."),
            _req("R5", "Upload the final ZIP to Moodle before the deadline."),
            _req("R6", "Passwords must be stored hashed.", type_="non_functional", confidence=0.9),
        ],
        "constraints": [{"id": "C1", "text": "Use Django 5.", "kind": "technology"}],
        "deliverables": [{"id": "D1", "name": "Source code ZIP", "format": "zip"},
                         {"id": "D2", "name": "User guide", "format": "PDF"}],
        "open_questions": ["Which email provider may be used?"],
    },
    # a writing project: the template switches to the document kind
    "essay": {
        "project_id": "P-essay",
        "requirements": [
            _req("R1", "Write a 2000-word report comparing two version control systems."),
            _req("R2", "The report must discuss the branching and merging models of both systems."),
            _req("R3", "Include at least five academic references."),
            _req("R4", "Summarise the findings in a conclusion section."),
            _req("R5", "You may include diagrams of each workflow.", priority="could"),
        ],
        "constraints": [{"id": "C1", "text": "Use APA citation style.", "kind": "format"},
                        {"id": "C2", "text": "The report may not exceed 2000 words.", "kind": "format"}],
        "deliverables": [{"id": "D1", "name": "Report", "format": "PDF"}],
        "evaluation_criteria": [{"id": "E1", "criterion": "Analysis", "max_marks": 40},
                                {"id": "E2", "criterion": "Use of sources", "max_marks": 30},
                                {"id": "E3", "criterion": "Structure and writing", "max_marks": 30}],
        "total_marks": 100,
    },
}
