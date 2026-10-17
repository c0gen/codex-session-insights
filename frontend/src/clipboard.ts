/** Copy text in browsers and desktop webviews that lack Clipboard API access. */
export async function copyText(text: string): Promise<void> {
  try {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(text);
      return;
    }
  } catch { /* Fall back when clipboard permissions are unavailable. */ }

  const focused = document.activeElement as HTMLElement | null;
  const input = document.createElement("textarea");
  input.value = text;
  input.readOnly = true;
  input.style.cssText = "position:fixed;left:-9999px;top:0";
  document.body.append(input);
  try {
    input.select();
    if (!document.execCommand("copy")) throw new Error("Could not copy to the clipboard. Please try again.");
  } finally {
    input.remove();
    focused?.focus({ preventScroll: true });
  }
}
