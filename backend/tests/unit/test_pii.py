"""Regex-based PII redaction tests."""
from __future__ import annotations

from app.services.pii import RegexPiiRedactor


def test_email_redaction():
    redactor = RegexPiiRedactor(["EMAIL"])
    text = "Please contact jane.doe@example.com for details."
    out, spans = redactor.redact(text)
    assert "jane.doe@example.com" not in out
    assert any(s.entity_type == "EMAIL" for s in spans)


def test_phone_redaction():
    redactor = RegexPiiRedactor(["PHONE"])
    text = "Call our hotline at +1 415-555-2671 between 9am and 5pm."
    out, spans = redactor.redaction if False else redactor.redact(text)  # noqa
    out, spans = redactor.redact(text)
    assert "[REDACTED:PHONE]" in out
    assert len(spans) >= 1


def test_ssn_redaction():
    redactor = RegexPiiRedactor(["SSN"])
    text = "Employee SSN is 123-45-6789 - keep confidential."
    out, spans = redactor.redact(text)
    assert "123-45-6789" not in out
    assert any(s.entity_type == "SSN" for s in spans)


def test_credit_card_redaction():
    redactor = RegexPiiRedactor(["CREDIT_DEBIT_NUMBER"])
    text = "Charge card 4111 1111 1111 1111 was approved."
    out, spans = redactor.redact(text)
    assert "4111 1111 1111 1111" not in out
    assert len(spans) == 1


def test_no_pii_is_passthrough():
    redactor = RegexPiiRedactor()
    text = "This is a clean corporate policy document."
    out, spans = redactor.redact(text)
    assert out == text
    assert spans == []


def test_span_offsets_are_correct():
    text = "Email jane@example.com or call 415-555-2671."
    redactor = RegexPiiRedactor(["EMAIL", "PHONE"])
    out, spans = redactor.redact(text)
    # Every reported span should slice back to the same substring in the original text.
    for span in spans:
        assert text[span.start:span.end] == span.text
