// Trial-only harness: expose the upstream normalizer, not a replacement.
// Input is an archived real Azure Retail Prices response, not fabricated data.
const fs = require('fs');
const Module = require('module');
const source = '/usr/src/app/dist/scrapers/azureRetail.js';
const m = new Module(source, module);
m.filename = source;
m.paths = Module._nodeModulePaths('/usr/src/app/dist/scrapers');
m._compile(fs.readFileSync(source, 'utf8') + '\nexports.trialParseProduct = parseProduct;\n', source);
const {upsertProducts} = require('/usr/src/app/dist/db/upsert.js');
const config = require('/usr/src/app/dist/config.js').default;
(async () => {
  const raw = JSON.parse(fs.readFileSync('/tmp/azure-vendor-response.json','utf8'));
  const products = raw.Items.map(m.exports.trialParseProduct);
  await upsertProducts(products);
  console.log(JSON.stringify({imported_vendor_records: products.length, synthetic:false, method:'upstream parseProduct + upsertProducts through trial harness; native job unchanged'}));
  await (await config.pg()).end();
})().catch(e => { console.error(e.message); process.exit(1); });
