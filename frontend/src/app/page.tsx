import { AreaTransition } from "@/components/layout/transitions";
import { Features, FinalCta, Footer, Hero, HomeNav, HowItWorks, LiveSection } from "@/components/home/sections";

export default function HomePage() {
  return (
    <AreaTransition>
      <div className="flex min-h-dvh flex-col">
        <HomeNav />
        <main className="flex-1">
          <Hero />
          <LiveSection />
          <HowItWorks />
          <Features />
          <FinalCta />
        </main>
        <Footer />
      </div>
    </AreaTransition>
  );
}
