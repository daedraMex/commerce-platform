"use client";

import { QueryClientProvider } from "@tanstack/react-query";
import * as React from "react";

import { ThemeProvider } from "@/components/providers/theme-provider";
import { installStoreHeader } from "@/lib/api/store-header";
import { createQueryClient } from "@/lib/query/client";
import { GlobalQueryClientProvider } from "@/lib/query/global-query-client";

installStoreHeader();

export function Providers({ children }: { children: React.ReactNode }) {
  const [queryClient] = React.useState(createQueryClient);

  return (
    <GlobalQueryClientProvider client={queryClient}>
      <ThemeProvider>
        <QueryClientProvider client={queryClient}>
          {children}
        </QueryClientProvider>
      </ThemeProvider>
    </GlobalQueryClientProvider>
  );
}
