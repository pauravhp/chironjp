import RFB from '/desktop-assets/core/rfb.js';

const screen = document.querySelector('#screen');
const status = document.querySelector('#status');
const take = document.querySelector('#take');
const release = document.querySelector('#release');
const pageDown = document.querySelector('#page-down');
const keyboard = document.querySelector('#keyboard');
const key = `chironjpDesktop:${location.pathname}`;
let session = sessionStorage.getItem(key);
if (!session) {
  session = crypto.randomUUID();
  sessionStorage.setItem(key, session);
}
let rfb;
let connected = false;
let controlState = 'view_only';

function show(message) { status.textContent = message; }
function controls() {
  const controlling = controlState === 'controlling';
  const uncertain = controlState === 'uncertain';
  take.disabled = !connected || controlling || uncertain;
  release.disabled = !connected || (!controlling && !uncertain);
  pageDown.disabled = !connected || !controlling;
  keyboard.disabled = !connected || !controlling;
  screen.classList.toggle('standby', !controlling);
  if (rfb) rfb.viewOnly = !controlling;
}

async function change(action, quiet = false) {
  take.disabled = release.disabled = true;
  try {
    const response = await fetch(`${location.pathname}${action}?session=${encodeURIComponent(session)}`, {
      method: 'POST', credentials: 'same-origin', headers: {'X-ChironJP-Desktop': '1'},
    });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.error || 'Control transition failed.');
    controlState = payload.state;
    if (quiet && controlState === 'view_only') {
      show('Connected view-only. Guard and input lock are verified.');
    } else {
      show(controlState === 'controlling'
        ? 'You have control. The worker is paused; review and make any final action yourself.'
        : 'Guard and view-only mode are verified; control returned.');
    }
  } catch (error) {
    controlState = 'uncertain';
    show(`${error.message} Control state is uncertain; reconnect if needed, then retry Return control.`);
  }
  controls();
}

take.addEventListener('click', () => change('take'));
release.addEventListener('click', () => change('return'));
pageDown.addEventListener('click', () => {
  if (connected && controlState === 'controlling' && rfb) rfb.sendKey(0xff56);
});

function sendKeys(text) {
  if (!connected || controlState !== 'controlling' || !rfb) return;
  for (const character of text) {
    const codepoint = character.codePointAt(0);
    const keysym = codepoint <= 0xff ? codepoint : 0x01000000 | codepoint;
    rfb.sendKey(keysym);
  }
}

keyboard.addEventListener('beforeinput', event => {
  if (controlState !== 'controlling') {
    event.preventDefault();
    return;
  }
  if (event.inputType === 'deleteContentBackward') {
    event.preventDefault();
    rfb.sendKey(0xff08);
  } else if (event.inputType === 'insertLineBreak') {
    event.preventDefault();
    rfb.sendKey(0xff0d);
  }
});
keyboard.addEventListener('input', event => {
  if (event.data) sendKeys(event.data);
  keyboard.value = '';
});

rfb = new RFB(screen, `${location.protocol === 'https:' ? 'wss:' : 'ws:'}//${location.host}${location.pathname}socket?session=${encodeURIComponent(session)}`);
rfb.viewOnly = true;
rfb.scaleViewport = true;
rfb.resizeSession = false;
rfb.addEventListener('connect', () => {
  connected = true;
  show('Connected. Verifying retained control state…');
  controls();
  change('observe', true);
});
rfb.addEventListener('disconnect', () => {
  connected = false;
  if (controlState === 'controlling') controlState = 'uncertain';
  show(controlState === 'uncertain'
    ? 'Disconnected while control may still be held. Reconnect to verify and retry Return control.'
    : 'Disconnected from the view-only retained desktop.');
  controls();
});
controls();
