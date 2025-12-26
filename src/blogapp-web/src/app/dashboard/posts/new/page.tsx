import { redirect } from 'next/navigation';

export default function NewPostPage() {
  redirect('/admin/dashboard/posts/new');
}
