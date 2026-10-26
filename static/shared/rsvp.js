// public rsvp page (/rsvp/<token>). a file, not inline, so the page keeps the app's script-src
(function () {
  var token = document.body.dataset.token;
  document.querySelectorAll('.rb').forEach(function (button) {
    button.addEventListener('click', async function () {
      var r = await fetch('/rsvp/' + encodeURIComponent(token), {
        method: 'POST', headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ status: button.dataset.status }),
      });
      if (r.ok) {
        document.querySelectorAll('.rb').forEach(function (b) { b.classList.remove('sel'); });
        button.classList.add('sel');
        document.getElementById('msg').textContent = 'response saved — thanks!';
      }
    });
  });
})();
