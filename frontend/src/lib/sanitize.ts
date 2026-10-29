// Second sanitising pass for the server-rendered comment HTML (docs/UI.md
// §1.4, docs/API.md §3.3): the same tag and attribute allowlist as the
// server's nh3 configuration, and only http(s), mailto and same-origin paths.
import DOMPurify, { type DOMPurify as Purifier } from 'dompurify';

const ALLOWED_TAGS = [
  'p', 'br', 'strong', 'em', 'code', 'pre', 'blockquote', 'ul', 'ol', 'li', 'a',
  'h1', 'h2', 'h3', 'h4', 'hr', 'table', 'thead', 'tbody', 'tr', 'th', 'td', 's', 'del',
];

/** Per-tag attributes, as in the server's `attributes` mapping. */
const ATTRIBUTES_BY_TAG: Record<string, readonly string[]> = {
  a: ['href'],
  th: ['align', 'colspan', 'rowspan'],
  td: ['align', 'colspan', 'rowspan'],
  ol: ['start'],
};

const ALLOWED_ATTR = [...new Set(Object.values(ATTRIBUTES_BY_TAG).flat())];

/**
 * DOMPurify checks every attribute that is not "URI-safe" against
 * ALLOWED_URI_REGEXP; these plain-value attributes must skip that check.
 */
const URI_SAFE_ATTR = ALLOWED_ATTR.filter((name) => name !== 'href');

/** Mirrors the server's `link_rel`. */
const LINK_REL = 'noopener noreferrer nofollow';

export const ALLOWED_URI_REGEXP = /^(?:https?:|mailto:|\/(?!\/))/i;

let purifier: Purifier | null = null;

/** A private instance, so the hooks never affect other DOMPurify users. */
function getPurifier(): Purifier {
  if (purifier) return purifier;
  const instance = DOMPurify(window);
  instance.addHook('uponSanitizeAttribute', (node, data) => {
    const allowed = ATTRIBUTES_BY_TAG[node.nodeName.toLowerCase()] ?? [];
    if (!allowed.includes(data.attrName)) data.keepAttr = false;
  });
  instance.addHook('afterSanitizeAttributes', (node) => {
    if (node.nodeName.toLowerCase() === 'a') node.setAttribute('rel', LINK_REL);
  });
  purifier = instance;
  return instance;
}

/** Sanitises comment `body_html` for injection in CommentBody. */
export function sanitizeCommentHtml(html: string): string {
  return getPurifier().sanitize(html, {
    ALLOWED_TAGS,
    ALLOWED_ATTR,
    ADD_URI_SAFE_ATTR: URI_SAFE_ATTR,
    ALLOWED_URI_REGEXP,
    ALLOW_DATA_ATTR: false,
    ALLOW_ARIA_ATTR: false,
    ALLOW_UNKNOWN_PROTOCOLS: false,
    RETURN_TRUSTED_TYPE: false,
  });
}
