"use client";

import { useState } from "react";
import { KeyRoundIcon, Loader2Icon, PlugZapIcon, Trash2Icon, TriangleAlertIcon } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { StatusPill } from "@/components/ui/status-pill";
import { ConfirmDialog, SecretDialog } from "@/components/providers/secret-dialog";
import { relativeTime } from "@/lib/format";
import { actions } from "@/lib/store";
import type { GithubCredential } from "@/types";

export function GithubCard({ github, now }: { github: GithubCredential | null; now: number | null }) {
  const [testing, setTesting] = useState(false);

  if (!github) return <Skeleton className="h-[120px] rounded-xl" />;

  const missing = github.state === "missing";
  const noRepoScope = !missing && !github.scopes.includes("repo");

  return (
    <Card className="gap-3 px-4">
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-mono text-sm font-semibold">GitHub token</span>
        {missing ? (
          <StatusPill tone="muted">Not set</StatusPill>
        ) : github.state === "valid" ? (
          <StatusPill tone="success">Valid</StatusPill>
        ) : (
          <StatusPill tone="danger">Invalid</StatusPill>
        )}
      </div>

      {missing ? (
        <p className="text-sm text-muted-foreground">
          Add a token so the agent can clone repos, push branches and open pull requests. It needs the{" "}
          <code className="font-mono">repo</code> scope.
        </p>
      ) : (
        <dl className="grid gap-x-6 gap-y-1 text-xs sm:grid-cols-[auto_1fr]">
          <dt className="text-muted-foreground">Source</dt>
          <dd>
            {github.source === "gh"
              ? "your GitHub CLI login (gh auth)"
              : github.source === "env"
                ? "an environment variable"
                : "encrypted vault"}
          </dd>
          <dt className="text-muted-foreground">Token</dt>
          <dd className="font-mono">{github.keyHint}</dd>
          <dt className="text-muted-foreground">Account</dt>
          <dd>@{github.login}</dd>
          <dt className="text-muted-foreground">Scopes</dt>
          <dd className="font-mono">{github.scopes.join(", ") || "none"}</dd>
          {github.checkedAt && now && (
            <>
              <dt className="text-muted-foreground">Checked</dt>
              <dd>{relativeTime(github.checkedAt, now)}</dd>
            </>
          )}
        </dl>
      )}

      {noRepoScope && (
        <p className="flex items-center gap-1.5 text-xs text-warning">
          <TriangleAlertIcon className="size-3.5" /> Missing the <code>repo</code> scope. The agent can&apos;t open PRs.
        </p>
      )}

      <div className="flex flex-wrap gap-2 border-t pt-3">
        <SecretDialog
          trigger={<Button variant={missing ? "default" : "outline"} size="sm" />}
          triggerContent={
            <>
              <KeyRoundIcon /> {missing ? "Add token" : github.source === "vault" ? "Rotate" : "Store a token here"}
            </>
          }
          title={missing ? "Add GitHub token" : "Rotate GitHub token"}
          description="Use a fine-grained or classic token with the repo scope. It's checked against GitHub, then stored encrypted."
          fieldLabel="Token"
          placeholder="ghp_… or github_pat_…"
          submitLabel="Validate & save"
          onSubmit={async (token) => {
            await actions.setGithubToken(token);
            toast.success("GitHub token saved");
          }}
        />
        {!missing && (
          <>
            <Button
              variant="outline"
              size="sm"
              disabled={testing}
              onClick={async () => {
                setTesting(true);
                try {
                  const g = await actions.testGithub();
                  toast.success(`Token works · signed in as @${g.login}`);
                } catch (err) {
                  toast.error(err instanceof Error ? err.message : String(err));
                } finally {
                  setTesting(false);
                }
              }}
            >
              {testing ? <Loader2Icon className="animate-spin" /> : <PlugZapIcon />} Test
            </Button>
            {github.source === "vault" && (
            <ConfirmDialog
              trigger={<Button variant="ghost" size="sm" className="text-destructive" />}
              triggerContent={
                <>
                  <Trash2Icon /> Remove
                </>
              }
              title="Remove GitHub token?"
              description="The agent won't be able to clone private repos or open pull requests until you add a new one."
              confirmLabel="Remove token"
              onConfirm={async () => {
                await actions.removeGithub();
                toast.success("GitHub token removed");
              }}
            />
            )}
          </>
        )}
      </div>
    </Card>
  );
}
