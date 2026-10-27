"""
finance.py
==========
Simplified financial calculations for MMR properties (6% BMC Stamp Duty,
1% Registration, and a default 80% LTV loan at 8.5% for 20 years).
"""

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


def get_quick_cost_summary(predicted_price: float) -> dict:
    """Returns a static 3-line cost breakdown for MMR properties."""
    # Convert from Crores to Rupees if passed in Crores (e.g., 2.50)
    if predicted_price < 500:
        predicted_price = predicted_price * RUPEES_PER_CRORE

    # --- STEP 4: STATIC MUMBAI ON-ROAD COST (6% BMC STAMP DUTY + 1% REG) ---
    stamp_duty = round(predicted_price * 0.06)        # Flat 6% BMC Stamp Duty
    registration = round(predicted_price * 0.01)      # Standard 1% Registration
    total_on_road = predicted_price + stamp_duty + registration

    # --- STEP 5: DEFAULT 20-YEAR EMI CALCULATION (80% LTV @ 8.5%) ---
    principal = predicted_price * 0.80
    r = (8.5 / 12) / 100
    n = 240
    emi = round(principal * r * ((1 + r) ** n) / (((1 + r) ** n) - 1))

    return {
        "stamp_duty_reg": stamp_duty + registration,
        "total_cost": round(total_on_road),
        "estimated_emi": emi
    }
