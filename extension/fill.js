// runs inside the page's top frame through chrome.scripting.executeScript, so it has to be one
// self-contained function: nothing from outside it exists there.
function fillPage(kind, data, expectedOrigin) {
  if (location.origin !== expectedOrigin) return { ok: false, error: 'the page changed before alles could fill it' };

  const usable = input => !input.disabled && !input.readOnly && input.type !== 'hidden' && input.getClientRects().length > 0;
  const fields = [...document.querySelectorAll('input, select, textarea')].filter(usable);
  // the last autocomplete token is the field's job ("billing cc-number" -> "cc-number")
  const token = input => String(input.getAttribute('autocomplete') || '').trim().toLowerCase().split(/\s+/).pop();
  const words = input => [input.name, input.id, input.placeholder, input.getAttribute('aria-label'),
    input.labels?.[0]?.textContent].filter(Boolean).join(' ').toLowerCase();
  const find = (tokens, pattern, skip = []) => fields.find(input => !skip.includes(input) && tokens.includes(token(input)))
    || (pattern ? fields.find(input => !skip.includes(input) && !token(input).startsWith('cc-') && pattern.test(words(input))) : null);

  const set = (input, value) => {
    if (!input || value === undefined || value === null || value === '') return false;
    value = String(value);
    if (input instanceof HTMLSelectElement) {
      const wanted = value.toLowerCase();
      const option = [...input.options].find(item => item.value.toLowerCase() === wanted || item.textContent.trim().toLowerCase() === wanted)
        || [...input.options].find(item => wanted.length > 2 && item.textContent.trim().toLowerCase().startsWith(wanted));
      if (!option) return false;
      input.value = option.value;
    } else {
      const proto = input instanceof HTMLTextAreaElement ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
      Object.getOwnPropertyDescriptor(proto, 'value')?.set.call(input, value);
    }
    input.dispatchEvent(new Event('input', { bubbles: true }));
    input.dispatchEvent(new Event('change', { bubbles: true }));
    return true;
  };

  if (kind === 'login') {
    const passwords = fields.filter(input => input.type === 'password');
    if (passwords.length !== 1) return { ok: false, error: 'alles fills only a form with one password field' };
    const password = passwords[0];
    if (/new-password/i.test(password.autocomplete || '')) return { ok: false, error: 'this looks like a new password form, so alles left it alone' };
    const form = password.form || password.closest('form') || document;
    const candidates = [...form.querySelectorAll('input')].filter(input => usable(input) && input !== password && ['text', 'email', ''].includes(input.type));
    const username = candidates.find(input => /^(username|email)$/i.test(token(input))) || candidates.find(input => input.type === 'email') || candidates[0];
    set(username, data.username);
    set(password, data.password);
    password.focus();
    return { ok: true, filled: username && data.username ? 2 : 1 };
  }

  let filled = 0;
  const put = (input, value) => { if (set(input, value)) filled += 1; };

  if (kind === 'card') {
    const number = find(['cc-number'], /card.?num|cc.?num|cardnumber/);
    if (!number) return { ok: false, error: 'no card number field on this page' };
    put(number, data.number);
    put(find(['cc-name'], /name.?on.?card|card.?holder|cc.?name/), data.cardholder);
    put(find(['cc-csc'], /cvv|cvc|csc|security.?code/), data.cvv);
    // "08/27", "8/2027", "2027-08", "0827"
    const raw = String(data.expiry || '').trim();
    let month = '';
    let year = '';
    let parts = raw.match(/^(\d{4})\D(\d{1,2})$/);
    if (parts) [, year, month] = parts;
    else if ((parts = raw.match(/^(\d{1,2})\D+(\d{2,4})$/))) [, month, year] = parts;
    else if ((parts = raw.match(/^(\d{2})(\d{2})$/))) [, month, year] = parts;
    if (month && year) {
      month = month.padStart(2, '0');
      const full = year.length === 2 ? `20${year}` : year;
      // selects list "08" or "8", "2027" or "27"; try both
      const monthField = find(['cc-exp-month'], /exp.*month|cc.?month|^mm$/);
      if (set(monthField, month) || set(monthField, String(Number(month)))) filled += 1;
      const yearField = find(['cc-exp-year'], /exp.*year|cc.?year|^yy(yy)?$/);
      if (set(yearField, full) || set(yearField, full.slice(2))) filled += 1;
      const both = !monthField && !yearField && find(['cc-exp'], /expir|exp.?date|mm.?\/?.?yy/);
      if (both) {
        const long = /yyyy/i.test(both.placeholder || '') || Number(both.maxLength) === 7;
        put(both, `${month}/${long ? full : full.slice(2)}`);
      }
    }
    return { ok: filled > 0, filled };
  }

  if (kind === 'address') {
    // "123 king st w\ntoronto, on m5v 1j2\ncanada" or the same on one line with commas
    const lines = String(data.address || '').split(/\n/).map(line => line.trim()).filter(Boolean);
    const parts = lines.length > 1 ? lines : (lines[0] || '').split(/\s*,\s*/).filter(Boolean);
    const postal = /([A-Za-z]\d[A-Za-z]\s?\d[A-Za-z]\d|\d{5}(?:-\d{4})?)$/;
    let city = '';
    let region = '';
    let code = '';
    let country = '';
    const postalAt = parts.findIndex((part, index) => index > 0 && postal.test(part));
    // where the street lines stop: the city's part, or the postal part when the city is in it
    let cityAt = postalAt > 0 ? postalAt : parts.length;
    if (postalAt > 0) {
      const tail = parts[postalAt].match(/^(.*?)[,\s]*\b([A-Za-z]{2})\s+([A-Za-z]\d[A-Za-z]\s?\d[A-Za-z]\d|\d{5}(?:-\d{4})?)$/);
      if (tail) [, city, region, code] = tail;
      else code = parts[postalAt].match(postal)[1];
      if (!city && postalAt > 1) { city = parts[postalAt - 1]; cityAt = postalAt - 1; }
      country = parts.slice(postalAt + 1).join(', ');
    }
    const street = parts[0] || '';
    const second = parts.slice(1, cityAt).join(', ');
    const name = String(data.fullname || '').trim();
    const given = name.split(/\s+/).slice(0, -1).join(' ') || name;
    const family = name.split(/\s+/).length > 1 ? name.split(/\s+/).pop() : '';

    const fullField = find(['name'], /^(full.?)?name$|full.?name|your.?name/);
    put(fullField, name);
    if (!fullField) {
      put(find(['given-name'], /first.?name|given/), given);
      put(find(['family-name'], /last.?name|family|surname/), family);
    }
    put(find(['email'], /e.?mail/), data.email);
    put(find(['tel', 'tel-national'], /phone|mobile|\btel/), data.phone);
    const streetField = find(['street-address'], null);
    if (streetField instanceof HTMLTextAreaElement) put(streetField, [street, second].filter(Boolean).join('\n'));
    else {
      const lineOne = streetField || find(['address-line1'], /address.?(line)?.?1|street|addr1|^address$/);
      put(lineOne, street);
      put(find(['address-line2'], /address.?(line)?.?2|apt|suite|unit|addr2/, [lineOne]), second);
    }
    put(find(['address-level2'], /city|town|locality/), city);
    put(find(['address-level1'], /state|province|region/), region);
    put(find(['postal-code'], /zip|postal|postcode/), code);
    put(find(['country', 'country-name'], /country/), country);
    return { ok: filled > 0, filled };
  }
  return { ok: false, error: 'alles can’t fill that here' };
}
