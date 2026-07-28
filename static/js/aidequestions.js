function answerPayload(card, request) {
  const answers = {};
  for (const question of request.questions || []) {
    const section = card.querySelector(`[data-aide-question-id="${CSS.escape(question.id)}"]`);
    const selected = [...section.querySelectorAll('[data-choice-id][aria-checked="true"]')]
      .map(button => button.dataset.choiceId);
    const freeText = section.querySelector('[data-question-free-text]')?.value.trim() || '';
    answers[question.id] = { selected, free_text: freeText };
  }
  return { cancelled: false, answers };
}

function isComplete(card, request) {
  return (request.questions || []).every(question => {
    const section = card.querySelector(`[data-aide-question-id="${CSS.escape(question.id)}"]`);
    return Boolean(
      section?.querySelector('[data-choice-id][aria-checked="true"]')
      || section?.querySelector('[data-question-free-text]')?.value.trim()
    );
  });
}

function setDisabled(card, disabled) {
  card.querySelectorAll('button, textarea').forEach(control => { control.disabled = disabled; });
  card.setAttribute('aria-busy', String(disabled));
}

function choiceButton(choice, selection) {
  const button = document.createElement('button');
  button.type = 'button';
  button.className = 'aide-question-choice';
  button.dataset.choiceId = choice.id;
  button.setAttribute('role', selection === 'multiple' ? 'checkbox' : 'radio');
  button.setAttribute('aria-checked', 'false');
  const label = document.createElement('span');
  label.className = 'aide-question-choice-label';
  label.textContent = choice.label;
  button.appendChild(label);
  if (choice.description) {
    const description = document.createElement('span');
    description.className = 'aide-question-choice-description';
    description.textContent = choice.description;
    button.appendChild(description);
  }
  return button;
}

export function markAideQuestionResolved(root, id, cancelled = false) {
  const card = root?.querySelector?.(`[data-aide-question-request="${CSS.escape(id || '')}"]`);
  if (!card) return;
  setDisabled(card, true);
  card.classList.add(cancelled ? 'cancelled' : 'answered');
  const status = card.querySelector('[data-question-status]');
  if (status) status.textContent = cancelled ? 'cancelled' : 'answer saved';
}

export function renderAideQuestion(root, request, { onResolved } = {}) {
  if (!root || !request?.id || !Array.isArray(request.questions)) return null;
  const prior = root.querySelector(`[data-aide-question-request="${CSS.escape(request.id)}"]`);
  if (prior) return prior;

  const card = document.createElement('section');
  card.className = 'aide-question-card';
  card.dataset.aideQuestionRequest = request.id;
  card.setAttribute('aria-labelledby', `aide-question-title-${request.id}`);

  const title = document.createElement('h3');
  title.id = `aide-question-title-${request.id}`;
  title.textContent = request.title || 'Aide needs your input';
  card.appendChild(title);

  request.questions.forEach((question, index) => {
    const section = document.createElement('section');
    section.className = 'aide-question-item';
    section.dataset.aideQuestionId = question.id;

    const heading = document.createElement('h4');
    heading.id = `aide-question-${request.id}-${question.id}`;
    heading.textContent = question.prompt;
    section.appendChild(heading);

    const group = document.createElement('div');
    group.className = 'aide-question-choices';
    group.setAttribute('role', question.selection === 'multiple' ? 'group' : 'radiogroup');
    group.setAttribute('aria-labelledby', heading.id);
    for (const choice of question.choices || []) {
      const button = choiceButton(choice, question.selection);
      button.addEventListener('click', () => {
        const next = button.getAttribute('aria-checked') !== 'true';
        if (question.selection !== 'multiple') {
          group.querySelectorAll('[data-choice-id]').forEach(other => {
            other.setAttribute('aria-checked', 'false');
            other.classList.remove('selected');
          });
        }
        button.setAttribute('aria-checked', String(next));
        button.classList.toggle('selected', next);
        submit.disabled = !isComplete(card, request);
      });
      button.addEventListener('keydown', event => {
        if (!['ArrowDown', 'ArrowRight', 'ArrowUp', 'ArrowLeft'].includes(event.key)) return;
        event.preventDefault();
        const buttons = [...group.querySelectorAll('[data-choice-id]')];
        const direction = ['ArrowDown', 'ArrowRight'].includes(event.key) ? 1 : -1;
        buttons[(buttons.indexOf(button) + direction + buttons.length) % buttons.length]?.focus();
      });
      group.appendChild(button);
    }
    section.appendChild(group);

    if (question.allow_free_text) {
      const label = document.createElement('label');
      label.className = 'aide-question-free-label';
      label.textContent = question.free_text_label || 'another answer';
      const textarea = document.createElement('textarea');
      textarea.rows = 2;
      textarea.maxLength = 2000;
      textarea.dataset.questionFreeText = '';
      textarea.addEventListener('input', () => { submit.disabled = !isComplete(card, request); });
      label.appendChild(textarea);
      section.appendChild(label);
    }
    card.appendChild(section);
    if (index === 0) section.dataset.firstQuestion = '';
  });

  const footer = document.createElement('div');
  footer.className = 'aide-question-footer';
  const status = document.createElement('span');
  status.dataset.questionStatus = '';
  status.setAttribute('aria-live', 'polite');
  const cancel = document.createElement('button');
  cancel.type = 'button';
  cancel.className = 'aide-question-cancel';
  cancel.textContent = 'cancel';
  const submit = document.createElement('button');
  submit.type = 'button';
  submit.className = 'aide-question-submit';
  submit.textContent = 'continue';
  submit.disabled = true;
  footer.append(status, cancel, submit);
  card.appendChild(footer);

  const send = async payload => {
    setDisabled(card, true);
    status.textContent = 'saving…';
    try {
      const response = await fetch(`/api/agent/questions/${encodeURIComponent(request.id)}/answer`, {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify(payload),
      });
      if (!response.ok) throw new Error('answer_not_saved');
      markAideQuestionResolved(root, request.id, payload.cancelled === true);
      onResolved?.(payload);
    } catch {
      setDisabled(card, false);
      submit.disabled = !isComplete(card, request);
      status.textContent = 'could not save - try again';
    }
  };
  submit.addEventListener('click', () => send(answerPayload(card, request)));
  cancel.addEventListener('click', () => send({ cancelled: true, answers: {} }));

  root.appendChild(card);
  card.querySelector('[data-choice-id]')?.focus();
  return card;
}
