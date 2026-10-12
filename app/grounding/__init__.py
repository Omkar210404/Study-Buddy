"""Grounding: a card is only kept if its supporting quote really appears in the source passage."""

from app.grounding.validator import REASONS, GroundingResult, check_quote, question_key

__all__ = ["REASONS", "GroundingResult", "check_quote", "question_key"]
