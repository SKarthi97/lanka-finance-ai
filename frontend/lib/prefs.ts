// Small per-browser preferences (rows per page, sort order...). Never holds financial data.
// Everything is best effort: blocked storage just means nothing is remembered.

function enabled(): boolean {
  try {
    return window.localStorage.getItem("rememberChoices") !== "0";
  } catch {
    return false;
  }
}

export function loadPref(key: string): string | null {
  if (!enabled()) return null;
  try {
    return window.localStorage.getItem(key);
  } catch {
    return null;
  }
}

export function savePref(key: string, value: string): void {
  if (!enabled()) return;
  try {
    window.localStorage.setItem(key, value);
  } catch {
    /* ignore */
  }
}
