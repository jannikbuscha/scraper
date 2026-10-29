import { describe, expect, it } from 'vitest';

import { sanitizeCommentHtml } from './sanitize';

describe('sanitizeCommentHtml', () => {
  it('keeps the Markdown subset the server allows', () => {
    const html =
      '<h2>Title</h2><p><strong>bold</strong> <em>it</em> <code>x</code> <s>gone</s></p>' +
      '<ol start="3"><li>three</li></ol><table><thead><tr><th align="left">h</th></tr></thead>' +
      '<tbody><tr><td colspan="2">c</td></tr></tbody></table>';
    expect(sanitizeCommentHtml(html)).toBe(html);
  });

  it('removes scripts, event handlers, styles and unknown tags', () => {
    const out = sanitizeCommentHtml(
      '<p onclick="x()" style="color:red" class="c" id="i">ok</p><script>alert(1)</script><img src=x onerror=alert(1)><iframe src="https://example.org"></iframe>',
    );
    expect(out).toBe('<p>ok</p>');
  });

  it('allows http(s), mailto and same-origin paths, never protocol-relative or script URLs', () => {
    const link = (href: string) => sanitizeCommentHtml(`<a href="${href}">x</a>`);
    expect(link('https://example.org/')).toBe('<a href="https://example.org/" rel="noopener noreferrer nofollow">x</a>');
    expect(link('mailto:person@example.org')).toContain('href="mailto:person@example.org"');
    expect(link('/projects/prj_1')).toContain('href="/projects/prj_1"');
    for (const href of ['javascript:alert(1)', 'java&#9;script:alert(1)', '//evil.example/', 'data:text/html,x', 'ftp://example.org/']) {
      expect(link(href), href).toBe('<a rel="noopener noreferrer nofollow">x</a>');
    }
  });

  it('keeps attributes only on the tags that allow them', () => {
    expect(sanitizeCommentHtml('<p align="center" href="https://example.org">x</p>')).toBe('<p>x</p>');
    expect(sanitizeCommentHtml('<a href="https://example.org" target="_blank" title="t">x</a>')).toBe(
      '<a href="https://example.org" rel="noopener noreferrer nofollow">x</a>',
    );
  });
});
