import { JobsView } from "@/components/jobs/jobs-view";
import { PageTransition } from "@/components/layout/transitions";

export default function JobsPage() {
  return (
    <PageTransition>
      <JobsView />
    </PageTransition>
  );
}
