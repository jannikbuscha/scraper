// Copying text to the clipboard (the detail page's "Copy link", docs/UI.md §4).
// The Clipboard API exists only in secure contexts (https, localhost); the
// team may open the app over plain http on a LAN or VPN address (README "Team
// access"), where only the older `execCommand('copy')` works. Callers show the
// text for manual copying when both fail, so a copy never fails silently.

/** Resolves true if the text was copied. */
export async function copyText(text: string): Promise<boolean> {
  // The DOM types declare `navigator.clipboard` always; insecure contexts lack it.
  const clipboard = (navigator as Partial<Navigator>).clipboard;
  if (window.isSecureContext && clipboard) {
    try {
      await clipboard.writeText(text);
      return true;
    } catch {
      // Permission refused or the document lost focus: try the fallback.
    }
  }
  return copyWithSelection(text);
}

/** The fallback for insecure contexts: select the text in a hidden field and copy the selection. */
function copyWithSelection(text: string): boolean {
  const field = document.createElement('textarea');
  field.value = text;
  field.setAttribute('readonly', '');
  field.setAttribute('aria-hidden', 'true');
  field.style.position = 'fixed';
  field.style.top = '0';
  field.style.left = '0';
  field.style.opacity = '0';
  field.style.pointerEvents = 'none';
  const focused = document.activeElement;
  document.body.append(field);
  field.select();
  field.setSelectionRange(0, text.length);
  let copied = false;
  try {
    // eslint-disable-next-line @typescript-eslint/no-deprecated -- the only clipboard access outside secure contexts (plain http on a LAN or VPN address)
    copied = document.execCommand('copy');
  } catch {
    copied = false;
  }
  field.remove();
  if (focused instanceof HTMLElement) focused.focus();
  return copied;
}
