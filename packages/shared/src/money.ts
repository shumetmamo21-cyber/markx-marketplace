/**
 * Money is stored and transported as an integer number of MINOR units
 * (cents, santim, …) together with an ISO-4217 currency code.
 *
 * Never use a float for money: 0.1 + 0.2 !== 0.3 in IEEE-754, and rounding
 * drift compounds across cart lines, tax and commission.
 */

export const SUPPORTED_CURRENCIES = ['ETB', 'USD', 'EUR'] as const;

export type Currency = (typeof SUPPORTED_CURRENCIES)[number];

/** Number of decimal places each currency subdivides into. */
const MINOR_UNIT_EXPONENT: Record<Currency, number> = {
  ETB: 2,
  USD: 2,
  EUR: 2,
};

export interface Money {
  /** Integer amount in minor units. 1234 with ETB === 12.34 ETB. */
  readonly amountMinor: number;
  readonly currency: Currency;
}

export function money(amountMinor: number, currency: Currency): Money {
  if (!Number.isInteger(amountMinor)) {
    throw new TypeError(`amountMinor must be an integer, received ${amountMinor}`);
  }
  return { amountMinor, currency };
}

function assertSameCurrency(a: Money, b: Money): void {
  if (a.currency !== b.currency) {
    throw new TypeError(`Currency mismatch: ${a.currency} vs ${b.currency}`);
  }
}

export function addMoney(a: Money, b: Money): Money {
  assertSameCurrency(a, b);
  return money(a.amountMinor + b.amountMinor, a.currency);
}

export function subtractMoney(a: Money, b: Money): Money {
  assertSameCurrency(a, b);
  return money(a.amountMinor - b.amountMinor, a.currency);
}

/** Multiply by an integer quantity. Exact — no rounding needed. */
export function multiplyMoney(value: Money, quantity: number): Money {
  if (!Number.isInteger(quantity)) {
    throw new TypeError(`quantity must be an integer, received ${quantity}`);
  }
  return money(value.amountMinor * quantity, value.currency);
}

/**
 * Apply a rate (commission, tax, discount) and round half-up to the
 * nearest minor unit. Rounding is explicit so the behaviour is auditable.
 */
export function applyRate(value: Money, rate: number): Money {
  if (!Number.isFinite(rate)) {
    throw new TypeError(`rate must be finite, received ${rate}`);
  }
  return money(Math.round(value.amountMinor * rate), value.currency);
}

export function formatMoney(value: Money, locale = 'en-US'): string {
  const exponent = MINOR_UNIT_EXPONENT[value.currency];
  return new Intl.NumberFormat(locale, {
    style: 'currency',
    currency: value.currency,
    minimumFractionDigits: exponent,
  }).format(value.amountMinor / 10 ** exponent);
}
