'use client';

import { useState, useEffect } from 'react';
import { useRouter } from 'next/navigation';
import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { useAuthStore } from '@/stores/auth-store';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { toast } from 'sonner';
import { Loader2, Eye, EyeOff, Shield } from 'lucide-react';
import { loginSchema, type LoginFormData } from '@/lib/validations';

export default function AdminLoginPage() {
  const router = useRouter();
  const { login, isLoading, error, clearError, isAuthenticated } = useAuthStore();
  const [showPassword, setShowPassword] = useState(false);

  // Zaten giriş yapılmışsa dashboard'a yönlendir
  useEffect(() => {
    if (isAuthenticated) {
      router.push('/admin/dashboard');
    }
  }, [isAuthenticated, router]);

  const {
    register,
    handleSubmit,
    formState: { errors },
  } = useForm<LoginFormData>({
    resolver: zodResolver(loginSchema),
  });

  const onSubmit = async (data: LoginFormData) => {
    clearError();
    const success = await login(data.email, data.password);
    if (success) {
      toast.success('Hoş geldiniz!');
      router.push('/admin/dashboard');
    } else {
      toast.error(error || 'Giriş başarısız');
    }
  };

  return (
    <div className="min-h-[calc(100vh-4rem)] sm:min-h-[calc(100vh-8rem)] flex items-center justify-center py-6 sm:py-12 px-3 sm:px-4 relative">
      {/* Background decoration */}
      <div className="absolute inset-0 -z-10 overflow-hidden">
        <div className="absolute top-1/4 left-1/4 w-48 sm:w-72 md:w-96 h-48 sm:h-72 md:h-96 bg-primary/5 rounded-full blur-3xl" />
        <div className="absolute bottom-1/4 right-1/4 w-40 sm:w-60 md:w-80 h-40 sm:h-60 md:h-80 bg-accent/10 rounded-full blur-3xl" />
      </div>

      <div className="w-full max-w-[calc(100%-1rem)] sm:max-w-md animate-fade-in-up">
        <Card className="border-border/50 shadow-2xl shadow-primary/5 bg-card/80 backdrop-blur-sm">
          <CardHeader className="text-center pb-2 px-4 sm:px-6 pt-6 sm:pt-8">
            <div className="mx-auto w-12 h-12 sm:w-16 sm:h-16 rounded-xl sm:rounded-2xl bg-gradient-to-br from-primary to-primary/60 flex items-center justify-center text-primary-foreground shadow-lg shadow-primary/30 mb-3 sm:mb-4">
              <Shield className="w-6 h-6 sm:w-8 sm:h-8" />
            </div>
            <CardTitle className="text-xl sm:text-2xl font-serif">Admin Paneli</CardTitle>
            <CardDescription className="text-sm sm:text-base">
              Yönetim paneline erişmek için giriş yapın
            </CardDescription>
          </CardHeader>

          <form onSubmit={handleSubmit(onSubmit)}>
            <CardContent className="space-y-4 sm:space-y-5 pt-4 sm:pt-6 px-4 sm:px-6 pb-6 sm:pb-8">
              <div className="space-y-1.5 sm:space-y-2">
                <Label htmlFor="email" className="text-xs sm:text-sm font-medium">E-posta</Label>
                <Input
                  id="email"
                  type="email"
                  placeholder="admin@email.com"
                  className="h-10 sm:h-12 text-sm sm:text-base bg-background/50 border-border/50 focus:border-primary"
                  {...register('email')}
                />
                {errors.email && (
                  <p className="text-xs sm:text-sm text-destructive flex items-center gap-1">
                    {errors.email.message}
                  </p>
                )}
              </div>

              <div className="space-y-1.5 sm:space-y-2">
                <Label htmlFor="password" className="text-xs sm:text-sm font-medium">Şifre</Label>
                <div className="relative">
                  <Input
                    id="password"
                    type={showPassword ? 'text' : 'password'}
                    placeholder="Şifrenizi girin"
                    className="h-10 sm:h-12 text-sm sm:text-base bg-background/50 border-border/50 focus:border-primary pr-10 sm:pr-12"
                    {...register('password')}
                  />
                  <Button
                    type="button"
                    variant="ghost"
                    size="icon"
                    className="absolute right-0 top-0 h-full px-2.5 sm:px-3 hover:bg-transparent text-muted-foreground hover:text-primary"
                    onClick={() => setShowPassword(!showPassword)}
                  >
                    {showPassword ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                  </Button>
                </div>
                {errors.password && (
                  <p className="text-xs sm:text-sm text-destructive">{errors.password.message}</p>
                )}
              </div>

              {error && (
                <div className="rounded-lg sm:rounded-xl bg-destructive/10 border border-destructive/20 p-3 sm:p-4 text-xs sm:text-sm text-destructive">
                  {error}
                </div>
              )}

              <Button type="submit" className="w-full h-10 sm:h-12 text-sm sm:text-base font-medium" disabled={isLoading}>
                {isLoading ? (
                  <>
                    <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                    Giriş yapılıyor...
                  </>
                ) : (
                  <>
                    <Shield className="mr-2 h-4 w-4" />
                    Giriş Yap
                  </>
                )}
              </Button>
            </CardContent>
          </form>
        </Card>
      </div>
    </div>
  );
}

