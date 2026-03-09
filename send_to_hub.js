const https = require('https');
const http = require('http');

const TARGET = process.argv[2];
const MSG = process.argv.slice(3).join(' ');

if (!TARGET || !MSG) {
  console.error('Usage: node send_to_hub.js <target_agent_id> <message>');
  process.exit(1);
}

const HUB_URL = 'https://a2a-hub.zeabur.app/invoke';
const API_KEY = 'sk-8652c38d5a40540d133692a882d047b8';

const payload = JSON.stringify({
  target_id: TARGET,
  message: MSG,
  sender_id: 'terminator'
});

function doRequest(attempt) {
  return new Promise((resolve, reject) => {
    const url = new URL(HUB_URL);
    const options = {
      hostname: url.hostname,
      port: url.port || (url.protocol === 'https:' ? 443 : 80),
      path: url.pathname,
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'x-api-key': API_KEY,
        'Content-Length': Buffer.byteLength(payload)
      },
      timeout: 45000
    };
    const lib = url.protocol === 'https:' ? https : http;
    const req = lib.request(options, (res) => {
      let data = '';
      res.on('data', chunk => data += chunk);
      res.on('end', () => resolve({ status: res.statusCode, body: data }));
    });
    req.on('error', reject);
    req.on('timeout', () => { req.destroy(); reject(new Error('Request timeout')); });
    req.write(payload);
    req.end();
  });
}

async function sendWithRetry(maxRetries = 3, delayMs = 3000) {
  for (let attempt = 1; attempt <= maxRetries; attempt++) {
    try {
      const result = await doRequest(attempt);
      if (result.status === 502 || result.status === 503 || result.status === 504) {
        console.error(`Attempt ${attempt}/${maxRetries}: Got ${result.status}, retrying in ${delayMs/1000}s...`);
        if (attempt < maxRetries) await new Promise(r => setTimeout(r, delayMs));
        continue;
      }
      console.log(result.body);
      process.exit(result.status >= 200 && result.status < 300 ? 0 : 1);
    } catch (err) {
      console.error(`Attempt ${attempt}/${maxRetries}: Error - ${err.message}`);
      if (attempt < maxRetries) await new Promise(r => setTimeout(r, delayMs));
    }
  }
  console.error('All retry attempts failed');
  process.exit(1);
}

sendWithRetry();
