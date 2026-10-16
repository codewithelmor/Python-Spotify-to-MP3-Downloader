// Copies the non-TypeScript renderer files (html, css) next to the compiled output.
const fs = require('fs');
const path = require('path');

const src = path.join(__dirname, '..', 'src', 'renderer');
const dest = path.join(__dirname, '..', 'out', 'renderer');
fs.mkdirSync(dest, { recursive: true });
for (const name of ['index.html', 'style.css']) {
  fs.copyFileSync(path.join(src, name), path.join(dest, name));
}
