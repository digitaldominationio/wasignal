"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";

import { Account, ApiError, api } from "./api";

type Partner = { pid: number; name: string; username?: string };

type WorkspaceValue = {
  accountId: number | null;
  account: Account | null;
  accounts: Account[];
  partner: Partner | null;
  loading: boolean;
  error: string | null;
  refresh: () => Promise<void>;
  handleError: (cause: unknown) => void;
};

const WorkspaceContext = createContext<WorkspaceValue | null>(null);

export function WorkspaceProvider({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [accountId, setAccountId] = useState<number | null>(null);
  const [partner, setPartner] = useState<Partner | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const session = await api<{ pid: number; username: string }>("/dashboard/auth/session");
      const accountsResponse = await api<{ items: Account[] }>("/dashboard/accounts");
      setPartner({ pid: session.pid, name: session.username });
      setAccounts(accountsResponse.items);
      setAccountId((current) => current ?? accountsResponse.items[0]?.id ?? null);
    } catch (cause) {
      const err = cause as ApiError;
      if (err.status === 401) {
        router.replace("/login");
        return;
      }
      setError(err.detail ?? "Could not load workspace");
    } finally {
      setLoading(false);
    }
  }, [router]);

  useEffect(() => {
    void load();
  }, [load]);

  const handleError = useCallback(
    (cause: unknown) => {
      const err = cause as ApiError;
      if (err.status === 401) {
        router.replace("/login");
        return;
      }
      setError(err.detail ?? String(cause));
    },
    [router],
  );

  const account = useMemo(
    () => accounts.find((item) => item.id === accountId) ?? accounts[0] ?? null,
    [accounts, accountId],
  );

  const value: WorkspaceValue = {
    accountId: account?.id ?? null,
    account,
    accounts,
    partner,
    loading,
    error,
    refresh: load,
    handleError,
  };

  return <WorkspaceContext.Provider value={value}>{children}</WorkspaceContext.Provider>;
}

export function useWorkspace(): WorkspaceValue {
  const value = useContext(WorkspaceContext);
  if (!value) throw new Error("useWorkspace must be used inside WorkspaceProvider");
  return value;
}
