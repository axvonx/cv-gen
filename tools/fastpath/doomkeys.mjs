/** Browser keyboard events to doomgeneric key codes (doomkeys.h) for the DOOM machine. */
const named = {
  ArrowRight: 0xae,
  ArrowLeft: 0xac,
  ArrowUp: 0xad,
  ArrowDown: 0xaf,
  Escape: 27,
  Enter: 13,
  Tab: 9,
  Backspace: 0x7f,
  Pause: 0xff,
  " ": 0xa2, // use (open doors, switches)
  Control: 0xa3, // fire
  Shift: 0x80 + 0x36, // run
  Alt: 0x80 + 0x38, // strafe modifier
  ",": 0xa0, // strafe left
  ".": 0xa1, // strafe right
  "-": 0x2d,
  "=": 0x3d,
};
for (let n = 1; n <= 10; n++) named[`F${n}`] = 0x80 + 0x3a + n;
named.F11 = 0x80 + 0x57;
named.F12 = 0x80 + 0x58;

/** Returns the key-FIFO event (0x100 | pressed << 9 | code), or null if unmapped. */
export function doomKeyEvent(key, pressed) {
  let code = named[key];
  if (code === undefined && key.length === 1 && /[a-z0-9]/i.test(key))
    code = key.toLowerCase().charCodeAt(0);
  if (code === undefined) return null;
  return 0x100 | (pressed ? 0x200 : 0) | code;
}
