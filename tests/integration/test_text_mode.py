"""Live text-mode run against real Gemini with a fixed scripted candidate."""

from __future__ import annotations

import pytest

from acme_agent.agent.text import TextInterview
from acme_agent.bootstrap import build_container
from acme_agent.config import Settings
from acme_agent.domain.models import EndReason, ScreeningStatus

pytestmark = pytest.mark.live

SCRIPT = [
    "Hola, sí, estoy de acuerdo con que se grabe la conversación.",
    "Quiero trabajar de repartidor.",
    "Me llamo Marta López García.",
    "Mi teléfono es 612 345 678.",
    "Mi correo es marta.lopez@example.com",
    "Me viene mejor la tienda de Sol, en Madrid.",
    "Puedo trabajar de lunes a viernes por las mañanas.",
    "Unas 25 horas a la semana.",
    "Puedo empezar el lunes que viene.",
    "Sí, tengo permiso para trabajar en España.",
    "Sí, tengo más de 18 años.",
    "Sí, tengo carnet de conducir.",
    "Sí, tengo moto propia.",
    "Tengo dos años de experiencia repartiendo comida en una pizzería.",
    "Hablo español e inglés.",
    "Sí, todo correcto, gracias.",
    "Eso es todo, muchas gracias. Adiós.",
]


async def test_scripted_spanish_rider_completes(live_settings: Settings) -> None:
    settings = live_settings
    interview = TextInterview(build_container(settings), language="es")
    await interview.start()
    for line in SCRIPT:
        if interview.is_over:
            break
        await interview.send(line)
    record = await interview.close()
    filled = [n for n, m in record.slot_meta.items() if m.status == "filled"]
    assert record.end_reason is EndReason.COMPLETED
    assert len(filled) >= 12
    assert record.screening.status is ScreeningStatus.MEETS_REQUIREMENTS
    assert record.model.text == settings.text_model
    assert record.model.prompt_version == "ana-v8"


async def test_rider_pay_question_is_answered_from_faq(live_settings: Settings) -> None:
    interview = TextInterview(build_container(live_settings), language="es")
    warmup = interview.start_faq_warmup()  # as `acme-agent chat` does; the cold build > 2 s
    await interview.start()
    await interview.send(SCRIPT[0])
    assert warmup is not None
    await warmup
    reply = await interview.send("¿cuánto pagan a los repartidores?")
    record = await interview.close()
    assert "10,50" in reply and "12,50" in reply
    answered = [e for e in record.events if e.type == "faq_answered"]
    assert answered and answered[0].payload["source"] == "faq_es.md#pay-rider"


async def test_declining_consent_asks_to_confirm_then_ends_with_goodbye(
    live_settings: Settings,
) -> None:
    interview = TextInterview(build_container(live_settings), language="es")
    await interview.start()
    first = await interview.send("No, prefiero que no se grabe.")
    assert not interview.is_over
    assert interview.controller.profile.consent_recording is None
    assert "?" in first  # asks whether they are sure / want to end the call
    last = await interview.send("Sí, estoy seguro, no quiero continuar.")
    assert interview.is_over
    assert interview.controller.end_reason is EndReason.DECLINED_CONSENT
    assert last.strip()  # a spoken goodbye, never a silent end
    record = await interview.close()
    assert record.transcript == []
    assert record.candidate.full_name is None


async def test_ambiguous_consent_is_not_recorded_and_gets_a_direct_question(
    live_settings: Settings,
) -> None:
    interview = TextInterview(build_container(live_settings), language="es")
    await interview.start()
    await interview.send("No, prefiero que no se grabe.")
    reply = await interview.send("No estoy de acuerdo, pero vale")
    assert interview.controller.profile.consent_recording is not True
    assert "?" in reply
    assert "consentimiento" in reply.lower() or "grab" in reply.lower()
    assert "sí o no" in reply.lower() or "si o no" in reply.lower()


async def test_faq_answer_returns_to_the_pending_question(live_settings: Settings) -> None:
    interview = TextInterview(build_container(live_settings), language="es")
    warmup = interview.start_faq_warmup()
    await interview.start()
    await interview.send(SCRIPT[0])
    assert warmup is not None
    await warmup
    pending = interview.controller.next_goal()
    reply = await interview.send("¿Dan uniforme?")
    assert interview.controller.next_goal() == pending  # nothing was skipped or filled
    lowered = reply.lower()
    assert "?" in reply, reply
    # The pending question is the role: the reply must ask about the position again.
    assert any(w in lowered for w in ("puesto", "rol", "repartidor", "cocina", "equipo")), reply
    await interview.close()


async def test_angry_candidate_is_offered_a_recruiter_and_escalated(
    live_settings: Settings,
) -> None:
    interview = TextInterview(build_container(live_settings), language="es")
    await interview.start()
    await interview.send(SCRIPT[0])
    replies = [
        await interview.send("esto es una pérdida de tiempo"),
        await interview.send("no entiendo por qué me preguntas esto otra vez, qué pesado"),
    ]
    scores = [t.sentiment for t in interview.transcript if t.speaker.value == "candidate"]
    print("sentiment scores:", scores)
    print("replies:", replies)
    assert interview.controller.consented
    offer = " ".join(replies).lower()
    assert any(w in offer for w in ("reclutador", "recruiter", "persona", "llame", "llamada")), (
        offer
    )
    if not interview.is_over:
        await interview.send("sí, que me llame una persona")
    record = await interview.close()
    assert record.end_reason is EndReason.ESCALATED
    assert record.screening.status is ScreeningStatus.NEEDS_HUMAN_REVIEW
    cand = [t for t in record.transcript if t.speaker.value == "candidate"]
    assert all(t.sentiment is not None for t in cand[1:3])
    assert record.sentiment is not None and record.sentiment.frustration_events >= 2
    print("aggregate:", record.sentiment)


async def test_escalation_collects_a_phone_before_promising_a_callback(
    live_settings: Settings,
) -> None:
    interview = TextInterview(build_container(live_settings), language="es")
    await interview.start()
    turns: list[str] = []
    for line in [
        "Sí, acepto que se grabe.",
        "Quiero trabajar de camarero.",
        "Esto es una pérdida de tiempo, qué desesperante.",
        "Qué pesadez, estoy harto de tantas preguntas. Quiero hablar con una persona.",
        "Sí, que me llame un reclutador.",
    ]:
        if interview.controller.escalated:
            break
        turns.append(f"> {line}\n{await interview.send(line)}")
    if not interview.controller.escalated:
        turns.append(await interview.send("Sí, quiero que me llame un reclutador."))
    ask = turns[-1]
    assert interview.controller.escalated, turns
    assert "teléfono" in ask.lower() or "número" in ask.lower(), ask
    bye = await interview.send("612 345 678")
    turns.append(bye)
    print("\n".join(turns))
    assert interview.controller.has_phone, turns
    record = await interview.close()
    assert record.end_reason is EndReason.ESCALATED
    assert record.candidate.phone
    assert "llam" in bye.lower() or "contacto" in bye.lower()
