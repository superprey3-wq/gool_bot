"""Presentation labels for the two auxiliary GOOL strategies."""
import multi_engine_card as card

_orig=card.kind_info

def kind_info(engine):
    if engine in {"first_half_goal","first_half","ht_hunter","ht"}:
        return "ht",card.BLUE,"GOOL • 1-Й ТАЙМ","ГОЛ В ПЕРВОМ ТАЙМЕ"
    if engine in {"second_half_over15","second_half"}:
        return "second",card.BLUE,"GOOL • 2-Й ТАЙМ","ТБ 1.5 ВО ВТОРОМ ТАЙМЕ"
    return _orig(engine)

card.kind_info=kind_info
