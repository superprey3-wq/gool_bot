# GOOL XG Consensus

Experimental SStats-inspired layer built only from sources already available to GOOL BOT.

## Four model components

- StrengthXG — recent-history Elo/Poisson forecast, converted to expected goals for the remaining match time.
- MarketXG — remaining-goal expectation inferred from the current LIVE total price using a Poisson model.
- RealXG — Flashscore observed xG, converted to a conservative remaining-match pace.
- CalcXG — GOOL's independent xG proxy based on shots, shots on target, big chances, shots inside the box, touches in the box and corners.

## Consensus

Available components are blended with conservative weights: Strength 30%, Market 30%, Real 25%, Calc 15%. The layer also measures agreement between models and converts the consensus remaining-goal expectation into a probability of at least one further goal.

## Safety rules

The layer may nudge an already-qualified MASTER score by at most +4/-2 points. A previously rejected match may only be rescued into OBSERVE when at least three sources agree, market and live evidence are present, agreement is at least 60%, and the consensus score is at least 64. It can never create ENTRY or STRONG by itself.

## Runtime logging

Each evaluated match emits a GOOL_XG line with Strength/Market/Real/Calc values, expected remaining goals, next-goal probability, agreement, source count and applied bonus.

## Telegram presentation

For sent signals, the layer adds two compact lines showing all four remaining-XG estimates plus the consensus probability and agreement.

## Activation

Import `gool_xg_consensus` after `market_math_patch` in the deployed entrypoint. The module itself imports `market_math_patch`, so it can also be loaded directly after the phase-market patches.
