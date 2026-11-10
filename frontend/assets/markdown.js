import { Marked } from './vendor/marked.esm.js';
import DOMPurify from './vendor/purify.es.js';
import { escapeHtml, safeUrl } from './shared.js';

const markdown = new Marked({
  gfm: true,
  renderer: {
    // The article title and section headings are already supplied by the UI.
    heading({tokens, depth}) {
      const level = Math.min(6, depth + 3);
      return `<h${level}>${this.parser.parseInline(tokens)}</h${level}>`;
    },
    html({text}) { return escapeHtml(text); },
    image({text}) { return escapeHtml(text); }
  }
});

export function renderMarkdown(text) {
  const fragment = DOMPurify.sanitize(markdown.parse(String(text)), {
    ALLOWED_TAGS: ['p', 'h4', 'h5', 'h6', 'ul', 'ol', 'li', 'strong', 'em',
      'code', 'pre', 'blockquote', 'a', 'hr', 'br', 'del', 'table', 'thead',
      'tbody', 'tr', 'th', 'td'],
    ALLOWED_ATTR: ['href', 'title', 'start'],
    ALLOW_DATA_ATTR: false,
    ALLOW_ARIA_ATTR: false,
    RETURN_DOM_FRAGMENT: true
  });
  for (const link of fragment.querySelectorAll('a')) {
    const href = link.getAttribute('href');
    const safe = href ? safeUrl(href) : '#';
    if (safe === '#') {
      link.replaceWith(...link.childNodes);
    } else {
      link.setAttribute('href', safe);
      link.setAttribute('target', '_blank');
      link.setAttribute('rel', 'noopener noreferrer');
    }
  }
  const container = document.createElement('div');
  container.append(fragment);
  return container.innerHTML;
}
