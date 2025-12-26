'use client';

import { useState } from 'react';
import { useAuthStore } from '@/stores/auth-store';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';
import { Separator } from '@/components/ui/separator';
import { toast } from 'sonner';
import { User, Shield, Bell, Palette } from 'lucide-react';

export default function SettingsPage() {
  const { user } = useAuthStore();
  const [profileData, setProfileData] = useState({
    firstName: user?.fullName?.split(' ')[0] || '',
    lastName: user?.fullName?.split(' ').slice(1).join(' ') || '',
    email: user?.email || '',
    bio: '',
  });

  const handleProfileUpdate = () => {
    toast.success('Profil ayarları kaydedildi');
  };

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold tracking-tight">Ayarlar</h1>
        <p className="text-muted-foreground">Hesap ve uygulama ayarlarınızı yönetin</p>
      </div>

      <div className="grid gap-6">
        {/* Profil Ayarları */}
        <Card>
          <CardHeader>
            <div className="flex items-center gap-2">
              <User className="h-5 w-5 text-primary" />
              <CardTitle>Profil Bilgileri</CardTitle>
            </div>
            <CardDescription>
              Profilinizde görünecek bilgileri düzenleyin
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="grid gap-4 md:grid-cols-2">
              <div className="space-y-2">
                <Label htmlFor="firstName">Ad</Label>
                <Input
                  id="firstName"
                  value={profileData.firstName}
                  onChange={(e) => setProfileData({ ...profileData, firstName: e.target.value })}
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="lastName">Soyad</Label>
                <Input
                  id="lastName"
                  value={profileData.lastName}
                  onChange={(e) => setProfileData({ ...profileData, lastName: e.target.value })}
                />
              </div>
            </div>
            <div className="space-y-2">
              <Label htmlFor="email">E-posta</Label>
              <Input
                id="email"
                type="email"
                value={profileData.email}
                onChange={(e) => setProfileData({ ...profileData, email: e.target.value })}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="bio">Biyografi</Label>
              <Textarea
                id="bio"
                value={profileData.bio}
                onChange={(e) => setProfileData({ ...profileData, bio: e.target.value })}
                placeholder="Kendinizden kısaca bahsedin..."
                rows={3}
              />
            </div>
            <Button onClick={handleProfileUpdate}>Kaydet</Button>
          </CardContent>
        </Card>

        {/* Güvenlik Ayarları */}
        <Card>
          <CardHeader>
            <div className="flex items-center gap-2">
              <Shield className="h-5 w-5 text-primary" />
              <CardTitle>Güvenlik</CardTitle>
            </div>
            <CardDescription>
              Şifre ve güvenlik ayarlarını yönetin
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="currentPassword">Mevcut Şifre</Label>
              <Input id="currentPassword" type="password" />
            </div>
            <div className="grid gap-4 md:grid-cols-2">
              <div className="space-y-2">
                <Label htmlFor="newPassword">Yeni Şifre</Label>
                <Input id="newPassword" type="password" />
              </div>
              <div className="space-y-2">
                <Label htmlFor="confirmPassword">Şifre Tekrar</Label>
                <Input id="confirmPassword" type="password" />
              </div>
            </div>
            <Button variant="outline">Şifreyi Değiştir</Button>
          </CardContent>
        </Card>

        {/* Bildirim Ayarları */}
        <Card>
          <CardHeader>
            <div className="flex items-center gap-2">
              <Bell className="h-5 w-5 text-primary" />
              <CardTitle>Bildirimler</CardTitle>
            </div>
            <CardDescription>
              E-posta bildirim tercihlerinizi ayarlayın
            </CardDescription>
          </CardHeader>
          <CardContent>
            <div className="space-y-4">
              <div className="flex items-center justify-between">
                <div>
                  <p className="font-medium">Yorum Bildirimleri</p>
                  <p className="text-sm text-muted-foreground">
                    Yazılarınıza yeni yorum geldiğinde bildirim alın
                  </p>
                </div>
                <Button variant="outline" size="sm">Açık</Button>
              </div>
              <Separator />
              <div className="flex items-center justify-between">
                <div>
                  <p className="font-medium">Haftalık Özet</p>
                  <p className="text-sm text-muted-foreground">
                    Haftalık istatistik özeti alın
                  </p>
                </div>
                <Button variant="outline" size="sm">Kapalı</Button>
              </div>
            </div>
          </CardContent>
        </Card>

        {/* Görünüm Ayarları */}
        <Card>
          <CardHeader>
            <div className="flex items-center gap-2">
              <Palette className="h-5 w-5 text-primary" />
              <CardTitle>Görünüm</CardTitle>
            </div>
            <CardDescription>
              Arayüz görünüm tercihlerinizi ayarlayın
            </CardDescription>
          </CardHeader>
          <CardContent>
            <div className="flex items-center justify-between">
              <div>
                <p className="font-medium">Tema</p>
                <p className="text-sm text-muted-foreground">
                  Açık veya koyu tema seçin
                </p>
              </div>
              <p className="text-sm text-muted-foreground">
                Tema değiştirmek için sağ üstteki tema butonunu kullanın
              </p>
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}

