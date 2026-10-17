import { MobileNav, Sidebar } from "@/components/layout/nav";
import { ConnectionBanner, Header } from "@/components/layout/header";
import { AreaTransition } from "@/components/layout/transitions";

export default function DashboardLayout({ children }: LayoutProps<"/">) {
  return (
    <AreaTransition>
      <div className="flex min-h-dvh">
        <Sidebar />
        <div className="flex min-w-0 flex-1 flex-col">
          <MobileNav />
          <Header />
          <ConnectionBanner />
          <main className="mx-auto w-full max-w-6xl flex-1 px-4 py-6 md:px-6">{children}</main>
        </div>
      </div>
    </AreaTransition>
  );
}
