export async function api(path, options = {}) {
  const { timeoutMs = 15000, ...request } = options;
  const signal = request.signal
    ? AbortSignal.any([request.signal, AbortSignal.timeout(timeoutMs)])
    : AbortSignal.timeout(timeoutMs);
  const response = await fetch(path, {
    ...request, signal,
    headers: { "Content-Type": "application/json", ...request.headers }
  });
  if (!response.ok) {
    const payload = await response.json().catch(() => ({ detail: "Request failed" }));
    const detail = Array.isArray(payload.detail)
      ? payload.detail.map(item => `${(item.loc || []).filter(part => part !== 'body').join('.')}: ${item.msg}`).join('; ')
      : payload.detail;
    throw new Error(typeof detail === 'string' ? detail : `Request failed (${response.status})`);
  }
  return response.json();
}

export function setStatus(message) {
  document.getElementById("status").textContent = message;
}

export function setActiveView(viewId) {
  document.querySelectorAll("[data-view-target]").forEach((button) => {
    button.classList.toggle("is-active", button.dataset.viewTarget === viewId);
    button.setAttribute("aria-current", button.dataset.viewTarget === viewId ? "page" : "false");
  });
  document.querySelectorAll(".view").forEach((view) => {
    view.classList.toggle("is-active", view.id === viewId);
  });
  const heading = document.querySelector(`#${viewId} h2`);
  if (heading) { heading.tabIndex = -1; heading.focus(); }
}

export function escapeHtml(value) {
  return String(value).replace(/[&<>"']/g, (char) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;"
  }[char]));
}

export function safeUrl(value) {
  try {
    const parsed = new URL(value, window.location.origin);
    if (parsed.protocol === "http:" || parsed.protocol === "https:") {
      return parsed.toString();
    }
  } catch (error) {
    return "#";
  }

  return "#";
}

// Avoid replacing unchanged markup; restore the same control after list updates.
export function renderHtml(node, html) {
  if (node.innerHTML === html) return;
  const active = document.activeElement;
  let selector = null;
  if (active && node.contains(active)) {
    const attributes = [...active.attributes].filter(attr => attr.name === 'id' || attr.name.startsWith('data-'));
    if (attributes.length) selector = active.tagName.toLowerCase() + attributes.map(attr => `[${attr.name}="${CSS.escape(attr.value)}"]`).join('');
  }
  node.innerHTML = html;
  if (selector) node.querySelector(selector)?.focus({preventScroll:true});
}

export function setPagination(prefix, data) {
  document.getElementById(`${prefix}-page`).textContent = `Page ${data.page} · ${data.total} records`;
  document.getElementById(`${prefix}-prev`).disabled = data.page <= 1;
  document.getElementById(`${prefix}-next`).disabled = data.page * data.limit >= data.total;
}
