/* Hold-to-run pointer controls. No network or robot state lives here.
   Separate pointer IDs allow two fingers; releasing one never drops another.
   clear() invalidates old contacts so a held finger cannot restart after Stop. */
function createHoldControls({ enabled, change, stop }) {
  const contacts = new Map();
  const begin = (id, action) => {
    if (action === 'stop') { stop(); return; }
    if (!enabled() || contacts.has(id)) return;
    const alreadyHeld = [...contacts.values()].includes(action);
    contacts.set(id, action);
    if (!alreadyHeld) change(action, true);
  };
  const end = id => {
    const action = contacts.get(id);
    if (!action) return;
    contacts.delete(id);
    if (![...contacts.values()].includes(action)) change(action, false);
  };
  return {
    clear() { contacts.clear(); },
    bind(button, action) {
      button.addEventListener('pointerdown', event => {
        if (event.button !== 0) return;
        event.preventDefault();
        button.setPointerCapture?.(event.pointerId);
        begin(event.pointerId, action);
      });
      for (const type of ['pointerup', 'pointercancel', 'lostpointercapture']) {
        button.addEventListener(type, event => end(event.pointerId));
      }
      button.addEventListener('contextmenu', event => event.preventDefault());
      // Enter holds a focused button; Space remains the universal stop.
      button.addEventListener('keydown', event => {
        if (event.key !== 'Enter' && event.key !== ' ') return;
        event.preventDefault();
        event.stopPropagation();
        if (event.key === ' ') stop();
        else if (!event.repeat) begin(`key:${action}`, action);
      });
      button.addEventListener('keyup', event => {
        if (event.key === 'Enter') end(`key:${action}`);
      });
      button.addEventListener('blur', () => end(`key:${action}`));
      // Accessible activation of Stop also works without a pointer event.
      if (action === 'stop') button.addEventListener('click', stop);
    },
  };
}
