import { ProvidersView } from "@/components/providers/providers-view";
import { PageTransition } from "@/components/layout/transitions";

export default function ProvidersPage() {
  return (
    <PageTransition>
      <ProvidersView />
    </PageTransition>
  );
}
