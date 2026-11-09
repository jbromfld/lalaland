# Local Markdown dependencies

These browser ES modules are vendored so Corpus formatting works offline without
CDN requests, Node packages at runtime, or a frontend build step.

- [Marked](https://github.com/markedjs/marked), version **18.1.3**:
  `marked/lib/marked.esm.js` from the npm package; MIT license in `marked.LICENSE.md`.
- [DOMPurify](https://github.com/cure53/DOMPurify), version **3.4.17**:
  `dompurify/dist/purify.es.mjs` from the npm package, saved as `purify.es.js`
  for JavaScript MIME compatibility in Nginx; license in `dompurify.LICENSE`.

Files are copied unchanged from their pinned npm package releases. To update,
install explicit package versions in a temporary directory and copy these same
modules and licenses. Run the Markdown rendering/security checks after updating.
Source maps are not needed at runtime and are not included.
