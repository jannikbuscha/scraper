// Comment bodies outside the comments panel are shown as plain-text excerpts
// of their Markdown (docs/UI.md §1.4: values as text).

const EXCERPT_LENGTH = 140;

/** The first words of a comment, whitespace collapsed, cut with an ellipsis. */
export function commentExcerpt(markdown: string, length = EXCERPT_LENGTH): string {
  const text = markdown.replace(/\s+/g, ' ').trim();
  return text.length > length ? `${text.slice(0, length - 1).trimEnd()}…` : text;
}
