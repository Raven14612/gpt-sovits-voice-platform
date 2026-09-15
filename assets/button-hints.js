() => {
  const hints = __BUTTON_HINTS__;
  const delay = 2000;
  window.__rjHintsCleanup?.();
  const controller = new AbortController();
  const listen = (node, event, handler, options = {}) =>
    node.addEventListener(event, handler, { ...options, signal: controller.signal });
  const selector = Object.keys(hints).map(id => `#${id}`).join(',');
  const bubble = document.createElement('div');
  bubble.id = 'rj-button-hint';
  bubble.className = 'rj-theme';
  bubble.setAttribute('role', 'tooltip');
  bubble.hidden = true;
  document.body.append(bubble);
  let target = null;
  let timer = null;
  let point = null;
  let described = null;
  let mode = null;

  function hide() {
    clearTimeout(timer);
    timer = null;
    bubble.hidden = true;
    if (described) {
      const ids = (described.getAttribute('aria-describedby') || '').split(/\s+/)
        .filter(id => id && id !== bubble.id);
      if (ids.length) described.setAttribute('aria-describedby', ids.join(' '));
      else described.removeAttribute('aria-describedby');
      described = null;
    }
  }
  function reset() {
    hide();
    target = null;
    point = null;
    mode = null;
  }
  function find(node) {
    return node instanceof Element ? node.closest(selector) : null;
  }
  function show() {
    if (!target?.isConnected || document.hidden || !target.getClientRects().length) return reset();
    const rect = target.getBoundingClientRect();
    if (rect.bottom <= 0 || rect.top >= innerHeight) return reset();
    bubble.textContent = hints[target.id].text;
    bubble.hidden = false;
    const box = bubble.getBoundingClientRect();
    const margin = 12;
    const gap = 16;
    // Prefer above and left of the pointer; keep the entire note on screen.
    const anchorX = Math.max(rect.left, Math.min(point.x, rect.right));
    const left = Math.max(margin, Math.min(anchorX - box.width + 28, innerWidth - box.width - margin));
    const above = rect.top - box.height - gap >= margin;
    const top = above ? rect.top - box.height - gap : Math.min(rect.bottom + gap, innerHeight - box.height - margin);
    bubble.style.left = `${left}px`;
    bubble.style.top = `${Math.max(margin, top)}px`;
    bubble.style.setProperty('--hint-tail-x', `${Math.max(18, Math.min(anchorX - left, box.width - 24))}px`);
    bubble.dataset.side = above ? 'above' : 'below';
    described = target.matches('button') ? target : target.querySelector('button') || target;
    const ids = (described.getAttribute('aria-describedby') || '').split(/\s+/).filter(Boolean);
    described.setAttribute('aria-describedby', [...new Set([...ids, bubble.id])].join(' '));
  }
  function arm(node, x, y, source = 'pointer') {
    hide();
    target = node;
    point = { x, y };
    mode = source;
    timer = setTimeout(show, delay);
  }
  listen(document, 'pointermove', event => {
    if (event.pointerType !== 'mouse') return reset();
    const node = find(event.target);
    if (!node) return reset();
    // Moving within one button preserves both the timer and the visible bubble.
    if (node !== target || mode !== 'pointer')
      arm(node, event.clientX, event.clientY);
    else point = { x: event.clientX, y: event.clientY };
  }, { capture: true, passive: true });
  listen(document, 'pointerout', event => {
    if (mode === 'pointer' && target && find(event.relatedTarget) !== target) reset();
  }, { capture: true, passive: true });
  listen(document, 'focusin', event => {
    const node = find(event.target);
    if (node && mode !== 'pointer' && event.target.matches(':focus-visible')) {
      const rect = node.getBoundingClientRect();
      arm(node, rect.left + rect.width / 2, rect.top, 'keyboard');
    }
  });
  listen(document, 'focusout', () => { if (mode === 'keyboard') reset(); });
  listen(document, 'pointerdown', event => {
    if (event.pointerType !== 'mouse' || find(event.target) !== target) reset();
  }, { capture: true, passive: true });
  listen(document, 'keydown', event => {
    if (event.key === 'Escape' || mode === 'keyboard') reset();
  }, { capture: true });
  function checkPosition() {
    if (!target) return;
    if (mode === 'pointer' && find(document.elementFromPoint(point.x, point.y)) !== target) reset();
    else if (!bubble.hidden) show();
  }
  listen(document, 'scroll', checkPosition, { capture: true, passive: true });
  listen(document, 'visibilitychange', reset);
  listen(window, 'blur', reset);
  listen(window, 'resize', checkPosition);
  window.__rjHintsCleanup = () => {
    reset();
    controller.abort();
    bubble.remove();
  };
}
