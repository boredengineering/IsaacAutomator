from run import run,ROOT
import json
run('docker cp /tmp/isaac-selfhost-trials/c3x/azure-fixture isaac-cost-c3x-cli:/trial/azure-fixture')
run('docker exec isaac-cost-c3x-cli wget -T 3 -qO- http://isaac-cost-c3x-proxy:4001/healthz')
base='docker exec isaac-cost-c3x-cli /c3x estimate --pricing-endpoint http://isaac-cost-c3x-proxy:4001/graphql --no-cache --no-remote-modules --currency USD --format json'
p=run(base+' --path /trial/azure-fixture --what-if azurerm_key_vault.public_price_trial.monthly_operations=100000',40);(ROOT/'actual-azure-quote.json').write_text(p.stdout)
# Force independent catalog request without altering source, using fresh cache path.
p=run(base+' --cache-path /tmp/fresh-audit/prices.db --path /trial/derived-hcl/g4-standard-48-flex_start',40);(ROOT/'g4-audited-quote.json').write_text(p.stdout)
p=run(base+' --path /trial/derived-hcl/g4-standard-48-standard --what-if google_compute_instance.workstation.machine_type=totally-unknown-machine',40);(ROOT/'unknown-machine-quote.json').write_text(p.stdout)
p=run('docker logs isaac-cost-c3x-proxy');(ROOT/'http-routing.jsonl').write_text(p.stdout)
p=run('docker exec isaac-cost-c3x-api /pricing-api scrape --vendor gcp',20);(ROOT/'gcp-auth-blocker.txt').write_text(p.stdout)
p=run('docker exec isaac-cost-c3x-db psql -U postgres -d pricing -c "SELECT vendor_name,service,count(*) FROM products GROUP BY 1,2;"');(ROOT/'database-counts.txt').write_text(p.stdout)
p=run('docker exec isaac-cost-c3x-api wget -qO- http://localhost:4000/metrics');(ROOT/'final-metrics.txt').write_text(p.stdout)
