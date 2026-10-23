"""
finance.py
==========
Handles financial calculations for purchase costs, rent, and growth projections.
Uses configuration values from app/config.py for calculations.
"""

from flask import current_app

RUPEES_PER_CRORE = 10_000_000


def format_inr(value):
    """Formats a number into Indian Rupee string format (e.g. 12,34,567)."""
    number = round(float(value))
    digits = str(abs(number))
    if len(digits) > 3:
        head, tail = digits[:-3], digits[-3:]
        head = ''.join(
            ch + (',' if i < len(head) - 1 and (len(head) - 1 - i) % 2 == 0 else '')
            for i, ch in enumerate(head)
        )
        digits = f'{head},{tail}'
    return ('-' if number < 0 else '') + digits


def acquisition_costs(price_cr, women_buyer=False):
    """Calculates all acquisition costs in rupees."""
    cfg = current_app.config
    price = float(price_cr) * RUPEES_PER_CRORE

    duty_rate = cfg['STAMP_DUTY_RATE_WOMEN'] if women_buyer else cfg['STAMP_DUTY_RATE']
    stamp_duty = price * duty_rate
    # Calculate registration fee with a maximum cap limit
    registration = min(price * cfg['REGISTRATION_FEE_RATE'], cfg['REGISTRATION_FEE_CAP'])
    legal = cfg['LEGAL_FEE_ESTIMATE']

    return {
        'agreement_value': price,
        'stamp_duty_rate': duty_rate,
        'stamp_duty': stamp_duty,
        'registration_fee': registration,
        'registration_capped': price * cfg['REGISTRATION_FEE_RATE'] > cfg['REGISTRATION_FEE_CAP'],
        'legal_fee': legal,
        'total': price + stamp_duty + registration + legal,
    }


def rent_estimate(price_cr):
    """Estimates rent based on the configured rental yield."""
    cfg = current_app.config
    annual = float(price_cr) * RUPEES_PER_CRORE * cfg['ASSUMED_RENTAL_YIELD']
    return {
        'yield_pct': cfg['ASSUMED_RENTAL_YIELD'] * 100,
        'annual': annual,
        'monthly': annual / 12,
    }


def growth_projection(price_cr, years=(1, 3, 5)):
    """Projects property value growth over specified years."""
    growth = current_app.config['ASSUMED_ANNUAL_GROWTH']
    rows = []
    for n in years:
        factor = (1 + growth) ** n
        rows.append({
            'years': n,
            'value_cr': float(price_cr) * factor,
            'change_pct': (factor - 1) * 100,
        })
    return {'annual_growth_pct': growth * 100, 'rows': rows}


def summary(price_cr):
    """Aggregates all financial data for a given price in Crores."""
    return {
        'costs': acquisition_costs(price_cr),
        'costs_women': acquisition_costs(price_cr, women_buyer=True),
        'rent': rent_estimate(price_cr),
        'growth': growth_projection(price_cr),
    }