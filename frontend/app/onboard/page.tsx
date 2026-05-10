"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";

import { Step1EmailDeps } from "@/components/Step1EmailDeps";
import { Step2Sources } from "@/components/Step2Sources";
import { Stepper } from "@/components/Stepper";
import { ApiError, api } from "@/lib/api";
import type { Dependency, SourceConfig } from "@/lib/types";

export default function OnboardPage() {
  const router = useRouter();
  const [step, setStep] = useState<1 | 2>(1);
  const [email, setEmail] = useState<string>("");
  const [deps, setDeps] = useState<Dependency[]>([]);
  const [config, setConfig] = useState<SourceConfig>({
    families: {},
    wire_defaults: "all_enabled_except_auth_required",
  });
  const [submitting, setSubmitting] = useState<boolean>(false);
  const [submitError, setSubmitError] = useState<string | null>(null);

  const handleSubmit = async () => {
    setSubmitting(true);
    setSubmitError(null);
    try {
      const result = await api.onboard({
        email: email.trim(),
        dependencies: deps,
        source_config: config,
      });
      const params = new URLSearchParams({
        user_id: result.user_id,
        email: email.trim(),
        deps: String(result.watch_item_count),
      });
      router.push(`/onboarded?${params.toString()}`);
    } catch (err) {
      setSubmitError(
        err instanceof ApiError
          ? `Save failed (${err.status}): ${err.message}`
          : `Save failed: ${(err as Error).message}`,
      );
      setSubmitting(false);
    }
  };

  return (
    <div>
      <Stepper
        current={step}
        steps={["Email + deps", "Source preferences", "Confirmation"]}
      />
      {step === 1 && (
        <Step1EmailDeps
          email={email}
          setEmail={setEmail}
          deps={deps}
          setDeps={setDeps}
          onNext={() => setStep(2)}
        />
      )}
      {step === 2 && (
        <Step2Sources
          config={config}
          setConfig={setConfig}
          onBack={() => setStep(1)}
          onSubmit={handleSubmit}
          submitting={submitting}
          submitError={submitError}
        />
      )}
    </div>
  );
}
