import { z } from 'zod/v4';

// Password validation messages (Turkish)
const passwordMessages = {
  min: 'Şifre en az 8 karakter olmalı',
  max: 'Şifre en fazla 100 karakter olabilir',
  uppercase: 'Şifre en az bir büyük harf içermeli',
  lowercase: 'Şifre en az bir küçük harf içermeli',
  digit: 'Şifre en az bir rakam içermeli',
  special: 'Şifre en az bir özel karakter içermeli (!@#$%^&* vb.)',
};

// Regex patterns
const patterns = {
  uppercase: /[A-Z]/,
  lowercase: /[a-z]/,
  digit: /[0-9]/,
  special: /[!@#$%^&*(),.?"':{}|<>_\-\[\]\\\/`~+=;]/,
  username: /^[a-zA-Z0-9_]+$/,
};

/**
 * Password schema with full validation matching backend rules
 */
export const passwordSchema = z
  .string()
  .min(8, passwordMessages.min)
  .max(100, passwordMessages.max)
  .refine((p) => patterns.uppercase.test(p), passwordMessages.uppercase)
  .refine((p) => patterns.lowercase.test(p), passwordMessages.lowercase)
  .refine((p) => patterns.digit.test(p), passwordMessages.digit)
  .refine((p) => patterns.special.test(p), passwordMessages.special);

/**
 * Username schema
 */
export const usernameSchema = z
  .string()
  .min(3, 'Kullanıcı adı en az 3 karakter olmalı')
  .max(50, 'Kullanıcı adı en fazla 50 karakter olabilir')
  .regex(patterns.username, 'Kullanıcı adı sadece harf, rakam ve alt çizgi içerebilir');

/**
 * Email schema
 */
export const emailSchema = z
  .string()
  .min(1, 'E-posta adresi gerekli')
  .email('Geçerli bir e-posta adresi girin')
  .max(256, 'E-posta en fazla 256 karakter olabilir');

/**
 * Login form schema
 */
export const loginSchema = z.object({
  email: emailSchema,
  password: z.string().min(1, 'Şifre gerekli'),
});

/**
 * Registration form schema with password confirmation
 */
export const registerSchema = z
  .object({
    userName: usernameSchema,
    email: emailSchema,
    password: passwordSchema,
    confirmPassword: z.string().min(1, 'Şifre tekrarı gerekli'),
    firstName: z.string().max(50, 'Ad en fazla 50 karakter olabilir').optional(),
    lastName: z.string().max(50, 'Soyad en fazla 50 karakter olabilir').optional(),
  })
  .refine((data) => data.password === data.confirmPassword, {
    message: 'Şifreler eşleşmiyor',
    path: ['confirmPassword'],
  });

/**
 * Password change schema
 */
export const changePasswordSchema = z
  .object({
    currentPassword: z.string().min(1, 'Mevcut şifre gerekli'),
    newPassword: passwordSchema,
    confirmNewPassword: z.string().min(1, 'Yeni şifre tekrarı gerekli'),
  })
  .refine((data) => data.newPassword === data.confirmNewPassword, {
    message: 'Yeni şifreler eşleşmiyor',
    path: ['confirmNewPassword'],
  })
  .refine((data) => data.currentPassword !== data.newPassword, {
    message: 'Yeni şifre mevcut şifreden farklı olmalı',
    path: ['newPassword'],
  });

// Type exports
export type LoginFormData = z.infer<typeof loginSchema>;
export type RegisterFormData = z.infer<typeof registerSchema>;
export type ChangePasswordFormData = z.infer<typeof changePasswordSchema>;

/**
 * Helper function to get password strength
 * Returns: 0-4 (weak to strong)
 */
export function getPasswordStrength(password: string): {
  score: number;
  label: string;
  color: string;
} {
  let score = 0;

  if (password.length >= 8) score++;
  if (password.length >= 12) score++;
  if (patterns.uppercase.test(password) && patterns.lowercase.test(password)) score++;
  if (patterns.digit.test(password)) score++;
  if (patterns.special.test(password)) score++;

  const labels = ['Çok Zayıf', 'Zayıf', 'Orta', 'Güçlü', 'Çok Güçlü'];
  const colors = ['bg-red-500', 'bg-orange-500', 'bg-yellow-500', 'bg-lime-500', 'bg-green-500'];

  const normalizedScore = Math.min(score, 4);

  return {
    score: normalizedScore,
    label: labels[normalizedScore],
    color: colors[normalizedScore],
  };
}
