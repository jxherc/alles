// the print button on a shared aide session (/s/<token>)
document.querySelectorAll('[data-print]').forEach(function (button) {
  button.addEventListener('click', function () { window.print(); });
});
