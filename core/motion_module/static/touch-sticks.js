/* On-screen thumbsticks for the Driver Station. No network or robot state
   lives here: a stick reports how far it is pushed, from -1 to 1 with up and
   right positive, and the page decides what each direction does.

   The stick centres itself wherever the thumb lands, so touching down never
   moves the robot; only dragging does. Each stick follows one finger, so two
   thumbs work two sticks. A finger that touched down while driving was not
   allowed, or was holding the stick when clear() let it go, does nothing
   until it lifts and touches again. */
function createTouchStick(pad, { enabled, change }) {
  const base = pad.querySelector('.stick-base');
  const knob = pad.querySelector('.stick-knob');
  const clamp = (value, low, high) => Math.min(Math.max(value, low), high);
  const round = value => Math.round(value * 1000) / 1000 || 0;
  let axes = { x: true, y: true };
  let pointer = null;
  let origin = null;
  let travel = null;
  let value = { x: 0, y: 0 };

  const report = next => {
    if (next.x === value.x && next.y === value.y) return;
    value = next;
    change({ ...value });
  };

  function letGo() {
    if (pointer !== null) {
      try { pad.releasePointerCapture?.(pointer); } catch (_) { /* already released */ }
    }
    pointer = null;
    origin = null;
    pad.classList.remove('held');
    base.style.transform = '';
    knob.style.transform = '';
    report({ x: 0, y: 0 });
  }

  pad.addEventListener('pointerdown', event => {
    if (event.button > 0 || pointer !== null) return;
    event.preventDefault();
    if (!enabled() || !(axes.x || axes.y)) return;
    const box = pad.getBoundingClientRect();
    const baseBox = base.getBoundingClientRect();
    const knobBox = knob.getBoundingClientRect();
    travel = {
      x: (baseBox.width - knobBox.width) / 2,
      y: (baseBox.height - knobBox.height) / 2,
    };
    if ((axes.x && !(travel.x > 0)) || (axes.y && !(travel.y > 0))) return;
    pointer = event.pointerId;
    origin = { x: event.clientX, y: event.clientY };
    try { pad.setPointerCapture?.(pointer); } catch (_) { /* moves outside the pad are lost */ }
    pad.classList.add('held');
    // The ring moves under the thumb, staying inside the pad.
    const centre = {
      x: clamp(event.clientX, box.left + baseBox.width / 2, box.right - baseBox.width / 2),
      y: clamp(event.clientY, box.top + baseBox.height / 2, box.bottom - baseBox.height / 2),
    };
    base.style.transform =
      `translate(${centre.x - (box.left + box.width / 2)}px, ${centre.y - (box.top + box.height / 2)}px)`;
  });

  pad.addEventListener('pointermove', event => {
    if (event.pointerId !== pointer) return;
    event.preventDefault();
    let dx = axes.x ? event.clientX - origin.x : 0;
    let dy = axes.y ? event.clientY - origin.y : 0;
    let x;
    let y;
    if (axes.x && axes.y) {
      const reach = Math.min(travel.x, travel.y);
      const length = Math.hypot(dx, dy);
      if (length > reach) {
        dx *= reach / length;
        dy *= reach / length;
      }
      x = dx / reach;
      y = -dy / reach;
    } else {
      dx = clamp(dx, -travel.x, travel.x);
      dy = clamp(dy, -travel.y, travel.y);
      x = axes.x ? dx / travel.x : 0;
      y = axes.y ? -dy / travel.y : 0;
    }
    knob.style.transform = `translate(${dx}px, ${dy}px)`;
    report({ x: round(x), y: round(y) });
  });

  for (const type of ['pointerup', 'pointercancel', 'lostpointercapture']) {
    pad.addEventListener(type, event => {
      if (event.pointerId === pointer) letGo();
    });
  }
  pad.addEventListener('contextmenu', event => event.preventDefault());

  return {
    get value() { return { ...value }; },
    // Which ways this stick moves: { x, y }. Changing it lets go.
    configure(next) {
      axes = { x: Boolean(next.x), y: Boolean(next.y) };
      pad.dataset.axes = `${axes.x ? 'x' : ''}${axes.y ? 'y' : ''}`;
      letGo();
    },
    clear: letGo,
  };
}
