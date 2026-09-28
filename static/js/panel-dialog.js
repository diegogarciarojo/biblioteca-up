(() => {
  const dialog = document.getElementById('delete-book-dialog');
  if (!dialog) return;

  const bookName = document.getElementById('delete-dialog-book');
  const cancel = document.getElementById('delete-dialog-cancel');
  const confirm = document.getElementById('delete-dialog-confirm');
  let pendingForm = null;

  // Native confirmation remains available if this script does not load.
  document.querySelectorAll('[data-delete-book]').forEach(form => form.removeAttribute('onsubmit'));

  document.addEventListener('submit', event => {
    const form = event.target;
    if (!(form instanceof HTMLFormElement) || !form.matches('[data-delete-book]')) return;
    if (form.dataset.deleteConfirmed === 'true') {
      delete form.dataset.deleteConfirmed;
      return;
    }
    event.preventDefault();
    if (typeof dialog.showModal !== 'function') {
      if (window.confirm('¿Eliminar este libro y su PDF de la biblioteca?')) form.submit();
      return;
    }
    pendingForm = form;
    bookName.textContent = form.dataset.bookTitle || '';
    dialog.showModal();
    cancel.focus();
  });

  cancel.addEventListener('click', () => dialog.close());
  dialog.addEventListener('close', () => { pendingForm = null; });
  confirm.addEventListener('click', () => {
    if (!pendingForm) return;
    const form = pendingForm;
    form.dataset.deleteConfirmed = 'true';
    dialog.close();
    form.requestSubmit();
  });
})();
