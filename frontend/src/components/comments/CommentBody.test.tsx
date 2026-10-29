import { MantineProvider } from '@mantine/core';
import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { theme } from '../../theme';
import { CommentBody } from './CommentBody';

/** The rendered comment, without the style elements Mantine adds to the document. */
function renderBody(html: string): HTMLElement {
  render(
    <MantineProvider theme={theme} env="test">
      <div data-testid="comment">
        <CommentBody html={html} />
      </div>
    </MantineProvider>,
  );
  return screen.getByTestId('comment');
}

describe('CommentBody', () => {
  it('renders the allowed Markdown subset of body_html', () => {
    const container = renderBody(
      '<p><strong>Example</strong> comment with <a href="https://example.org/page">a link</a></p><ul><li>item</li></ul>',
    );
    expect(container.querySelector('strong')?.textContent).toBe('Example');
    expect(container.querySelector('li')?.textContent).toBe('item');
    const link = container.querySelector('a');
    expect(link?.getAttribute('href')).toBe('https://example.org/page');
    expect(link?.getAttribute('rel')).toBe('noopener noreferrer nofollow');
  });

  it('removes script tags', () => {
    const container = renderBody('<p>before</p><script>window.compromised = true</script><p>after</p>');
    expect(container.querySelector('script')).toBeNull();
    expect(container.textContent).toBe('beforeafter');
  });

  it('removes event handlers and the elements that carry them', () => {
    const container = renderBody(
      '<p onclick="steal()" onmouseover="steal()">text</p><img src="x" onerror="steal()"><svg onload="steal()"></svg>',
    );
    expect(container.querySelector('img, svg')).toBeNull();
    const paragraph = container.querySelector('p');
    expect(paragraph?.textContent).toBe('text');
    expect(paragraph?.attributes).toHaveLength(0);
    for (const element of container.querySelectorAll('*')) {
      for (const attribute of element.attributes) expect(attribute.name.startsWith('on'), attribute.name).toBe(false);
    }
  });

  it('removes javascript: and other unsafe link targets but keeps the text', () => {
    const container = renderBody(
      '<p><a href="javascript:steal()">one</a> <a href="JaVaScRiPt:steal()">two</a> ' +
        '<a href="java&#x09;script:steal()">three</a> <a href="data:text/html,x">four</a> <a href="//evil.example/">five</a></p>',
    );
    const links = [...container.querySelectorAll('a')];
    expect(links.map((link) => link.textContent)).toEqual(['one', 'two', 'three', 'four', 'five']);
    for (const link of links) expect(link.hasAttribute('href'), link.textContent).toBe(false);
  });
});
