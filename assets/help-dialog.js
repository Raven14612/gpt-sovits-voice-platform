() => {
  window.__projectHelpCleanup?.();
  const controller = new AbortController();
  const dialog = document.getElementById('project-help-dialog');
  if (!dialog) return;
  let returnFocus = null;
  let oldOverflow = '';
  const listen = (node, event, handler) =>
    node.addEventListener(event, handler, {signal: controller.signal});
  listen(document, 'click', event => {
    const opener = event.target.closest('#project-help-open');
    if (opener) {
      event.preventDefault();
      if (!dialog.open) {
        returnFocus = opener;
        oldOverflow = document.body.style.overflow;
        dialog.showModal();
        document.body.style.overflow = 'hidden';
      }
    }
    const link = event.target.closest('.help-toc a');
    if (link && dialog.contains(link)) {
      event.preventDefault();
      const heading = dialog.querySelector(link.getAttribute('href'));
      heading?.scrollIntoView({block: 'start'});
      heading?.focus({preventScroll: true});
    }
  });
  listen(dialog.querySelector('#project-help-close'), 'click', () => dialog.close());
  listen(dialog, 'keydown', event => {
    if (event.key !== 'Tab') return;
    const stops = Array.from(dialog.querySelectorAll('button, a[href], [tabindex="0"]'))
      .filter(node => !node.disabled && node.getClientRects().length);
    const first = stops[0], last = stops.at(-1);
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last?.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first?.focus();
    }
  });
  let backdropPress = false;
  const outside = event => {
    const rect = dialog.getBoundingClientRect();
    return event.target === dialog && (event.clientX < rect.left || event.clientX > rect.right ||
      event.clientY < rect.top || event.clientY > rect.bottom);
  };
  listen(dialog, 'pointerdown', event => { backdropPress = outside(event); });
  listen(dialog, 'click', event => {
    if (backdropPress && outside(event)) dialog.close();
    backdropPress = false;
  });
  listen(dialog, 'close', () => {
    document.body.style.overflow = oldOverflow;
    returnFocus?.focus({preventScroll: true});
  });
  window.__projectHelpCleanup = () => {
    if (dialog.open) {
      dialog.close();
      document.body.style.overflow = oldOverflow;
    }
    controller.abort();
  };
}
