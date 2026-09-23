"use client";

import { useContext } from "react";

import { EndUserAuthContext } from "./EndUserAuthContext";

export function useEndUserAuth() {
  const context = useContext(EndUserAuthContext);

  if (context === undefined) {
    throw new Error("useEndUserAuth must be used within an EndUserAuthProvider.");
  }

  return context;
}