"""``classify`` as one schema-constrained ``generate`` (Sprint 1, doc 02 §2.2). Swappable later (Sprint 11 may back
it with a dedicated classifier) because callers only see ``LLMClient.classify``.

Schema: one property per question (keyed by the question name) holding ``{"answer": <enum>, "confidence": 0..1}``.
Option lists: ``bool`` -> ``yes``/``no``; ``choice`` -> ``options``; ``score`` -> ``options`` or ``"1".."5"``.
"""

from typing import Annotated, Any

from pydantic import AfterValidator, BaseModel, BeforeValidator, ConfigDict, Field, JsonValue, create_model

from hmap.core.llm.base import ClassifyAnswer, ClassifyQuestion, Message
from hmap.core.llm.errors import LLMConfigError

BOOL_OPTIONS = ("yes", "no")
DEFAULT_SCORE_OPTIONS = ("1", "2", "3", "4", "5")

SYSTEM_PROMPT = (
    "You make short, typed decisions about the given state. For every question pick exactly one of the allowed "
    "options and give your confidence between 0 and 1. Reply only with the JSON object."
)


def options_for(question: ClassifyQuestion) -> list[str]:
    if question.kind == "bool":
        return list(BOOL_OPTIONS)
    if question.kind == "score":
        return list(question.options) or list(DEFAULT_SCORE_OPTIONS)
    if not question.options:
        raise LLMConfigError(f"classify question {question.name!r} (choice) has no options")
    return list(question.options)


def _canonical(options: list[str]) -> Any:
    lookup = {o.casefold(): o for o in options}

    def before(value: Any) -> Any:
        if isinstance(value, bool):
            value = "yes" if value else "no"
        if isinstance(value, int | float):
            value = str(value)
        if isinstance(value, str):
            return lookup.get(value.strip().casefold(), value)
        return value

    def after(value: str) -> str:
        if value not in options:
            raise ValueError(f"answer must be one of {options}")
        return value

    enum: list[JsonValue] = list(options)
    return Annotated[str, BeforeValidator(before), AfterValidator(after), Field(json_schema_extra={"enum": enum})]


def _clamp(value: Any) -> Any:
    if isinstance(value, int | float) and not isinstance(value, bool):
        return min(1.0, max(0.0, float(value)))
    return value


Confidence = Annotated[float, Field(ge=0.0, le=1.0), BeforeValidator(_clamp)]


def build_schema(questions: list[ClassifyQuestion]) -> type[BaseModel]:
    if not questions:
        raise LLMConfigError("classify needs at least one question")
    names = [q.name for q in questions]
    if len(set(names)) != len(names):
        raise LLMConfigError(f"classify question names must be unique: {names}")
    fields: dict[str, Any] = {}
    for i, q in enumerate(questions):
        item = create_model(f"Decision{i}", __config__=ConfigDict(extra="ignore"),
                            answer=(_canonical(options_for(q)), ...), confidence=(Confidence, ...))
        fields[f"q{i}"] = (item, Field(alias=q.name))
    model: type[BaseModel] = create_model("ClassifyAnswers", __config__=ConfigDict(extra="ignore"), **fields)
    return model


def build_messages(state: str, questions: list[ClassifyQuestion]) -> list[Message]:
    lines = ["State:", state.strip(), "", "Questions:"]
    for q in questions:
        lines.append(f"- {q.name} ({q.kind}); options: {' | '.join(options_for(q))}")
        for option, text in sorted(q.criteria.items()):
            lines.append(f"    {option}: {text}")
    return [Message(role="system", content=SYSTEM_PROMPT), Message(role="user", content="\n".join(lines))]


def to_answers(parsed: BaseModel, questions: list[ClassifyQuestion]) -> list[ClassifyAnswer]:
    out: list[ClassifyAnswer] = []
    for i, q in enumerate(questions):
        item = getattr(parsed, f"q{i}")
        answer: str = item.answer
        confidence = float(item.confidence)
        probabilities = {answer: round(confidence, 4)}
        if q.kind == "bool":
            other = "no" if answer == "yes" else "yes"
            probabilities[other] = round(1.0 - confidence, 4)
        out.append(ClassifyAnswer(name=q.name, answer=answer, probabilities=probabilities))
    return out
