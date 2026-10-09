import { IdeSidebarLeft } from '@/components/layout/ide-sidebar-left';
import { IdeSidebarRight } from '@/components/layout/ide-sidebar-right';
import { IdeLayoutWrapper } from '@/components/layout/ide-layout-wrapper';

export default function PublicLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <IdeLayoutWrapper
      leftSidebar={<IdeSidebarLeft />}
      rightSidebar={<IdeSidebarRight />}
    >
      {children}
    </IdeLayoutWrapper>
  );
}
