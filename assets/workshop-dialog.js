() => {
  if (window.__workshopDialogReady) return;
  window.__workshopDialogReady = true;
  let active = false, returnFocus = null, blocked = [], oldOverflow = '';
  const modal = () => document.getElementById('workshop-modal');
  const close = () => document.getElementById('workshop-dialog-close')?.click();
  const visible = el => el && el.getClientRects().length && getComputedStyle(el).visibility !== 'hidden';
  const sync = () => {
    const shell = modal();
    const shown = !!visible(shell);
    if (shown === active) return;
    active = shown;
    if (shown) {
      returnFocus = document.activeElement;
      const panel = document.getElementById('workshop-dialog-panel');
      panel.setAttribute('role', 'dialog');
      panel.setAttribute('aria-modal', 'true');
      panel.setAttribute('aria-labelledby', 'workshop-dialog-title');
      for (let node = shell; node.parentElement && node !== document.body; node = node.parentElement) {
        for (const sibling of node.parentElement.children) {
          if (sibling !== node && !sibling.inert && !['SCRIPT', 'STYLE', 'LINK'].includes(sibling.tagName)) {
            sibling.inert = true;
            blocked.push(sibling);
          }
        }
      }
      oldOverflow = document.body.style.overflow;
      document.body.style.overflow = 'hidden';
      document.getElementById('workshop-dialog-close')?.focus();
    } else {
      blocked.forEach(el => el.inert = false);
      blocked = [];
      document.body.style.overflow = oldOverflow;
      if (returnFocus?.isConnected) returnFocus.focus({preventScroll: true});
    }
  };
  new MutationObserver(sync).observe(document.body, {subtree: true, childList: true, attributes: true, attributeFilter: ['style', 'class', 'hidden']});
  document.addEventListener('click', event => { if (active && event.target === modal()) close(); });
  document.addEventListener('keydown', event => {
    if (!active) return;
    if (event.key === 'Escape') { event.preventDefault(); event.stopPropagation(); close(); }
    if (event.key === 'Tab') {
      const focusable = Array.from(modal().querySelectorAll('button, input, textarea, select, a[href], [tabindex]'))
        .filter(el => !el.disabled && el.tabIndex >= 0 && visible(el));
      const first = focusable[0], last = focusable.at(-1);
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus(); }
    }
  }, true);
  sync();
}
