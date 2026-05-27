"""
Source-grounding constraint — Pattern 2 of three anti-hallucination patterns.

Append GROUNDING_RULES to every Claude system prompt. The rules forbid
inventing numeric facts when the underlying data is missing, require
citing the source for any specific quantitative claim, and instruct
Claude to use hedging language for general industry knowledge.

Usage:
    from backend.agents.grounding import GROUNDING_RULES
    SYSTEM_X = "...your normal system prompt..." + GROUNDING_RULES
"""

GROUNDING_RULES = """

CRITICAL — SOURCE GROUNDING RULES (read carefully):
1. Every numeric claim you make MUST be supported by a field in the data
   I gave you in this prompt. If a field is null, missing, or not provided,
   write "data not available for [field]" rather than estimating.
2. When citing a number, name the source field or API in parentheses, e.g.
   "carbon intensity 138 g/kWh (IESO fuel mix + IPCC AR5)" or "LCOE $47.2/MWh
   (NREL utility rates)". Don't restate numbers without their source.
3. General industry context is allowed but must use hedging phrases like
   "typically", "industry rule of thumb", or "in comparable regions" so it
   is clearly separable from data-grounded facts.
4. Never invent specific values (LCOE, headroom MW, latency ms, customer
   counts, distances). If a field is absent, omit the sentence or use
   "data not available".
"""
