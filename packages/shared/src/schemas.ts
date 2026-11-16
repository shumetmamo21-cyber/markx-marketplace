import { z } from 'zod';
import { SUPPORTED_CURRENCIES } from './money';

/** Shared enums — kept in step with the Prisma schema in @markx/db. */
export const userRoleSchema = z.enum(['BUYER', 'SELLER', 'ADMIN']);
export const orderStatusSchema = z.enum(['PENDING', 'PAID', 'FULFILLED', 'CANCELLED', 'REFUNDED']);
export const productStatusSchema = z.enum(['DRAFT', 'ACTIVE', 'ARCHIVED']);
export const currencySchema = z.enum(SUPPORTED_CURRENCIES);

export type UserRole = z.infer<typeof userRoleSchema>;
export type OrderStatus = z.infer<typeof orderStatusSchema>;
export type ProductStatus = z.infer<typeof productStatusSchema>;

/** URL-safe slug: lowercase alphanumerics separated by single hyphens. */
export const slugSchema = z
  .string()
  .min(1)
  .max(120)
  .regex(/^[a-z0-9]+(?:-[a-z0-9]+)*$/, 'must be a lowercase hyphen-separated slug');

export const priceMinorSchema = z
  .number()
  .int('price must be an integer number of minor units')
  .nonnegative();

export const createProductSchema = z.object({
  title: z.string().min(1).max(200).trim(),
  slug: slugSchema,
  description: z.string().max(10_000).default(''),
  priceMinor: priceMinorSchema,
  currency: currencySchema,
  status: productStatusSchema.default('DRAFT'),
  categoryId: z.string().cuid2().optional(),
});

export type CreateProductInput = z.infer<typeof createProductSchema>;

export const cartItemSchema = z.object({
  productId: z.string().cuid2(),
  quantity: z.number().int().positive().max(999),
});

export type CartItemInput = z.infer<typeof cartItemSchema>;

export const addressSchema = z.object({
  fullName: z.string().min(1).max(200),
  line1: z.string().min(1).max(200),
  line2: z.string().max(200).optional(),
  city: z.string().min(1).max(120),
  region: z.string().max(120).optional(),
  postalCode: z.string().max(32).optional(),
  /** ISO 3166-1 alpha-2, e.g. "ET". */
  countryCode: z.string().length(2).toUpperCase(),
  phone: z.string().max(32).optional(),
});

export type AddressInput = z.infer<typeof addressSchema>;

/** Page-based list query, clamped so a client cannot request unbounded rows. */
export const paginationSchema = z.object({
  page: z.coerce.number().int().positive().default(1),
  perPage: z.coerce.number().int().positive().max(100).default(24),
});

export type Pagination = z.infer<typeof paginationSchema>;
