// Teste ponta a ponta da página da assistente SEM a Recall: abre a página no Chromium com um
// "microfone falso" alimentado por um WAV (simulando o áudio da reunião) e registra o console.
//
// Uso: node scripts/e2e_assistant.mjs <url-da-pagina-da-assistente> <arquivo.wav> [segundos] [--ws]
// (instale antes: npm i playwright && npx playwright install chromium, em uma pasta qualquer; defina NODE_PATH)
import { chromium } from 'playwright';

const [url, wav, secondsArg, ...flags] = process.argv.slice(2);
if (!url || !wav) { console.error('uso: node scripts/e2e_assistant.mjs <url> <wav> [segundos] [--ws]'); process.exit(1); }
const seconds = Number(secondsArg || 60);
const forceWs = flags.includes('--ws');

const browser = await chromium.launch({
  headless: true, executablePath: process.env.CHROME_EXE || undefined, channel: process.env.CHROME_CHANNEL || undefined,
  args: [
    '--use-fake-ui-for-media-stream',
    '--use-fake-device-for-media-stream',
    `--use-file-for-fake-audio-capture=${wav}%noloop`,
    '--autoplay-policy=no-user-gesture-required',
    ...(forceWs ? ['--force-webrtc-ip-handling-policy=disable_non_proxied_udp'] : []),
  ],
});
const context = await browser.newContext({ viewport: { width: 1280, height: 720 }, permissions: ['microphone'] });
const page = await context.newPage();
const lines = [];
page.on('console', (msg) => { const t = msg.text(); if (t.includes('[navi]') || msg.type() === 'error') { lines.push(t); console.log(t); } });
page.on('pageerror', (err) => console.log('PAGEERROR', err.message));
await page.goto(url, { waitUntil: 'load' });
await page.waitForTimeout(seconds * 1000);
await page.screenshot({ path: 'e2e_assistant.png' });
const status = await page.textContent('#status');
const caption = await page.textContent('#caption');
console.log('--- fim ---'); console.log('status:', status); console.log('caption:', caption);
await browser.close();
